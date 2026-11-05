"""Normalisation: each source's real payload shape into one :class:`Job` shape.

Phase 4's core problem is that the sources agree on almost nothing. This module is
where each disagreement is resolved **honestly**, meaning we record what the
publisher actually asserted and never upgrade a guess to a fact
(:mod:`models.job` carries the provenance).

The shapes handled here are the ones verified live on 2026-10-31
(``docs/analysis/job-sources-research.md``, reproducible with
``tools/probe_job_sources.py``), not idealised guesses:

* **softgarden** — schema.org ``DataFeed`` wrapping ``JobPosting`` with a real
  ``PostalAddress`` including ``addressCountry``. The best case: country is
  published, so it is :attr:`FieldSource.STRUCTURED`.
* **Personio** — ``<workzag-jobs><position>`` XML with ``office`` as a bare city
  name and **no country field at all**. Country stays absent rather than inferred.
* **Lever** — a real ``country`` field (``"DE"``) plus ``categories.location``.
* **Greenhouse** — ``location.name`` is a display string (``"Berlin, Germany"``),
  so this is the one source where a country genuinely can be parsed from text.
* **Ashby** — nested ``address.postalAddress.addressCountry``, plus ``isRemote``.
* **Arbeitnow** — free-text ``location`` (``"Munich HQ"``), no country at all.

Two rules are applied consistently and are worth stating because they are policy,
not implementation detail:

1. **A structured country is used as given; a country parsed out of a display
   string is :attr:`FieldSource.PARSED`.** Both count as verified, because both
   are the publisher's own words. Neither is inferred.
2. **A bare city name never becomes a country.** Personio's ``office`` and
   Arbeitnow's ``location`` are kept verbatim in ``city``/``location_raw``, and
   ``country`` stays absent. Guessing here would be exactly the silent
   fact-invention ADR 0008 warns against.
"""
from __future__ import annotations

import html
import re
from typing import Iterable, Iterator, Optional
from xml.etree import ElementTree

from models.job import (
    Job,
    JobField,
    Remote,
    normalise_country,
    parse_iso_datetime,
)

#: Trailing country name in a display location, e.g. "Berlin, Germany".
_TRAILING_COUNTRY_RE = re.compile(r"[,\u2013-]\s*([A-Za-z\u00c0-\u017f .]+)\s*$")

#: Country names/aliases that a display location may contain *anywhere*, not only
#: as a trailing segment. Arbeitnow publishes "Germany (remote)", which names the
#: country the publisher itself stated -- reading it is parsing, not inference.
#: Ordered longest-first so "united states" wins over "states". Multi-word aliases
#: are matched first because the phrase is the publisher's own.
_DISPLAY_COUNTRY_ALIASES = (
    "united states of america", "united kingdom", "united states", "great britain",
    "czech republic", "new zealand", "south africa",
    "germany", "deutschland", "austria", "\u00f6sterreich", "oesterreich",
    "switzerland", "schweiz", "suisse", "netherlands", "nederland", "belgium",
    "belgien", "france", "frankreich", "spain", "spanien", "italy", "italien",
    "poland", "polen", "portugal", "sweden", "schweden", "denmark",
    "d\u00e4nemark", "finland", "finnland", "norway", "norwegen", "ireland",
    "canada", "kanada", "australia", "australien", "india", "indien",
    "singapore", "singapur", "hungary", "ungarn", "romania", "rum\u00e4nien",
    "bulgaria", "bulgarien", "luxembourg", "luxemburg", "greece",
    "griechenland", "croatia", "kroatien", "slovakia", "slowakei", "slovenia",
    "slowenien", "estonia", "estland", "latvia", "lettland", "lithuania",
    "litauen",
)


