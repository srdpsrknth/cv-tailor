# cv-tailor/backend/services/tailor_service.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from pypdf import PdfReader

from dotenv import load_dotenv

from models.requests import TailorResponse, TokenUsage
from models.tailored_output import TailoredOutput, TailoredCV, TailoredCoverLetter
from models.profile import Profile
from renderers import create_latex_renderer, create_docx_renderer
from services.gemini_service import GeminiService, GeminiServiceError


logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

PROMPT_CV_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tailor_cv_prompt.md"
PROMPT_CL_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tailor_cl_prompt.md"
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

    # Load CV and cover letter prompts separately
    cv_prompt_template = PROMPT_CV_PATH.read_text(encoding="utf-8")
    cl_prompt_template = PROMPT_CL_PATH.read_text(encoding="utf-8")
    
    # Extract style snippet for cover letter
    style_snippet = _extract_style_snippet()
    style_block = ""
    if style_snippet:
        style_block = (
            "STYLE SNIPPET (tone/structure inspiration — do NOT copy; output MUST be JSON only):\n"
            f"{style_snippet}\n"
            "Note: Use this cadence and specificity as inspiration; personalize to the provided JD and base profile. Do NOT output this snippet. Return ONLY valid JSON.\n\n"
        )

    cv_prompt = (
        f"{cv_prompt_template}\n\n"
        f"COMPANY: {company_name or 'N/A'}\n"
        f"ROLE: {role_title or 'N/A'}\n"
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"BASE PROFILE (JSON):\n{profile.model_dump_json(indent=2)}"
    )

    cl_prompt = (
        f"{cl_prompt_template}\n\n"
        f"{style_block}"
        f"COMPANY: {company_name or 'N/A'}\n"
        f"ROLE: {role_title or 'N/A'}\n"
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"BASE PROFILE (JSON):\n{profile.model_dump_json(indent=2)}"
    )

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
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            return None

    # ========== CV GENERATION ==========
    response_text_cv = ""
    input_tokens_cv = 0
    output_tokens_cv = 0
    tailored_cv = None
    cv_error_log = []
    
    for attempt in range(3):
        try:
            prompt = cv_prompt
            if attempt > 0:
                prompt += "\n\nSTRICT: Return ONLY valid JSON matching the expected structure. No markdown, no comments, no trailing text."

            response_text_cv, input_tokens_cv, output_tokens_cv = service._call_gemini(
                prompt,
                response_schema=None,
            )

            logger.info(f"[CV Gen Attempt {attempt+1}] Raw response length: {len(response_text_cv)} chars")
            logger.info(f"[CV Gen Attempt {attempt+1}] First 200 chars: {response_text_cv[:200]}")

            try:
                data = json.loads(response_text_cv)
                logger.info(f"[CV Gen Attempt {attempt+1}] JSON parsed successfully")
            except json.JSONDecodeError as je:
                logger.warning(f"[CV Gen Attempt {attempt+1}] JSON decode error at pos {je.pos}: {je.msg}")
                # Try extracting JSON block
                extracted = _extract_json_block(response_text_cv)
                if not extracted:
                    cv_error_log.append(f"Attempt {attempt+1}: Could not extract JSON block. Raw error: {str(je)}")
                    raise
                logger.info(f"[CV Gen Attempt {attempt+1}] Extracted JSON block, length: {len(extracted)}")
                data = json.loads(extracted)

            cv_data = data.get("cv", data)
            logger.info(f"[CV Gen Attempt {attempt+1}] CV data keys: {list(cv_data.keys())}")
            logger.info(f"[CV Gen Attempt {attempt+1}] Experience count: {len(cv_data.get('experience', []))}")
            
            # Debug: Check projects in first experience
            if cv_data.get('experience'):
                first_exp = cv_data['experience'][0]
                logger.info(f"[CV Gen Attempt {attempt+1}] First experience keys: {list(first_exp.keys())}")
                if 'projects' in first_exp:
                    logger.info(f"[CV Gen Attempt {attempt+1}] Projects count in first exp: {len(first_exp['projects'])}")
                    if first_exp['projects']:
                        logger.info(f"[CV Gen Attempt {attempt+1}] First project: {first_exp['projects'][0]}")

            tailored_cv = TailoredCV.model_validate(cv_data)
            logger.info(f"[CV Gen Attempt {attempt+1}] ✅ Validation passed!")
            break

        except Exception as e:
            error_msg = f"Attempt {attempt+1}: {type(e).__name__}: {str(e)}"
            cv_error_log.append(error_msg)
            logger.error(f"[CV Gen Attempt {attempt+1}] ❌ {error_msg}")
            continue

    if tailored_cv is None:
        log_msg = "\n".join(cv_error_log)
        full_error = (
            f"Failed to generate valid CV JSON after 3 attempts.\n"
            f"Errors:\n{log_msg}\n\n"
            f"Last response (first 1000 chars):\n{response_text_cv[:1000]}"
        )
        logger.error(full_error)
        raise ValueError(full_error)

    # ========== COVER LETTER GENERATION ==========
    response_text_cl = ""
    input_tokens_cl = 0
    output_tokens_cl = 0
    tailored_cl = None
    cl_error_log = []
    
    for attempt in range(3):
        try:
            prompt = cl_prompt
            if attempt > 0:
                prompt += "\n\nSTRICT: Return ONLY valid JSON matching the expected structure. No markdown, no comments, no trailing text."

            response_text_cl, input_tokens_cl, output_tokens_cl = service._call_gemini(
                prompt,
                response_schema=None,
            )

            logger.info(f"[CL Gen Attempt {attempt+1}] Raw response length: {len(response_text_cl)} chars")
            logger.info(f"[CL Gen Attempt {attempt+1}] First 200 chars: {response_text_cl[:200]}")

            try:
                data = json.loads(response_text_cl)
                logger.info(f"[CL Gen Attempt {attempt+1}] JSON parsed successfully")
            except json.JSONDecodeError as je:
                logger.warning(f"[CL Gen Attempt {attempt+1}] JSON decode error at pos {je.pos}: {je.msg}")
                # Try extracting JSON block
                extracted = _extract_json_block(response_text_cl)
                if not extracted:
                    cl_error_log.append(f"Attempt {attempt+1}: Could not extract JSON block. Raw error: {str(je)}")
                    raise
                logger.info(f"[CL Gen Attempt {attempt+1}] Extracted JSON block, length: {len(extracted)}")
                data = json.loads(extracted)

            cl_data = data.get("cover_letter", data)
            logger.info(f"[CL Gen Attempt {attempt+1}] CL data keys: {list(cl_data.keys())}")

            tailored_cl = TailoredCoverLetter.model_validate(cl_data)
            
            # Validate exactly 4 paragraphs as per prompt requirements
            if len(tailored_cl.paragraphs) != 4:
                error_msg = f"Expected exactly 4 paragraphs, got {len(tailored_cl.paragraphs)}"
                logger.warning(f"[CL Gen Attempt {attempt+1}] ⚠️  {error_msg}")
                if attempt < 2:  # Retry on validation failure
                    cl_error_log.append(f"Attempt {attempt+1}: {error_msg}")
                    continue
                else:
                    # On final attempt, log warning but accept it
                    logger.warning(f"[CL Gen Attempt {attempt+1}] Accepting {len(tailored_cl.paragraphs)} paragraphs on final attempt")
            
            logger.info(f"[CL Gen Attempt {attempt+1}] ✅ Validation passed! Paragraphs count: {len(tailored_cl.paragraphs)}")
            break

        except Exception as e:
            error_msg = f"Attempt {attempt+1}: {type(e).__name__}: {str(e)}"
            cl_error_log.append(error_msg)
            logger.error(f"[CL Gen Attempt {attempt+1}] ❌ {error_msg}")
            continue

    if tailored_cl is None:
        log_msg = "\n".join(cl_error_log)
        full_error = (
            f"Failed to generate valid cover letter JSON after 3 attempts.\n"
            f"Errors:\n{log_msg}\n\n"
            f"Last response (first 1000 chars):\n{response_text_cl[:1000]}"
        )
        logger.error(full_error)
        raise ValueError(full_error)

    # Create combined output
    tailored_output = TailoredOutput(
        cv=tailored_cv,
        cover_letter=tailored_cl,
        confidence="high",
        notes=[]
    )
    
    input_tokens = input_tokens_cv + input_tokens_cl
    output_tokens = output_tokens_cv + output_tokens_cl

    # Create job-specific folder
    from uuid import uuid4
    job_id = str(uuid4())[:8]
    outputs_base = Path(__file__).resolve().parents[2] / "outputs"
    job_folder = outputs_base / job_id
    job_folder.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Created job folder: {job_folder}")

    # Render documents
    latex = create_latex_renderer(outputs_dir=str(job_folder))
    docx = create_docx_renderer(outputs_dir=str(job_folder))

    job_position = role_title or tailored_output.cover_letter.role_title or tailored_output.cv.title

    cv_path = latex.render_cv(
        tailored_cv=tailored_output.cv,
        profile=profile,
        job_position=job_position,
    )

    cl_path, cl_pdf_path = docx.render_cover_letter(
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

    return TailorResponse(
        job_id=job_id,
        status="success",
        cv_path=str(cv_path),
        cover_letter_path=str(cl_path),
        cl_pdf_path=str(cl_pdf_path) if cl_pdf_path else None,
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
