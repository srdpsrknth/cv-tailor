"""Deterministic, explainable job matching (Phase 4, item 5).

The roadmap's acceptance criterion is *"normalised, deduplicated jobs with
human-readable match explanations; **no invented scores**"*. That phrase drives
every decision in this module:

**A score is a count of named evidence, never a judgement.** The rank is the
number of distinct reasons that fired, and each reason is recorded with the
evidence that produced it. There is no opaque weighting, no tuned coefficient, and
no model call. Two runs over the same input always produce the same order, so a
result can be explained and re-checked rather than trusted.

**Hard eligibility is separate from preference, and is never a score.** The two
answer different questions and conflating them is how a tool quietly shows someone
a job they cannot take:

* :class:`Eligibility` answers *"is this job possible for this candidate at all?"*
  and has three values, not two. A geographic or language constraint can be
  checked against facts, so it is ``INELIGIBLE`` or ``ELIGIBLE``.
* But a *possible* blocker that the data cannot settle (a posting demanding a
  permit the candidate may not have) is :attr:`Eligibility.UNCERTAIN`, **not**
  ``INELIGIBLE`` and **not** silently ``ELIGIBLE``. Collapsing "we know they can't"
  into "we don't know" would either hide a legitimate job or overstate confidence.
  Uncertain jobs are surfaced **with the reason**, so the candidate decides.

**Nothing is fabricated to break a tie or fill a gap.** If a posting says nothing
about a preference, that preference simply does not score -- it does not score zero
and it does not score by default. A missing fact is reported in
:attr:`MatchResult.unknowns`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from models.job import Job, Remote


class Eligibility(str, Enum):
    """Whether a candidate could take a job, kept apart from how well it fits."""

    ELIGIBLE = "eligible"
    #: A constraint we cannot settle from the available data. Surfaced, not hidden.
    UNCERTAIN = "uncertain"
    INELIGIBLE = "ineligible"


class Reason(str, Enum):
    """A named piece of evidence for a match. Every point traces to one of these."""

    TITLE_KEYWORD = "title_keyword"
    SKILL_IN_DESCRIPTION = "skill_in_description"
    SKILL_IN_TITLE = "skill_in_title"
    LANGUAGE_MATCH = "language_match"
    LOCATION_PREFERENCE = "location_preference"
    REMOTE_PREFERENCE = "remote_preference"
    RECENCY = "recency"


class Blocker(str, Enum):
    """A named reason a job is ineligible or uncertain. Never a score."""

    #: The posting names a country the candidate is not eligible to work in.
    COUNTRY_NOT_ELIGIBLE = "country_not_eligible"
    #: The posting demands a language the candidate does not have.
    LANGUAGE_REQUIRED_MISSING = "language_required_missing"
    #: The posting appears to require existing work authorisation.
    WORK_AUTHORISATION_UNCLEAR = "work_authorisation_unclear"
    #: The posting names a seniority far above the candidate's.
    SENIORITY_MISMATCH = "seniority_mismatch"


#: How a blocker affects eligibility. INELIGIBLE hides; UNCERTAIN shows with a warning.
_BLOCKER_SEVERITY = {
    Blocker.COUNTRY_NOT_ELIGIBLE: Eligibility.INELIGIBLE,
    Blocker.LANGUAGE_REQUIRED_MISSING: Eligibility.INELIGIBLE,
    Blocker.WORK_AUTHORISATION_UNCLEAR: Eligibility.UNCERTAIN,
    Blocker.SENIORITY_MISMATCH: Eligibility.UNCERTAIN,
}


@dataclass(frozen=True)
class MatchPreferences:
    """What the candidate wants. All optional; a preference with no value is inert.

    ``skills`` and ``languages`` are read from the profile by the caller rather than
    invented here, so the matcher has no opinion about a candidate it was not told
    about.
    """

    #: Keywords the candidate is looking for, matched against title and description.
    keywords: tuple = ()
    #: Skills the candidate can evidence, from the profile.
    skills: tuple = ()
    #: Languages the candidate speaks, from the profile.
    languages: tuple = ()
    #: Country codes the candidate may work in. Empty means "no constraint".
    eligible_countries: tuple = ()
    #: Cities the candidate prefers, lowercased.
    preferred_cities: tuple = ()
    #: Whether the candidate wants remote work. ``None`` means no preference.
    prefers_remote: Optional[bool] = None
    #: Postings newer than this many days score for recency.
    recency_days: int = 30
    #: Seniority words that put a posting out of reach, matched case-insensitively.
    over_senior_titles: tuple = ("head of", "director", "vp ", "vice president",
                                 "chief ", "principal", "lead ")

    def as_dict(self) -> dict:
        return {
            "keywords": list(self.keywords),
            "skills": list(self.skills),
            "languages": list(self.languages),
            "eligible_countries": list(self.eligible_countries),
            "preferred_cities": list(self.preferred_cities),
            "prefers_remote": self.prefers_remote,
            "recency_days": self.recency_days,
        }

    @classmethod
    def from_profile(cls, profile, **overrides) -> "MatchPreferences":
        """Build preferences from a candidate profile.

        Reads only fields the profile actually declares: the skills inventory, the
        spoken languages, and the home countries from its rules. Nothing is
        defaulted from another candidate's data, matching the fail-closed spirit of
        ADR 0003 -- a profile that declares no skills yields no skill preferences
        rather than a guess.
        """
        skills = []
        for values in (getattr(profile, "skills", None) or {}).values():
            skills.extend(values)
        languages = [entry.name for entry in (getattr(profile, "languages", None) or [])]
        rules = getattr(profile, "rules", None)
        countries = tuple(getattr(rules, "home_countries", None) or ()) if rules else ()

        base = {
            "skills": tuple(skills),
            "languages": tuple(languages),
            "eligible_countries": tuple(countries),
        }
        base.update(overrides)
        return cls(**base)


@dataclass
class MatchEvidence:
    """One reason a job scored, with the evidence that produced it."""

    reason: Reason
    detail: str
    #: The matched terms, so the explanation can name them.
    terms: tuple = ()

    def as_dict(self) -> dict:
        return {"reason": self.reason.value, "detail": self.detail,
                "terms": list(self.terms)}


@dataclass
class MatchResult:
    """A scored job plus everything needed to explain and audit the score."""

    job: Job
    eligibility: Eligibility = Eligibility.ELIGIBLE
    evidence: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    #: Facts the posting did not state, so a low score is not mistaken for a bad job.
    unknowns: list = field(default_factory=list)
    #: Whether the caller's keyword filter was actually applied.
    matched_keywords: bool = True

    @property
    def score(self) -> int:
        """The rank: how many named reasons fired. Never a tuned coefficient.

        This is deliberately a count rather than a weighted sum. A weight would
        imply a precision this data does not support -- the sources disagree about
        location, several omit descriptions, and none publishes an expiry date. A
        count can be verified by reading the evidence list; a weight cannot.
        """
        return len(self.evidence)

    @property
    def is_visible(self) -> bool:
        """True unless a *known* constraint rules the job out.

        Uncertain jobs remain visible on purpose: hiding them would discard
        legitimate opportunities, and showing them silently would overstate what we
        know.
        """
        return self.eligibility is not Eligibility.INELIGIBLE

    def explanation(self) -> list:
        """Human-readable lines explaining the result, for CLI output."""
        lines = []
        if self.blockers:
            for blocker, detail in self.blockers:
                prefix = ("cannot apply" if _BLOCKER_SEVERITY[blocker]
                          is Eligibility.INELIGIBLE else "check first")
                lines.append(f"{prefix}: {detail}")
        for item in self.evidence:
            lines.append(f"match: {item.detail}")
        if not self.evidence and not self.blockers:
            lines.append("no specific match reasons; shown without a preference score")
        for unknown in self.unknowns:
            lines.append(f"not stated by the source: {unknown}")
        return lines

    def as_dict(self) -> dict:
        return {
            "job": self.job.as_dict(),
            "score": self.score,
            "eligibility": self.eligibility.value,
            "is_visible": self.is_visible,
            "evidence": [item.as_dict() for item in self.evidence],
            "blockers": [
                {"blocker": blocker.value,
                 "severity": _BLOCKER_SEVERITY[blocker].value,
                 "detail": detail}
                for blocker, detail in self.blockers
            ],
            "unknowns": list(self.unknowns),
            "explanation": self.explanation(),
        }


# --- keyword and skill matching ---------------------------------------------------------

def _tokens(text: str) -> set:
    """Lowercased word tokens, for whole-word comparison rather than substring."""
    return {token for token in re.split(r"[^\w+#.]+", (text or "").lower()) if token}


def _contains_term(haystack_lower: str, term: str) -> bool:
    """True when ``term`` appears in ``haystack_lower`` at a word boundary.

    Substring matching alone would let "R" match "React" and "SQL" match
    "NoSQL" -- a false positive that would award a pointless match point. Terms
    containing punctuation (``c++``, ``ci/cd``, ``.net``) fall back to a plain
    substring test, because a word-boundary regex is meaningless for them.
    """
    if not term:
        return False
    lowered = term.lower().strip()
    if re.search(r"[^\w\s]", lowered):
        return lowered in haystack_lower
    return re.search(rf"(?<!\w){re.escape(lowered)}(?!\w)", haystack_lower) is not None


def _hits(haystack: str, terms: Iterable[str]) -> list:
    """The terms that appear, preserving the caller's order and de-duplicated."""
    lowered = (haystack or "").lower()
    found, seen = [], set()
    for term in terms:
        key = (term or "").lower().strip()
        if not key or key in seen:
            continue
        if _contains_term(lowered, key):
            found.append(term)
            seen.add(key)
    return found


