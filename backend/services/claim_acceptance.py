"""Accept (or reject) suggested claims: write confirmed statements into the PRIVATE profile.

Used by both the CLI (``cvtailor claims accept``) and the UI. The candidate has confirmed
the statement is true; this module then

1. resolves each chosen suggestion to a list in the profile (an experience entry's bullets,
   a project's bullets, or a skills category);
2. computes the new YAML with a **targeted text insertion** so comments and layout survive
   (``services.profile_text_edit``), falling back to a full ``yaml.safe_dump`` only when
   the file's shape is not one the editor handles safely, and saying so in a warning;
3. saves ``profile.backup-<timestamp>.yaml`` beside the profile, writes the result, reloads
   it through the real profile validator, and **restores the backup** if anything is off;
4. records each decision in the application's ``source/suggested_claims.json``.

Suggestion numbers are **1-based**, matching ``claims list`` and the UI.
"""
from __future__ import annotations

import copy
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

import yaml

from services import suggested_claims as claims
from services.profile_text_edit import Unsupported, add_mapping_list, insert_list_item

logger = logging.getLogger(__name__)

APPROACH_TARGETED = "targeted-insert"
APPROACH_FULL_DUMP = "full-dump"
MAX_CONFIRMED_TEXT = 1600


class ClaimError(ValueError):
    """The request cannot be carried out; nothing was changed (or it was rolled back)."""


def confirmed_claim_text(text: str, kind: str) -> str:
    """Validate an editable statement before previewing or storing it."""
    text = " ".join(text.split())
    limit = claims.MAX_SKILL_CHARS if kind == "skill" else MAX_CONFIRMED_TEXT
    if not text or len(text) > limit or claims._is_question(text):
        raise ClaimError(f"Enter a factual statement of 1–{limit} characters.")
    return text


@dataclass
class Change:
    number: int
    attach_to: dict
    text: str
    description: str


@dataclass
class AcceptanceResult:
    changes: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # (number, reason)
    approach: str = "none"
    warnings: list = field(default_factory=list)
    backup: Optional[Path] = None
    profile_path: Optional[Path] = None
    dry_run: bool = False
    new_text: str = ""

    @property
    def accepted(self) -> list:
        return [change.number for change in self.changes]

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "skipped": [{"number": n, "reason": r} for n, r in self.skipped],
            "changes": [c.description for c in self.changes],
            "approach": self.approach,
            "warnings": self.warnings,
            "backup": str(self.backup) if self.backup else None,
            "profile": str(self.profile_path) if self.profile_path else None,
            "dry_run": self.dry_run,
        }


# --------------------------------------------------------------------------- helpers


def application_profile_id(content_path) -> Optional[str]:
    """The profile id an application folder belongs to, when it sits in ``outputs/<id>/<job>``."""
    parts = Path(content_path).resolve()
    parts = parts if parts.is_dir() else parts.parent
    folder = parts.parent if parts.name == "source" else parts
    if folder.parent.parent.name == "outputs":
        return folder.parent.name
    return None


def _check_owner(content_path, expected_profile_id: Optional[str]) -> None:
    owner = application_profile_id(content_path)
    if expected_profile_id and owner and owner != expected_profile_id:
        raise ClaimError(
            f"This application belongs to profile {owner!r}, not {expected_profile_id!r}. "
            "Refusing to write another candidate's claims into this profile."
        )


def _select(record: dict, numbers: Sequence[int]) -> list[tuple[int, dict]]:
    suggestions = record["suggestions"]
    chosen: list[tuple[int, dict]] = []
    for number in dict.fromkeys(numbers):  # keep order, drop repeats
        if not isinstance(number, int) or not 1 <= number <= len(suggestions):
            raise ClaimError(
                f"No suggestion number {number!r}; this application has {len(suggestions)}."
            )
        chosen.append((number, suggestions[number - 1]))
    if not chosen:
        raise ClaimError("No suggestions chosen.")
    return chosen


def _entry_index(data: dict, company: str) -> int:
    for index, entry in enumerate(data.get("experience") or []):
        if isinstance(entry, dict) and str(entry.get("company", "")).casefold() == company.casefold():
            return index
    raise ClaimError(f"Experience entry {company!r} is no longer in the profile.")


def _named_index(items, name: str, what: str) -> int:
    for index, item in enumerate(items or []):
        if isinstance(item, dict) and str(item.get("name", "")).casefold() == name.casefold():
            return index
    raise ClaimError(f"{what} {name!r} is no longer in the profile.")


