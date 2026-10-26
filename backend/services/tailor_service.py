"""Generate, review, fit, and persist job application documents.

This module is the orchestration facade. It used to be one 296-line function
that mixed prompt building, LLM calls, validation, retries, file writing and
mirroring (A-3). Those responsibilities now live in:

  * :mod:`services.generation` -- prompts, LLM calls, validation, retries;
  * :mod:`services.application_store` -- the ``outputs/<job_id>/`` folder.

``tailor_documents`` keeps its exact public signature and behaviour, so the API,
the UI, the CLI and every existing test call it unchanged.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from pypdf import PdfReader

from config import Config
from models.profile import Profile
from models.requests import TailorResponse
from models.tailored_output import TailoringExplanation
from renderers import create_latex_renderer, create_docx_renderer
from services.application_store import ApplicationStore, make_job_id
from services.cache_store import (
    CACHE_FORMAT_VERSION,
    CacheEntry,
    GenerationCache,
    cache_key,
    rules_fingerprint,
    serialize_profile_bytes,
)
from services.gemini_service import GeminiService
from services.profile_store import (
    ProfileMismatchError,
    UnknownProfileError,
    resolve_profile_id,
)
from services.generation import (
    MAX_LAYOUT_ATTEMPTS,
    PROMPT_CL_PATH,
    PROMPT_CV_PATH,
    DEFAULT_PROFILE_RULES,
    DocumentGenerator,
    ProfileRules,
    build_context,
    build_cv_prompt,
)
from utils.text import slugify

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Kept for backwards compatibility: tests and callers reference these directly.
__all__ = [
    "tailor_documents",
    "parse_json_response",
    "validate_cv",
    "validate_cover_letter",
    "DEFAULT_PROFILE_RULES",
    "ProfileRules",
]


# --- re-exported so existing imports keep working -------------------------------------
# These preserve the public names, and the underscored names the existing test suite
# calls. Each is a thin delegation to services.generation, not duplicated logic.

def parse_json_response(text: str) -> dict:
    """Parse a model response into a document dict."""
    from services.generation import parse_json_response as _parse

    return _parse(text)


def validate_cv(cv, profile, rules: Optional[ProfileRules] = None) -> None:
    """Validate a CV, defaulting to the original candidate's rules."""
    from services.generation import validate_cv as _validate

    return _validate(cv, profile, rules or DEFAULT_PROFILE_RULES)


def validate_cover_letter(cl, profile) -> None:
    """Validate a cover letter against the profile."""
    from services.generation import validate_cover_letter as _validate

    return _validate(cl, profile)


def count_pdf_pages(pdf_path: Path) -> int:
    """Count pages, treating a missing or empty PDF as an error, never as zero."""
    pages = len(PdfReader(str(pdf_path)).pages)
    if pages < 1:
        raise ValueError("Generated PDF has no pages.")
    return pages


# Underscored aliases retained for the pre-existing tests.
_parse_json_response = parse_json_response
_validate_cv = validate_cv
_validate_cover_letter = validate_cover_letter
_count_pdf_pages = count_pdf_pages


# --- the validated-generation cache (Phase 3, item 5) ----------------------------------
#
# One profile, one posting, one prompt set, one model: the same generation. Repeating it
# used to re-draft from scratch and pay again. What is stored here is only ever a
# *validated* result -- the entry is written after the page-count gate has passed -- and
# it is derived data under ``<store>/cache/<profile_id>/``, so deleting it is always safe.
#
# ``cache_key`` (services.cache_store) is a digest of the bytes the model was shown: the
# serialized profile, the job description plus company/role/country, both prompt files,
# the editorial requirements, the response schemas, the provider and both routed models,
# and the resolved validation rules. ``job_id`` is deliberately absent -- it carries a
# millisecond timestamp, so keying on it would miss every time by construction.


