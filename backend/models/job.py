"""The ``Job`` domain model and the ``JobSource`` connector contract.

Phase 4 normalises many heterogeneous sources into **one** job shape. This module
defines that shape and nothing else: it is pure data and pure rules, with no
network, no filesystem and no configuration, so it can be tested exhaustively
without a fixture server (ADR 0008's "connectors stay modular behind one
``JobSource`` interface, normalising to a shared ``Job`` model").

Three design decisions are load-bearing, and each answers a real disagreement
found in the ADR 0008 §1 source research
(``docs/analysis/job-sources-research.md``):

**1. Every field records how it was obtained.** The sources agree on less than one
might hope. softgarden publishes a structured ``PostalAddress`` with
``addressCountry: "DE"``; Arbeitnow publishes the free-text string ``"Munich HQ"``.
Both are useful, and they are *not* the same kind of fact. So a ``JobField``
carries its value **and** its provenance, and :meth:`Job.verified_fields` can tell
a caller which fields a source actually asserted. This is ADR 0008's own
consequence clause: *"Every record preserves its source and distinguishes verified
fields from inferred ones."* A model that flattened both to ``country="DE"`` would
make an inference indistinguishable from a published fact, and no later code could
recover the difference.

**2. ``country`` is never guessed.** It is populated only from a structured
country/region field or a postal code. A free-text city name is *not* used to
infer a country, because that would silently convert a guess into a fact. The
value stays ``None`` with the raw location preserved in ``location_raw``.

**3. Absent is not the same as empty.** ``None`` means "the source did not say".
An empty string is normalised to ``None`` at construction, so downstream code has
one absence to handle rather than two.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Optional


class FieldSource(str, Enum):
    """How a field's value was obtained. Ordered from strongest to weakest.

    The order is meaningful and is used to decide which of two values for the same
    field wins when records are merged during deduplication.
    """

    #: The source published this as its own structured field (e.g. softgarden's
    #: ``addressCountry``). Strongest: a machine-readable assertion by the publisher.
    STRUCTURED = "structured"
    #: Parsed out of a published string with an unambiguous format (e.g. an ISO-8601
    #: date in a free-text field). Still the publisher's own words, but interpreted.
    PARSED = "parsed"
    #: We concluded it. Never overwrites a STRUCTURED or PARSED value.
    INFERRED = "inferred"
    #: The field is absent; no value exists.
    ABSENT = "absent"


#: Coverage rank, so the strongest provenance wins a merge. ``ABSENT`` is lowest.
_PROVENANCE_RANK = {
    FieldSource.STRUCTURED: 3,
    FieldSource.PARSED: 2,
    FieldSource.INFERRED: 1,
    FieldSource.ABSENT: 0,
}


@dataclass(frozen=True)
class JobField:
    """One value together with how we came to have it.

    ``value`` is ``None`` exactly when ``source`` is :attr:`FieldSource.ABSENT`,
    which :meth:`__post_init__` enforces in both directions so the two can never
    disagree.
    """

    value: Optional[str] = None
    source: FieldSource = FieldSource.ABSENT
    #: Optional human-readable note, e.g. the raw string an inference came from.
    #: Kept so a surprising value can be explained later without re-fetching.
    note: Optional[str] = None

    def __post_init__(self) -> None:
        # Normalise an empty/blank string to real absence, then keep value and
        # source consistent. A caller that passes `""` means "nothing", and a
        # caller that passes a value must not also claim ABSENT.
        if isinstance(self.value, str):
            stripped = self.value.strip()
            object.__setattr__(self, "value", stripped or None)
        if self.value is None:
            object.__setattr__(self, "source", FieldSource.ABSENT)
        elif self.source is FieldSource.ABSENT:
            raise ValueError(
                "A JobField with a value cannot have source=ABSENT. Use PARSED, "
                "STRUCTURED or INFERRED so the value's provenance is honest."
            )

    @classmethod
    def absent(cls) -> "JobField":
        return cls(value=None, source=FieldSource.ABSENT)

    @classmethod
    def structured(cls, value: Optional[str], note: Optional[str] = None) -> "JobField":
        return cls(value=value, source=FieldSource.STRUCTURED, note=note)

    @classmethod
    def parsed(cls, value: Optional[str], note: Optional[str] = None) -> "JobField":
        return cls(value=value, source=FieldSource.PARSED, note=note)

    @classmethod
    def inferred(cls, value: Optional[str], note: Optional[str] = None) -> "JobField":
        return cls(value=value, source=FieldSource.INFERRED, note=note)

    @property
    def is_present(self) -> bool:
        """True when the source gave us something, however weakly."""
        return self.value is not None

    @property
    def is_verified(self) -> bool:
        """True only when the *publisher* asserted it, not when we concluded it.

        This is the distinction ADR 0008 requires: an inferred country is useful
        for ranking but must never be reported as a verified fact.
        """
        return self.source in (FieldSource.STRUCTURED, FieldSource.PARSED)

    @property
    def rank(self) -> int:
        return _PROVENANCE_RANK[self.source]

    def preferred_over(self, other: "JobField") -> bool:
        """True when this field should win a merge against ``other``.

        A stronger provenance always wins. At equal strength the existing value is
        kept, so merging is deterministic and does not depend on input order beyond
        the caller's own sorting.
        """
        return self.rank > other.rank

    def as_dict(self) -> dict:
        return {"value": self.value, "source": self.source.value, "note": self.note}


class Remote(str, Enum):
    """Whether the posting is remote, as stated or as concluded."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    #: The source did not say. Distinct from ONSITE, which is a claim.
    UNKNOWN = "unknown"