def _dedupe_terms(terms: Iterable[str]) -> list:
    """The distinct, non-blank terms in a preference list.

    Needed because the keyword rule is "all of them matched": the denominator must
    count distinct terms, or a caller passing ``("sql", "SQL")`` could never
    satisfy it.
    """
    out, seen = [], set()
    for term in terms or ():
        key = (term or "").lower().strip()
        if key and key not in seen:
            out.append(term)
            seen.add(key)
    return out


# --- eligibility ------------------------------------------------------------------------

def evaluate_eligibility(job: Job, preferences: MatchPreferences) -> tuple:
    """Return ``(eligibility, blockers)``. Never counts towards the score.

    Checks only what the posting actually states. A country the candidate may not
    work in is a hard block; a language the posting explicitly demands and the
    candidate lacks is a hard block; an unclear authorisation requirement is
    uncertain. Silence about a constraint is not a block -- it is an unknown.
    """
    blockers: list = []
    text = f"{job.title} {job.description}".lower()

    # Country: only a *verified* country can prove ineligibility. An absent country
    # is an unknown, not a violation.
    if preferences.eligible_countries and job.country.is_verified and job.country.value:
        allowed = {code.upper() for code in preferences.eligible_countries}
        codes = {job.country.value.upper()}
        # Profiles list home countries as names or codes; normalise both sides.
        from models.job import normalise_country
        allowed = {normalise_country(code) or code for code in allowed}
        if not (codes & allowed):
            blockers.append((
                Blocker.COUNTRY_NOT_ELIGIBLE,
                f"posting is in {job.country.value}, and the profile's eligible "
                f"countries are {', '.join(sorted(allowed))}",
            ))

    # Language: only a *stated requirement* can block. A description that merely
    # mentions a language, or is written in one, is not a requirement.
    required = _stated_language_requirements(text)
    if required:
        have = {lang.lower() for lang in preferences.languages}
        missing = sorted(lang for lang in required if lang.lower() not in have)
        if missing:
            blockers.append((
                Blocker.LANGUAGE_REQUIRED_MISSING,
                f"posting requires {', '.join(missing)} and the profile does not "
                "list it",
            ))

    # Work authorisation: a posting that demands existing permission is uncertain
    # rather than fatal, because the profile's own permit status may satisfy it.
    if _mentions_work_authorisation_requirement(text):
        blockers.append((
            Blocker.WORK_AUTHORISATION_UNCLEAR,
            "posting mentions work authorisation or a permit requirement; whether "
            "the profile's status satisfies it cannot be determined from the data",
        ))

    # Seniority: an over-senior title is a judgement call, so uncertain, not fatal.
    if preferences.over_senior_titles:
        matched = _hits(job.title, preferences.over_senior_titles)
        if matched:
            blockers.append((
                Blocker.SENIORITY_MISMATCH,
                f"title contains {', '.join(repr(term) for term in matched)}, which "
                "is typically above the profile's level",
            ))

    if any(_BLOCKER_SEVERITY[blocker] is Eligibility.INELIGIBLE
           for blocker, _detail in blockers):
        return Eligibility.INELIGIBLE, blockers
    if blockers:
        return Eligibility.UNCERTAIN, blockers
    return Eligibility.ELIGIBLE, blockers


