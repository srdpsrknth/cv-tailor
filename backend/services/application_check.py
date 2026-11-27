"""Offline re-check of saved applications against the *current* validators.

Validators get stricter over time (skills and numbers must come from the profile, gap
statements and tense are checked, spoken languages are not skills). This module answers
"would today's rules still accept the applications I already have?" without a network or
LLM call and without touching the store:

* every ``<store>/outputs/<profile_id>/<job_id>/source/content.json`` is loaded;
* the CV and the cover letter are run through :func:`services.validation.validate_cv` and
  :func:`services.validation.validate_cover_letter` on deep copies (the CV validator
  reorders and rewrites in place, so the saved model is never handed to it);
* optionally each application is re-rendered into a temporary folder that is deleted
  afterwards, so the saved documents are never overwritten.

Only ``outputs/<profile_id>`` holds applications (ADR 0003, ADR 0011); there is no separate
per-store ``applications/`` tree to scan.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

PASS = "PASS"
FAIL = "FAIL"


@dataclass
class ApplicationCheck:
    job_id: str
    content_path: Path
    messages: List[str] = field(default_factory=list)  #: validator or load failures
    render: Optional[dict] = None  #: ``{"cv_pages", "cover_letter_pages", "error"}`` with --render

    @property
    def render_error(self) -> Optional[str]:
        return (self.render or {}).get("error")

    @property
    def passed(self) -> bool:
        return not self.messages and not self.render_error

    @property
    def status(self) -> str:
        return PASS if self.passed else FAIL

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "content": str(self.content_path),
            "status": self.status,
            "messages": list(self.messages),
            "render": self.render,
        }


def find_saved_contents(outputs_dir: Path) -> List[Path]:
    """Every ``*/source/content.json`` under one candidate's outputs, ordered by job id."""
    if not Path(outputs_dir).is_dir():
        return []
    return sorted(Path(outputs_dir).glob("*/source/content.json"), key=lambda p: p.parent.parent.name)


def _count_pages(pdf: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf)).pages)


def validate_content(data: dict, profile, rules=None) -> List[str]:
    """Run the current CV and cover-letter validators over one saved ``content.json``."""
    from models.tailored_output import TailoredCoverLetter, TailoredCV
    from services import validation

    rules = rules or validation.ProfileRules.from_profile(profile)
    try:
        cv = TailoredCV.model_validate(data["cv"])
    except KeyError:
        return ["content.json has no 'cv' document"]
    except ValueError as error:
        return [f"CV does not match the current schema: {error}"]
    try:
        cl = TailoredCoverLetter.model_validate(data["cover_letter"])
    except KeyError:
        return ["content.json has no 'cover_letter' document"]
    except ValueError as error:
        return [f"Cover letter does not match the current schema: {error}"]
    messages: List[str] = []
    for label, check, document in (
        ("CV", lambda doc: validation.validate_cv(doc, profile, rules), cv),
        ("Cover letter", lambda doc: validation.validate_cover_letter(doc, profile, rules), cl),
    ):
        try:
            check(document.model_copy(deep=True))
        except ValueError as error:
            messages.append(f"{label}: {error}")
    return messages


def render_content(data: dict, profile, *, timezone_name: Optional[str] = None) -> dict:
    """Render one saved content into a throwaway folder and report page counts.

    Returns ``{"cv_pages", "cover_letter_pages", "error"}``; a renderer failure is
    reported in ``error`` rather than raised.
    """
    from models.tailored_output import TailoredCoverLetter, TailoredCV
    from renderers import create_docx_renderer, create_latex_renderer

    report: dict = {"cv_pages": None, "cover_letter_pages": None, "error": None}
    try:
        cv = TailoredCV.model_validate(data["cv"])
        cl = TailoredCoverLetter.model_validate(data["cover_letter"])
        role = data.get("role_title") or cl.role_title
        # ignore_cleanup_errors: Windows may hold a freshly written PDF open briefly.
        with tempfile.TemporaryDirectory(prefix="cvtailor-check-", ignore_cleanup_errors=True) as tmp:
            pdf = Path(create_latex_renderer(outputs_dir=tmp).render_cv(cv, profile, job_position=role))
            report["cv_pages"] = _count_pages(pdf)
            _, cl_pdf = create_docx_renderer(
                outputs_dir=tmp, timezone_name=timezone_name
            ).render_cover_letter(cl, profile, job_position=role)
            if cl_pdf:
                report["cover_letter_pages"] = _count_pages(Path(cl_pdf))
    except Exception as error:  # noqa: BLE001 -- any renderer failure is a result, not a crash
        report["error"] = f"{type(error).__name__}: {error}"
    return report


def check_applications(
    profile,
    outputs_dir: Path,
    *,
    render: bool = False,
    timezone_name: Optional[str] = None,
    progress: Optional[Callable[[ApplicationCheck], None]] = None,
) -> List[ApplicationCheck]:
    """Check every saved application of one candidate. Reads the store, never writes to it."""
    results: List[ApplicationCheck] = []
    for content_path in find_saved_contents(outputs_dir):
        check = ApplicationCheck(job_id=content_path.parent.parent.name, content_path=content_path)
        data = None
        try:
            data = json.loads(content_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("content.json is not a JSON object")
        except (OSError, ValueError) as error:
            check.messages.append(f"Could not read content.json: {error}")
            data = None
        if data is not None:
            check.messages.extend(validate_content(data, profile))
            if render:
                check.render = render_content(data, profile, timezone_name=timezone_name)
        if progress:
            progress(check)
        results.append(check)
    return results
