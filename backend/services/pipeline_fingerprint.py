"""What else, besides the prompt files and the profile, shapes a generated document.

The generation cache key already hashes the prompt files, the profile bytes, the schemas,
the models and the rules. Four more inputs change the *bytes the model is shown* or the
document that is accepted, and were missing, so editing them served stale drafts:

* the editorial requirements injected into the CV prompt (``prompts.EDITORIAL_REQUIREMENTS``);
* the wording built in code -- the context block, the CV prompt and the layout-retry brief;
* the layout reduction percentage and retry limits, which decide
  how hard a long CV is shortened;
* the CV template, whose rendered length decides whether a draft passes the page gate;
* the source of the validators (validation, fact_checks, cv_structure and the suggested-claims
  leak guard), which decide whether a draft is accepted.

Like the prompt files these are hashed at call time rather than tracked by a version
constant a change could forget to bump. Everything is normalised so the digest is the same
on Windows and macOS: line endings are folded to LF before hashing, and code is hashed as
source text rather than as bytecode.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The CV template that sets how much text fits on two pages.
CV_TEMPLATE_PATH = PROJECT_ROOT / "templates/cv/main.tex.jinja2"


def _lf(data) -> str:
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    return text.replace("\r\n", "\n").replace("\r", "\n")


def template_digest(path: Optional[Path] = None) -> str:
    """Digest of the CV template's bytes, CRLF folded to LF; ``""`` when unreadable."""
    try:
        data = (path or CV_TEMPLATE_PATH).read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(_lf(data).encode("utf-8")).hexdigest()


def _source(obj) -> str:
    try:
        return _lf(inspect.getsource(obj))
    except (OSError, TypeError):
        return repr(obj)


def pipeline_fingerprint(template_path: Optional[Path] = None) -> str:
    """One digest of the editorial text, prompt-building code, budgets and CV template."""
    from services import cv_structure, fact_checks, pipeline, prompts, suggested_claims, validation

    wording = [
        prompts.build_context,
        prompts.build_cv_prompt,
        prompts.candidate_guidance_block,
        prompts.layout_correction_instruction,
        prompts.layout_retry_instruction,
        prompts.layout_inventory,
        prompts.pinned_project_clause,
        prompts.layout_budget,
        prompts.cv_body_words,
        prompts._cv_prose_counts,
    ]
    leak_guard = [
        suggested_claims._norm,
        suggested_claims._fold,
        suggested_claims._profile_lines,
        suggested_claims._cv_lines,
        suggested_claims._similar,
        suggested_claims.claim_texts,
        suggested_claims.reject_suggestion_leak,
    ]
    payload = {
        "editorial_requirements": _lf(prompts.EDITORIAL_REQUIREMENTS),
        "layout_retry_marker": prompts.LAYOUT_RETRY_MARKER,
        "wording": [_source(fn) for fn in wording],
        "budget": {
            "LAYOUT_REDUCTION_PERCENT": prompts.LAYOUT_REDUCTION_PERCENT,
            "MAX_LAYOUT_ATTEMPTS": pipeline.MAX_LAYOUT_ATTEMPTS,
            "MAX_VALIDATION_ATTEMPTS": pipeline.MAX_VALIDATION_ATTEMPTS,
        },
        "template": template_digest(template_path),
        # Tightening a validator changes which drafts are accepted, so cached drafts
        # accepted by the old rules must not be served.
        "validators": [_source(module) for module in (validation, fact_checks, cv_structure)]
        + [_source(fn) for fn in leak_guard],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