#: Country names/aliases that map to an ISO 3166-1 alpha-2 code.
#:
#: Covers the DACH markets Phase 4 implements *and* the other countries that the
#: verified sources actually publish (Lever and Greenhouse both emitted ``US`` and
#: ``GB`` in the 2026-10-31 probes). Recognising a non-DACH country matters even
#: though Phase 4 is DACH-first: if ``US`` normalised to ``None``, a posting the
#: source explicitly placed in the United States would be indistinguishable from
#: one whose country the source never stated. That would destroy the
#: verified-versus-absent distinction the whole model rests on -- and would make
#: ``is_dach`` correct only by accident. Scope is kept to well-known countries
#: rather than guessing at every name, so an unrecognised string is still ``None``.
_COUNTRY_ALIASES = {
    # DACH -- the implemented and validated markets (Phase 4 scope, ADR 0008 §5).
    "de": "DE", "deu": "DE", "germany": "DE", "deutschland": "DE",
    "at": "AT", "aut": "AT", "austria": "AT", "österreich": "AT", "oesterreich": "AT",
    "ch": "CH", "che": "CH", "switzerland": "CH", "schweiz": "CH", "suisse": "CH",
    # Other markets the verified sources publish. Recorded so a stated country is
    # never confused with an absent one; the connectors and the matcher stay
    # DACH-first through ``is_dach``, not by throwing information away here.
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
    "gb": "GB", "uk": "GB", "united kingdom": "GB", "great britain": "GB",
    "ie": "IE", "irl": "IE", "ireland": "IE",
    "nl": "NL", "nld": "NL", "netherlands": "NL", "nederland": "NL",
    "fr": "FR", "fra": "FR", "france": "FR", "frankreich": "FR",
    "es": "ES", "esp": "ES", "spain": "ES", "spanien": "ES",
    "it": "IT", "ita": "IT", "italy": "IT", "italien": "IT",
    "pl": "PL", "pol": "PL", "poland": "PL", "polen": "PL",
    "pt": "PT", "prt": "PT", "portugal": "PT",
    "se": "SE", "swe": "SE", "sweden": "SE", "schweden": "SE",
    "dk": "DK", "dnk": "DK", "denmark": "DK", "dänemark": "DK",
    "fi": "FI", "fin": "FI", "finland": "FI", "finnland": "FI",
    "no": "NO", "nor": "NO", "norway": "NO", "norwegen": "NO",
    "be": "BE", "bel": "BE", "belgium": "BE", "belgien": "BE",
    "ca": "CA", "can": "CA", "canada": "CA", "kanada": "CA",
    "au": "AU", "aus": "AU", "australia": "AU", "australien": "AU",
    "in": "IN", "ind": "IN", "india": "IN", "indien": "IN",
    "sg": "SG", "sgp": "SG", "singapore": "SG", "singapur": "SG",
    "cz": "CZ", "cze": "CZ", "czechia": "CZ", "czech republic": "CZ",
    "hu": "HU", "hun": "HU", "hungary": "HU", "ungarn": "HU",
    "ro": "RO", "rou": "RO", "romania": "RO", "rumänien": "RO",
    "bg": "BG", "bgr": "BG", "bulgaria": "BG", "bulgarien": "BG",
    "lu": "LU", "lux": "LU", "luxembourg": "LU", "luxemburg": "LU",
    "gr": "GR", "grc": "GR", "greece": "GR", "griechenland": "GR",
    "hr": "HR", "hrv": "HR", "croatia": "HR", "kroatien": "HR",
    "sk": "SK", "svk": "SK", "slovakia": "SK", "slowakei": "SK",
    "si": "SI", "svn": "SI", "slovenia": "SI", "slowenien": "SI",
    "ee": "EE", "est": "EE", "estonia": "EE", "estland": "EE",
    "lv": "LV", "lva": "LV", "latvia": "LV", "lettland": "LV",
    "lt": "LT", "ltu": "LT", "lithuania": "LT", "litauen": "LT",
}