#: Language names the matcher recognises in a requirement phrase.
_KNOWN_LANGUAGES = ("german", "deutsch", "english", "englisch", "french", "französisch",
                    "spanish", "spanisch", "italian", "italienisch", "dutch",
                    "niederländisch")

#: Phrases that turn a language mention into a *requirement*.
_LANGUAGE_REQUIREMENT_RE = re.compile(
    r"(fluent|native|business[- ]fluent|verhandlungssicher|flie[ßs]end|"
    r"proficient|kenntnisse|required|erforderlich|vorausgesetzt|"
    r"c1|c2|b2)\s+(?:in\s+)?([a-zäöüß]+)",
    re.IGNORECASE,
)
#: Also catch "<language> is required" and "very good <language>".
_LANGUAGE_REQUIREMENT_RE2 = re.compile(
    r"([a-zäöüß]+)\s+(?:is\s+)?(?:required|erforderlich|vorausgesetzt|"
    r"verhandlungssicher)",
    re.IGNORECASE,
)


def _stated_language_requirements(text: str) -> set:
    """Languages the posting explicitly *requires*, not merely mentions."""
    required = set()
    for pattern in (_LANGUAGE_REQUIREMENT_RE, _LANGUAGE_REQUIREMENT_RE2):
        for match in pattern.finditer(text or ""):
            for group in match.groups():
                candidate = (group or "").lower()
                if candidate in _KNOWN_LANGUAGES:
                    required.add(canonical_language(candidate))
    return required


