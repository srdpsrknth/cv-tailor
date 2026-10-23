"""Generate, review, fit, and persist job application documents."""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from config import Config
from models.profile import Profile
from models.requests import TailorResponse
from models.tailored_output import TailoredCV, TailoredCoverLetter, TailoringExplanation
from renderers import create_latex_renderer, create_docx_renderer
from services.gemini_service import GeminiService
from utils.text import slugify as _slugify

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_CV_PATH = PROJECT_ROOT / "backend/prompts/tailor_cv_prompt.md"
PROMPT_CL_PATH = PROJECT_ROOT / "backend/prompts/tailor_cl_prompt.md"


def _parse_json_response(text: str) -> dict:
    """Use the same parser for first drafts, reviews, and length retries.

    Accept wrappers around complete JSON; never repair truncated document data.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned an empty document.")
    decoder = json.JSONDecoder()
    for start in [0] + [match.start() for match in re.finditer(r"\{", text)]:
        try:
            value, _ = decoder.raw_decode(text[start:].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and any(
            key in value for key in ("cv", "cover_letter", "experience", "paragraphs")
        ):
            return value
    raise ValueError("The model response did not contain a complete document JSON object.")


def _extract_explanation(data: dict) -> Optional[dict]:
    """Find the tailoring explanation wherever the model put it.

    The prompt asks for it at the top level, but the more natural document shape nests it
    inside ``cv``. Reading only the top level silently yields ``None`` for a nested
    response: the UI then shows no explanation, with no error. Accept both, preferring
    the documented top-level key.
    """
    if not isinstance(data, dict):
        return None
    top_level = data.get("tailoring_explanation")
    if isinstance(top_level, dict):
        return top_level
    cv = data.get("cv")
    if isinstance(cv, dict):
        nested = cv.get("tailoring_explanation")
        if isinstance(nested, dict):
            return nested
    return None


def _count_pdf_pages(pdf_path: Path) -> int:
    # A missing/unreadable PDF must fail validation, never count as zero pages.
    pages = len(PdfReader(str(pdf_path)).pages)
    if pages < 1:
        raise ValueError("Generated PDF has no pages.")
    return pages


def _validate_cv(cv: TailoredCV, profile: Profile) -> None:
    expected = {exp.company: exp for exp in profile.experience}
    companies = [exp.company for exp in cv.experience]
    if len(companies) != len(set(companies)) or set(companies) != set(expected):
        raise ValueError("Include each profile employer exactly once, including older roles.")
    cv.experience.sort(key=lambda exp: list(expected).index(exp.company))
    for exp in cv.experience:
        base = expected[exp.company]
        if (exp.role, exp.start_date, exp.end_date) != (base.role, base.start_date, base.end_date):
            raise ValueError(f"Keep the exact profile title and dates for {exp.company}.")
        if not base.bullets and not base.selected_projects and (exp.bullets or exp.projects):
            raise ValueError(f"Do not invent responsibilities for {exp.company}.")
        if "aklamio" in exp.company.lower():
            if len(exp.projects) != 1 or len(exp.projects[0].bullets) != 3:
                raise ValueError("Aklamio must have one attribution project with exactly three bullets; fold other projects into role bullets.")
            name = exp.projects[0].name
            if re.search(r"entrypoints|in progress|20\d{2}", name, re.I):
                raise ValueError("Use a clear external attribution project name without dates or status labels.")
            for bullet in exp.bullets:
                if re.search(r"\bMCP\b", bullet) and not re.search(r"developing|development|working on", bullet, re.I):
                    raise ValueError("Describe Aklamio MCP integration as ongoing development, not shipped work.")
            if re.search(r"\b(lead|led|own|owned)\b[^.]{0,50}(framework|80)", " ".join(exp.bullets), re.I):
                raise ValueError("Aklamio DQ framework is a contribution; ownership is limited to funnel/sales-channel checks.")
    summary = " ".join(cv.summary)
    if re.search(r"\b(combines|builds|aims|passionate|dedicated to)\b", summary, re.I):
        raise ValueError("Use a factual career summary with 'experience across' or 'background in', not third-person verbs or aspirations.")
    # Catch common keyword stuffing for technologies absent from this profile.
    source = profile.model_dump_json().lower()
    text = cv.model_dump_json().lower()
    for tool in ("Fivetran", "Databricks", "Tableau", "ThoughtSpot", "DealCloud", "Cortex", "AWS"):
        if re.search(r"\b" + re.escape(tool.lower()) + r"\b", text) and not re.search(r"\b" + re.escape(tool.lower()) + r"\b", source):
            raise ValueError(f"Do not claim {tool} experience: it is not in the profile.")


def _validate_cover_letter(cl: TailoredCoverLetter, profile: Profile) -> None:
    words = sum(len(paragraph.split()) for paragraph in cl.paragraphs)
    if len(cl.paragraphs) != 4 or not 290 <= words <= 310:
        raise ValueError(f"Cover letter has {len(cl.paragraphs)} paragraphs and {words} words; return exactly four body paragraphs totaling 290-310 words.")
    if cl.signature_name != profile.identity.full_name:
        raise ValueError("Use the exact candidate name from the profile.")
    if any(re.search(r"(?:^|\n)\s*(Dear Hiring|Sincerely|Best regards|Kind regards)", paragraph, re.I) for paragraph in cl.paragraphs):
        raise ValueError("Body paragraphs must not contain a salutation or signature.")


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def tailor_documents(
    job_description: str,
    profile: Profile,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    work_country: Optional[str] = None,
    config: Optional[Config] = None,
) -> TailorResponse:
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
    work_country = (work_country or '').strip() or None
    country_context = (
        f"\nWORK COUNTRY (explicit user selection; overrides country inference): {work_country}. "
        "Apply the work-authorization rules for this country. Company headquarters and past job locations are irrelevant.\n"
        if work_country else "\nWORK COUNTRY: infer only from a clear actual job location; do not guess from company headquarters.\n"
    )
    context = (
        f"\nCOMPANY: {company_name or 'Infer from job description'}\n"
        f"ROLE: {role_title or 'Infer from job description'}\n"
        + country_context +
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"BASE PROFILE (authoritative JSON):\n{profile.model_dump_json(indent=2)}"
    )
    cv_prompt = PROMPT_CV_PATH.read_text(encoding="utf-8") + context
    cl_prompt = PROMPT_CL_PATH.read_text(encoding="utf-8") + context
    counts = {"cv": [0, 0, 0], "cover_letter": [0, 0, 0]}
    drafts = []
    explanation = None

    def generate(prompt, kind):
        last_error = ""
        previous = ""
        for _ in range(3):
            counts[kind][2] += 1
            feedback = f"\nCORRECTION REQUIRED: {last_error}\nPREVIOUS RESPONSE:\n{previous}\nReturn the corrected complete JSON document." if last_error else ""
            response, inputs, outputs = service._call_gemini(prompt + feedback)
            counts[kind][0] += inputs
            counts[kind][1] += outputs
            drafts.append({"component": kind, "response": response})
            try:
                data = _parse_json_response(response)
                if kind == "cv":
                    model = TailoredCV.model_validate(data.get("cv", data))
                    # Keep immigration status separate from sponsorship wording.
                    if work_country and 'blue card' in (profile.identity.visa_status or '').lower():
                        model.work_authorization = None if work_country.lower() in ('germany', 'deutschland', 'de') else 'German EU Blue Card holder'
                    if re.search(r'sponsorship|employer support|work permit support', model.model_dump_json(), re.I):
                        raise ValueError('Sponsorship and work permit support requirements belong only in the cover letter, never in the CV.')
                    _validate_cv(model, profile)
                else:
                    model = TailoredCoverLetter.model_validate(data.get("cover_letter", data))
                    _validate_cover_letter(model, profile)
                    if work_country and work_country.lower() not in ('germany', 'deutschland', 'de') and 'blue card' in (profile.identity.visa_status or '').lower():
                        closing = model.paragraphs[-1]
                        if not re.search(r'Blue Card', closing, re.I) or not re.search(r'employer support|sponsor', closing, re.I):
                            raise ValueError(f'Include the German-issued EU Blue Card and employer permit support needed for {work_country} in the final cover-letter paragraph.')
                        if work_country.lower() in ('ireland', 'denmark') and re.search(r'Irish (?:EU )?Blue Card|Danish (?:EU )?Blue Card', closing, re.I):
                            raise ValueError('Ireland and Denmark do not issue EU Blue Cards; refer to the appropriate local employment permit.')
                    if company_name:
                        model.company_name = company_name
                    if role_title:
                        model.role_title = role_title
                return model, data
            except ValueError as error:
                last_error = str(error)
                previous = response
                logger.warning("%s document validation failed: %s", kind, last_error)
        raise ValueError(f"Could not produce a valid {kind} document after three attempts: {last_error}")

    if status_callback:
        status_callback("Drafting CV...")
    cv, _ = generate(cv_prompt, "cv")
    # The Booking workflow included editorial review. Apply it to UI generation too.
    cv, data = generate(
        cv_prompt
        + "\nEDITORIAL AND FACTUAL REVIEW: Review the following draft against the profile. "
        "Remove invented outcomes, tools, claims of sole ownership, and claims that developing projects are complete. "
        "Improve plain-language writing and remove repeated responsibilities/project bullets. "
        "Check alignment with the supplied role and job description: preserve natural supported keywords, "
        "prioritize relevant examples, and retain profile-backed foundational skills expected for the role. "
        "Treat the approved summary as a style reference, not mandatory identical wording. "
        "Preserve work history and factual metrics. Return a complete revised CV JSON.\nDRAFT:\n"
        + cv.model_dump_json(indent=2),
        "cv",
    )
    explanation = _extract_explanation(data)

    # Generate the letter only once the CV's wording has passed validation.
    cl, _ = generate(cl_prompt, "cover_letter")
    year = datetime.now(ZoneInfo("Europe/Berlin")).year
    job_id = f"{year}_{_slugify(company_name or cl.company_name)}_{_slugify(role_title or cl.role_title)}_{time.time_ns() // 1_000_000}"
    job_folder = PROJECT_ROOT / "outputs" / job_id
    source_folder = job_folder / "source"
    source_folder.mkdir(parents=True)
    _write_json(source_folder / "profile_snapshot.json", profile.model_dump())
    (source_folder / "job_description.txt").write_text(job_description, encoding="utf-8")
    _write_json(source_folder / "drafts.json", {"drafts": drafts})
    latex = create_latex_renderer(outputs_dir=str(job_folder))
    docx = create_docx_renderer(outputs_dir=str(job_folder))
    position = role_title or cl.role_title
    page_count = 0
    history = []

    def save_content():
        _write_json(source_folder / "content.json", {
            "company_name": cl.company_name, "role_title": position,
            "work_country": work_country,
            "cv": cv.model_dump(), "cover_letter": cl.model_dump(),
        })

    try:
        for attempt in range(4):
            save_content()
            cv_path = latex.render_cv(cv, profile, job_position=position)
            page_count = _count_pdf_pages(Path(cv_path))
            history.append(page_count)
            if page_count <= 2:
                break
            if attempt == 3:
                raise ValueError(f"CV is still {page_count} pages after four layout attempts. Editable drafts are saved at {source_folder}; generation was not marked successful.")
            if status_callback:
                status_callback(f"CV is {page_count} pages; shortening content...")
            # Revise the CURRENT candidate, with increasingly strong reductions.
            # Use the identical complete-JSON parser and validation on every attempt.
            budget = max(400, 650 - attempt * 100)
            cv, data = generate(
                cv_prompt
                + f"\nLAYOUT CORRECTION: The current CV rendered to {page_count} pages. "
                f"Reduce its body text to approximately {budget} words or fewer. "
                "Prioritize concise responsibilities; reduce repetitive bullets and less relevant project detail. "
                "Keep all employers and exact dates, education and core skills. "
                "Keep one Aklamio attribution project with three concise bullets; other projects can be summarized in role bullets. "
                "Do not change facts, shrink the font, or turn ongoing work into completed work. "
                "Return the complete shorter CV JSON, not just changes.\nCURRENT CV:\n"
                + cv.model_dump_json(indent=2),
                "cv",
            )
            explanation = _extract_explanation(data) or explanation
        cl_path, cl_pdf_path = docx.render_cover_letter(cl, profile, job_position=position)
        if not cl_pdf_path:
            raise ValueError("Cover-letter PDF rendering failed.")
        cl_pages = _count_pdf_pages(Path(cl_pdf_path))
        if cl_pages != 1:
            raise ValueError(f"Cover-letter PDF is {cl_pages} pages; expected one page.")
    except Exception as error:
        save_content()
        _write_json(source_folder / "drafts.json", {"drafts": drafts})
        _write_json(source_folder / "generation_result.json", {
            "job_id": job_id, "status": "failed", "error": str(error),
            "cv_page_history": history,
        })
        raise

    # Separate CV/letter usage and include every review and shortening attempt.
    usage = service.calculate_token_usage(
        cv_input_tokens=counts["cv"][0], cv_output_tokens=counts["cv"][1],
        cl_input_tokens=counts["cover_letter"][0], cl_output_tokens=counts["cover_letter"][1],
        cv_attempts=counts["cv"][2], cl_attempts=counts["cover_letter"][2],
    )
    explanation_dict = TailoringExplanation.model_validate(explanation).model_dump() if isinstance(explanation, dict) else None
    result = TailorResponse(
        job_id=job_id, cv_path=str(cv_path), cover_letter_path=str(cl_path),
        cl_pdf_path=str(cl_pdf_path), token_usage=usage,
        cv_page_count=page_count, cover_letter_page_count=cl_pages,
        source_path=str(source_folder / "content.json"),
        tailoring_explanation=explanation_dict,
        message=f"CV checked: {page_count} pages. Cover letter: {cl_pages} page, {sum(len(p.split()) for p in cl.paragraphs)} words.",
    )
    _write_json(source_folder / "drafts.json", {"drafts": drafts})
    # Mirroring is read from the config at call time, never at import time.
    mirror = None
    if config.is_mirroring:
        mirror = config.outputs_dir / job_id
        if mirror != job_folder.resolve():
            mirror.mkdir(parents=True, exist_ok=True)
            for key in ("cv_path", "cover_letter_path", "cl_pdf_path"):
                original = Path(getattr(result, key))
                shutil.copy2(original, mirror / original.name)
                setattr(result, key, str(mirror / original.name))
            shutil.copytree(source_folder, mirror / "source", dirs_exist_ok=True)
    _write_json(source_folder / "generation_result.json", {**result.model_dump(), "cv_page_history": history})
    if mirror is not None and mirror != job_folder.resolve():
        shutil.copy2(source_folder / "generation_result.json", mirror / "source/generation_result.json")
    logger.info("Generated %s: %s CV pages; layout history %s", job_id, page_count, history)
    return result
