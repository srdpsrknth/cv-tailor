"""One place where environment configuration is read.

Previously ``gemini_service`` and ``main`` read ``os.getenv`` at module import,
which made the model and output paths fixed for the process lifetime and made
tests awkward. Configuration is now an explicit object that can be built at any
time, so a caller (the CLI, the API, a test) decides *when* the environment is
consulted and can override it without touching process state.

``Config.from_env()`` is the only function that reads the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

#: Repository root, derived from this file's location (backend/config.py -> repo).
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: The model assumed when none is configured. Kept in sync with PRICING, which is
#: asserted to contain it.
DEFAULT_MODEL = "gemini-3.8-flash"

#: Directory used as the profile store when none is configured (ADR 0011 expects a
#: sibling directory outside the repository; this keeps a bare checkout working).
DEFAULT_STORE_DIRNAME = "storage"


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration.

    Frozen so a value cannot be mutated halfway through a generation run; use
    :meth:`with_overrides` to derive a variant instead.
    """

    project_root: Path
    outputs_dir: Path
    api_key: Optional[str]
    model: str
    temperature: float
    max_output_tokens: int
    #: Root of the private profile store (ADR 0004, ADR 0011).
    profile_store_dir: Path
    #: Which candidate this config acts for. ``None`` is a real, meaningful state:
    #: it means "not chosen", and every consumer must fail closed (ADR 0003).
    profile_id: Optional[str] = None
    #: An explicit profile file, bypassing the store. Only ever set by a caller that
    #: named a file on purpose (``--profile <path>``, tests). It is never inferred.
    profile_path: Optional[Path] = None

    # --- construction -----------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env_file: Optional[Path] = None,
        load_env_file: bool = True,
        overrides: Optional[dict] = None,
    ) -> "Config":
        """Build a config from the environment.

        This is the ONLY place that reads environment variables. Call it at the
        point of use rather than at import time.

        Args:
            env_file: ``.env`` to load first. Defaults to ``<project_root>/.env``.
            load_env_file: set False when the caller has already configured the
                environment and must not have a file change it underneath them.
            overrides: values that win over the environment, used by the CLI and tests.
        """
        overrides = dict(overrides or {})
        project_root = Path(overrides.pop("project_root", PROJECT_ROOT)).resolve()

        if load_env_file:
            candidate = Path(env_file) if env_file is not None else project_root / ".env"
            if candidate.exists():
                load_dotenv(candidate)

        outputs = overrides.pop("outputs_dir", None)
        if outputs is None:
            outputs = os.getenv("OUTPUTS_DIR", "").strip() or None
        outputs_dir = cls._resolve_path(outputs, project_root, default=project_root / "outputs")

        # The private store root. Resolved before the profile, because the profile
        # path is derived from it. ``CVTAILOR_STORE`` is the multi-profile name;
        # ``storage/`` inside the project is only a fallback for a bare checkout.
        store = overrides.pop("profile_store_dir", None)
        if store is None:
            store = os.getenv("CVTAILOR_STORE", "").strip() or None
        profile_store_dir = cls._resolve_path(
            store, project_root, default=project_root / DEFAULT_STORE_DIRNAME
        )

        # profile_id is taken as given. A blank string is normalised to None, which
        # means "not chosen" -- it never resolves to a profile (ADR 0003).
        profile_id = overrides.pop("profile_id", None)
        if profile_id is None:
            profile_id = os.getenv("CVTAILOR_PROFILE_ID", "").strip() or None
        if profile_id is not None and not str(profile_id).strip():
            profile_id = None

        # An explicit file is honoured only when the caller passed one. There is no
        # branch that fills this in with a default path.
        profile = overrides.pop("profile_path", None)

        config = cls(
            project_root=project_root,
            outputs_dir=outputs_dir,
            api_key=overrides.pop("api_key", None) or os.getenv("GEMINI_API_KEY") or None,
            model=overrides.pop("model", None) or os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
            temperature=float(overrides.pop("temperature", None) or os.getenv("GEMINI_TEMPERATURE", "0.3")),
            max_output_tokens=int(
                overrides.pop("max_output_tokens", None) or os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8000")
            ),
            profile_store_dir=profile_store_dir,
            profile_id=str(profile_id) if profile_id is not None else None,
            profile_path=Path(profile) if profile else None,
        )
        if overrides:
            raise TypeError(f"Unknown config overrides: {sorted(overrides)}")
        return config

    @staticmethod
    def _resolve_path(value, project_root: Path, default: Path) -> Path:
        """Interpret a configured path, treating a relative one as project-relative."""
        if value is None or value == "":
            return default.resolve()
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        return path.resolve()

    # --- derivation -------------------------------------------------------------------

    def with_overrides(self, **changes) -> "Config":
        """Return a copy with the given fields replaced."""
        if "project_root" in changes:
            changes["project_root"] = Path(changes["project_root"]).resolve()
        if "outputs_dir" in changes:
            changes["outputs_dir"] = self._resolve_path(
                changes["outputs_dir"], changes.get("project_root", self.project_root),
                default=self.outputs_dir,
            )
        if "profile_store_dir" in changes:
            changes["profile_store_dir"] = self._resolve_path(
                changes["profile_store_dir"],
                changes.get("project_root", self.project_root),
                default=self.profile_store_dir,
            )
        if "profile_path" in changes and changes["profile_path"] is not None:
            changes["profile_path"] = Path(changes["profile_path"])
        if "profile_id" in changes and changes["profile_id"] is not None:
            changes["profile_id"] = str(changes["profile_id"])
        return replace(self, **changes)

    # --- profiles ---------------------------------------------------------------------

    @property
    def store(self):
        """The :class:`~services.profile_store.ProfileStore` for this config."""
        from services.profile_store import ProfileStore

        return ProfileStore.at(self.profile_store_dir)

    def require_profile_id(self) -> str:
        """Return the profile id, or fail closed.

        There is deliberately no default. Callers that need a profile for a real
        operation must name one; a missing id is a bug, not a cue to guess.
        """
        from services.profile_store import validate_profile_id

        return validate_profile_id(self.profile_id)

    def require_profile_path(self) -> Path:
        """Return the ``profile.yaml`` this config acts for, or fail closed.

        An explicitly configured file wins, because a caller named it on purpose.
        Otherwise the id is resolved through the store -- which raises when the id
        is missing or unknown rather than falling back (ADR 0003).
        """
        if self.profile_path is not None:
            return Path(self.profile_path)
        return self.store.profile_path(self.require_profile_id())

    def load_profile(self):
        """Load this config's profile. Fails closed; never returns another's."""
        if self.profile_path is not None:
            from services.profile_loader import load_profile

            return load_profile(str(self.profile_path))
        return self.store.load(self.require_profile_id())

    # --- convenience ------------------------------------------------------------------

    @property
    def has_api_key(self) -> bool:
        """True when a usable-looking API key is configured.

        This is a presence check, never a network call: the key is not verified
        against Google unless the caller explicitly asks for that.
        """
        return bool(self.api_key) and self.api_key != "your_gemini_api_key_here"

    @property
    def is_mirroring(self) -> bool:
        """True when a separate mirror directory is configured."""
        return self.outputs_dir != (self.project_root / "outputs").resolve()

    def require_api_key(self) -> str:
        """Return the API key, or explain how to set it."""
        if not self.has_api_key:
            raise ConfigError(
                "GEMINI_API_KEY is not set. Add it to .env "
                f"({self.project_root / '.env'}) or pass --api-key. "
                "Run `cvtailor doctor` to check your setup."
            )
        return self.api_key


class ConfigError(Exception):
    """Raised when required configuration is missing or unusable."""