def html_to_text(value: Optional[str]) -> str:
    """Reduce an HTML description to readable plain text.

    Every verified source that carries a description publishes it as HTML (or, for
    Personio, CDATA-wrapped HTML). The generation pipeline consumes
    ``job_description.txt`` as text, so this conversion is the adapter between
    them. Block-level tags become newlines so bullet lists do not collapse into
    one run-on line, which would lose the structure a posting's requirements are
    usually carried in.
    """
    if not value:
        return ""
    text = str(value)
    # Block boundaries become newlines before tags are stripped, so list items and
    # paragraphs stay on separate lines instead of concatenating.
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|ul|ol|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    # Collapse runs of spaces but keep intentional line breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def country_from_display_location(value: Optional[str]) -> Optional[str]:
    """Extract a country code from a display string like ``"Berlin, Germany"``.

    Recognises a country named anywhere in the string, not only as a trailing
    segment: Arbeitnow publishes ``"Germany (remote)"``, which states the country
    just as plainly. Returns ``None`` when no country is named, which is the common
    case (``"Munich HQ"``, ``"Anywhere"``). Callers record the result as
    :attr:`FieldSource.PARSED`, never as an inference, because the country name is
    the publisher's own word.
    """
    if not value:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    # A trailing segment is the most common shape, so try it first.
    match = _TRAILING_COUNTRY_RE.search(text)
    if match:
        resolved = normalise_country(match.group(1))
        if resolved:
            return resolved
    # Otherwise look for a country name anywhere in the string, longest alias
    # first so a multi-word name is not shadowed by a shorter one inside it.
    for alias in _DISPLAY_COUNTRY_ALIASES:
        if _contains_word(text, alias):
            resolved = normalise_country(alias)
            if resolved:
                return resolved
    return None


