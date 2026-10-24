"""Multi-profile storage keyed by ``profile_id`` (ADR 0003, ADR 0004).

This module is the *only* place that decides where a profile lives. The rule it
enforces is the whole point of Phase 2:

    ``profile_id`` is explicit and **fails closed**.

There is no default profile, no "first one found" fallback and no inference from
the environment. A missing, empty or unknown ``profile_id`` raises. That is
deliberate: the failure mode this prevents is silent, not loud — candidate B's
draft validated against candidate A's facts, or one candidate's documents
written into the other's folder. Both look like success.

Layout (ADR 0004), with ``<store>`` outside the public repository (ADR 0011)::

    <store>/profiles/<profile_id>/profile.yaml
    <store>/outputs/<profile_id>/<job_id>/...

``profile_id`` becomes a directory name and is therefore validated against
``^[a-z0-9][a-z0-9_-]*$``. Path traversal is rejected structurally rather than
by hoping the caller sanitises.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from models.profile import Profile

logger = logging.getLogger(__name__)

#: Filename of the authoritative profile inside a profile directory.
PROFILE_FILENAME = "profile.yaml"

#: A profile id is a directory name: lowercase, digits, ``-`` and ``_`` only.
#: Deliberately strict -- it also makes the id safe in a URL and on every OS.
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: Environment variable naming the private store root. Read in ``Config``, never
#: here, so importing this module stays side-effect free (ADR 0010).
STORE_ENV_VAR = "CVTAILOR_STORE"

#: Directory name used when the store is kept inside the project root. Kept for
#: a checkout that has no external store yet; real data belongs outside (ADR 0011).
DEFAULT_STORE_DIRNAME = "storage"


class ProfileStoreError(Exception):
    """Raised when a profile cannot be resolved. Never caught to pick a default."""


class UnknownProfileError(ProfileStoreError):
    """The requested ``profile_id`` has no directory in the store."""


class InvalidProfileIdError(ProfileStoreError):
    """The ``profile_id`` is missing, empty or not a legal directory name."""


class ProfileMismatchError(ProfileStoreError):
    """The ``profile_id`` and the profile object name different candidates.

    Raised when a caller pairs one candidate's id with another's profile. Filing
    the documents under the wrong id is the silent, unrecoverable failure ADR 0003
    exists to prevent, so this is an error rather than a warning.
    """


def validate_profile_id(profile_id) -> str:
    """Return ``profile_id`` unchanged, or raise.

    Fail-closed by construction: every rejection path raises, and there is no
    branch that substitutes another value.
    """
    if profile_id is None:
        raise InvalidProfileIdError(
            "A profile_id is required and none was given. cv-tailor never picks a "
            "profile for you: pass --profile-id <id>, or set CVTAILOR_PROFILE_ID. "
            "Run `cvtailor profile list` to see the profiles in the store."
        )
    text = str(profile_id).strip()
    if not text:
        raise InvalidProfileIdError(
            "The profile_id is empty. Pass a real profile id, or run "
            "`cvtailor profile list`."
        )
    if not PROFILE_ID_PATTERN.match(text):
        raise InvalidProfileIdError(
            f"Invalid profile_id {profile_id!r}. Use lowercase letters, digits, "
            "'-' and '_', starting with a letter or digit (for example "
            "'sreedeep'). The id becomes a directory name, so anything else is "
            "rejected rather than sanitised."
        )
    return text


@dataclass(frozen=True)
class ProfileStore:
    """Resolves profiles and their output folders inside one store root.

    The store root is configuration, not code (ADR 0004), so moving from a local
    directory to the remote store of ADR 0006 changes the root only.
    """

    root: Path

    def __post_init__(self) -> None:
        # frozen dataclass: bypass the setattr guard for this one normalisation.
        object.__setattr__(self, "root", Path(self.root))

    # --- construction -----------------------------------------------------------------

    @classmethod
    def at(cls, root) -> "ProfileStore":
        """Build a store rooted at ``root``."""
        return cls(root=Path(root))

    @classmethod
    def from_config(cls, config) -> "ProfileStore":
        """Build the store described by a :class:`~config.Config`."""
        return cls(root=Path(config.profile_store_dir))

    # --- paths ------------------------------------------------------------------------

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    def profile_dir(self, profile_id) -> Path:
        """``<store>/profiles/<profile_id>``. Validates the id, never falls back."""
        return self.profiles_dir / validate_profile_id(profile_id)

    def profile_path(self, profile_id) -> Path:
        """``<store>/profiles/<profile_id>/profile.yaml``."""
        return self.profile_dir(profile_id) / PROFILE_FILENAME

    def outputs_dir(self, profile_id) -> Path:
        """``<store>/outputs/<profile_id>`` -- the one candidate's job folders.

        The candidate segment is part of the path even when only one profile
        exists, so adding a second can never collide with the first (ADR 0003).
        """
        return self.root / "outputs" / validate_profile_id(profile_id)

    # --- reading ----------------------------------------------------------------------

    def exists(self, profile_id) -> bool:
        """True when ``profile_id`` names a profile in this store.

        An invalid id is not a lookup failure to be tolerated -- it raises, so a
        typo cannot be answered with a misleading ``False``.
        """
        return self.profile_path(profile_id).is_file()

    def list_ids(self) -> list:
        """Every profile id in the store, sorted. Empty when the store is new."""
        if not self.profiles_dir.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.profiles_dir.iterdir()
            if entry.is_dir() and (entry / PROFILE_FILENAME).is_file()
        )

    def iter_profiles(self) -> Iterator[tuple]:
        """Yield ``(profile_id, path)`` for every profile, in id order."""
        for profile_id in self.list_ids():
            yield profile_id, self.profile_path(profile_id)

    def load(self, profile_id) -> Profile:
        """Load and validate one profile.

        Raises:
            InvalidProfileIdError: the id is missing, empty or malformed.
            UnknownProfileError: no profile with that id exists in this store.
            ValueError: the file exists but does not validate.
        """
        resolved = validate_profile_id(profile_id)
        path = self.profile_path(resolved)
        if not path.is_file():
            raise UnknownProfileError(self.unknown_message(resolved))

        from services.profile_loader import load_profile

        return load_profile(str(path))

    def unknown_message(self, profile_id: str) -> str:
        """Explain the miss without ever suggesting a different profile as a default."""
        path = self.profile_path(profile_id)
        known = self.list_ids()
        if known:
            return (
                f"No profile {profile_id!r} in the store at {self.profiles_dir}. "
                f"Known profiles: {', '.join(known)}. "
                f"Expected {path}."
            )
        return (
            f"No profile {profile_id!r}: the store at {self.profiles_dir} has no "
            f"profiles yet. Create one with `cvtailor profile new {profile_id}`, or "
            "migrate an existing profile with `cvtailor profile import <path> "
            f"--profile-id {profile_id}`."
        )

    # --- writing ----------------------------------------------------------------------

    def create(self, profile_id, profile: Profile, *, overwrite: bool = False) -> Path:
        """Write ``profile`` into the store under ``profile_id``.

        Refuses to overwrite an existing profile unless ``overwrite`` is set, so a
        re-import cannot silently replace a candidate's maintained facts.
        """
        import yaml

        resolved = validate_profile_id(profile_id)
        path = self.profile_path(resolved)
        if path.exists() and not overwrite:
            raise ProfileStoreError(
                f"A profile already exists at {path}. Re-run with --force to replace it."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(profile.model_dump(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    def import_file(self, source, profile_id, *, overwrite: bool = False) -> Path:
        """Copy an existing ``profile.yaml`` in verbatim, preserving manual edits.

        The bytes are copied, not round-tripped through the model, so comments,
        key order, quoting and the ``rules:`` block survive exactly. Validation
        happens first: an unreadable profile is never copied into the store.
        """
        from services.profile_loader import load_profile

        resolved = validate_profile_id(profile_id)
        source_path = Path(source)
        if not source_path.is_file():
            raise ProfileStoreError(f"Profile to import not found: {source_path}")

        # Validate before writing anything, so a broken file cannot land in the store.
        load_profile(str(source_path))

        destination = self.profile_path(resolved)
        if destination.exists() and not overwrite:
            raise ProfileStoreError(
                f"A profile already exists at {destination}. "
                "Re-run with --force to replace it."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        return destination


def resolve_profile_id(config, explicit: Optional[str] = None) -> str:
    """Resolve the profile id from an explicit value, then config. Never guesses.

    The order is intentional and short: an explicit argument, then the configured
    value. There is no third step that looks around the store for "the" profile.
    """
    if explicit is not None and str(explicit).strip():
        return validate_profile_id(explicit)
    return validate_profile_id(getattr(config, "profile_id", None))


def store_root_from_env(project_root: Path, overrides: Optional[dict] = None) -> Path:
    """Resolve the store root. The only place that reads the store environment.

    Falls back to ``<project_root>/storage`` so a fresh checkout still works, but
    ADR 0011 expects real data to live outside the repository.
    """
    value = (overrides or {}).get("store_dir")
    if value is None:
        value = os.getenv(STORE_ENV_VAR, "").strip() or None
    if value is None:
        return (project_root / DEFAULT_STORE_DIRNAME).resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()