#: The markets Phase 4 is implemented and validated against. Other countries are
#: still normalised and stored (the model is market-agnostic by design), but these
#: are the ones the connectors were built and verified for.
DACH_COUNTRIES = ("DE", "AT", "CH")

#: German/Austrian/Swiss postal code shapes. Used only to *confirm* a country
#: already suggested by a region field, never to invent one -- DE and AT both use
#: four digits and CH uses four, so a postal code alone cannot identify a country.
_POSTAL_RE = re.compile(r"^\d{4,5}$")


def normalise_country(value: Optional[str]) -> Optional[str]:
    """Map a country name or code to ISO 3166-1 alpha-2, or ``None``.

    Returns ``None`` rather than the input when unrecognised: an unknown string is
    not a country code, and storing it in a field named ``country`` would be a lie.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _COUNTRY_ALIASES.get(text.lower())


def parse_iso_datetime(value) -> Optional[datetime]:
    """Parse an ISO-8601 string or a Unix timestamp into an aware UTC datetime.

    Accepts what the verified sources actually publish: ISO strings with offsets
    (softgarden ``2026-09-23T10:37:06.121+02:00``), ISO with ``Z`` (Ashby), and
    epoch seconds (Arbeitnow) or milliseconds (Lever). Returns ``None`` for
    anything else rather than guessing -- a wrong date is worse than no date.
    """
    if value is None or value == "":
        return None
    # Epoch numbers: Arbeitnow publishes seconds, Lever publishes milliseconds.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        # ~1e11 is 1973 in ms but year 5138 in seconds; the split is unambiguous
        # for any plausible job posting date.
        if number > 1e11:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # A digits-only string is still an epoch.
    if text.isdigit():
        return parse_iso_datetime(int(text))
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    # Convert rather than merely tag: fromisoformat keeps the original offset, so a
    # '+02:00' string would otherwise reach callers as a 10:37+02:00 value while this
    # function promises UTC. Two sources publishing one instant in different offsets
    # must compare equal.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean(value) -> Optional[str]:
    """Collapse whitespace and normalise blank to ``None``."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


