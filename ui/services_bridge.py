"""UI-facing service helpers: everything the interface needs, and no rules of its own.

This module exists so the UI layer contains **no business logic**. The roadmap's
acceptance criterion for the interface is explicit — *"the UI reuses the same
services as the CLI — no duplicated business rules"* — and the way that is achieved
is by putting every non-presentational decision here, where it can be tested
without a browser or a server.

Three responsibilities, all of them lookups or translations:

1. **Resolve the candidate, fail closed** (ADR 0003). :func:`list_profiles` and
   :func:`load_profile` never default and never guess.
2. **Translate a result into display-ready values.** A cost, a page count, a
   validation message — computed here from the shared services, so the UI cannot
   disagree with the CLI about what a run cost.
3. **Describe what is possible without doing it.** Which profiles exist, whether a
   store is reachable, what a generation would need.

Nothing here performs a paid call. The one function that generates
(:func:`run_generation`) delegates straight to ``services.tailor_service``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from services.profile_store import (
    InvalidProfileIdError,
    ProfileStoreError,
    UnknownProfileError,
    validate_profile_id,
)


@dataclass(frozen=True)
class ProfileOption:
    """One selectable candidate, for the profile picker."""

    profile_id: str
    name: str
    roles: int
    #: Empty when the profile is fine; otherwise why it could not be read.
    problem: str = ""

    @property
    def is_usable(self) -> bool:
        return not self.problem

    def label(self) -> str:
        """How the option reads in a picker."""
        if self.problem:
            return f"{self.profile_id} — unusable: {self.problem}"
        return f"{self.profile_id} — {self.name} ({self.roles} roles)"


def list_profiles(config) -> List[ProfileOption]:
    """Every profile in the store, each annotated with whether it is usable.

    A broken profile is **listed with the reason**, never hidden: a candidate who
    cannot be selected because their file is malformed needs to see that, and a
    picker that silently omits them looks identical to having no profile at all.
    """
    store = config.store
    options: List[ProfileOption] = []
    for profile_id, path in store.iter_profiles():
        try:
            from services.profile_loader import load_profile

            profile = load_profile(str(path))
            options.append(ProfileOption(
                profile_id=profile_id,
                name=profile.identity.full_name,
                roles=len(profile.experience),
            ))
        except Exception as error:  # noqa: BLE001 - reported, not raised
            options.append(ProfileOption(
                profile_id=profile_id, name="", roles=0,
                problem=f"{type(error).__name__}: {error}",
            ))
    return options


def require_profile_id(config, explicit: Optional[str]) -> str:
    """Resolve the candidate, or raise a message the UI can show verbatim.

    Fail-closed by construction (ADR 0003): an explicit choice wins, then the
    configured default, and there is **no third step** that picks "the only one".
    A single-profile store therefore still requires a selection, which is the whole
    point — the rule exists because the failure it prevents is silent.

    Two distinct checks, because they catch different mistakes:
    :func:`validate_profile_id` rejects a malformed id (so it cannot become a path),
    and :meth:`ProfileStore.exists` rejects a well-formed id that names nobody. The
    second matters here: a picker can be handed a stale id from a saved session, and
    accepting it would let the UI proceed and fail much later, after paid work.
    """
    # A blank string is not a choice. Streamlit in particular hands back "" from an
    # untouched text input, and "   " from a cleared one, so both must fall through
    # to the configured default rather than being rejected as a bad id. Only a
    # genuinely empty answer -- after stripping -- counts as "no selection".
    explicit = (explicit or "").strip()
    configured = str(getattr(config, "profile_id", None) or "").strip()
    candidate = explicit or configured
    if not candidate:
        known = [option.profile_id for option in list_profiles(config) if option.is_usable]
        if known:
            raise InvalidProfileIdError(
                "Choose a profile. CV Tailor never picks one for you, even when "
                f"only one exists. Available: {', '.join(known)}."
            )
        raise InvalidProfileIdError(
            "No profiles exist yet. Create one with `cvtailor profile new <id>`, or "
            "import an existing profile.yaml with `cvtailor profile import <path>`."
        )
    resolved = validate_profile_id(candidate)
    if not config.store.exists(resolved):
        raise UnknownProfileError(config.store.unknown_message(resolved))
    return resolved


def load_profile(config, profile_id: str):
    """Load one profile, raising a message the UI can show."""
    resolved = validate_profile_id(profile_id)
    try:
        return config.store.load(resolved)
    except UnknownProfileError as error:
        raise UnknownProfileError(str(error)) from error


def describe_configuration(config) -> dict:
    """A plain-language summary of what this install can do, for the header.

    Reports facts only. It does not claim generation will succeed: the honest
    statement is whether a key and a model are *configured*, which is different
    from whether the provider will accept them.
    """
    store = config.store
    profiles = list_profiles(config)
    return {
        "store": str(store.root),
        "store_exists": Path(store.root).is_dir(),
        "profile_count": len(profiles),
        "usable_profiles": sum(1 for option in profiles if option.is_usable),
        "configured_profile_id": getattr(config, "profile_id", None),
        "model": getattr(config, "model", None) or getattr(config, "llm_model", None),
        "provider": getattr(config, "provider", None),
    }


# --- generation ---------------------------------------------------------------------------

@dataclass
class GenerationOutcome:
    """What a generation attempt produced, success or failure."""

    ok: bool
    #: Set on success.
    job_id: Optional[str] = None
    job_folder: Optional[Path] = None
    #: Ready-to-display lines describing what happened and what it cost.
    summary: List[str] = field(default_factory=list)
    #: Set on failure: a message safe to show a user.
    error: str = ""
    #: Set on failure: whether the drafts were still saved (they usually are).
    drafts_saved: bool = False


def format_cost_breakdown(usage) -> List[str]:
    """Human-readable cost lines, computed from the shared pricing service.

    Deliberately reads ``services.pricing`` rather than holding a table. The old
    UI kept its own copy and it drifted — it still priced a model Phase 1 had
    retired. Sharing the module is what makes the figure shown here and the figure
    the backend charges incapable of disagreeing.
    """
    if usage is None:
        return []
    from services import pricing

    model_name = getattr(usage, "model_name", None) or "unknown"
    provider = getattr(usage, "provider", None) or pricing.DEFAULT_PROVIDER
    total_input = (getattr(usage, "cv_input_tokens", 0)
                   + getattr(usage, "cl_input_tokens", 0))
    total_output = (getattr(usage, "cv_output_tokens", 0)
                    + getattr(usage, "cl_output_tokens", 0))

    lines = [
        f"Input tokens: {total_input:,}",
        f"Output tokens: {total_output:,}",
    ]
    try:
        if pricing.is_priced(model_name, provider):
            tier = pricing.describe_tier(total_input, model_name, provider=provider)
            lines.append(f"Model: {model_name} via {provider} ({tier} tier)")
        else:
            lines.append(
                f"Model: {model_name} via {provider} — not in the verified price "
                "table, so this estimate may be wrong"
            )
    except Exception:  # noqa: BLE001 - a display helper must not break a page
        lines.append(f"Model: {model_name} via {provider}")

    cost = getattr(usage, "estimated_cost_usd", None)
    if cost is not None:
        lines.append(f"Estimated cost: ${cost:.6f}")
    return lines


def run_generation(
    config,
    profile_id: str,
    job_description: str,
    *,
    company: Optional[str] = None,
    role: Optional[str] = None,
    work_country: Optional[str] = None,
    use_cache: bool = True,
    status: Optional[Callable[[str], None]] = None,
) -> GenerationOutcome:
    """Generate documents for one posting, in-process.

    Calls :func:`services.tailor_service.tailor_documents` directly rather than
    going through the HTTP API: the UI and the API are both interfaces over the
    same service, and routing through the network would add a failure mode without
    adding a capability.

    Every failure is converted into a message rather than a traceback, because the
    UI's job is to explain, and a stack trace in a browser helps nobody.
    """
    from services.tailor_service import tailor_documents

    def report(message: str) -> None:
        if status:
            status(message)

    try:
        profile = load_profile(config, profile_id)
    except (ProfileStoreError, ValueError) as error:
        return GenerationOutcome(ok=False, error=str(error))

    if not job_description or not job_description.strip():
        return GenerationOutcome(
            ok=False,
            error="Paste the job description first — there is nothing to tailor to.",
        )

    try:
        result = tailor_documents(
            job_description=job_description,
            profile=profile,
            company_name=company or None,
            role_title=role or None,
            work_country=work_country or None,
            status_callback=report,
            config=config,
            profile_id=profile_id,
            use_cache=use_cache,
        )
    except Exception as error:  # noqa: BLE001 - converted for display
        return GenerationOutcome(
            ok=False,
            error=f"{type(error).__name__}: {error}",
            drafts_saved=True,
        )

    summary = []
    message = getattr(result, "message", None)
    if message:
        summary.append(message)
    summary.extend(format_cost_breakdown(getattr(result, "token_usage", None)))

    return GenerationOutcome(
        ok=True,
        job_id=getattr(result, "job_id", None),
        job_folder=job_folder(config, profile_id, getattr(result, "job_id", None)),
        summary=summary,
    )


def job_folder(config, profile_id: str, job_id: Optional[str]) -> Optional[Path]:
    """Where one application's documents live, or ``None`` when it cannot be known."""
    if not job_id:
        return None
    try:
        resolved = validate_profile_id(profile_id)
    except InvalidProfileIdError:
        return None
    return config.store.outputs_dir(resolved) / job_id


