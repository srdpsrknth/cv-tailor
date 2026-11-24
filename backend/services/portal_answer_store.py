"""Atomic append-only editor revisions scoped to one saved application."""

import os
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints

from config import Config
from models.portal_answers import AnswerEdit, AnswerQuestion, AnswerSheet, PublicAnswerSource
from services.application_review import application_folder
from services.profile_store import UnknownProfileError, validate_profile_id


REVISION_NAME = re.compile(r"[a-f0-9]{32}\.json")
MAX_REVISION_BYTES = 2_000_000
RevisionId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class AnswerSheetConflict(ValueError):
    """The editor must reload or recover its saved history before saving again."""


class _Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    parent_revision: RevisionId | None = None
    revision: RevisionId
    saved_at: datetime
    sheet: AnswerSheet


def _answer_directory(config: Config, profile_id: str, job_id: str) -> Path:
    store = config.store
    if not store.exists(profile_id):
        raise UnknownProfileError(store.unknown_message(profile_id))
    directory = application_folder(config, profile_id, job_id) / "source" / "portal_answers"
    if directory.resolve() != directory:
        raise ValueError("Answer history resolves outside its application directory.")
    return directory


def _read_sheet(directory: Path, profile_id: str, job_id: str) -> AnswerSheet:
    sheet = AnswerSheet(profile_id=profile_id, job_id=job_id)
    if not directory.exists():
        return sheet

    warnings = set()
    history = {}
    for path in directory.iterdir():
        if ".sync-conflict-" in path.name.lower():
            warnings.add("A sync conflict copy exists in answer history. Recover the competing edits before saving.")
            continue
        if not REVISION_NAME.fullmatch(path.name):
            continue
        try:
            if path.resolve() != path or path.stat().st_size > MAX_REVISION_BYTES:
                raise ValueError("Unsafe or oversized revision.")
            revision = _Revision.model_validate_json(path.read_bytes())
            saved = revision.sheet
            if (revision.revision != path.stem or saved.revision != revision.revision
                    or saved.profile_id != profile_id or saved.job_id != job_id or saved.warnings):
                raise ValueError("Mismatched revision identity.")
        except (OSError, ValueError):
            warnings.add("A saved answer revision could not be read. Recover it before saving.")
            continue
        history[revision.revision] = revision

    children = defaultdict(list)
    for revision in history.values():
        children[revision.parent_revision].append(revision.revision)

    visited = set()
    while len(children[sheet.revision]) == 1:
        revision_id = children[sheet.revision][0]
        if revision_id in visited:
            break
        visited.add(revision_id)
        sheet = history[revision_id].sheet

    if len(children[sheet.revision]) > 1:
        warnings.add("Answer edits diverged. Both histories are preserved. Resolve the competing revisions before saving.")
    elif len(visited) != len(history):
        warnings.add("Answer history is incomplete or still syncing. Wait for the missing revisions before saving.")
    return sheet.model_copy(update={"warnings": sorted(warnings)})


def load_answer_sheet(config: Config, *, profile_id: str, job_id: str) -> AnswerSheet:
    """Open the last unambiguous editor revision; do not modify files on read."""
    profile_id = validate_profile_id(profile_id)
    return _read_sheet(_answer_directory(config, profile_id, job_id), profile_id, job_id)


def save_answer_sheet(
    config: Config,
    *,
    profile_id: str,
    job_id: str,
    expected_revision: str | None,
    questions: Sequence[AnswerQuestion],
    edits: Sequence[AnswerEdit],
    public_sources: Sequence[PublicAnswerSource] = (),
) -> AnswerSheet:
    """Save an explicit editor state. Concurrent writers keep both branch files."""
    profile_id = validate_profile_id(profile_id)
    directory = _answer_directory(config, profile_id, job_id)
    previous = _read_sheet(directory, profile_id, job_id)
    if previous.warnings:
        raise AnswerSheetConflict(previous.warnings[0])
    if previous.revision != expected_revision:
        raise AnswerSheetConflict("Saved answers changed since you opened them. Reload the latest revision before saving.")

    revision_id = uuid4().hex
    sheet = AnswerSheet(
        profile_id=profile_id, job_id=job_id, revision=revision_id, questions=list(questions),
        edits=list(edits), public_sources=list(public_sources),
    )
    if (sheet.questions, sheet.edits, sheet.public_sources) == (
        previous.questions, previous.edits, previous.public_sources,
    ):
        return previous

    revision = _Revision(
        parent_revision=previous.revision, revision=revision_id, saved_at=datetime.now(timezone.utc), sheet=sheet,
    )
    payload = revision.model_dump_json(indent=2).encode("utf-8")
    if len(payload) > MAX_REVISION_BYTES:
        raise ValueError("Saved answers exceed the revision size limit.")

    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory:
        raise ValueError("Answer history resolves outside its application directory.")
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=directory, prefix=".answer-write-", suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, directory / f"{revision_id}.json")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return _read_sheet(directory, profile_id, job_id)
