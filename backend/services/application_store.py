"""Persistence for generated applications.

Extracted from ``tailor_service.tailor_documents`` (A-3), which mixed LLM
orchestration, validation, layout retries, file writing and mirroring in one
296-line function. Everything that touches the filesystem for a generated
application lives here, so the generation logic can be tested without a disk
and the storage layout can change in one place.

Since Phase 2 the layout carries the candidate (ADR 0003), so two profiles on the
same posting cannot collide. ``<outputs_root>`` is ``<store>/outputs`` when the
store is authoritative (ADR 0011)::

    <store>/outputs/<profile_id>/<job_id>/
        <rendered CV and cover-letter artifacts>
        source/
            content.json            the editable text authority
            profile_snapshot.json   the profile used
            job_description.txt     the posting
            drafts.json             every raw model response
            generation_result.json  success marker and manifest

``profile_id`` is a required argument, not an optional one: a store that cannot
name its candidate cannot isolate anything.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from services.profile_store import validate_profile_id

logger = logging.getLogger(__name__)

#: Manifest keys holding artifact paths that mirroring rewrites.
ARTIFACT_KEYS = ("cv_path", "cover_letter_path", "cl_pdf_path")

#: Files written into ``source/`` that are copied when mirroring.
SOURCE_FILES = (
    "content.json",
    "profile_snapshot.json",
    "job_description.txt",
    "drafts.json",
)


def write_json(path: Path, value) -> None:
    """Write JSON with a stable, diff-friendly shape."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class ApplicationStore:
    """Owns the ``<outputs_root>/<profile_id>/<job_id>/`` folder for one generation run.

    ``outputs_root`` is the directory that *contains* the per-candidate segment --
    in practice ``<store>/outputs`` (ADR 0011), so real documents never land in the
    public repository. The candidate segment is appended here, not by the caller.
    """

    outputs_root: Path
    job_id: str
    #: Which candidate this application belongs to. Required (ADR 0003).
    profile_id: Optional[str] = None
    source_folder: Path = field(init=False)
    job_folder: Path = field(init=False)

    def __post_init__(self) -> None:
        self.outputs_root = Path(self.outputs_root)
        # Fail closed: no candidate means no folder, never a shared one.
        self.profile_id = validate_profile_id(self.profile_id)
        self.job_folder = self.outputs_root / self.profile_id / self.job_id
        self.source_folder = self.job_folder / "source"

    # --- creation ---------------------------------------------------------------------

    def create(self, profile_dump: dict, job_description: str) -> None:
        """Create the job folder and write the inputs that must survive any failure."""
        self.source_folder.mkdir(parents=True)
        write_json(self.source_folder / "profile_snapshot.json", profile_dump)
        (self.source_folder / "job_description.txt").write_text(job_description, encoding="utf-8")

    # --- incremental writes -----------------------------------------------------------

    def save_drafts(self, drafts: Iterable[dict]) -> None:
        """Persist raw model responses. Called on failure too, so work is never lost."""
        write_json(self.source_folder / "drafts.json", {"drafts": list(drafts)})

    def save_content(self, content: dict) -> None:
        """Persist the editable text authority, rewritten after each layout attempt."""
        write_json(self.source_folder / "content.json", content)

    def save_manifest(self, manifest: dict, page_history: list) -> None:
        write_json(
            self.source_folder / "generation_result.json",
            {**manifest, "cv_page_history": list(page_history)},
        )

    def save_failure(self, error: str, page_history: list) -> None:
        """Record an explicit failure manifest (D-14).

        A partial folder without a manifest is ambiguous; this marks it failed.
        """
        write_json(
            self.source_folder / "generation_result.json",
            {"job_id": self.job_id, "status": "failed", "error": error,
             "cv_page_history": list(page_history)},
        )

    def save_manifest_copy(self, destination: Path) -> None:
        """Copy the final manifest into a mirror folder.

        Called after :meth:`mirror` has already copied ``source/``, so the manifest
        written there is the pre-result one and must be refreshed.
        """
        manifest = self.source_folder / "generation_result.json"
        if manifest.exists():
            target = Path(destination) / "source" / manifest.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest, target)

    # --- mirroring (A-10) -------------------------------------------------------------

    def mirror(self, result, config) -> Optional[Path]:
        """Copy artifacts to the configured mirror, rewriting paths on ``result``.

        Returns the mirror folder, or None when mirroring is not configured or the
        mirror resolves to the job folder itself (which would copy onto itself).

        Uses ``dirs_exist_ok=True`` deliberately: a re-run must refresh an existing
        mirror rather than fail. The caller is responsible for confirming the
        configured mirror is the intended one -- a typo'd absolute path would
        otherwise write elsewhere (A-10).
        """
        if not config.is_mirroring:
            return None
        # Carry the candidate segment into the mirror as well: a mirror that dropped
        # it would reintroduce the very collision the job folder just stopped having.
        destination = Path(config.outputs_dir) / self.profile_id / self.job_id
        if destination.resolve() == self.job_folder.resolve():
            return None

        destination.mkdir(parents=True, exist_ok=True)
        for key in ARTIFACT_KEYS:
            value = getattr(result, key, None)
            if not value:
                continue
            original = Path(value)
            if not original.exists():
                continue
            shutil.copy2(original, destination / original.name)
            setattr(result, key, str(destination / original.name))
        shutil.copytree(self.source_folder, destination / "source", dirs_exist_ok=True)
        return destination


def make_job_id(company: str, role: str, slugify, profile_id: Optional[str] = None) -> str:
    """Build ``<year>_<company>_<role>_<ms>`` using the Berlin calendar year.

    The timestamp keeps concurrent applications to the same posting distinct. The
    candidate is carried by the *folder* (``outputs/<profile_id>/<job_id>/``), not
    by this slug, so two profiles applying to one posting write to different trees
    and cannot overwrite each other (A-9).

    ``profile_id`` is validated when supplied so a caller cannot build a job id for
    no one. The slug itself stays candidate-free: the filename convention is part of
    the render contract and existing artifacts keep their names.
    """
    if profile_id is not None:
        validate_profile_id(profile_id)
    year = datetime.now(ZoneInfo("Europe/Berlin")).year
    milliseconds = time.time_ns() // 1_000_000
    return f"{year}_{slugify(company)}_{slugify(role)}_{milliseconds}"