def _resolve(data: dict, attach_to: dict, category: Optional[str]):
    """``(path, new_category)`` of the list a suggestion appends to.

    ``new_category`` is the name to create when the user explicitly named a category the
    profile lacks; otherwise ``None``. A path is a tuple of keys/indices into the YAML.
    """
    kind = attach_to["type"]
    if kind == "experience":
        return ("experience", _entry_index(data, attach_to["company"]), "bullets"), None
    if kind == "experience_project":
        i = _entry_index(data, attach_to["company"])
        j = _named_index(data["experience"][i].get("selected_projects"), attach_to["project"], "Project")
        return ("experience", i, "selected_projects", j, "bullets"), None
    if kind == "standalone_project":
        j = _named_index(data.get("standalone_projects"), attach_to["project"], "Standalone project")
        return ("standalone_projects", j, "bullets"), None
    skills = data.get("skills") or {}
    wanted = category or attach_to.get("category")
    for name in skills:
        if str(name).casefold() == str(wanted).casefold():
            return ("skills", name), None
    if category:  # explicitly named by the user: the only way a category is created
        return ("skills", category), category
    raise ClaimError(f"Skills category {wanted!r} is no longer in the profile.")


def _get(data, path):
    node = data
    for part in path:
        node = node[part]
    return node


def _apply_to_data(data: dict, path, new_category: Optional[str], text: str) -> None:
    if new_category and new_category not in (data.get("skills") or {}):
        data.setdefault("skills", {})[new_category] = [text]
        return
    target = _get(data, path[:-1])
    if target.get(path[-1]) is None:
        target[path[-1]] = []
    target[path[-1]].append(text)


def _describe(attach_to: dict, path, new_category: Optional[str]) -> str:
    where = claims.describe_target(attach_to)
    if attach_to["type"] == "skill":
        name = path[-1]
        where = f"skills category '{name}'" + (" (new category)" if new_category else "")
    return where


