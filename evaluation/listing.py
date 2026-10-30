"""The OpenRouter listing, reduced to what curation actually uses -- and committed.

**Why this module exists.** The 2026-10-26 curation read a 467-model JSON payload,
recorded its SHA-256, and gitignored the payload. The consequence was measured twice
over: ``tests/test_evaluation_suite.py`` has two tests that compare the curated set's
recorded prices and capabilities **against that listing**, and both **skip** in a fresh
working copy because the file is not there. So this repository could not prove its own
recorded prices -- a curated set whose provenance is a hash of a document nobody has.

A digest proves *that* a document was read. It cannot prove *what it said*. This module
keeps what it said, in a form small enough to commit: the fields curation uses, for the
models that pass the structural screen, plus the digest and model count of the full
payload so a future read can still be tied to exactly what was seen.

**What is committed and what is not.**

* **Committed:** ``evaluation/listing_<date>.json`` -- the screened record. Six fields per
  entry. The digest is the *full* payload's, so the record is verifiable against a future
  fetch rather than being self-certifying.
* **Not committed:** the raw payload. It is ~750 KB of descriptions, modalities and link
  templates, none of which any decision rests on.

**The record is deliberately not the curated set.** Two different questions are answered
by two different modules, and conflating them is what made the old artefact useless:

* :mod:`evaluation.listing` -- *what was in the catalogue, and is a price still true?*
* :mod:`evaluation.curated_models` -- *which models does this tool offer, and on what
  evidence?*

A listing record naming a model that is not curated is normal and correct. A curated
model absent from the listing is a **defect**, because the price recorded for it can no
longer be checked -- and :func:`missing_from_record` is what reports that.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# The owner's recency floor is defined **once**, where the curated set enforces it, and
# read here rather than restated. Two copies of a rule is how this project's schema
# dialects drifted apart; the floor is a single number with a single owner.
from evaluation.curated_models import MIN_CREATED

#: The endpoint every recorded listing was read from. Asserted by a test, because a
#: record without a stated source is a price without a provenance.
LISTING_URL = "https://openrouter.ai/api/v1/models"

#: The file name pattern for a screened record. Dated so two reads cannot be confused,
#: and so "which listing is this price from?" has a file-level answer.
RECORD_PREFIX = "listing_"
RECORD_SUFFIX = ".json"

#: The fields kept per entry, and nothing else. Each is here because a curation
#: decision reads it:
#:
#: * ``id`` -- the thing being decided about;
#: * ``prompt``/``completion`` -- the price, per 1M tokens, and the ranking input;
#: * ``created`` -- the owner's "nothing older than 2025-10" floor;
#: * ``structured_outputs`` -- the product requirement (schema-valid JSON), and the
#:   filter that excludes the otherwise-cheapest candidates;
#: * ``context_length``/``max_completion_tokens`` -- whether an endpoint can emit a
#:   document at all.
RECORD_FIELDS = (
    "id",
    "prompt",
    "completion",
    "created",
    "structured_outputs",
    "context_length",
    "max_completion_tokens",
)

#: A CV draft is ~1,350 output tokens and a letter ~622, so an endpoint whose ceiling
#: cannot hold one is unusable however cheap it is. The figure is a floor for
#: *usability*, not a quality judgement -- the same reasoning ``curated_models`` records
#: for its own ceiling filter.
MIN_MAX_COMPLETION_TOKENS = 2_000


def record_path(root: Optional[Path] = None) -> Path:
    """The directory screened records live in: this package, so they are committed."""
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parent


def record_files(root: Optional[Path] = None) -> list[Path]:
    """Every screened record present, newest name first (names are dated)."""
    directory = record_path(root)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.glob(f"{RECORD_PREFIX}*{RECORD_SUFFIX}")),
        key=lambda p: p.name,
        reverse=True,
    )


def latest_record(root: Optional[Path] = None) -> Optional[Path]:
    """The most recent screened record, or ``None`` when none is committed.

    ``None`` is the meaningful answer rather than an exception: a caller that must have
    a record should fail with its own message about what it needed, not with a
    ``FileNotFoundError`` from four frames down.
    """
    files = record_files(root)
    return files[0] if files else None


@dataclass(frozen=True)
class ListingEntry:
    """One model, as the listing described it."""

    id: str
    #: USD per 1M tokens, converted from the listing's per-token strings at read time
    #: so no caller has to remember the 1e6.
    prompt: float
    completion: float
    #: ``YYYY-MM-DD``, converted from the listing's unix seconds.
    created: str
    structured_outputs: bool
    context_length: int
    max_completion_tokens: int

    def as_dict(self) -> dict:
        """The committed form: exactly :data:`RECORD_FIELDS`, in that order."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "completion": self.completion,
            "created": self.created,
            "structured_outputs": self.structured_outputs,
            "context_length": self.context_length,
            "max_completion_tokens": self.max_completion_tokens,
        }


