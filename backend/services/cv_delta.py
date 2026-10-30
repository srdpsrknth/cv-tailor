"""Parsing a model response, and the targeted layout retry's delta.

`parse_json_response` is the one parser for drafts, letters and retries -- it accepts
wrappers around complete JSON and never repairs truncated document data. `accept_delta`
additionally accepts the retry shape, which has no document key, and is off by default
so a draft that returns a stray object still fails loudly.

The delta is merged onto the CV that was just rendered and validated, and the merged
document re-enters the same gate -- a delta has no path around `validate_cv`.
Employers, titles, dates, education, certifications and ``work_authorization`` are
**not addressable**, so no delta can invent or drop a fact.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from models.tailored_output import TailoredCV


def parse_json_response(text: str, accept_delta: bool = False) -> dict:
    """Use the same parser for first drafts, reviews, and length retries.

    Accept wrappers around complete JSON; never repair truncated document data.

    ``accept_delta`` additionally accepts the *targeted* retry shape: an object of unit
    ids such as ``{"experience[0].bullets[1]": "..."}``, which has no document key and
    would otherwise be rejected as "not a document". It is off by default and is only
    switched on for layout retries, so a draft that returns a stray object still fails
    loudly rather than being treated as a partial document. Whether the object really
    is a delta -- rather than an arbitrary JSON blob -- is then decided by
    :func:`looks_like_cv_delta`, and every key is validated by
    :func:`apply_cv_delta` before anything is merged.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned an empty document.")
    decoder = json.JSONDecoder()
    for start in [0] + [match.start() for match in re.finditer(r"\{", text)]:
        try:
            value, _ = decoder.raw_decode(text[start:].lstrip())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if any(key in value for key in ("cv", "cover_letter", "experience", "paragraphs")):
            return value
        if accept_delta and looks_like_cv_delta(value):
            return value
    raise ValueError("The model response did not contain a complete document JSON object.")

def extract_explanation(data: dict) -> Optional[dict]:
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

#: Units a delta may replace. Everything it cannot address is a fact the CV was
#: already validated on: employers, titles, dates, education, certifications, the
#: work-authorization label, and the skills categories themselves.
_DELTA_KEY_PATTERN = re.compile(
    r"^(?:"
    r"summary"
    r"|experience\[\d+\]\.bullets"
    r"|experience\[\d+\]\.bullets\[\d+\]"
    r"|experience\[\d+\]\.projects\[\d+\]\.name"
    r"|experience\[\d+\]\.projects\[\d+\]\.bullets"
    r"|experience\[\d+\]\.projects\[\d+\]\.bullets\[\d+\]"
    r"|skills\.[^.\[\]]+"
    r")$"
)

def looks_like_cv_delta(data: dict) -> bool:
    """True when a parsed retry response replaces units instead of returning the document.

    A response containing ``cv`` or ``experience`` is a complete document, which is what
    ``parse_json_response`` guarantees and what both fixture transcripts use. Anything
    else with at least one recognisable delta key is a delta. A response that is
    neither fails loudly rather than being guessed at.
    """
    if not isinstance(data, dict):
        return False
    if any(key in data for key in ("cv", "experience")):
        return False
    return bool(data) and all(isinstance(key, str) for key in data) and any(
        _DELTA_KEY_PATTERN.match(key) for key in data
    )

def _require_strings(value, key: str) -> list:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"unknown unit {key!r}: expected a string or a list of strings")
    if not any(item.strip() for item in value):
        raise ValueError(f"unknown unit {key!r}: an empty replacement would delete text")
    return value

def apply_cv_delta(cv: TailoredCV, delta: dict) -> TailoredCV:
    """Merge a delta of replacement values onto a CV, returning a new CV.

    This is why a targeted retry cannot break the promises ``validate_cv`` makes. The
    input was already accepted by the gate, and the only units a delta may address are
    prose the gate does not anchor a fact to: the summary, bullets, project names and
    the skills list. Employers, titles, dates, education, certifications and the
    work-authorization label are simply **not addressable**, so no delta can invent an
    employer, change a date, or turn ongoing work into completed work.

    A key that is not addressable, names a unit that does not exist, or carries a value
    of the wrong type raises ``ValueError``. It is never ignored: silently dropping part
    of a delta would produce a document the model did not ask for.

    The result is a *copy*; the caller's CV is left untouched, so a rejected retry
    cannot leave the accepted document half-edited.
    """
    merged = cv.model_copy(deep=True)
    unknown: list[str] = []
    for key, value in delta.items():
        if not isinstance(key, str) or not _DELTA_KEY_PATTERN.match(key):
            unknown.append(str(key))
            continue
        if key == "summary":
            merged.summary = _require_strings(value, key)
        elif key.startswith("skills."):
            merged.skills[key[len("skills."):]] = _require_strings(value, key)
        else:
            _merge_experience_unit(merged, key, value)
    if unknown:
        raise ValueError(
            "unknown unit(s) " + ", ".join(repr(item) for item in unknown)
            + ": a delta may only replace the summary, bullets, project names/bullets "
            "or an existing skills category"
        )
    return merged

def _merge_experience_unit(cv: TailoredCV, key: str, value) -> None:
    """Apply one ``experience[...]`` key, rejecting anything that does not exist."""
    failure = ValueError(f"unknown unit {key!r}: no such unit in the current CV")
    match = re.match(
        r"^experience\[(\d+)\](?:\.bullets(?:\[(\d+)\])?|\.projects\[(\d+)\]"
        r"\.(?:name|bullets(?:\[(\d+)\])?))$",
        key,
    )
    if match is None:
        raise failure
    exp_index, bullet_index, project_index, project_bullet_index = match.groups()
    if int(exp_index) >= len(cv.experience):
        raise failure
    exp = cv.experience[int(exp_index)]

    if bullet_index is not None:
        if int(bullet_index) >= len(exp.bullets):
            raise failure
        exp.bullets[int(bullet_index)] = _require_strings(value, key)[0]
        return
    if project_index is None:
        exp.bullets = _require_strings(value, key)
        return

    if int(project_index) >= len(exp.projects):
        raise failure
    project = exp.projects[int(project_index)]
    if project_bullet_index is not None:
        if int(project_bullet_index) >= len(project.bullets):
            raise failure
        project.bullets[int(project_bullet_index)] = _require_strings(value, key)[0]
    elif key.endswith(".name"):
        project.name = _require_strings(value, key)[0]
    else:
        project.bullets = _require_strings(value, key)