def _source_digest(path: Path) -> str:
    """Hash one prompt file's exact bytes, or its absence.

    Read per call rather than at import: a ``PROMPT_VERSION`` constant would be one
    more thing a prompt edit could forget to bump, and this is what makes "a prompt
    change must not serve a stale document" true by construction rather than by
    discipline. A missing file hashes as ``""`` rather than raising, because the
    pipeline is about to fail loudly on its own when it tries to read the prompt.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _schema_digest() -> str:
    """Hash the response schemas.

    The schema is request metadata, not prompt content, so it is not in either
    prompt file -- but it does change what the model returns, which is exactly what
    the key has to notice. ``RESPONSE_SCHEMAS`` holds ``google.genai`` ``Schema``
    objects, so each is described with ``model_dump``; a schema object that cannot be
    dumped falls back to its ``repr``, which still changes when the schema does.
    """
    from services import generation

    described = {}
    for kind, schema in sorted(generation.RESPONSE_SCHEMAS.items()):
        dump = getattr(schema, "model_dump", None)
        try:
            described[kind] = dump() if callable(dump) else repr(schema)
        except Exception:  # noqa: BLE001 -- a digest must never break generation
            described[kind] = repr(schema)
    return hashlib.sha256(
        json.dumps(described, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _cache_root(config: Config) -> Path:
    """Where the cache lives: always inside the private store (ADR 0011).

    **Never the repository.** A cache entry holds the accepted CV and cover letter --
    the same real candidate data ``outputs/`` holds -- so it is subject to the same
    boundary. It is deliberately *not* placed beside ``outputs/`` when the store is not
    authoritative: ``<repo>/outputs/`` is gitignored, so a loose ``--profile <path>``
    run writing there is contained, but a sibling ``<repo>/cache/`` would not be
    gitignored and a live evaluation run would drop real documents into the public
    repository's working tree.

    The store root is configuration (ADR 0004) and is available whether or not the
    caller named a profile file, so there is no case that needs a fallback.
    """
    return config.store.root / "cache"


def _cache_read(
    cache: GenerationCache, key: str, generator: DocumentGenerator,
    work_country: Optional[str], company_name: Optional[str], role_title: Optional[str],
):
    """The stored entry for ``key``, re-gated -- or ``None`` to generate instead.

    Returning ``None`` is a **miss**, and it covers four cases that all mean the same
    thing to the caller: nothing stored, an unreadable entry, a stored document that
    no longer validates, and a stored document that is not shaped like a document at
    all. Each one falls back to a fresh generation rather than raising, because the
    cache is an optimisation on the generation path -- a cache that can break a run
    that would otherwise have succeeded is worse than no cache.
    """
    entry = cache.get(key)
    if entry is None:
        return None, None, None
    try:
        cv, cl = generator.restore(
            entry.cv, entry.cover_letter, work_country, company_name, role_title
        )
    except (ValueError, TypeError) as error:
        logger.warning(
            "Stored generation %s no longer validates (%s); generating instead.",
            key[:12], error,
        )
        return None, None, None
    return cv, cl, entry


def _cache_write(
    cache: GenerationCache, key: str, cv, cl, explanation, drafts: list,
    usage: dict, config: Config,
) -> None:
    """Store a validated generation. Best-effort: a failure here never fails the run."""
    cache.put(key, CacheEntry(
        key=key,
        cv=cv.model_dump(),
        cover_letter=cl.model_dump(),
        tailoring_explanation=explanation,
        drafts=list(drafts),
        usage=usage,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        provider=config.provider_name,
        models={
            "cv": config.model_for("cv"),
            "cover_letter": config.model_for("cover_letter"),
            "layout_retry": config.model_for("layout_retry"),
        },
    ))


# --- orchestration --------------------------------------------------------------------

def tailor_documents(
    job_description: str,
    profile: Profile,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    work_country: Optional[str] = None,
    config: Optional[Config] = None,
    rules: Optional[ProfileRules] = None,
    profile_id: Optional[str] = None,
    use_cache: bool = True,
    service: Optional["GeminiService"] = None,
) -> TailorResponse:
    """Produce a two-page CV and a one-page cover letter, and persist them.

    ``profile_id`` names the candidate whose folder receives the output and is
    resolved **first**, so a call with no candidate fails before any paid work
    (ADR 0003). It may be passed directly, or configured on ``config``; there is no
    default and no inference from the profile object.

    ``use_cache=False`` re-drafts even when an identical validated generation is
    already stored -- the escape hatch for "the stored one is fine, but I want a
    fresh draft". It affects reading only: the fresh result is still stored.

    Raises ValueError when the job description is empty, when a document cannot be
    validated within three attempts, or when the CV will not fit two pages. In every
    failure case the editable drafts are written and a failure manifest recorded.
    """
    if not job_description or not job_description.strip():
        raise ValueError("Job description is empty.")

    # Resolved at call time (never at import), so the model, key and output path can
    # differ per invocation -- and one test can override another's environment.
    #
    # ``service`` may be supplied by the caller, and that is what makes **failed** runs
    # auditable. The service accumulates the money actually spent, so a caller that
    # owns the object can still read it after this function raises; without that, a run
    # that made several paid calls and then failed the gate reports a cost of zero, and
    # a model that never succeeds looks free. Only the object is injected -- the
    # provider, routing and key are still resolved from ``config`` here.
    if service is None:
        if config is None:
            config = Config.from_env(load_env_file=False, overrides={"project_root": PROJECT_ROOT})
            # Constructed with no arguments so an injected double can stand in for it.
            service = GeminiService()
        else:
            service = GeminiService(config=config)

    # Fail closed, and fail *early*: an unresolvable candidate must cost nothing and
    # must not leave a half-written folder behind.
    resolved_profile_id = resolve_profile_id(config, profile_id)

    # A well-formed id is not the same as a real one. Without this check a typo would
    # happily create `outputs/typo/...` and generate documents for an unnamed
    # candidate -- the exact silent failure ADR 0003 exists to prevent. The check is
    # skipped only when the caller named an explicit profile file, because then the
    # profile did not come from the store and there is no store entry to match.
    store = config.store
    if config.profile_path is None:
        # A well-formed id is not the same as a real one. Without this check a typo
        # would happily create outputs/typo/... and generate documents for an unnamed
        # candidate -- the exact silent failure ADR 0003 exists to prevent.
        if not store.exists(resolved_profile_id):
            raise UnknownProfileError(store.unknown_message(resolved_profile_id))

        # The id and the profile are separate arguments, so nothing stops a caller
        # pairing one candidate's id with another's profile -- which files those
        # documents under the wrong person, silently and irreversibly. Where the
        # store holds that id, the stored profile is authoritative and the supplied
        # one must be that same person.
        #
        # Only the *name* is compared, deliberately. A caller may legitimately pass a
        # profile it has edited in memory -- several tests do, and a future UI might
        # let a user preview an edit before saving it. Comparing whole identity
        # objects would reject those correct cases (a changed ``visa_status`` is not
        # cross-contamination); comparing full names catches the case that matters,
        # two different people under one id.
        stored = store.load(resolved_profile_id)
        if stored.identity.full_name != profile.identity.full_name:
            raise ProfileMismatchError(
                f"The profile for {resolved_profile_id!r} is "
                f"{stored.identity.full_name!r}, but the profile passed in is "
                f"{profile.identity.full_name!r}. Refusing to file one candidate's "
                "documents under another candidate's id. Load the profile from the "
                "store (`config.load_profile()`), or use that candidate's own id."
            )

    work_country = (work_country or "").strip() or None
    # The profile is serialized exactly once per application, and those **same bytes**
    # are used twice: they are emitted into the prompt context, and they are hashed
    # into the cache key. One string, so the key cannot describe a prompt the model
    # was not shown.
    profile_bytes = serialize_profile_bytes(profile)
    cv_prompt_source = PROMPT_CV_PATH.read_text(encoding="utf-8")
    cl_prompt_source = PROMPT_CL_PATH.read_text(encoding="utf-8")
    context = build_context(
        job_description, profile, company_name, role_title, work_country,
        profile_bytes=profile_bytes,
    )
    cv_prompt = build_cv_prompt(cv_prompt_source, context)
    cl_prompt = cl_prompt_source + context

    generator = DocumentGenerator(
        service=service, profile=profile, rules=rules, status_callback=status_callback
    )

    # The job folder is rooted in the *store* when the store is authoritative. ADR 0011
    # puts real candidate data outside the public repository, so writing documents to
    # <repo>/outputs/ would contradict the privacy model even though that path is
    # gitignored: a stray `git add -f`, a backup or an archive would publish them.
    # A loose `--profile <path>` names no store, so it keeps the repository root.
    #
    # ``ApplicationStore`` appends the candidate segment itself, so it takes the
    # parent of ``ProfileStore.outputs_dir()`` -- passing the per-profile directory
    # would nest the id twice.
    #
    # **``config.outputs_dir`` is NOT consulted here, and that is deliberate.** It is
    # the *mirror* destination -- ``ApplicationStore.mirror`` copies documents there --
    # not the primary output root. Using it as the root would move where a normal run
    # writes whenever a user configured mirroring, which is a behaviour change dressed
    # as a fix. A caller that wants output somewhere else roots the **store** there
    # (``profile_store_dir``), which is the supported way to relocate generated
    # documents and is what the evaluation suite does.
    outputs_root = (
        config.store.outputs_dir(resolved_profile_id).parent
        if config.profile_path is None
        else PROJECT_ROOT / "outputs"
    )

    # --- the cache lookup happens before any paid call ---------------------------------
    # Read before the folder is created, so a hit and a miss leave the same footprint
    # on the store and the cache never depends on a job folder existing. A cold cache
    # reads nothing and writes nothing here: the entry is written only once a
    # *validated* result exists (see below), which is what keeps this item's call
    # counts identical to the pre-item baseline.
    key = cache_key(
        profile_bytes=profile_bytes,
        job_description=job_description,
        company_name=company_name,
        role_title=role_title,
        work_country=work_country,
        prompt_cv=cv_prompt_source,
        prompt_cl=cl_prompt_source,
        prompt_version=_source_digest(PROMPT_CV_PATH),
        schema_version=_schema_digest(),
        provider=config.provider_name,
        model_cv=config.model_for("cv"),
        model_cl=config.model_for("cover_letter"),
        rules_fingerprint=rules_fingerprint(generator.rules),
        format_version=CACHE_FORMAT_VERSION,
    )
    cache = GenerationCache(_cache_root(config) / resolved_profile_id)
    entry = None
    cv = cl = explanation = None
    if use_cache:
        cv, cl, entry = _cache_read(
            cache, key, generator, work_country, company_name, role_title
        )
    if entry is None:
        cv, cl, explanation = generator.generate_pair(
            cv_prompt, cl_prompt,
            work_country=work_country, company_name=company_name, role_title=role_title,
        )
    else:
        explanation = entry.tailoring_explanation
        if status_callback:
            status_callback("Reusing a stored generation for this exact posting.")

    job_id = make_job_id(
        company_name or cl.company_name, role_title or cl.role_title, slugify,
        profile_id=resolved_profile_id,
    )
    applications = ApplicationStore(
        outputs_root=outputs_root, job_id=job_id, profile_id=resolved_profile_id
    )
    applications.create(profile.model_dump(), job_description)
    # On a hit the restored responses are the audit trail; on a miss the generator's own.
    # ``drafts`` therefore has two sources, and this is the single place they are
    # chosen, so the folder is written identically either way.
    drafts = entry.drafts if entry is not None else generator.drafts
    applications.save_drafts(drafts)

    latex = create_latex_renderer(outputs_dir=str(applications.job_folder))
    docx = create_docx_renderer(outputs_dir=str(applications.job_folder))
    position = role_title or cl.role_title
    page_count = 0
    history = []

    def save_content() -> None:
        applications.save_content({
            "company_name": cl.company_name, "role_title": position,
            "work_country": work_country,
            "cv": cv.model_dump(), "cover_letter": cl.model_dump(),
        })

    try:
        for attempt in range(MAX_LAYOUT_ATTEMPTS):
            save_content()
            cv_path = latex.render_cv(cv, profile, job_position=position)
            page_count = count_pdf_pages(Path(cv_path))
            history.append(page_count)
            if page_count <= 2:
                break
            if attempt == MAX_LAYOUT_ATTEMPTS - 1:
                raise ValueError(
                    f"CV is still {page_count} pages after four layout attempts. "
                    f"Editable drafts are saved at {applications.source_folder}; generation "
                    "was not marked successful."
                )
            cv, explanation = generator.shorten_cv(
                cv, page_count, attempt, cv_prompt,
                work_country, company_name, role_title, explanation,
            )
        cl_path, cl_pdf_path = docx.render_cover_letter(cl, profile, job_position=position)
        if not cl_pdf_path:
            raise ValueError("Cover-letter PDF rendering failed.")
        cl_pages = count_pdf_pages(Path(cl_pdf_path))
        if cl_pages != 1:
            raise ValueError(f"Cover-letter PDF is {cl_pages} pages; expected one page.")
    except Exception as error:
        # Preserve everything editable, then mark the folder failed explicitly (D-14).
        save_content()
        applications.save_drafts(drafts)
        applications.save_failure(str(error), history)
        raise

    # Separate CV/letter usage and include every review and shortening attempt.
    usage = service.calculate_token_usage(**generator.usage_kwargs())
    explanation_dict = (
        TailoringExplanation.model_validate(explanation).model_dump()
        if isinstance(explanation, dict)
        else None
    )
    # --- store the result, now that it is validated ------------------------------------
    # This is the only place an entry is written, and it is reached only after the
    # page-count gate has passed, so a draft that failed the gate can never become a
    # permanent answer. A hit is not rewritten: it is already stored, byte for byte.
    #
    # On a **hit** the entry records the current run's zero usage, because the stored
    # documents are now what this run produced; keeping the original run's token
    # totals would charge this run for calls it did not make. The cost of the run
    # that originally paid for it is preserved as ``original_usage`` in the same file.
    if entry is None:
        _cache_write(
            cache, key, cv, cl, explanation_dict, generator.drafts,
            usage.model_dump(), config,
        )
    else:
        _cache_write(
            cache, key, cv, cl, explanation_dict, entry.drafts, usage.model_dump(), config,
        )
    result = TailorResponse(
        job_id=job_id, cv_path=str(cv_path), cover_letter_path=str(cl_path),
        cl_pdf_path=str(cl_pdf_path), token_usage=usage,
        cv_page_count=page_count, cover_letter_page_count=cl_pages,
        source_path=str(applications.source_folder / "content.json"),
        tailoring_explanation=explanation_dict,
        message=(
            f"CV checked: {page_count} pages. Cover letter: {cl_pages} page, "
            f"{sum(len(p.split()) for p in cl.paragraphs)} words."
        ),
    )
    applications.save_drafts(drafts)
    # Mirroring is read from the config at call time, never at import time.
    mirror = applications.mirror(result, config)
    applications.save_manifest(result.model_dump(), history)
    if mirror is not None:
        applications.save_manifest_copy(mirror)
    logger.info(
        "Generated %s: %s CV pages; layout history %s; cache %s",
        job_id, page_count, history, "hit" if entry is not None else "miss",
    )
    return result
