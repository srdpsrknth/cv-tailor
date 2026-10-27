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
#:
#: **Switched from `gemini-3.8-flash` on 2026-10-27**, on the study's measurement rather
#: than on reputation (ADR 0005 requires benchmarking before a switch; ADR 0016 records
#: the study). `openai/gpt-6-luna` accepted 3/3 cases with **no** correction calls in
#: every run, at **$0.00281 per accepted result against the previous default's
#: $0.08607-$0.11384** -- roughly 30-40x cheaper for a document that passes the same
#: factual and layout gates.
DEFAULT_MODEL = "openai/gpt-6-luna"

#: The provider used when none is configured (ADR 0005).
#:
#: Switched to OpenRouter with the model above, because the selected model is served
#: there. The previous default was Gemini, and `gemini-3.8-flash` remains available and
#: priced -- it is simply no longer what the tool picks for you.
DEFAULT_PROVIDER = "openrouter"

#: Providers this build can construct. A name outside this set fails closed rather
#: than falling back to the default, because a silent provider substitution would
#: change the response contract underneath the caller.
KNOWN_PROVIDERS = ("gemini", "openrouter")

#: Tasks that may have their own model, and the environment variable suffix for
#: each. Model-per-task routing (ADR 0005) exists so a cheap model can serve
#: routine work while document writing keeps the stronger one.
ROUTABLE_TASKS = ("cv", "cover_letter", "layout_retry")

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
    #: Which provider implementation to speak to (ADR 0005). ``gemini`` by default.
    provider: str = DEFAULT_PROVIDER
    #: Key for the OpenRouter provider. Separate from ``api_key`` because the two
    #: providers are authenticated independently and neither substitutes for the
    #: other; a missing key for the *selected* provider fails closed.
    openrouter_api_key: Optional[str] = None
    #: Per-task model overrides (ADR 0005's model-per-task routing). A task absent
    #: from this mapping uses :attr:`model`, so routing is opt-in per task and an
    #: unconfigured task cannot accidentally get a weaker model.
    task_models: Optional[dict] = None
    #: Optional ceiling on a single generation run's estimated cost, in USD. ``None``
    #: means no cap. This is a *guard*, not an estimate: when the accumulated cost
    #: would exceed it the run stops rather than continuing to spend.
    max_cost_usd: Optional[float] = None

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

        # --- provider selection (ADR 0005) ---------------------------------------
        # An unknown name is rejected here, at config time, rather than silently
        # falling back to Gemini: a provider substitution would change the response
        # contract without the caller asking for it.
        provider = overrides.pop("provider", None) or os.getenv("CVTAILOR_PROVIDER", "").strip() or DEFAULT_PROVIDER
        provider = str(provider).strip().lower()
        if provider not in KNOWN_PROVIDERS:
            raise ConfigError(
                f"Unknown provider {provider!r}. Known providers: "
                f"{', '.join(KNOWN_PROVIDERS)}. Set CVTAILOR_PROVIDER."
            )

        # --- model-per-task routing (ADR 0005) ------------------------------------
        # Opt-in per task. A task with no override falls back to ``model``, so
        # configuring routing for one task cannot silently weaken another.
        task_models = dict(overrides.pop("task_models", None) or {})
        for task in ROUTABLE_TASKS:
            if task in task_models and task_models[task]:
                continue
            env_name = f"CVTAILOR_MODEL_{task.upper()}"
            value = os.getenv(env_name, "").strip()
            if value:
                task_models[task] = value
        unknown_tasks = sorted(set(task_models) - set(ROUTABLE_TASKS))
        if unknown_tasks:
            raise ConfigError(
                f"Unknown task(s) in model routing: {', '.join(unknown_tasks)}. "
                f"Routable tasks: {', '.join(ROUTABLE_TASKS)}."
            )

        # --- optional budget cap --------------------------------------------------
        # A cap exists so an evaluation or a real run cannot spend without limit.
        # A malformed value is an error, never a silently-ignored cap: a budget
        # that fails open is worse than no budget, because it looks like one.
        max_cost_usd = overrides.pop("max_cost_usd", None)
        if max_cost_usd is None:
            raw_cost = os.getenv("CVTAILOR_MAX_COST_USD", "").strip()
            max_cost_usd = raw_cost or None
        if max_cost_usd is not None:
            try:
                max_cost_usd = float(max_cost_usd)
            except (TypeError, ValueError) as error:
                raise ConfigError(
                    f"CVTAILOR_MAX_COST_USD must be a number of USD, got {max_cost_usd!r}."
                ) from error
            if max_cost_usd < 0:
                raise ConfigError(
                    f"CVTAILOR_MAX_COST_USD must not be negative, got {max_cost_usd}."
                )

        config = cls(
            project_root=project_root,
            outputs_dir=outputs_dir,
            api_key=overrides.pop("api_key", None) or os.getenv("GEMINI_API_KEY") or None,
            model=_resolve_model(
                overrides.pop("model", None),
                provider=provider,
                env=os.environ,
            ),
            temperature=float(overrides.pop("temperature", None) or os.getenv("GEMINI_TEMPERATURE", "0.3")),
            max_output_tokens=int(
                overrides.pop("max_output_tokens", None) or os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8000")
            ),
            profile_store_dir=profile_store_dir,
            profile_id=str(profile_id) if profile_id is not None else None,
            profile_path=Path(profile) if profile else None,
            provider=provider,
            openrouter_api_key=(
                overrides.pop("openrouter_api_key", None)
                or os.getenv("OPENROUTER_API_KEY")
                or None
            ),
            task_models=task_models,
            max_cost_usd=max_cost_usd,
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

    # --- provider and routing ---------------------------------------------------------

    def model_for(self, task: str) -> str:
        """Return the model this config routes ``task`` to (ADR 0005).

        Falls back to :attr:`model` for a task with no override, so routing is
        opt-in and an unconfigured task never gets a weaker model by accident.
        An unknown task falls back too rather than raising: a new call site must
        not be able to crash a run by asking for a model, and falling back to the
        configured default is the behaviour every existing caller already had.
        """
        return (self.task_models or {}).get(task) or self.model

    @property
    def provider_name(self) -> str:
        """The configured provider's name, normalised."""
        return (self.provider or DEFAULT_PROVIDER).strip().lower()

    def require_provider_key(self) -> str:
        """Return the API key for the **selected** provider, or fail closed.

        Each provider is authenticated separately and neither key substitutes for
        the other, so selecting OpenRouter without its key is an error rather than
        a silent attempt to use the Gemini key.
        """
        if self.provider_name == "openrouter":
            if not self.openrouter_api_key:
                raise ConfigError(
                    "OPENROUTER_API_KEY is not set. Add it to .env "
                    f"({self.project_root / '.env'}) or pass --api-key. "
                    "Run `cvtailor doctor` to check your setup."
                )
            return self.openrouter_api_key
        return self.require_api_key()

    # --- optional budget cap ----------------------------------------------------------

    @property
    def has_cost_cap(self) -> bool:
        """True when a spending cap is configured."""
        return self.max_cost_usd is not None

    def budget_exceeded(self, spent_usd: float) -> bool:
        """Whether ``spent_usd`` has reached the configured cap.

        With no cap configured this is always False, so the unconfigured path
        behaves exactly as it did before caps existed.
        """
        if self.max_cost_usd is None:
            return False
        return spent_usd >= self.max_cost_usd

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


#: Environment variables that name a model, per provider. ``GEMINI_MODEL`` is
#: **Gemini-specific**, and that distinction became load-bearing on 2026-10-27: the
#: default provider moved to OpenRouter while the owner's ``.env`` still carried
#: ``GEMINI_MODEL=gemini-3.8-flash``. Because the variable was read for *any* provider,
#: it silently overrode the new default and the tool ran the old, ~30x more expensive
#: model through OpenRouter -- where the bare name ``gemini-3.8-flash`` is not even a
#: priced route, so its cost was reported from the wrong row.
#:
#: Nothing failed loudly. The call resolved to ``google/gemini-3.8-flash`` and returned a
#: document, which is precisely why this needed fixing rather than documenting: a
#: provider-specific setting must not decide another provider's model.
PROVIDER_MODEL_ENV = {
    "gemini": "GEMINI_MODEL",
    "openrouter": "OPENROUTER_MODEL",
}


def _resolve_model(override, *, provider: str, env) -> str:
    """The model to use, honouring only the selected provider's own variable.

    Precedence: an explicit ``override``, then the provider-neutral ``CVTAILOR_MODEL``,
    then the selected provider's own variable, then :data:`DEFAULT_MODEL`. A *different*
    provider's variable is ignored on purpose -- see :data:`PROVIDER_MODEL_ENV`.

    The neutral variable outranks the provider-specific one because it is the more
    explicit statement of intent: a caller who sets ``CVTAILOR_MODEL`` has named the
    model deliberately, whereas ``GEMINI_MODEL`` may simply be a leftover from a
    previous configuration.
    """
    if override:
        return override

    neutral = (env.get("CVTAILOR_MODEL") or "").strip()
    if neutral:
        return neutral

    own = PROVIDER_MODEL_ENV.get(provider)
    if own:
        value = (env.get(own) or "").strip()
        if value:
            return value

    return DEFAULT_MODEL


class ConfigError(Exception):
    """Raised when required configuration is missing or unusable."""
