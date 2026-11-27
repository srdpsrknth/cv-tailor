"""Confirm-first claim suggestions: parsing, validation, storage and the leak guard.

The CV call may return a top-level ``suggested_claims`` list beside ``cv``. Each item is a
**question for the candidate** ("is this true of you?"), never CV content:

* they are validated against the profile (the target must exist) and invalid items are
  dropped with a log note rather than failing the generation;
* they are stored beside the application as ``source/suggested_claims.json`` and never
  rendered;
* :func:`reject_suggestion_leak` makes sure a suggestion's wording cannot reach the CV
  unless the profile already says it. Accepting a suggestion (``claim_acceptance``) writes
  it into the private profile first, which is what makes it citable.

This module does no profile writing and imports nothing heavy, so the pipeline can use it.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

SUGGESTIONS_FILENAME = "suggested_claims.json"
SCHEMA_VERSION = 1
MAX_SUGGESTIONS = 8
ATTACH_TYPES = ("experience", "experience_project", "standalone_project", "skill")
MAX_BULLET_CHARS = 320
MAX_SKILL_CHARS = 80

#: Similarity above which a CV line counts as a copy of a suggestion (or of the profile).
_NEAR_DUPLICATE = 0.86


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^\w+#]+", " ", str(text or "").casefold()).split())


def _fold(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


# --------------------------------------------------------------------------- targets


def find_target(profile, attach_to: dict) -> tuple[Optional[dict], str]:
    """Resolve ``attach_to`` against a loaded profile.

    Returns ``(canonical_attach_to, "")`` using the profile's own spelling, or
    ``(None, reason)`` when the target does not exist.
    """
    if not isinstance(attach_to, dict):
        return None, "attach_to is not an object"
    kind = str(attach_to.get("type") or "").strip()
    if kind not in ATTACH_TYPES:
        return None, f"unknown attach_to type {kind!r}"
    company = attach_to.get("company")
    project = attach_to.get("project")
    category = attach_to.get("category")

    if kind in ("experience", "experience_project"):
        if not company:
            return None, "attach_to.company is required"
        matches = [
            e for e in profile.experience
            if _fold(e.company) == _fold(company)
            or (e.display_name and _fold(e.display_name) == _fold(company))
        ]
        if len(matches) != 1:
            return None, f"no single experience entry named {company!r}"
        entry = matches[0]
        if kind == "experience":
            return {"type": kind, "company": entry.company}, ""
        if not project:
            return None, "attach_to.project is required"
        for item in entry.selected_projects:
            if _fold(item.name) == _fold(project):
                return {"type": kind, "company": entry.company, "project": item.name}, ""
        return None, f"no project {project!r} under {entry.company!r}"

    if kind == "standalone_project":
        if not project:
            return None, "attach_to.project is required"
        for item in profile.standalone_projects:
            if _fold(item.name) == _fold(project):
                return {"type": kind, "project": item.name}, ""
        return None, f"no standalone project {project!r}"

    if not category:
        return None, "attach_to.category is required"
    for name in profile.skills:
        if _fold(name) == _fold(category):
            return {"type": kind, "category": name}, ""
    return None, f"no skills category {category!r}"


def target_texts(profile, attach_to: dict) -> list[str]:
    """The text items already present at a canonical target."""
    kind = attach_to["type"]
    if kind == "experience":
        entry = next(e for e in profile.experience if e.company == attach_to["company"])
        return list(entry.bullets)
    if kind == "experience_project":
        entry = next(e for e in profile.experience if e.company == attach_to["company"])
        return list(next(p for p in entry.selected_projects if p.name == attach_to["project"]).bullets)
    if kind == "standalone_project":
        return list(next(p for p in profile.standalone_projects if p.name == attach_to["project"]).bullets)
    return list(profile.skills[attach_to["category"]])


def describe_target(attach_to: dict) -> str:
    kind = attach_to.get("type")
    if kind == "experience":
        return f"experience '{attach_to.get('company')}'"
    if kind == "experience_project":
        return f"project '{attach_to.get('project')}' at '{attach_to.get('company')}'"
    if kind == "standalone_project":
        return f"standalone project '{attach_to.get('project')}'"
    return f"skills category '{attach_to.get('category')}'"


# --------------------------------------------------------------------------- parsing


def raw_suggestions(data: Any) -> list:
    """The ``suggested_claims`` value from a parsed CV response, wherever it was put."""
    if not isinstance(data, dict):
        return []
    value = data.get("suggested_claims")
    if value is None and isinstance(data.get("cv"), dict):
        value = data["cv"].get("suggested_claims")
    return value if isinstance(value, list) else []


def suggestions_from_drafts(drafts: Iterable[dict]) -> list:
    """Recover the suggestions of the first CV draft (used when a cache hit skips the call)."""
    from services.cv_delta import parse_json_response

    for draft in drafts or []:
        if isinstance(draft, dict) and draft.get("component") == "cv":
            try:
                return raw_suggestions(parse_json_response(draft.get("response") or ""))
            except (ValueError, TypeError):
                return []
    return []


def validate_suggestions(raw: Any, profile) -> tuple[list[dict], list[dict]]:
    """Split a raw list into ``(kept, dropped)``. Never raises.

    Dropped items keep a ``reason`` and are logged. At most :data:`MAX_SUGGESTIONS` are
    kept; extras are dropped. Duplicates and text the profile already states at the
    target are dropped too, because asking the candidate about a fact the profile has is
    noise.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    if raw is None or raw == []:
        return kept, dropped
    if not isinstance(raw, list):
        dropped.append({"item": raw, "reason": "suggested_claims is not a list"})
        logger.warning("Dropped suggested_claims: not a list.")
        return kept, dropped
    seen: set = set()
    for item in raw:
        reason = ""
        target = None
        if not isinstance(item, dict):
            reason = "not an object"
        else:
            text = " ".join(str(item.get("proposed_text") or "").split())
            requirement = " ".join(str(item.get("requirement") or "").split())
            rationale = " ".join(str(item.get("rationale") or "").split())
            target, reason = find_target(profile, item.get("attach_to"))
            limit = MAX_SKILL_CHARS if target and target["type"] == "skill" else MAX_BULLET_CHARS
            if not reason and (not text or not requirement):
                reason = "requirement and proposed_text are required"
            elif not reason and len(text) > limit:
                reason = f"proposed_text is longer than {limit} characters"
            elif not reason and any(_norm(text) == _norm(t) for t in target_texts(profile, target)):
                reason = "the profile already states this at the target"
            elif not reason and (target["type"], tuple(sorted(target.items())), _norm(text)) in seen:
                reason = "duplicate suggestion"
            elif not reason and len(kept) >= MAX_SUGGESTIONS:
                reason = f"more than {MAX_SUGGESTIONS} suggestions"
        if reason:
            dropped.append({"item": item, "reason": reason})
            logger.warning("Dropped suggested claim: %s.", reason)
            continue
        seen.add((target["type"], tuple(sorted(target.items())), _norm(text)))
        kept.append({
            "requirement": requirement,
            "proposed_text": text,
            "attach_to": target,
            "rationale": rationale,
            "status": "pending",
        })
    return kept, dropped


