"""Generate, review, fit, and persist job application documents.

This module is the orchestration facade. It used to be one 296-line function
that mixed prompt building, LLM calls, validation, retries, file writing and
mirroring (A-3). Those responsibilities now live in:

  * :mod:`services.generation` -- prompts, LLM calls, validation, retries;
  * :mod:`services.application_store` -- the ``outputs/<job_id>/`` folder.

``tailor_documents`` keeps its exact public signature and behaviour, so the API,
the UI, the CLI and every existing test call it unchanged.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from pypdf import PdfReader

from config import Config
from models.profile import Profile
from models.requests import TailorResponse
from models.tailored_output import TailoringExplanation
from renderers import create_latex_renderer, create_docx_renderer
from services.application_store import ApplicationStore, make_job_id
from services.gemini_service import GeminiService
from services.generation import (
    MAX_LAYOUT_ATTEMPTS,
    PROMPT_CL_PATH,
    PROMPT_CV_PATH,
    DEFAULT_PROFILE_RULES,
    DocumentGenerator,
    ProfileRules,
    build_context,
)
from utils.text import slugify

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Kept for backwards compatibility: tests and callers reference these directly.
__all__ = [
    "tailor_documents",
    "parse_json_response",
    "validate_cv",
    "validate_cover_letter",
    "DEFAULT_PROFILE_RULES",
    "ProfileRules",
]


# --- re-exported so existing imports keep working -------------------------------------
# These preserve the public names, and the underscored names the existing test suite
# calls. Each is a thin delegation to services.generation, not duplicated logic.

def parse_json_response(text: str) -> dict:
    """Parse a model response into a document dict."""
    from services.generation import parse_json_response as _parse

    return _parse(text)


def validate_cv(cv, profile, rules: Optional[ProfileRules] = None) -> None:
    """Validate a CV, defaulting to the original candidate's rules."""
    from services.generation import validate_cv as _validate

    return _validate(cv, profile, rules or DEFAULT_PROFILE_RULES)


def validate_cover_letter(cl, profile) -> None:
    """Validate a cover letter against the profile."""
    from services.generation import validate_cover_letter as _validate

    return _validate(cl, profile)


def count_pdf_pages(pdf_path: Path) -> int:
    """Count pages, treating a missing or empty PDF as an error, never as zero."""
    pages = len(PdfReader(str(pdf_path)).pages)
    if pages < 1:
        raise ValueError("Generated PDF has no pages.")
    return pages


# Underscored aliases retained for the pre-existing tests.
_parse_json_response = parse_json_response
_validate_cv = validate_cv
_validate_cover_letter = validate_cover_letter
_count_pdf_pages = count_pdf_pages


# --- orchestration --------------------------------------------------------------------

def tailor_documents(
    job_description: str,
    profile: Profile,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    work_country: Optional[str] = None,
    config: Optional[Config] = None,
    rules: Optional[ProfileRules] = None,
) -> TailorResponse:
    """Produce a two-page CV and a one-page cover letter, and persist them.

    Raises ValueError when the job description is empty, when a document cannot be
    validated within three attempts, or when the CV will not fit two pages. In every
    failure case the editable drafts are written and a failure manifest recorded.
    """
    if not job_description or not job_description.strip():
        raise ValueError("Job description is empty.")

    # Resolved at call time (never at import), so the model, key and output path can
    # differ per invocation -- and one test can override another's environment.
    if config is None:
        config = Config.from_env(load_env_file=False, overrides={"project_root": PROJECT_ROOT})
        # Constructed with no arguments so an injected double can stand in for it.
        service = GeminiService()
    else:
        service = GeminiService(config=config)

    work_country = (work_country or "").strip() or None
    context = build_context(job_description, profile, company_name, role_title, work_country)
    cv_prompt = PROMPT_CV_PATH.read_text(encoding="utf-8") + context
    cl_prompt = PROMPT_CL_PATH.read_text(encoding="utf-8") + context

    generator = DocumentGenerator(
        service=service, profile=profile, rules=rules, status_callback=status_callback
    )
    cv, cl, explanation = generator.generate_pair(
        cv_prompt, cl_prompt,
        work_country=work_country, company_name=company_name, role_title=role_title,
    )

    job_id = make_job_id(
        company_name or cl.company_name, role_title or cl.role_title, slugify
    )
    store = ApplicationStore(project_root=PROJECT_ROOT, job_id=job_id)
    store.create(profile.model_dump(), job_description)
    store.save_drafts(generator.drafts)

    latex = create_latex_renderer(outputs_dir=str(store.job_folder))
    docx = create_docx_renderer(outputs_dir=str(store.job_folder))
    position = role_title or cl.role_title
    page_count = 0
    history = []

    def save_content() -> None:
        store.save_content({
            "company_name": cl.company_name, "role_title": position,
            "work_country": work_country,
            "cv": cv.model_dump(), "cover_letter": cl.model_dump(),
        })

    try:
        for attempt in range(MAX_LAYOUT_ATTEMPTS):
            save_content()
            cv_path = latex.render_cv(cv, profile, job_position=position)
            page_count = count_pdf_pages(Path(cv_path))
            history.append(page_count)
            if page_count <= 2:
                break
            if attempt == MAX_LAYOUT_ATTEMPTS - 1:
                raise ValueError(
                    f"CV is still {page_count} pages after four layout attempts. "
                    f"Editable drafts are saved at {store.source_folder}; generation "
                    "was not marked successful."
                )
            cv, explanation = generator.shorten_cv(
                cv, page_count, attempt, cv_prompt,
                work_country, company_name, role_title, explanation,
            )
        cl_path, cl_pdf_path = docx.render_cover_letter(cl, profile, job_position=position)
        if not cl_pdf_path:
            raise ValueError("Cover-letter PDF rendering failed.")
        cl_pages = count_pdf_pages(Path(cl_pdf_path))
        if cl_pages != 1:
            raise ValueError(f"Cover-letter PDF is {cl_pages} pages; expected one page.")
    except Exception as error:
        # Preserve everything editable, then mark the folder failed explicitly (D-14).
        save_content()
        store.save_drafts(generator.drafts)
        store.save_failure(str(error), history)
        raise

    # Separate CV/letter usage and include every review and shortening attempt.
    usage = service.calculate_token_usage(**generator.usage_kwargs())
    explanation_dict = (
        TailoringExplanation.model_validate(explanation).model_dump()
        if isinstance(explanation, dict)
        else None
    )
    result = TailorResponse(
        job_id=job_id, cv_path=str(cv_path), cover_letter_path=str(cl_path),
        cl_pdf_path=str(cl_pdf_path), token_usage=usage,
        cv_page_count=page_count, cover_letter_page_count=cl_pages,
        source_path=str(store.source_folder / "content.json"),
        tailoring_explanation=explanation_dict,
        message=(
            f"CV checked: {page_count} pages. Cover letter: {cl_pages} page, "
            f"{sum(len(p.split()) for p in cl.paragraphs)} words."
        ),
    )
    store.save_drafts(generator.drafts)
    # Mirroring is read from the config at call time, never at import time.
    mirror = store.mirror(result, config)
    store.save_manifest(result.model_dump(), history)
    if mirror is not None:
        store.save_manifest_copy(mirror)
    logger.info("Generated %s: %s CV pages; layout history %s", job_id, page_count, history)
    return result