def list_artifacts(folder: Optional[Path]) -> List[dict]:
    """The downloadable files in one application folder, newest naming first.

    Returns plain dicts so the UI can render them without importing a model. Types
    are inferred from the extension, which is enough to pick a download button and
    to tell a browser what the file is.
    """
    if not folder or not Path(folder).is_dir():
        return []
    kinds = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".json": "application/json",
        ".txt": "text/plain",
    }
    artifacts = []
    for path in sorted(Path(folder).iterdir()):
        if not path.is_file() or path.suffix.lower() not in kinds:
            continue
        artifacts.append({
            "name": path.name,
            "path": str(path),
            "size_kb": round(path.stat().st_size / 1024, 1),
            "mime": kinds[path.suffix.lower()],
            "kind": path.suffix.lower().lstrip("."),
        })
    return artifacts


def list_applications(config, profile_id: str, limit: int = 20) -> List[dict]:
    """Recent applications for one candidate, newest first.

    Reads the real store, so a user can get back to documents produced by the CLI
    as well as by the UI. That matters: the two interfaces share one store, and an
    application generated in a terminal must not be invisible in the browser.
    """
    resolved = validate_profile_id(profile_id)
    outputs = config.store.outputs_dir(resolved)
    if not outputs.is_dir():
        return []
    folders = sorted(
        (entry for entry in outputs.iterdir() if entry.is_dir()),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "job_id": folder.name,
            "path": str(folder),
            "artifacts": list_artifacts(folder),
            "has_content": (folder / "source" / "content.json").is_file(),
        }
        for folder in folders[:limit]
    ]