def canonical_language(value: str) -> str:
    """Map a language name or its German spelling to one canonical name."""
    lowered = (value or "").lower()
    pairs = {"deutsch": "German", "englisch": "English", "französisch": "French",
             "spanisch": "Spanish", "italienisch": "Italian",
             "niederländisch": "Dutch", "german": "German", "english": "English",
             "french": "French", "spanish": "Spanish", "italian": "Italian",
             "dutch": "Dutch"}
    return pairs.get(lowered, value.title() if value else value)


_AUTHORISATION_RE = re.compile(
    r"(work permit|arbeitserlaubnis|work authorisation|work authorization|"
    r"right to work|blue card|visa sponsorship|aufenthaltstitel|"
    r"must be authorised|must be authorized)",
    re.IGNORECASE,
)


def _mentions_work_authorisation_requirement(text: str) -> bool:
    return _AUTHORISATION_RE.search(text or "") is not None


# --- scoring ----------------------------------------------------------------------------

def score_job(job: Job, preferences: MatchPreferences,
              now=None) -> MatchResult:
    """Score one job against the preferences, recording every reason.

    A preference the posting says nothing about **does not score at all**. It is
    not awarded a default and it is not penalised: the point of a match score here
    is to count positive evidence, and a missing fact is recorded in ``unknowns``
    instead so the absence is visible rather than silently scored as zero.
    """
    from datetime import datetime, timezone

    moment = now or datetime.now(timezone.utc)
    evidence: list = []
    unknowns: list = []
    title = job.title or ""
    description = job.description or ""
    haystack = f"{title} {description}"

    # Keywords. Title hits and body hits are separate evidence, and both use the
    # SAME all-terms-must-match rule as the normaliser's keyword filter (AND), so
    # a caller that filters and then ranks gets one consistent meaning of
    # "keywords" rather than two subtly different ones.
    if preferences.keywords:
        title_hits = _hits(title, preferences.keywords)
        title_complete = len(title_hits) == len(_dedupe_terms(preferences.keywords))
        if title_complete and title_hits:
            evidence.append(MatchEvidence(
                Reason.TITLE_KEYWORD,
                f"title matches {', '.join(title_hits)}",
                tuple(title_hits),
            ))
        else:
            body_hits = _hits(haystack, preferences.keywords)
            body_complete = len(body_hits) == len(_dedupe_terms(preferences.keywords))
            if body_complete and body_hits:
                evidence.append(MatchEvidence(
                    Reason.TITLE_KEYWORD,
                    f"title and description together match {', '.join(body_hits)}",
                    tuple(body_hits),
                ))
            else:
                unknowns.append(
                    f"the posting does not mention all of the keywords "
                    f"{', '.join(preferences.keywords)}"
                )

    # Skills: in the title is stronger evidence than in the body, so they are
    # separate reasons rather than one combined count.
    if preferences.skills:
        title_skill_hits = _hits(title, preferences.skills)
        if title_skill_hits:
            evidence.append(MatchEvidence(
                Reason.SKILL_IN_TITLE,
                f"title names {', '.join(title_skill_hits)}",
                tuple(title_skill_hits),
            ))
        body_skill_hits = [term for term in _hits(description, preferences.skills)
                           if term not in title_skill_hits]
        if body_skill_hits:
            evidence.append(MatchEvidence(
                Reason.SKILL_IN_DESCRIPTION,
                f"description names {', '.join(body_skill_hits)}",
                tuple(body_skill_hits),
            ))
        if not title_skill_hits and not body_skill_hits:
            unknowns.append(
                "none of the profile's skills are named in the posting"
            )

    # Languages: a match only counts for a language the posting actually mentions.
    if preferences.languages and description:
        mentioned = {canonical_language(name) for name in _KNOWN_LANGUAGES
                     if _contains_term(description.lower(), name)}
        overlap = sorted(mentioned & {canonical_language(l) for l in preferences.languages})
        if overlap:
            evidence.append(MatchEvidence(
                Reason.LANGUAGE_MATCH,
                f"posting mentions {', '.join(overlap)}, which the profile lists",
                tuple(overlap),
            ))

    # Location preference: distinct from eligibility, which is about possibility.
    if preferences.preferred_cities:
        hits = _hits(f"{job.city.value or ''} {job.location_raw or ''}",
                     preferences.preferred_cities)
        if hits:
            evidence.append(MatchEvidence(
                Reason.LOCATION_PREFERENCE,
                f"location matches preferred {', '.join(hits)}",
                tuple(hits),
            ))
        elif not job.city.value and not job.location_raw:
            unknowns.append("the source did not state a location")

    # Remote preference.
    if preferences.prefers_remote is not None:
        resolved = job.resolved_remote()
        if resolved is Remote.UNKNOWN:
            unknowns.append("the source did not state whether the role is remote")
        elif preferences.prefers_remote and resolved is Remote.REMOTE:
            evidence.append(MatchEvidence(Reason.REMOTE_PREFERENCE,
                                          "role is remote, as preferred"))
        elif not preferences.prefers_remote and resolved is not Remote.REMOTE:
            evidence.append(MatchEvidence(Reason.REMOTE_PREFERENCE,
                                          "role is not remote, as preferred"))

    # Recency: only when the source stated a date. No date is an unknown, not a miss.
    if job.posted_at is not None and preferences.recency_days:
        age_days = (moment - job.posted_at).days
        if age_days <= preferences.recency_days:
            evidence.append(MatchEvidence(
                Reason.RECENCY,
                f"posted {age_days} day(s) ago, within {preferences.recency_days}",
            ))
    elif job.posted_at is None:
        unknowns.append("the source did not state when the job was posted")

    eligibility, blockers = evaluate_eligibility(job, preferences)

    return MatchResult(
        job=job,
        eligibility=eligibility,
        evidence=evidence,
        blockers=blockers,
        unknowns=unknowns,
    )