@dataclass
class Job:
    """One normalised posting, with provenance on every source-dependent field.

    Fields that a connector always determines itself (``source``, ``source_id``,
    ``url``) are plain values: there is nothing to infer about where a record came
    from, because the connector is what fetched it.
    """

    # --- identity: what the connector always knows ------------------------------------
    #: Connector name that produced this record, e.g. ``"softgarden"``.
    source: str
    #: The source's own identifier for the posting. ``source`` + ``source_id`` is
    #: the natural key and the basis of deduplication.
    source_id: str
    #: Canonical public URL for the posting.
    url: str

    # --- content ----------------------------------------------------------------------
    #: Job title as published. Plain, because a posting without a title is not a
    #: usable record and the connectors are required to supply one.
    title: str
    #: Company name as published.
    company: str = ""
    #: Full description text (HTML already reduced to text by the connector).
    description: str = ""
    #: Free-text location exactly as published, before any interpretation.
    location_raw: Optional[str] = None

    # --- source-dependent fields, each carrying provenance ----------------------------
    country: JobField = field(default_factory=JobField.absent)
    city: JobField = field(default_factory=JobField.absent)
    region: JobField = field(default_factory=JobField.absent)
    postal_code: JobField = field(default_factory=JobField.absent)
    employment_type: JobField = field(default_factory=JobField.absent)
    #: Raw remote flag from the source, e.g. ``"true"``; see :meth:`resolved_remote`.
    remote_flag: JobField = field(default_factory=JobField.absent)

    # --- dates ------------------------------------------------------------------------
    #: When the posting was published, as an aware UTC datetime (plain: connectors
    #: either parse it or omit it, and a wrong date is worse than none).
    posted_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self.title = _clean(self.title) or ""
        self.company = _clean(self.company) or ""
        self.source = _clean(self.source) or ""
        self.source_id = _clean(self.source_id) or ""
        self.url = (self.url or "").strip()
        self.location_raw = _clean(self.location_raw)
        if not self.title:
            raise ValueError(f"Job {self.source}:{self.source_id} has no title.")
        if not self.source_id:
            raise ValueError("A Job requires a source_id; it is half of the natural key.")
        if not self.source:
            raise ValueError("A Job requires a source; provenance is not optional.")

    # --- derived properties -----------------------------------------------------------

    @property
    def key(self) -> str:
        """The natural key: source name plus the source's own id."""
        return f"{self.source}:{self.source_id}"

    @property
    def is_dach(self) -> bool:
        """True when the country is *verified* as DACH, not merely inferred.

        Deliberately strict. Phase 4 is DACH-first, and a market filter that
        accepted inferred countries would let a guess drive which postings the user
        sees -- the failure this flag exists to prevent.
        """
        return (
            self.country.is_verified
            and self.country.value in DACH_COUNTRIES
        )

    def resolved_remote(self) -> Remote:
        """Resolve remoteness, preferring the source's own statement.

        Reads structured flags first, then the free text. Returns
        :attr:`Remote.UNKNOWN` when the source never said, which is a different
        answer from :attr:`Remote.ONSITE`.
        """
        flag = (self.remote_flag.value or "").lower()
        if flag in ("true", "1", "yes", "remote"):
            return Remote.REMOTE
        if flag in ("false", "0", "no"):
            # An explicit false is a real claim of non-remote, but it does not say
            # whether that means on-site or hybrid.
            return Remote.ONSITE
        haystack = " ".join(
            part.lower() for part in (self.title, self.location_raw or "",
                                      self.employment_type.value or "")
        )
        if "remote" in haystack or "homeoffice" in haystack or "home office" in haystack:
            return Remote.REMOTE
        if "hybrid" in haystack:
            return Remote.HYBRID
        return Remote.UNKNOWN

    def verified_fields(self) -> dict:
        """The fields the *source* asserted, as ``{name: value}``.

        The inverse of :meth:`inferred_fields`, and the honest answer to "what do
        we actually know about this posting?".
        """
        return {
            name: value.value
            for name in self._provenance_fields()
            if (value := getattr(self, name)).is_verified
        }

    def inferred_fields(self) -> dict:
        """The fields we concluded ourselves, with the note explaining each."""
        reported = {}
        for name in self._provenance_fields():
            job_field = getattr(self, name)
            if job_field.source is FieldSource.INFERRED:
                reported[name] = {"value": job_field.value, "note": job_field.note}
        return reported

    @staticmethod
    def _provenance_fields() -> tuple:
        return ("country", "city", "region", "postal_code", "employment_type",
                "remote_flag")

    def content_fingerprint(self) -> str:
        """A digest of the fields that identify the *posting*, not the record.

        Used by deduplication: two sources carrying the same vacancy should agree
        here even though their ids, urls and wording differ. Deliberately built
        from normalised text so punctuation and case differences do not defeat it.
        """
        parts = [
            _normalise_for_digest(self.company),
            _normalise_for_digest(self.title),
            (self.city.value or "").lower().strip(),
            (self.country.value or "").upper().strip(),
        ]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        """A JSON-serialisable view, keeping provenance explicit."""
        return {
            "source": self.source,
            "source_id": self.source_id,
            "key": self.key,
            "url": self.url,
            "title": self.title,
            "company": self.company,
            "location_raw": self.location_raw,
            "country": self.country.as_dict(),
            "city": self.city.as_dict(),
            "region": self.region.as_dict(),
            "postal_code": self.postal_code.as_dict(),
            "employment_type": self.employment_type.as_dict(),
            "remote_flag": self.remote_flag.as_dict(),
            "remote": self.resolved_remote().value,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "is_dach": self.is_dach,
            "description": self.description,
        }