@dataclass(frozen=True)
class ListingRecord:
    """A dated, screened reading of the catalogue, with the full payload's digest.

    :attr:`source_sha256` is the digest of the **whole** response, not of the screened
    subset, and that distinction is the point: it is what lets a future fetch be checked
    against this record. A digest of the reduced form would only prove the file had not
    been edited.
    """

    read_on: str
    source_url: str
    source_sha256: str
    source_model_count: int
    entries: tuple[ListingEntry, ...]

    def by_id(self) -> dict[str, ListingEntry]:
        return {entry.id: entry for entry in self.entries}

    def find(self, model_id: str) -> Optional[ListingEntry]:
        """The entry for ``model_id``, or ``None`` -- never a fabricated default."""
        return self.by_id().get(model_id)

    def as_dict(self) -> dict:
        return {
            "read_on": self.read_on,
            "source_url": self.source_url,
            "source_sha256": self.source_sha256,
            "source_model_count": self.source_model_count,
            "screened_model_count": len(self.entries),
            "fields": list(RECORD_FIELDS),
            "models": [entry.as_dict() for entry in self.entries],
        }

    def to_json(self) -> str:
        """The committed text. Sorted keys and a trailing newline, so a re-write of
        identical content is byte-identical and shows up as no diff."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=False) + "\n"


def sha256_of_bytes(data: bytes) -> str:
    """Uppercase hex, matching the digests already recorded in this project."""
    return hashlib.sha256(data).hexdigest().upper()


def _created_date(unix_seconds) -> str:
    """``YYYY-MM-DD`` from the listing's unix seconds, or ``""`` when unusable.

    An absent figure is reported as absent rather than defaulted to today, because a
    defaulted date would silently satisfy the "nothing older than 2025-10" floor -- the
    exact failure that floor exists to prevent.
    """
    from datetime import datetime, timezone

    try:
        seconds = int(unix_seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d")


def _price_per_1m(value) -> float:
    """USD per 1M tokens from the listing's per-token string.

    ``None`` and unparseable both become ``0.0``, which reads as "not priced" rather
    than crashing a read. A zero price is itself suspicious and the screen reports it.

    The multiplication is rounded to 6 decimal places **at read time**, and that is not
    cosmetic. ``float("0.0000001") * 1_000_000`` is ``0.09999999999999999``, and the
    committed record then carries that noise for every entry -- 20 characters instead of
    4, in a file that exists to be read by people reviewing prices. Six places is far
    finer than any rate this catalogue quotes (the finest observed is $0.000000003 per
    token, i.e. $0.003 per 1M).
    """
    if value is None:
        return 0.0
    try:
        return round(float(value) * 1_000_000, 6)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def entry_from_payload(row: dict) -> Optional[ListingEntry]:
    """One payload row as a :class:`ListingEntry`, or ``None`` when it has no id.

    Structural permissiveness is deliberate: a row this module cannot read is skipped
    rather than raising, so one malformed entry in a 456-model payload does not make the
    whole listing unreadable. The *screen* then decides whether the resulting absence
    matters.
    """
    model_id = row.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None

    pricing = row.get("pricing") or {}
    parameters = row.get("supported_parameters") or []
    top_provider = row.get("top_provider") or {}

    return ListingEntry(
        id=model_id.strip(),
        prompt=_price_per_1m(pricing.get("prompt")),
        completion=_price_per_1m(pricing.get("completion")),
        created=_created_date(row.get("created")),
        # Presence in the array, not truthiness: the listing advertises the parameter
        # by listing it, and a test asserts the curated model carries it.
        structured_outputs="structured_outputs" in parameters,
        context_length=_int_or_zero(row.get("context_length")),
        max_completion_tokens=_int_or_zero(top_provider.get("max_completion_tokens")),
    )


def structurally_usable(entry: ListingEntry) -> bool:
    """Whether an endpoint could serve this pipeline at all, before any judgement.

    Three structural requirements, each a property of the *request* rather than of
    model quality, so none of them is a preference dressed as a filter:

    1. **structured output is advertised** -- a model that cannot be relied on for
       schema-valid JSON cannot be trusted with the product's contract;
    2. **the output ceiling can hold a document** -- a ceiling below
       :data:`MIN_MAX_COMPLETION_TOKENS` truncates the response before it is finished;
    3. **a price exists** -- a model with no priced route reports the fallback route's
       invented cost, and the run's headline metric becomes fiction (see
       ``curated_models.unpriced_entries``).

    Recency is deliberately **not** here. The owner's "nothing older than 2025-10" floor
    is a curation rule, not a structural property, and it belongs with the other
    curation rules so a reader can tell the two kinds apart.
    """
    return (
        entry.structured_outputs
        and entry.max_completion_tokens >= MIN_MAX_COMPLETION_TOKENS
        and entry.prompt > 0
        and entry.completion > 0
    )


def screen_payload(payload: dict, *, read_on: str, source_sha256: str) -> ListingRecord:
    """Reduce a raw listing payload to a committable, screened record.

    ``read_on`` and ``source_sha256`` are supplied rather than derived, because both
    are facts about the *fetch* -- when it happened and what exactly came back -- and
    neither is recoverable from the payload's contents.

    **Two filters, both recorded rules rather than this module's taste:**

    * :func:`structurally_usable` -- can this endpoint serve the pipeline at all;
    * the **owner's recency floor** (``created >= MIN_CREATED``), the same 2025-10-01
      rule ``curated_models`` enforces on its own entries.

    The recency floor is applied here for a size reason that is worth stating, because
    leaving it out would also be defensible. The 2026-10-30 read returned **456 models,
    369 structurally usable, 267 above the floor** -- so the floor removes about a
    quarter of the file. The record is committed, and it exists to be *read* by a person
    reviewing prices; archiving models the owner has already ruled out spends 25 KB of
    every future diff on entries no decision can use. What is deliberately NOT filtered
    is anything evaluative: no capability ranking, no price band, nothing that would
    make this record a curation decision rather than a catalogue reading. A model above
    the floor and structurally usable is in the record whether or not it is any good.
    """
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError(
            "the listing payload has no 'data' list; OpenRouter's /api/v1/models "
            "returns {'data': [...]}, so this is not that payload"
        )

    entries, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = entry_from_payload(row)
        if entry is None or entry.id in seen:
            continue
        seen.add(entry.id)
        if structurally_usable(entry) and entry.created >= MIN_CREATED:
            entries.append(entry)

    return ListingRecord(
        read_on=read_on,
        source_url=LISTING_URL,
        source_sha256=source_sha256,
        source_model_count=len(rows),
        entries=tuple(sorted(entries, key=lambda e: e.id)),
    )


def parse_record(text: str) -> ListingRecord:
    """A committed record back into a :class:`ListingRecord`.

    Raises on a structurally wrong record rather than returning an empty one: a record
    that cannot be read must not be mistakable for a catalogue with no models in it.
    """
    data = json.loads(text)
    if not isinstance(data, dict) or "models" not in data:
        raise ValueError("not a listing record: no 'models' key")

    entries = []
    for row in data["models"]:
        if not isinstance(row, dict) or not row.get("id"):
            raise ValueError(f"listing record has a model row with no id: {row!r}")
        missing = [field for field in RECORD_FIELDS if field not in row]
        if missing:
            raise ValueError(
                f"listing record entry {row['id']} is missing {missing}; the record's "
                f"field list is {list(RECORD_FIELDS)}"
            )
        entries.append(
            ListingEntry(
                id=row["id"],
                prompt=float(row["prompt"]),
                completion=float(row["completion"]),
                created=str(row["created"]),
                structured_outputs=bool(row["structured_outputs"]),
                context_length=int(row["context_length"]),
                max_completion_tokens=int(row["max_completion_tokens"]),
            )
        )
    return ListingRecord(
        read_on=str(data.get("read_on", "")),
        source_url=str(data.get("source_url", "")),
        source_sha256=str(data.get("source_sha256", "")),
        source_model_count=int(data.get("source_model_count", 0)),
        entries=tuple(entries),
    )


def load_record(path) -> ListingRecord:
    """Read a committed record from ``path``."""
    return parse_record(Path(path).read_text(encoding="utf-8"))


def missing_from_record(model_ids: Iterable[str], record: ListingRecord) -> tuple[str, ...]:
    """Curated ids **absent** from a record -- which is a defect, not a difference.

    A curated model the listing no longer carries cannot have its price checked, and
    the price is what the whole ranking rests on. Reported as a tuple rather than
    raised, so a caller can say *which* ids are unverifiable.
    """
    known = record.by_id()
    return tuple(model_id for model_id in model_ids if model_id not in known)


def price_disagreements(model_prices: dict, record: ListingRecord) -> tuple[dict, ...]:
    """Curated ids whose recorded price differs from the listing's.

    ``model_prices`` maps a model id to ``(input_per_1m, output_per_1m)``. Disagreement
    is reported, never corrected: which figure is right is a curation decision, and
    ``PRICE_SOURCES`` carries the date the table was verified.
    """
    disagreements = []
    for model_id, (input_per_1m, output_per_1m) in sorted(model_prices.items()):
        entry = record.find(model_id)
        if entry is None:
            continue
        if not _close(entry.prompt, input_per_1m) or not _close(
            entry.completion, output_per_1m
        ):
            disagreements.append(
                {
                    "id": model_id,
                    "recorded": (input_per_1m, output_per_1m),
                    "listing": (entry.prompt, entry.completion),
                }
            )
    return tuple(disagreements)


def _close(left: float, right: float, *, tolerance: float = 1e-6) -> bool:
    """Float equality with a tolerance, because both sides are parsed from strings.

    The listing gives ``"0.0000001"`` and the record stores ``0.1``. Comparing those
    exactly would report a disagreement on every single model.
    """
    return abs(float(left) - float(right)) <= tolerance