def _backup_path(profile_path: Path, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    candidate = profile_path.with_name(f"{profile_path.stem}.backup-{stamp}{profile_path.suffix}")
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = profile_path.with_name(
            f"{profile_path.stem}.backup-{stamp}-{counter}{profile_path.suffix}"
        )
    return candidate


# --------------------------------------------------------------------------- planning


def plan_acceptance(
    content_path, profile_path, numbers: Sequence[int], *, category: Optional[str] = None,
    expected_profile_id: Optional[str] = None,
    edits: Optional[Mapping[int, str]] = None,
) -> AcceptanceResult:
    """What accepting ``numbers`` would change, without writing anything."""
    from services.profile_loader import load_profile

    _check_owner(content_path, expected_profile_id)
    record = claims.load_suggestions(content_path)
    chosen = _select(record, numbers)
    profile_path = Path(profile_path)
    if not profile_path.is_file():
        raise ClaimError(f"Profile not found: {profile_path}")
    raw = profile_path.read_bytes().decode("utf-8")
    try:
        original = yaml.safe_load(raw.lstrip("﻿"))
        load_profile(str(profile_path))
    except (yaml.YAMLError, ValueError) as error:
        raise ClaimError(f"The profile is not valid before any change: {error}")
    if not isinstance(original, dict):
        raise ClaimError("The profile is not a YAML mapping.")

    result = AcceptanceResult(profile_path=profile_path, dry_run=True)
    expected = copy.deepcopy(original)
    steps: list[tuple[tuple, Optional[str], str]] = []
    for number, suggestion in chosen:
        if suggestion.get("status") == "accepted":
            result.skipped.append((number, "already accepted"))
            continue
        attach_to = dict(suggestion["attach_to"])
        text = confirmed_claim_text(
            (edits or {}).get(number, suggestion["proposed_text"]), attach_to["type"],
        )
        try:
            path, new_category = _resolve(expected, attach_to, category if attach_to["type"] == "skill" else None)
        except ClaimError as error:
            result.skipped.append((number, str(error)))
            continue
        existing = _get(expected, path[:-1]).get(path[-1]) if not new_category else None
        if any(claims._norm(text) == claims._norm(item) for item in (existing or [])):
            result.skipped.append((number, "the profile already states this at the target"))
            continue
        if attach_to["type"] == "skill":
            attach_to["category"] = path[-1]
        _apply_to_data(expected, path, new_category, text)
        steps.append((path, new_category, text))
        result.changes.append(Change(
            number, attach_to, text,
            f"#{number}: add {text!r} to {_describe(attach_to, path, new_category)}",
        ))

    if not steps:
        return result
    try:
        new_text = raw
        for path, new_category, text in steps:
            if new_category and new_category not in (yaml.safe_load(new_text.lstrip("﻿")).get("skills") or {}):
                new_text = add_mapping_list(new_text, ("skills",), new_category, [text])
            else:
                new_text = insert_list_item(new_text, path, text)
        if yaml.safe_load(new_text.lstrip("﻿")) != expected:
            raise Unsupported("the edited text does not reload to the expected data")
        result.approach = APPROACH_TARGETED
    except (Unsupported, KeyError, IndexError, TypeError, AttributeError, yaml.YAMLError) as error:
        new_text = yaml.safe_dump(expected, sort_keys=False, allow_unicode=True, width=1000)
        result.approach = APPROACH_FULL_DUMP
        result.warnings.append(
            "Could not insert into the profile's text safely "
            f"({error}); the profile will be rewritten with a full YAML dump, which drops "
            "comments and formatting. The backup keeps the original."
        )
    result.new_text = new_text
    return result


# --------------------------------------------------------------------------- acting


def accept_suggestions(
    content_path, profile_path, numbers: Sequence[int], *, category: Optional[str] = None,
    expected_profile_id: Optional[str] = None, dry_run: bool = False,
    now: Optional[datetime] = None, edits: Optional[Mapping[int, str]] = None,
) -> AcceptanceResult:
    """Write the chosen suggestions into the profile and record the decision.

    The caller is responsible for the candidate's confirmation: this function assumes the
    statements are true. Raises :class:`ClaimError`; on a failed write the original profile
    is restored from the backup before the error is raised.
    """
    from services.profile_loader import load_profile

    result = plan_acceptance(
        content_path, profile_path, numbers, category=category,
        expected_profile_id=expected_profile_id, edits=edits,
    )
    result.dry_run = dry_run
    if dry_run or not result.changes:
        return result

    profile_path = Path(profile_path)
    now = now or datetime.now(timezone.utc)
    backup = _backup_path(profile_path, now)
    shutil.copy2(profile_path, backup)
    result.backup = backup
    temporary = profile_path.with_name(profile_path.name + ".tmp")
    try:
        temporary.write_bytes(result.new_text.encode("utf-8"))
        os.replace(temporary, profile_path)
        load_profile(str(profile_path))
        reloaded = yaml.safe_load(profile_path.read_text(encoding="utf-8").lstrip("﻿"))
        expected = yaml.safe_load(result.new_text.lstrip("﻿"))
        if reloaded != expected:
            raise ValueError("the written profile does not match the intended content")
    except Exception as error:  # noqa: BLE001 -- restore on any failure, then report it
        shutil.copy2(backup, profile_path)
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ClaimError(
            f"Writing the profile failed ({error}); the original was restored from {backup.name}."
        ) from error

    _record(content_path, result, backup, now, "accepted")
    logger.info("Accepted suggested claims %s into %s (%s).", result.accepted, profile_path, result.approach)
    return result


def reject_suggestions(content_path, numbers: Sequence[int], *, now: Optional[datetime] = None) -> list:
    """Mark suggestions rejected in the application record. The profile is not touched."""
    record = claims.load_suggestions(content_path)
    chosen = _select(record, numbers)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    done = []
    for number, suggestion in chosen:
        if suggestion.get("status") == "accepted":
            continue
        suggestion["status"] = "rejected"
        suggestion["decided_at"] = stamp
        done.append(number)
    if done:
        claims.write_suggestions(content_path, record)
    return done


def _record(content_path, result: AcceptanceResult, backup: Path, now: datetime, status: str) -> None:
    try:
        record = claims.load_suggestions(content_path)
        stamp = now.isoformat(timespec="seconds")
        for change in result.changes:
            suggestion = record["suggestions"][change.number - 1]
            suggestion["status"] = status
            suggestion["decided_at"] = stamp
            suggestion["accepted_attach_to"] = change.attach_to
            suggestion["accepted_text"] = change.text
            suggestion["write"] = {"approach": result.approach, "backup": backup.name}
        claims.write_suggestions(content_path, record)
    except OSError:
        logger.warning("The profile was updated but the application record was not.", exc_info=True)
        result.warnings.append("The profile was updated, but the application's record could not be saved.")