def _contains_word(haystack: str, needle: str) -> bool:
    """True when ``needle`` appears in ``haystack`` as a whole phrase."""
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def city_from_display_location(value: Optional[str]) -> Optional[str]:
    """The leading city part of a display location, or ``None``.

    ``"Berlin, Germany"`` -> ``"Berlin"``; ``"Remote - US"`` -> ``"Remote"``;
    ``"Munich HQ"`` -> ``"Munich HQ"`` (kept whole, because splitting on a space
    alone would invent a boundary that is not there).
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Split on a comma, an en/em dash, or a spaced hyphen -- the separators the
    # verified sources actually use between city and country/region. A bare
    # unspaced hyphen is left alone: "Munich-Haidhausen" is one place name.
    head = re.split(r"\s*[,\u2013\u2014]\s*|\s+-\s+", text, maxsplit=1)[0].strip()
    # Strip a trailing country that had no separator, e.g. "Berlin Germany".
    for alias in ("Germany", "Deutschland", "Austria", "Oesterreich", "Österreich",
                  "Switzerland", "Schweiz"):
        if head.lower().endswith(alias.lower()) and len(head) > len(alias):
            head = head[: -len(alias)].strip(" ,-")
            break
    return head or None


# --- softgarden -------------------------------------------------------------------------

def normalise_softgarden_item(item: dict, source_name: str = "softgarden") -> Optional[Job]:
    """Normalise one ``DataFeedItem`` from softgarden's schema.org DataFeed.

    This is the richest verified source: the country is published structurally, so
    it is recorded as :attr:`FieldSource.STRUCTURED` and the job is correctly
    recognised as DACH without any interpretation.
    """
    if not isinstance(item, dict):
        return None
    # The DataFeedItem wraps the JobPosting in `item`; tolerate a bare JobPosting
    # too, since the same normaliser serves embedded JSON-LD.
    posting = item.get("item") if isinstance(item.get("item"), dict) else item
    if posting.get("@type") not in (None, "JobPosting"):
        return None

    identifier = posting.get("identifier")
    source_id = None
    if isinstance(identifier, dict):
        source_id = identifier.get("value")
    elif identifier is not None:
        source_id = identifier
    if source_id is None:
        return None

    organisation = posting.get("hiringOrganization") or {}
    company = organisation.get("name") if isinstance(organisation, dict) else None

    address = {}
    location = posting.get("jobLocation")
    if isinstance(location, list) and location:
        location = location[0]
    if isinstance(location, dict):
        address = location.get("address") or {}

    country = normalise_country(address.get("addressCountry"))
    return Job(
        source=source_name,
        source_id=str(source_id),
        url=posting.get("url") or "",
        title=posting.get("title") or "",
        company=company or "",
        description=html_to_text(posting.get("description")),
        location_raw=_compose_location(address) or None,
        country=(
            JobField.structured(country, note="addressCountry")
            if country else JobField.absent()
        ),
        city=JobField.structured(address.get("addressLocality")),
        region=JobField.structured(address.get("addressRegion")),
        postal_code=JobField.structured(address.get("postalCode")),
        employment_type=JobField.structured(posting.get("employmentType")),
        posted_at=parse_iso_datetime(posting.get("datePosted")),
    )


def iter_softgarden(payload: dict, source_name: str = "softgarden") -> Iterator[Job]:
    """Yield every job in a softgarden ``DataFeed`` payload.

    Also accepts a **bare** ``JobPosting`` (or a list of them), so the same
    normaliser serves the DataFeed and a JSON-LD block scraped out of a job page.
    That shared path is the reason the DataFeed is worth preferring: one parser
    covers both.
    """
    if not isinstance(payload, dict):
        return
    elements = payload.get("dataFeedElement")
    if elements:
        for element in elements:
            job = normalise_softgarden_item(element, source_name)
            if job is not None:
                yield job
        return
    # A bare posting, which is what a JSON-LD block on a job page contains.
    job = normalise_softgarden_item(payload, source_name)
    if job is not None:
        yield job


def _compose_location(address: dict) -> str:
    """A readable location string from a schema.org PostalAddress."""
    if not isinstance(address, dict):
        return ""
    parts = [address.get("addressLocality"), address.get("addressRegion"),
             address.get("addressCountry")]
    return ", ".join(str(part) for part in parts if part)


# --- Personio ---------------------------------------------------------------------------

def iter_personio(xml_text: str, source_name: str = "personio") -> Iterator[Job]:
    """Yield jobs from Personio's ``<workzag-jobs>`` XML feed.

    Personio publishes **no country field**. The ``office`` value is a bare city
    name, so ``country`` is left absent and ``city`` carries what was actually
    said. A caller wanting DACH filtering must therefore apply its own rule rather
    than trusting this normaliser to have guessed.
    """
    if not xml_text or not xml_text.strip():
        return
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return
    for position in root.iter("position"):
        source_id = _text(position, "id")
        if not source_id:
            continue
        office = _text(position, "office")
        descriptions = [
            html_to_text(_text(node, "value"))
            for node in position.iter("jobDescription")
        ]
        description = "\n\n".join(part for part in descriptions if part)
        # Personio names the role `name` and the company `subcompany`.
        #
        # The feed carries **no url**, so this is left empty rather than filled with
        # a plausible-looking guess. The connector is what knows the tenant
        # subdomain and can build a real link; a placeholder here would surface in
        # the user's output as a broken link that looks legitimate.
        yield Job(
            source=source_name,
            source_id=source_id,
            url="",
            title=_text(position, "name") or "",
            company=_text(position, "subcompany") or "",
            description=description,
            location_raw=office,
            # No country field exists in this feed: absent, not guessed.
            country=JobField.absent(),
            city=JobField.structured(office),
            employment_type=JobField.structured(_text(position, "employmentType")),
            posted_at=parse_iso_datetime(_text(position, "createdAt")),
        )


def _text(node, tag: str) -> Optional[str]:
    """The stripped text of a direct child, or ``None``."""
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


# --- Lever ------------------------------------------------------------------------------

def iter_lever(payload, source_name: str = "lever") -> Iterator[Job]:
    """Yield jobs from Lever's ``/v0/postings/{site}?mode=json`` array.

    Lever publishes a real ``country`` field, so the country is structured. Its
    ``categories.location`` is a display string kept verbatim in ``location_raw``.
    """
    for posting in payload or []:
        if not isinstance(posting, dict):
            continue
        source_id = posting.get("id")
        if not source_id:
            continue
        categories = posting.get("categories") or {}
        country = normalise_country(posting.get("country"))
        workplace = posting.get("workplaceType")
        yield Job(
            source=source_name,
            source_id=str(source_id),
            url=posting.get("hostedUrl") or "",
            title=posting.get("text") or "",
            company=posting.get("company") or "",
            description=html_to_text(posting.get("descriptionPlain")
                                     or posting.get("description")),
            location_raw=categories.get("location"),
            country=(
                JobField.structured(country, note="postings.country")
                if country else JobField.absent()
            ),
            city=JobField.structured(city_from_display_location(categories.get("location"))),
            employment_type=JobField.structured(categories.get("commitment")),
            remote_flag=_remote_flag_from_workplace(workplace),
            posted_at=parse_iso_datetime(posting.get("createdAt")),
        )


def _remote_flag_from_workplace(value: Optional[str]) -> JobField:
    """Map Lever/Ashby ``workplaceType`` onto the structured remote flag."""
    if not value:
        return JobField.absent()
    text = str(value).strip().lower()
    if text in ("remote",):
        return JobField.structured("true", note="workplaceType")
    if text in ("on-site", "onsite", "office"):
        return JobField.structured("false", note="workplaceType")
    if text in ("hybrid",):
        # Hybrid is not remote; record the explicit false rather than silence.
        return JobField.structured("false", note="workplaceType=hybrid")
    return JobField.absent()


# --- Greenhouse -------------------------------------------------------------------------

def iter_greenhouse(payload, source_name: str = "greenhouse",
                    company: str = "") -> Iterator[Job]:
    """Yield jobs from Greenhouse's ``/v1/boards/{token}/jobs`` object.

    Greenhouse has **no country field and no JSON-LD**. ``location.name`` is a
    display string, so the country here is genuinely *parsed* from the publisher's
    text rather than published structurally -- a weaker but still honest claim,
    recorded as :attr:`FieldSource.PARSED`.
    """
    jobs = (payload or {}).get("jobs")
    for record in jobs or []:
        if not isinstance(record, dict):
            continue
        source_id = record.get("id")
        if source_id is None:
            continue
        location = record.get("location") or {}
        display = location.get("name") if isinstance(location, dict) else None
        country = country_from_display_location(display)
        yield Job(
            source=source_name,
            source_id=str(source_id),
            url=record.get("absolute_url") or "",
            title=record.get("title") or "",
            company=record.get("company_name") or company,
            description="",
            location_raw=display,
            country=(
                JobField.parsed(country, note=f"parsed from location {display!r}")
                if country else JobField.absent()
            ),
            city=JobField.parsed(city_from_display_location(display),
                                 note=f"parsed from location {display!r}")
            if display else JobField.absent(),
            posted_at=parse_iso_datetime(record.get("first_published")
                                         or record.get("updated_at")),
        )


# --- Ashby ------------------------------------------------------------------------------

def iter_ashby(payload, source_name: str = "ashby", company: str = "",
               include_unlisted: bool = False) -> Iterator[Job]:
    """Yield jobs from Ashby's ``posting-api/job-board/{name}`` object.

    Ashby publishes a nested ``address.postalAddress.addressCountry``, so the
    country is structured. ``isListed: false`` entries are internal and are skipped
    by default -- surfacing an unlisted internal role as a job opportunity would be
    wrong even though the API returns it.
    """
    jobs = (payload or {}).get("jobs")
    for record in jobs or []:
        if not isinstance(record, dict):
            continue
        if not include_unlisted and record.get("isListed") is False:
            continue
        source_id = record.get("id")
        if not source_id:
            continue
        address = record.get("address") or {}
        postal = address.get("postalAddress") if isinstance(address, dict) else None
        postal = postal if isinstance(postal, dict) else {}
        country = normalise_country(postal.get("addressCountry"))
        remote = record.get("isRemote")
        yield Job(
            source=source_name,
            source_id=str(source_id),
            url=record.get("jobUrl") or "",
            title=record.get("title") or "",
            company=company,
            description=html_to_text(record.get("descriptionPlain")
                                     or record.get("descriptionHtml")),
            location_raw=record.get("location"),
            country=(
                JobField.structured(country, note="address.postalAddress.addressCountry")
                if country else JobField.absent()
            ),
            city=JobField.structured(postal.get("addressLocality")),
            region=JobField.structured(postal.get("addressRegion")),
            employment_type=JobField.structured(record.get("employmentType")),
            remote_flag=(
                JobField.structured("true" if remote else "false", note="isRemote")
                if isinstance(remote, bool) else JobField.absent()
            ),
            posted_at=parse_iso_datetime(record.get("publishedAt")),
        )


# --- Arbeitnow --------------------------------------------------------------------------

def iter_arbeitnow(payload, source_name: str = "arbeitnow") -> Iterator[Job]:
    """Yield jobs from Arbeitnow's ``data[]`` array.

    Arbeitnow publishes a **free-text** ``location`` and no country field. Where that
    string names a country -- ``"Germany (remote)"`` -- the country is *parsed* from
    the publisher's own words. Where it does not -- ``"Munich HQ"`` -- the country
    stays absent and the raw string is preserved, so a city is never promoted to a
    country.
    """
    for record in (payload or {}).get("data") or []:
        if not isinstance(record, dict):
            continue
        source_id = record.get("slug")
        if not source_id:
            continue
        remote = record.get("remote")
        job_types = record.get("job_types") or []
        location = record.get("location")
        country = country_from_display_location(location)
        yield Job(
            source=source_name,
            source_id=str(source_id),
            url=record.get("url") or "",
            title=record.get("title") or "",
            company=record.get("company_name") or "",
            description=html_to_text(record.get("description")),
            location_raw=location,
            country=(
                JobField.parsed(country, note=f"parsed from location {location!r}")
                if country else JobField.absent()
            ),
            city=JobField.structured(location),
            employment_type=JobField.structured(
                ", ".join(str(t) for t in job_types) if job_types else None
            ),
            remote_flag=(
                JobField.structured("true" if remote else "false", note="data.remote")
                if isinstance(remote, bool) else JobField.absent()
            ),
            posted_at=parse_iso_datetime(record.get("created_at")),
        )


def matches_local_filters(job: Job, query) -> bool:
    """Apply the constraints a source could not apply server-side.

    Returns True when the job satisfies everything in ``query`` that can be checked
    locally. Used together with :class:`~models.job.SourceCapabilities` so a caller
    is told when filtering happened here rather than at the source, instead of
    silently receiving a list it believes was narrowed upstream.
    """
    if query.country:
        # Strict: a DACH query excludes jobs whose country is absent, because we
        # cannot show that they match without inventing the country.
        if (job.country.value or "").upper() != query.country.upper():
            return False
    if query.city:
        haystack = " ".join(filter(None, [job.city.value, job.location_raw])).lower()
        if query.city.lower() not in haystack:
            return False
    if query.remote is not None:
        resolved = job.resolved_remote()
        if query.remote and resolved is not Remote.REMOTE:
            return False
        if not query.remote and resolved is Remote.REMOTE:
            return False
    return True


def matches_keywords(job: Job, keywords: Optional[str]) -> bool:
    """True when every keyword token appears in the job's title or description.

    All tokens must match (AND), which is what a user typing two words expects.
    Matching is case-insensitive and token-based rather than substring, so
    "engineer" does not match "engineering" by accident of substring but does match
    a real word boundary.
    """
    if not keywords or not keywords.strip():
        return True
    haystack = f"{job.title} {job.company} {job.description}".lower()
    tokens = [token for token in re.split(r"\W+", keywords.lower()) if token]
    return all(token in haystack for token in tokens)
