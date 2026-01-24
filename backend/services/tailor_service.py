# cv-tailor/backend/services/tailor_service.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pypdf import PdfReader

from dotenv import load_dotenv

from models.requests import TailorResponse, TokenUsage
from models.tailored_output import TailoredOutput
from models.profile import Profile
from renderers import create_latex_renderer, create_docx_renderer
from services.gemini_service import GeminiService, GeminiServiceError


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tailor_prompt.md"
STYLE_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "cover_letter_examples"


def tailor_documents(
    job_description: str,
    profile: Profile,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
) -> TailorResponse:
    """
    Use Gemini to tailor CV + cover letter, then render PDF/DOCX.
    """
    if not job_description or not job_description.strip():
        raise ValueError("Job description is empty.")

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    style_snippet = _extract_style_snippet()
    style_block = ""
    if style_snippet:
        style_block = (
            "STYLE SNIPPET (tone/structure inspiration — do NOT copy; output MUST be JSON only):\n"
            f"{style_snippet}\n"
            "Note: Use this cadence and specificity as inspiration; personalize to the provided JD and base profile. Do NOT output this snippet. Return ONLY valid JSON.\n\n"
        )

    base_prompt = (
        f"{prompt_template}\n\n"
        f"{style_block}"
        f"COMPANY: {company_name or 'N/A'}\n"
        f"ROLE: {role_title or 'N/A'}\n"
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"BASE PROFILE (JSON):\n{profile.model_dump_json(indent=2)}"
    )

    # Gemini doesn't support additionalProperties, so we skip schema validation
    # and rely on Pydantic validation after parsing
    response_schema = None

    service = GeminiService()

    def _extract_json_block(text: str) -> Optional[str]:
        """Best-effort extraction of the outermost JSON object from text."""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = text[start:end + 1]
        # Quick sanity: attempt to load
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            return None

    # Try up to 3 attempts to obtain valid JSON
    response_text = ""
    input_tokens = 0
    output_tokens = 0
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            prompt = base_prompt
            if attempt > 0:
                prompt += "\n\nSTRICT: Return ONLY valid JSON matching the expected structure. No markdown, no comments, no trailing text."

            response_text, input_tokens, output_tokens = service._call_gemini(
                prompt,
                response_schema=None,
            )

            # First, try direct parse
            try:
                data = json.loads(response_text)
            except Exception:
                # Attempt to extract a JSON block
                extracted = _extract_json_block(response_text)
                if not extracted:
                    raise
                data = json.loads(extracted)

            tailored_output = TailoredOutput.model_validate(data)
            break  # success

        except Exception as e:
            last_error = e
            tailored_output = None  # type: ignore
            continue

    if not 'tailored_output' in locals() or tailored_output is None:
        raise ValueError(f"Model did not return valid JSON. Raw output:\n{response_text}")

    # Render documents
    latex = create_latex_renderer()
    docx = create_docx_renderer()

    job_position = role_title or tailored_output.cover_letter.role_title or tailored_output.cv.title

    cv_path = latex.render_cv(
        tailored_cv=tailored_output.cv,
        profile=profile,
        job_position=job_position,
    )

    cl_path = docx.render_cover_letter(
        tailored_cl=tailored_output.cover_letter,
        profile=profile,
        job_position=job_position,
    )

    token_usage = service.calculate_token_usage(
        cv_input_tokens=input_tokens,
        cv_output_tokens=output_tokens,
        cl_input_tokens=0,
        cl_output_tokens=0,
    )

    job_id = Path(cv_path).stem

    return TailorResponse(
        job_id=job_id,
        status="success",
        cv_path=str(cv_path),
        cover_letter_path=str(cl_path),
        token_usage=token_usage,
        message=None,
    )


def _extract_style_snippet(min_words: int = 120, max_words: int = 180) -> Optional[str]:
    """
    Extract a short text snippet from a cover letter example PDF to guide tone/structure.
    Returns a single paragraph string or None if not available.
    """
    try:
        if not STYLE_EXAMPLES_DIR.exists():
            return None

        # Prefer a generic/example file if present
        preferred = [
            "2026_CoverLetter_GENERIC.pdf",
        ]

        pdf_path: Optional[Path] = None
        for name in preferred:
            candidate = STYLE_EXAMPLES_DIR / name
            if candidate.exists():
                pdf_path = candidate
                break

        if pdf_path is None:
            pdfs = sorted(STYLE_EXAMPLES_DIR.glob("*.pdf"))
            if not pdfs:
                return None
            pdf_path = pdfs[0]

        reader = PdfReader(str(pdf_path))
        text_chunks = []
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
                if page_text:
                    text_chunks.append(page_text)
            except Exception:
                continue

        if not text_chunks:
            return None

        words = " ".join(text_chunks).split()
        if len(words) < min_words:
            return None

        snippet_words = words[:max_words]
        snippet = " ".join(snippet_words)
        return snippet.strip()

    except Exception:
        return None