# --------------------------------------------------------------------------- storage


def suggestions_path(content_path) -> Path:
    """``suggested_claims.json`` beside a ``source/content.json`` (or in a source folder)."""
    path = Path(content_path)
    folder = path if path.is_dir() else path.parent
    return folder / SUGGESTIONS_FILENAME


def save_suggestions(source_folder, kept: list[dict], dropped: list[dict]) -> Optional[Path]:
    """Write the suggestions file, or nothing when the model proposed none."""
    if not kept and not dropped:
        return None
    path = Path(source_folder) / SUGGESTIONS_FILENAME
    path.write_text(
        json.dumps(
            {"version": SCHEMA_VERSION, "suggestions": kept, "dropped": dropped},
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )
    return path


def store_from_response(source_folder, profile, raw) -> Optional[Path]:
    """Validate a raw model list against the profile and save it. Never raises.

    A failure to write the suggestions must not fail a generation whose documents are fine.
    """
    try:
        kept, dropped = validate_suggestions(raw, profile)
        return save_suggestions(source_folder, kept, dropped)
    except Exception:  # noqa: BLE001 -- suggestions are optional extras
        logger.warning("Could not store suggested claims.", exc_info=True)
        return None


def load_suggestions(content_path) -> dict:
    """The saved suggestions, or an empty record for an application without any.

    Older applications have no file; a damaged one is treated as absent rather than
    breaking the application it belongs to.
    """
    empty = {"version": SCHEMA_VERSION, "suggestions": [], "dropped": []}
    path = suggestions_path(content_path)
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        logger.warning("Could not read %s; treating as no suggestions.", path)
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("suggestions"), list):
        return empty
    data.setdefault("dropped", [])
    data["suggestions"] = [
        s for s in data["suggestions"]
        if isinstance(s, dict) and isinstance(s.get("attach_to"), dict) and s.get("proposed_text")
    ]
    return data


def write_suggestions(content_path, record: dict) -> None:
    suggestions_path(content_path).write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


# --------------------------------------------------------------------------- the guard


def _profile_lines(profile) -> list[str]:
    lines = list(profile.summary_base)
    for entry in profile.experience:
        lines += entry.bullets
        for project in entry.selected_projects:
            lines += project.bullets
    for project in profile.standalone_projects:
        lines += project.bullets
    for items in profile.skills.values():
        lines += items
    return [_norm(line) for line in lines if _norm(line)]


def _cv_lines(cv) -> list[str]:
    lines = list(cv.summary)
    for entry in cv.experience:
        lines += entry.bullets
        for project in entry.projects:
            lines += project.bullets
    for item in cv.standalone_projects:
        if not isinstance(item, str):
            lines += item.bullets
    for items in cv.skills.values():
        lines += items
    return [_norm(line) for line in lines if _norm(line)]


def _similar(a: str, b: str) -> bool:
    return a == b or difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= _NEAR_DUPLICATE


def claim_texts(raw: Any) -> list[str]:
    """The proposed texts of a raw suggestion list, for the guard."""
    return [
        " ".join(str(item.get("proposed_text") or "").split())
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict) and item.get("proposed_text")
    ]


def reject_suggestion_leak(cv, texts: Iterable[str], profile) -> None:
    """Raise ``ValueError`` if a suggestion's wording is in the CV but not in the profile.

    A suggestion is an unconfirmed question. Its text may reach a document only after the
    candidate accepted it into the profile, at which point the profile contains it and
    this check passes. Matching is on normalised text, exact or near-identical, and a
    suggestion that merely restates a profile line is allowed because the CV is entitled
    to that line.
    """
    candidates = [(text, _norm(text)) for text in texts if _norm(text)]
    if not candidates:
        return
    cv_lines = _cv_lines(cv)
    profile_lines = _profile_lines(profile)
    for original, normalised in candidates:
        if any(_similar(normalised, line) for line in profile_lines):
            continue
        if any(_similar(normalised, line) or f" {normalised} " in f" {line} " for line in cv_lines):
            raise ValueError(
                "A suggested claim was used in the CV but is not in the profile: "
                f"{original!r}. Suggested claims are questions for the candidate; keep them "
                "out of the CV and use only facts already in the profile."
            )
