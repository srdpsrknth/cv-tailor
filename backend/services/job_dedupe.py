"""Deduplication and expiry detection for normalised jobs (Phase 4, item 4).

Two problems, both created by the fact that Phase 4 reads *many* sources at once:

**Deduplication.** The same vacancy is routinely listed on several boards, and the
records disagree: different ids, different urls, different wording ("Senior Data
Engineer (m/w/d)" on one board, "Senior Data Engineer" on another), sometimes
different cities for one role. Showing a user the same job four times in a ranked
list is the most visible failure Phase 4 can produce.

The rule here is deliberately **conservative and explainable**, in that order of
priority:

1. The same ``(source, source_id)`` is the same record, trivially.
2. An identical :meth:`Job.content_fingerprint` (normalised company + title + city
   + country) **from a different source** is the same vacancy.
3. Otherwise they are **kept separate**. No fuzzy matching, no title-similarity
   threshold, no "same company and similar title" heuristic.

Two parts of that rule are load-bearing and were both learned by testing:

**Rule 2 requires a different source.** A single source's id is authoritative: two
ids from one source are two postings, even with identical titles, because employers
routinely open several reqs for one role in one city ("Data Engineer" x3). Merging
those on content alone hides a vacancy, which is precisely the silent failure this
module is written to avoid. Cross-source matching is the case the fingerprint is
for, because two boards carrying one vacancy share no id.

**Rule 3 is the important one.** A false merge **loses a job the user never sees**
and is invisible; a false split shows a duplicate, which is merely annoying and can
be seen. When the cost is asymmetric and one error is silent, the merge must earn
its confidence. So a merge happens only on a key that is exactly equal after
normalisation, and every merge records **why** (:class:`MergeReason`) so the output
can be audited rather than trusted.

**Expiry detection.** No DACH source publishes an expiry date -- only Himalayas
offers one, and it is not a DACH source. So expiry cannot be read; it must be
**observed**: a posting that a source used to return and no longer does has almost
certainly been filled or withdrawn. This module records what a source returned in
each sweep and reports the difference, which is the only honest answer available
from the data. A posting that is merely *missing from this sweep* is reported as
:attr:`ExpiryStatus.DISAPPEARED` rather than deleted, because a source outage looks
identical to a mass expiry from one sweep alone and erasing a user's saved job
because a board had a bad afternoon would be the wrong call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Optional

from models.job import Job


class MergeReason(str, Enum):
    """Why two records were judged to be the same vacancy. Always recorded."""

    #: Same source, same id: the same record seen twice.
    IDENTICAL_KEY = "identical_key"
    #: Identical normalised content fingerprint, across different sources/ids.
    CONTENT_FINGERPRINT = "content_fingerprint"


@dataclass
class DuplicateGroup:
    """One surviving job plus the records merged into it.

    ``merged`` holds the *other* records, so nothing is discarded silently and a
    user (or a test) can always see what a merge swallowed.
    """

    primary: Job
    merged: list = field(default_factory=list)
    #: MergeReason -> count, so a report can say how the merge was justified.
    reasons: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        """How many source records this group represents."""
        return 1 + len(self.merged)

    def all_sources(self) -> list:
        """Every source that carried this vacancy, primary first."""
        return [self.primary.source] + [job.source for job in self.merged]

    def as_dict(self) -> dict:
        return {
            "job": self.primary.as_dict(),
            "merged_count": len(self.merged),
            "sources": self.all_sources(),
            "reasons": {reason.value: count for reason, count in self.reasons.items()},
            "merged": [
                {"source": job.source, "source_id": job.source_id, "url": job.url,
                 "title": job.title, "company": job.company}
                for job in self.merged
            ],
        }


def _record_reason(group: DuplicateGroup, reason: MergeReason) -> None:
    group.reasons[reason] = group.reasons.get(reason, 0) + 1


def _prefer_over(candidate: Job, incumbent: Job) -> bool:
    """True when ``candidate`` should represent the group instead of ``incumbent``.

    Preference is deterministic, so the same input always produces the same output
    and a re-run does not shuffle which url a user sees:

    1. A record with a description beats one without -- the description is what the
       generation pipeline actually consumes, so a duplicate without one is worth
       less.
    2. Then a *verified* country beats an absent one, because a group whose country
       is known can be DACH-filtered correctly.
    3. Then the source that provides more verified fields.
    4. Finally the natural key, purely so the result is stable.
    """
    def score(job: Job) -> tuple:
        return (
            1 if job.description else 0,
            1 if job.country.is_verified else 0,
            len(job.verified_fields()),
        )

    mine, theirs = score(candidate), score(incumbent)
    if mine != theirs:
        return mine > theirs
    return candidate.key < incumbent.key


def deduplicate(jobs: Iterable[Job]) -> list:
    """Group duplicate records, keeping one representative per vacancy.

    Returns a list of :class:`DuplicateGroup`, in the order each vacancy was first
    seen, so the caller's ordering is preserved and the function is stable.

    Matching is **exact after normalisation**, and a content match additionally
    requires that the two records come from **different sources**. Two ids from one
    source are two postings even when everything else is identical, because
    employers do open several reqs for one title in one city. Anything less certain
    is left as two jobs, because a wrong merge hides a vacancy from the user and
    cannot be noticed from the output.
    """
    by_key: dict = {}
    #: fingerprint -> {source name: group}. Keyed by source so only a *different*
    #: source can match on content (see the module docstring).
    by_fingerprint: dict = {}
    groups: list = []

    for job in jobs:
        # Rule 1: the same record from the same source.
        if job.key in by_key:
            group = by_key[job.key]
            _record_reason(group, MergeReason.IDENTICAL_KEY)
            if _prefer_over(job, group.primary):
                group.merged.append(group.primary)
                group.primary = job
            else:
                group.merged.append(job)
            by_key[job.key] = group
            continue

        # Rule 2: the same vacancy under a different key, from a different source.
        fingerprint = job.content_fingerprint()
        seen_sources = by_fingerprint.setdefault(fingerprint, {})
        existing = next(
            (group for source, group in seen_sources.items() if source != job.source),
            None,
        )
        if existing is not None:
            _record_reason(existing, MergeReason.CONTENT_FINGERPRINT)
            if _prefer_over(job, existing.primary):
                existing.merged.append(existing.primary)
                existing.primary = job
            else:
                existing.merged.append(job)
            by_key[job.key] = existing
            seen_sources[job.source] = existing
            continue

        # Rule 3: not provably the same, so it stays its own job.
        group = DuplicateGroup(primary=job)
        by_key[job.key] = group
        seen_sources[job.source] = group
        groups.append(group)

    return groups


def collapse(jobs: Iterable[Job]) -> list:
    """Convenience: the surviving :class:`Job` per vacancy, duplicates dropped."""
    return [group.primary for group in deduplicate(jobs)]


def duplicate_report(groups: Iterable[DuplicateGroup]) -> dict:
    """A summary of what was merged, for the CLI and for auditability."""
    groups = list(groups)
    collapsed = [group for group in groups if group.size > 1]
    return {
        "jobs_in": sum(group.size for group in groups),
        "jobs_out": len(groups),
        "duplicates_removed": sum(group.size - 1 for group in groups),
        "groups_with_duplicates": len(collapsed),
        "by_reason": {
            reason.value: sum(
                group.reasons.get(reason, 0) for group in groups
            )
            for reason in MergeReason
        },
    }


# --- expiry -----------------------------------------------------------------------------

class ExpiryStatus(str, Enum):
    """What a sweep comparison says about a previously seen posting."""

    #: Still returned by its source.
    ACTIVE = "active"
    #: Not returned this sweep. Reported, never silently deleted -- a source
    #: outage looks the same as a mass expiry from one sweep alone.
    DISAPPEARED = "disappeared"
    #: Seen for the first time this sweep.
    NEW = "new"
    #: The source stated an expiry date and it has passed. Rare and authoritative.
    EXPIRED_DECLARED = "expired_declared"


@dataclass
class ExpiryVerdict:
    """The expiry judgement for one job, with the evidence behind it."""

    job_key: str
    status: ExpiryStatus
    #: Human-readable justification, so the answer is never a bare enum.
    reason: str
    #: How long since it was last seen, when it has disappeared.
    missing_since: Optional[datetime] = None
    #: For DISAPPEARED: how many consecutive sweeps it has been absent.
    consecutive_misses: int = 0

    @property
    def is_live(self) -> bool:
        """True when the posting should still be offered to the user."""
        return self.status in (ExpiryStatus.ACTIVE, ExpiryStatus.NEW)

    def as_dict(self) -> dict:
        return {
            "job_key": self.job_key,
            "status": self.status.value,
            "reason": self.reason,
            "missing_since": self.missing_since.isoformat() if self.missing_since else None,
            "consecutive_misses": self.consecutive_misses,
            "is_live": self.is_live,
        }


@dataclass
class SweepRecord:
    """When each job was last seen, per source. The memory expiry needs.

    Kept as plain data so it can be persisted as JSON in the private store; the
    shape is intentionally small, because it is written on every search.
    """

    #: job key -> {"first_seen": iso, "last_seen": iso, "misses": int}
    seen: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"seen": self.seen}

    @classmethod
    def from_dict(cls, payload: Optional[dict]) -> "SweepRecord":
        """Rebuild from stored JSON, tolerating a missing or malformed payload."""
        if not isinstance(payload, dict):
            return cls()
        seen = payload.get("seen")
        return cls(seen=dict(seen) if isinstance(seen, dict) else {})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_expiry(
    jobs: Iterable[Job],
    record: SweepRecord,
    *,
    swept_sources: Optional[Iterable[str]] = None,
    now: Optional[datetime] = None,
    grace: timedelta = timedelta(0),
) -> list:
    """Compare this sweep with the stored record and judge each job.

    ``swept_sources`` is **required for a correct answer** and is the subtle part.
    A job is only "disappeared" if the source that carried it was actually
    *consulted* this time. Treating an unswept source's jobs as vanished would
    report every posting from a source the user temporarily disabled as expired.

    ``grace`` suppresses a DISAPPEARED verdict until a job has been missing for
    longer than that, which absorbs a single flaky sweep.
    """
    moment = now or _now()
    consulted = set(swept_sources) if swept_sources is not None else None
    verdicts: list = []
    current_keys = set()

    for job in jobs:
        current_keys.add(job.key)
        entry = record.seen.get(job.key) or {}
        first_seen = _parse(entry.get("first_seen")) or moment
        record.seen[job.key] = {
            "first_seen": first_seen.isoformat(),
            "last_seen": moment.isoformat(),
            "misses": 0,
        }
        if entry:
            verdicts.append(ExpiryVerdict(
                job_key=job.key,
                status=ExpiryStatus.ACTIVE,
                reason="returned by its source in this sweep",
            ))
        else:
            verdicts.append(ExpiryVerdict(
                job_key=job.key,
                status=ExpiryStatus.NEW,
                reason="first seen in this sweep",
            ))

    for key, entry in list(record.seen.items()):
        if key in current_keys:
            continue
        source = key.split(":", 1)[0]
        # Only a source we actually consulted can tell us a job is gone.
        if consulted is not None and source not in consulted:
            verdicts.append(ExpiryVerdict(
                job_key=key,
                status=ExpiryStatus.ACTIVE,
                reason=(f"source {source!r} was not searched this sweep, so its "
                        "absence is not evidence of expiry"),
            ))
            continue
        misses = int(entry.get("misses") or 0) + 1
        last_seen = _parse(entry.get("last_seen"))
        missing_since = last_seen
        record.seen[key] = {**entry, "misses": misses}
        if grace and last_seen and (moment - last_seen) < grace:
            verdicts.append(ExpiryVerdict(
                job_key=key,
                status=ExpiryStatus.ACTIVE,
                reason=(f"missing for less than the grace period "
                        f"({grace}); treated as still live"),
                missing_since=missing_since,
                consecutive_misses=misses,
            ))
            continue
        verdicts.append(ExpiryVerdict(
            job_key=key,
            status=ExpiryStatus.DISAPPEARED,
            reason=(f"not returned by {source!r} in {misses} consecutive "
                    "sweep(s); likely filled or withdrawn"),
            missing_since=missing_since,
            consecutive_misses=misses,
        ))

    return verdicts


def expiry_report(verdicts: Iterable[ExpiryVerdict]) -> dict:
    """Counts per status, for a CLI summary."""
    verdicts = list(verdicts)
    counts = {status.value: 0 for status in ExpiryStatus}
    for verdict in verdicts:
        counts[verdict.status.value] += 1
    return {
        "total": len(verdicts),
        "live": sum(1 for verdict in verdicts if verdict.is_live),
        "counts": counts,
    }