#: Words dropped when digesting a title/company, because they are boilerplate that
#: differs between boards carrying the identical vacancy.
_DIGEST_STOPWORDS = re.compile(
    r"\b(m/w/d|m/w/x|w/m/d|m/f/d|f/m/d|gn|all genders|any gender|"
    r"full[- ]?time|part[- ]?time|vollzeit|teilzeit)\b",
    re.IGNORECASE,
)


def _normalise_for_digest(value: str) -> str:
    """Reduce a title/company string to a comparable form for fingerprinting."""
    text = _DIGEST_STOPWORDS.sub(" ", value or "")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


class JobSourceError(Exception):
    """A connector could not produce jobs. Carries the connector's own name.

    Connectors raise this rather than leaking transport exceptions, so a broken
    source degrades to one failing connector and never takes the run down with it
    (ADR 0008: *"A source that changes or withdraws access affects only its own
    connector."*).
    """

    def __init__(self, source: str, message: str, *, retryable: bool = False):
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class SearchQuery:
    """What the caller asked for, independent of any source's parameter names.

    Each connector translates this into its own dialect. A source that cannot
    express a constraint must **report** that rather than ignore it, so a caller
    is never shown a filtered list that was not actually filtered.
    """

    keywords: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    remote: Optional[bool] = None
    limit: int = 50

    def __post_init__(self) -> None:
        if self.country:
            object.__setattr__(self, "country", normalise_country(self.country))
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be at least 1.")

    def describe(self) -> str:
        bits = []
        if self.keywords:
            bits.append(f"keywords={self.keywords!r}")
        if self.country:
            bits.append(f"country={self.country}")
        if self.city:
            bits.append(f"city={self.city!r}")
        if self.remote is not None:
            bits.append(f"remote={self.remote}")
        bits.append(f"limit={self.limit}")
        return ", ".join(bits)


