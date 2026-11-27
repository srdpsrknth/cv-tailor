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
from datetime import datetime, timezone
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
            options.append(
                ProfileOption(
                    profile_id=profile_id,
                    name=profile.identity.full_name,
                    roles=len(profile.experience),
                )
            )
        except Exception as error:  # noqa: BLE001 - reported, not raised
            options.append(
                ProfileOption(
                    profile_id=profile_id,
                    name="",
                    roles=0,
                    problem=f"{type(error).__name__}: {error}",
                )
            )
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
        known = [
            option.profile_id for option in list_profiles(config) if option.is_usable
        ]
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
    details: dict = field(default_factory=dict)


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
    total_input = getattr(usage, "cv_input_tokens", 0) + getattr(
        usage, "cl_input_tokens", 0
    )
    total_output = getattr(usage, "cv_output_tokens", 0) + getattr(
        usage, "cl_output_tokens", 0
    )

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
    balance_cv_pages: bool = False,
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

    from services.posting import validate_posting

    try:
        job_description = validate_posting(job_description)
    except ValueError as error:
        return GenerationOutcome(ok=False, error=str(error))

    before = {a["job_id"] for a in list_applications(config, profile_id, limit=None)}
    layout_options = {"balance_cv_pages": True} if balance_cv_pages else {}
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
            **layout_options,
        )
    except Exception as error:  # noqa: BLE001 - converted for display
        return GenerationOutcome(
            ok=False,
            error=f"{type(error).__name__}: {error}",
            drafts_saved=bool(
                [
                    a
                    for a in list_applications(config, profile_id, limit=None)
                    if a["job_id"] not in before
                    and (Path(a["path"]) / "source" / "drafts.json").is_file()
                ]
            ),
            details={
                "applications": [
                    a["job_id"]
                    for a in list_applications(config, profile_id, limit=None)
                    if a["job_id"] not in before
                ]
            },
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


def run_job_search(
    config,
    profile_id: str,
    query,
    *,
    preferences=None,
    sources=None,
    include_ineligible: bool = False,
):
    """Search public job sources and rank the results. Free: no key, no LLM call.

    Delegates entirely to :func:`services.job_search.search_jobs`, so the interface
    cannot apply different ranking or deduplication rules from the CLI. The profile
    is loaded here rather than passed in, because a search is *for* a candidate:
    ranking uses their skills and languages, and the sweep record is filed under
    their id (ADR 0003).
    """
    from services.job_connectors import build_default_sources
    from services.job_search import search_jobs

    profile = load_profile(config, profile_id)
    return search_jobs(
        sources if sources is not None else build_default_sources(),
        profile,
        query,
        preferences=preferences,
        store_root=config.profile_store_dir,
        profile_id=profile_id,
        include_ineligible=include_ineligible,
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
        if (
            not path.is_file()
            or path.suffix.lower() not in kinds
            or ".sync-conflict-" in path.name.lower()
            or not path.resolve().is_relative_to(Path(folder).resolve())
        ):
            continue
        artifacts.append(
            {
                "name": path.name,
                "path": str(path),
                "size_kb": round(path.stat().st_size / 1024, 1),
                "mime": kinds[path.suffix.lower()],
                "kind": path.suffix.lower().lstrip("."),
            }
        )
    return artifacts


def _recent_folders(config, profile_id):
    resolved = validate_profile_id(profile_id)
    outputs = config.store.outputs_dir(resolved)
    if not outputs.is_dir():
        return []
    return sorted(
        (
            entry
            for entry in outputs.iterdir()
            if entry.is_dir() and entry.resolve().parent == outputs.resolve()
        ),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True,
    )


def list_applications(config, profile_id: str, limit: Optional[int] = 20) -> List[dict]:
    """Recent applications for one candidate, newest first."""
    return [
        {
            "job_id": folder.name,
            "path": str(folder),
            "artifacts": list_artifacts(folder),
            "has_content": (folder / "source" / "content.json").is_file(),
        }
        for folder in _recent_folders(config, profile_id)[:limit]
    ]


def load_application(config, profile_id, job_id, *, include_quality=False):
    from services.application_review import load_review

    detail = load_review(
        config, profile_id, job_id, include_quality=include_quality
    )
    detail["artifacts"] = list_artifacts(Path(detail["path"]))
    return detail


def check_word_layout(config, profile_id, job_id):
    from services.application_review import check_saved_word_layout

    return check_saved_word_layout(config, profile_id, job_id)


def application_library(config, profile_id):
    """All saved applications with human labels, including partial historical runs."""
    from services.application_review import load_application_summary

    records = []
    for folder in _recent_folders(config, profile_id):
        try:
            records.append(load_application_summary(config, profile_id, folder.name))
        except (OSError, ValueError):
            continue
    return records


def model_options(config):
    from evaluation.curated_models import curated_models

    return (
        [model for model in curated_models()]
        if config.provider_name == "openrouter"
        else []
    )


def generation_config(config, selected):
    if not selected:
        return config
    if selected not in {m.id for m in model_options(config)}:
        raise ValueError("Choose a model from the curated catalogue.")
    return config.with_overrides(model=selected, task_models={})


def preflight(config):
    from cli.commands.doctor import check_pdflatex

    return {
        "key_configured": config.has_api_key,
        "models": {
            t: config.model_for(t) for t in ("cv", "cover_letter", "layout_retry")
        },
        "pdf_engine": check_pdflatex().status == "ok",
    }


def posting_handoff(job):
    """Transfer only published text and metadata, without fetching or generating."""
    known_country = job.country.value if job.country.is_verified else ""
    return {
        "job_description": job.description or "",
        "company": job.company,
        "role": job.title,
        "work_country": known_country or "",
        "provenance": {
            "url": job.url,
            "source": job.source,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
            "transferred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def document_label(name):
    if name.startswith("cv_balanced_") and name.endswith(".pdf"):
        return f"Balanced CV · {name.removeprefix('cv_balanced_').removesuffix('.pdf')} · PDF"
    if Path(name).stem.lower().endswith('_upload'):
        return f"CV for autofill · {Path(name).suffix.lstrip('.').upper()}"
    suffix = Path(name).suffix.lstrip(".").upper()
    lower = name.lower()
    kind = (
        "Cover letter"
        if "cover" in lower or "letter" in lower
        else "CV" if "cv" in lower else Path(name).stem.replace("_", " ")
    )
    return f"{kind} · {suffix}"


def export_upload_cv(config, profile_id, job_id):
    from services.upload_cv import export_saved_upload_cv

    return export_saved_upload_cv(config, profile_id, job_id)


def read_artifact(config, profile_id, job_id, name):
    from services.application_review import application_folder

    folder = application_folder(config, profile_id, job_id)
    if name not in {a["name"] for a in list_artifacts(folder)}:
        raise ValueError("Document not found in this application.")
    return (folder / name).read_bytes()


def saved_posting(config, profile_id, job_id):
    from services.application_review import application_folder, read_saved_posting

    folder = application_folder(config, profile_id, job_id)
    return read_saved_posting(folder) or "No posting was saved."


def save_posting_provenance(config, profile_id, job_id, provenance):
    """Persist known source metadata beside the accepted input, never in the profile."""
    from services.application_review import application_folder
    import json

    folder = application_folder(config, profile_id, job_id)
    allowed = {
        key: value
        for key, value in provenance.items()
        if key in ("url", "source", "posted_at", "transferred_at")
        and isinstance(value, (str, type(None)))
    }
    (folder / "source" / "posting_provenance.json").write_text(
        json.dumps(allowed, indent=2), encoding="utf-8"
    )


def source_coverage():
    from services.job_connectors import build_default_sources

    return [
        f"{source.name} · configured public-source connector"
        for source in build_default_sources()
    ]


def search_from_fields(config, profile_id, keywords, country, city, remote, limit):
    from models.job import SearchQuery
    from services.job_match import MatchPreferences

    profile = load_profile(config, profile_id)
    query = SearchQuery(
        keywords=keywords or None,
        country=country or None,
        city=city or None,
        remote=True if remote else None,
        limit=limit,
    )
    if country and country.strip() and query.country is None:
        raise ValueError("Unknown search country. Supply a supported country name or code.")
    return run_job_search(
        config,
        profile_id,
        query,
        preferences=MatchPreferences.from_profile(
            profile, keywords=tuple(keywords.split()) if keywords else ()
        ),
    )


def setup_checks(config):
    from cli.commands import doctor

    return [
        check.as_dict()
        for check in (
            doctor.check_python(),
            doctor.check_venv(config.project_root),
            doctor.check_store(config),
            doctor.check_profile(config),
            doctor.check_timezone(config.timezone_name),
            doctor.check_templates(config.project_root),
            doctor.check_pdflatex(),
            doctor.check_outputs(config),
            doctor.check_api_key(config, verify=False),
        )
    ]


def initial_gui_profile(config, available_ids):
    from services.gui_preferences import initial_profile

    return initial_profile(config, available_ids)


def remember_gui_profile(config, profile_id):
    from services.gui_preferences import remember_profile

    return remember_profile(config, profile_id)


# --- confirm-first suggested claims (WP9) -------------------------------------------------


def _claims_content(config, profile_id, job_id) -> Path:
    from services.application_review import application_folder

    return application_folder(config, profile_id, job_id) / "source" / "content.json"


def claims_for(config, profile_id, job_id) -> List[dict]:
    """The application's suggested claims with 1-based ``number``; empty for older runs."""
    from services.suggested_claims import load_suggestions

    record = load_suggestions(_claims_content(config, profile_id, job_id))
    return [{"number": n, **item} for n, item in enumerate(record["suggestions"], 1)]


def plan_claims(config, profile_id, job_id, numbers):
    """Exactly what accepting ``numbers`` would change in the profile. Writes nothing."""
    from services.claim_acceptance import accept_suggestions

    return accept_suggestions(
        _claims_content(config, profile_id, job_id), config.store.profile_path(profile_id),
        list(numbers), expected_profile_id=profile_id, dry_run=True,
    )


def accept_claims(config, profile_id, job_id, numbers):
    """Write the confirmed suggestions into the private profile (after a backup)."""
    from services.claim_acceptance import accept_suggestions

    return accept_suggestions(
        _claims_content(config, profile_id, job_id), config.store.profile_path(profile_id),
        list(numbers), expected_profile_id=profile_id,
    )


def reject_claims(config, profile_id, job_id, numbers):
    """Record the selected suggestions as rejected. The profile is not touched."""
    from services.claim_acceptance import reject_suggestions

    return reject_suggestions(_claims_content(config, profile_id, job_id), list(numbers))