def rank_jobs(jobs: Iterable[Job], preferences: MatchPreferences,
              *, now=None, include_ineligible: bool = False) -> list:
    """Score and order jobs, best first, with a deterministic tie-break.

    Ordering is by score, then by recency when known, then by natural key. The
    final key tie-break matters: without it the order would depend on input order,
    and two runs over the same sources could present jobs differently.

    Ineligible jobs are excluded by default. They are kept out of the *ranking*,
    not out of the data, so a caller can still ask for them.
    """
    results = [score_job(job, preferences, now=now) for job in jobs]
    if not include_ineligible:
        results = [result for result in results if result.is_visible]

    def sort_key(result: MatchResult):
        posted = result.job.posted_at
        # Newest first, so negate the timestamp; a missing date sorts last rather
        # than being treated as ancient.
        stamp = -(posted.timestamp()) if posted else float("inf")
        return (-result.score, stamp, result.job.key)

    return sorted(results, key=sort_key)


def ranking_report(results: Iterable[MatchResult]) -> dict:
    """Counts for a CLI summary, including why jobs were excluded."""
    results = list(results)
    return {
        "total": len(results),
        "visible": sum(1 for result in results if result.is_visible),
        "ineligible": sum(1 for result in results
                          if result.eligibility is Eligibility.INELIGIBLE),
        "uncertain": sum(1 for result in results
                         if result.eligibility is Eligibility.UNCERTAIN),
        "with_blockers": sum(1 for result in results if result.blockers),
        "scored_above_zero": sum(1 for result in results if result.score > 0),
    }