@dataclass(frozen=True)
class SourceCapabilities:
    """What a connector can and cannot do. Declared, then trusted by callers.

    This exists so the CLI and the matcher can warn honestly. A source that cannot
    filter by keyword server-side must say so: the alternative is a caller
    believing a search was narrowed when the connector actually fetched everything
    and relied on the caller to filter.
    """

    #: Can the source narrow results by keyword itself?
    server_side_keywords: bool = False
    #: Can it filter by location/country itself?
    server_side_location: bool = False
    #: Can it filter by remote-ness itself?
    server_side_remote: bool = False
    #: Does it enumerate the whole corpus (so local filtering is complete)?
    enumerable: bool = False
    #: Does it state a publication date per posting?
    provides_posted_at: bool = False
    #: Does it state an expiry date per posting?
    provides_expiry: bool = False
    #: Does the API need a key or account?
    requires_credentials: bool = False
    #: Verified reachable and permitted on the date below.
    verified_on: Optional[str] = None

    def limitations_for(self, query: SearchQuery) -> list:
        """Human-readable warnings for constraints this source cannot honour.

        Returns an empty list when the source can express everything asked for.
        """
        notes = []
        if query.keywords and not self.server_side_keywords:
            notes.append(
                "this source has no keyword search; every posting it has was "
                "fetched and the keyword was applied locally"
            )
        if (query.city or query.country) and not self.server_side_location:
            notes.append(
                "this source cannot filter by location; the location filter was "
                "applied locally"
            )
        if query.remote is not None and not self.server_side_remote:
            notes.append(
                "this source cannot filter by remote; the remote filter was "
                "applied locally"
            )
        return notes


class JobSource:
    """The contract every connector implements (ADR 0008 §3).

    Deliberately tiny: a name, a declaration of what it can do, and one method
    that yields :class:`Job` objects. Everything source-specific -- URLs, auth,
    pagination, payload shapes, rate limiting -- lives inside the implementation,
    so adding or removing a source cannot affect any other part of the system.

    Implementations must:

    * **Normalise, never leak.** Return :class:`Job` objects; raise
      :class:`JobSourceError` rather than a transport exception.
    * **Identify themselves honestly** in the ``User-Agent`` (ADR 0008 §3), which
      :func:`user_agent` builds centrally so no connector can forget.
    * **Respect ``robots.txt``** where the source is a website rather than a
      documented API. A published API is used through its documented endpoint.
    * **Never invent a value.** An unknown field is absent, not guessed.
    """

    #: Stable short name, used in ``job.source`` and in CLI output.
    name: str = "unnamed"
    #: What this connector can do.
    capabilities: SourceCapabilities = SourceCapabilities()

    def search(self, query: SearchQuery) -> Iterable[Job]:
        """Yield normalised jobs matching ``query``.

        May return fewer than ``query.limit``; must not return more. Implementations
        should stop fetching once the limit is reached.
        """
        raise NotImplementedError

    def fetch_one(self, source_id: str) -> Optional[Job]:
        """Fetch a single posting by its source id, or ``None`` when it is gone.

        Optional: only connectors that can address one posting implement it, which
        is what lets expiry detection re-check a specific job.
        """
        raise NotImplementedError(
            f"{self.name} cannot fetch a single posting by id."
        )

    @property
    def can_fetch_one(self) -> bool:
        """True when :meth:`fetch_one` is implemented, so callers can check first."""
        return type(self).fetch_one is not JobSource.fetch_one


#: Contact detail placed in the User-Agent so a source operator can identify and
#: reach whoever is making requests (ADR 0008 §3: "identify itself honestly").
#: Deliberately not an email address: this repository is public, and a personal
#: address would be committed to it. The repository URL is the honest contact.
_UA_TEMPLATE = "cv-tailor/{version} (+{url})"
_PROJECT_URL = "https://github.com/srdpsrknth/cv-tailor"


def user_agent(version: str = "0.4") -> str:
    """The honest User-Agent every connector sends. Built in one place, on purpose."""
    return _UA_TEMPLATE.format(version=version, url=_PROJECT_URL)
