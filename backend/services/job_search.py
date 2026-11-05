"""The job-search service: connectors, dedupe, expiry and matching, in one call.

This is the seam the CLI and any future UI use, in the same spirit as
:mod:`services.tailor_service` -- the business rules live here and the interface
stays thin, so nothing is duplicated between a CLI and a web front end later.

Three behaviours are worth stating because they are what a caller relies on:

**One failing source does not fail the search.** ADR 0008 requires that a source
which changes or withdraws access affects only its own connector, so a
:class:`~models.job.JobSourceError` is caught, recorded in
:attr:`SearchOutcome.failures` and reported. A search that quietly returned fewer
jobs because one source 500'd would be worse than one that says so.

**Dedupe happens before ranking**, because ranking duplicates would let one
vacancy occupy several positions and crowd out others.

**Expiry is observed, never assumed.** The sweep record persists what each source
returned, and only sources actually consulted this run can expire their own jobs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from models.job import Job, JobSource, JobSourceError, SearchQuery
from models.profile import Profile
from services.job_dedupe import (
    DuplicateGroup,
    ExpiryVerdict,
    SweepRecord,
    deduplicate,
    duplicate_report,
    evaluate_expiry,
    expiry_report,
)
from services.job_match import (
    Eligibility,
    MatchPreferences,
    MatchResult,
    rank_jobs,
    ranking_report,
)

#: Filename of the sweep record inside a profile's job directory.
SWEEP_FILENAME = "sweep.json"


@dataclass
class SearchOutcome:
    """Everything one search produced, including what went wrong."""

    query: SearchQuery
    results: List[MatchResult] = field(default_factory=list)
    #: Vacancies collapsed by dedupe, for auditing.
    groups: List[DuplicateGroup] = field(default_factory=list)
    #: Expiry verdicts for everything seen, live or not.
    expiry: List[ExpiryVerdict] = field(default_factory=list)
    #: source name -> error message, for sources that failed.
    failures: dict = field(default_factory=dict)
    #: Honest warnings about filtering a source could not do itself.
    notes: List[str] = field(default_factory=list)
    #: Jobs read from sources before dedupe.
    jobs_read: int = 0

    @property
    def jobs(self) -> List[Job]:
        """The surviving jobs, best match first."""
        return [result.job for result in self.results]

    def as_dict(self) -> dict:
        return {
            "query": {
                "keywords": self.query.keywords, "country": self.query.country,
                "city": self.query.city, "remote": self.query.remote,
                "limit": self.query.limit,
            },
            "jobs_read": self.jobs_read,
            "dedupe": duplicate_report(self.groups),
            "expiry": expiry_report(self.expiry),
            "ranking": ranking_report(self.results),
            "failures": self.failures,
            "notes": self.notes,
            "results": [result.as_dict() for result in self.results],
        }


def sweep_path(store_root, profile_id: str) -> Path:
    """Where the sweep record lives: ``<store>/jobs/<profile_id>/sweep.json``.

    Under the candidate segment like every other per-candidate artefact
    (ADR 0003), and inside the private store rather than the repository
    (ADR 0002/0011), because which jobs someone looked at is personal data.
    """
    from services.profile_store import validate_profile_id

    return Path(store_root) / "jobs" / validate_profile_id(profile_id) / SWEEP_FILENAME


def load_sweep(store_root, profile_id: str) -> SweepRecord:
    """Read the sweep record, tolerating absence and corruption.

    A missing or malformed file costs one sweep of expiry accuracy, never an
    error: a search must work on a fresh machine.
    """
    path = sweep_path(store_root, profile_id)
    if not path.is_file():
        return SweepRecord()
    try:
        return SweepRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return SweepRecord()


def save_sweep(store_root, profile_id: str, record: SweepRecord) -> Path:
    """Persist the sweep record, creating the directory when needed."""
    path = sweep_path(store_root, profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.as_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def collect_jobs(sources: Iterable[JobSource], query: SearchQuery) -> tuple:
    """Read from every source, isolating failures.

    Returns ``(jobs, failures, notes, sources_consulted)``. A source that raises is
    recorded and skipped, so one withdrawn or broken source cannot take the search
    down with it (ADR 0008).
    """
    jobs: List[Job] = []
    failures: dict = {}
    notes: List[str] = []
    consulted: List[str] = []

    for source in sources:
        consulted.append(source.name)
        for note in source.capabilities.limitations_for(query):
            notes.append(f"{source.name}: {note}")
        try:
            jobs.extend(source.search(query))
        except JobSourceError as error:
            failures[source.name] = error.message
        except Exception as error:  # noqa: BLE001 - one source must not break the run
            failures[source.name] = f"{type(error).__name__}: {error}"

    return jobs, failures, notes, consulted


def search_jobs(
    sources: Iterable[JobSource],
    profile: Profile,
    query: SearchQuery,
    *,
    preferences: Optional[MatchPreferences] = None,
    store_root=None,
    profile_id: Optional[str] = None,
    sweep: Optional[SweepRecord] = None,
    persist_sweep: bool = True,
    now: Optional[datetime] = None,
    include_ineligible: bool = False,
    grace: timedelta = timedelta(days=1),
) -> SearchOutcome:
    """Read, deduplicate, expire-check and rank jobs for one candidate.

    ``profile_id`` is required whenever ``store_root`` is given, and fails closed
    through :func:`sweep_path` (ADR 0003): which jobs a candidate looked at must
    never be filed under another candidate's id.
    """
    moment = now or datetime.now(timezone.utc)
    jobs, failures, notes, consulted = collect_jobs(sources, query)

    groups = deduplicate(jobs)
    survivors = [group.primary for group in groups]

    # Expiry is judged against the *deduplicated* set, so a vacancy carried by two
    # sources is only "gone" when neither returned it.
    record = sweep if sweep is not None else (
        load_sweep(store_root, profile_id) if store_root and profile_id else SweepRecord()
    )
    verdicts = evaluate_expiry(survivors, record, swept_sources=consulted,
                               now=moment, grace=grace)
    gone = {verdict.job_key for verdict in verdicts
            if verdict.status.value == "disappeared"}

    # The query's keywords must reach the matcher, or a keyword search would show
    # every job the sources returned regardless of relevance -- which is exactly
    # what happened before this was wired through. An explicit `preferences`
    # argument wins, but the query's keywords still apply unless that argument
    # already carries keywords of its own.
    if preferences is None:
        keywords = tuple(query.keywords.split()) if query.keywords else ()
        effective_preferences = MatchPreferences.from_profile(profile, keywords=keywords)
    elif not preferences.keywords and query.keywords:
        effective_preferences = MatchPreferences(
            **{**preferences.__dict__, "keywords": tuple(query.keywords.split())}
        )
    else:
        effective_preferences = preferences

    results = rank_jobs(
        (job for job in survivors if job.key not in gone),
        effective_preferences,
        now=moment,
        include_ineligible=include_ineligible,
    )

    if persist_sweep and store_root and profile_id:
        save_sweep(store_root, profile_id, record)

    return SearchOutcome(
        query=query,
        results=results,
        groups=groups,
        expiry=verdicts,
        failures=failures,
        notes=notes,
        jobs_read=len(jobs),
    )


def summarise(outcome: SearchOutcome) -> str:
    """A short human-readable summary, used by the CLI."""
    lines = [
        f"Read {outcome.jobs_read} job(s) from "
        f"{len(outcome.groups)} distinct vacancy/vacancies"
        if outcome.jobs_read else "No jobs were read.",
        f"Showing {len(outcome.results)} ranked match(es).",
    ]
    report = ranking_report(outcome.results)
    if report["uncertain"]:
        lines.append(f"{report['uncertain']} need a check before applying.")
    expiry = expiry_report(outcome.expiry)
    if expiry["counts"]["disappeared"]:
        lines.append(f"{expiry['counts']['disappeared']} previously seen job(s) "
                     "no longer appear at their source.")
    if outcome.failures:
        for name, message in outcome.failures.items():
            lines.append(f"source {name} failed: {message}")
    return "\n".join(lines)
