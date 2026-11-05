"""The Phase 4 connectors: softgarden, Personio, and the ATS family.

Every class here implements :class:`~models.job.JobSource`, so the rest of the
system does not know or care which source a job came from. Which sources exist is
the outcome of the ADR 0008 §1 research
(``docs/analysis/job-sources-research.md``), approved by the owner on 2026-11-05:

**Built** — softgarden, Personio, and one ATS connector family covering Lever,
Greenhouse and Ashby. All are documented or long-stable public endpoints requiring
no credentials, verified reachable on 2026-11-05.

**Not built, and why** — recorded in code because "we decided not to" is exactly
the knowledge that gets lost:

* **StepStone, Indeed, LinkedIn** publish ``robots.txt`` rules that disallow the
  very paths a connector would need (Indeed disallows ``/jobs/DE/`` explicitly).
  ADR 0008 §4 forbids unreliable workarounds that violate terms. Respecting a
  refusal means not making the request.
* **SmartRecruiters** returns perfect data and its API host's ``robots.txt`` is
  ``Disallow: /``. It is excluded on the operator's own terms. A ``200`` is not
  permission.
* **Bundesagentur für Arbeit** refused the well-known public key with ``403`` on
  both the token and search endpoints. It remains the natural candidate for a
  partner application and is not written off, only unavailable today.
* **Workday, JOIN, Umantis, Recruitee, d.vinci, onlyfy** each need a
  reverse-engineered or per-customer integration; deferred rather than guessed at.

The **sample employer list** for the ATS family is deliberately small and
replaceable, per the owner's answer to Q3: the connector ships configured with
public example boards and the caller supplies their own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional

from models.job import (
    Job,
    JobSource,
    JobSourceError,
    SearchQuery,
    SourceCapabilities,
)
from services.job_http import JobHttpClient, RobotsPolicy
from services.job_normalize import (
    iter_arbeitnow,
    iter_ashby,
    iter_greenhouse,
    iter_lever,
    iter_personio,
    iter_softgarden,
    matches_keywords,
    matches_local_filters,
)

#: A source that enumerates its whole corpus can be filtered locally *completely*.
#: One that supports server-side filtering should be asked to do so, because
#: fetching everything and filtering locally would be both slower and ruder.


class SoftgardenSource(JobSource):
    """softgarden's official schema.org DataFeed.

    The best-fitting DACH source found: officially published for machine
    consumption, no credentials, and the payload *is* ``JobPosting``, so the same
    parser also handles embedded JSON-LD. Its ``robots.txt`` says "All robots
    allowed" and names AI crawlers as permitted, but this connector reads the
    published feed rather than crawling, which is why ``robots`` is not consulted.
    """

    name = "softgarden"
    capabilities = SourceCapabilities(
        server_side_keywords=False,
        server_side_location=False,
        server_side_remote=False,
        enumerable=True,
        provides_posted_at=True,
        provides_expiry=False,
        requires_credentials=False,
        verified_on="2026-11-05",
    )

    #: Tenant subdomains to read. One per employer career site.
    def __init__(self, tenants: Iterable[str], client: Optional[JobHttpClient] = None):
        self.tenants = [str(tenant).strip() for tenant in tenants if str(tenant).strip()]
        self.client = client or JobHttpClient()

    def feed_url(self, tenant: str) -> str:
        return f"https://{tenant}.career.softgarden.de/jobs.feed.json"

    def search(self, query: SearchQuery) -> Iterator[Job]:
        yielded = 0
        for tenant in self.tenants:
            if yielded >= query.limit:
                return
            payload = self.client.get_json(self.feed_url(tenant), self.name)
            for job in iter_softgarden(payload, self.name):
                if not matches_local_filters(job, query):
                    continue
                if not matches_keywords(job, query.keywords):
                    continue
                yield job
                yielded += 1
                if yielded >= query.limit:
                    return


class PersonioSource(JobSource):
    """Personio's official career-site XML feed.

    Covers the German/Austrian/Swiss SME market that no other approved source
    reaches. Personio publishes **no country field**, so its jobs are never DACH by
    ``is_dach`` -- correct rather than a limitation, because inferring the country
    from ``office`` would turn a guess into a fact.

    ``fetch_one`` is not implemented: the feed has no single-position endpoint
    documented, and synthesising one would be invention.
    """

    name = "personio"
    capabilities = SourceCapabilities(
        server_side_keywords=False,
        server_side_location=False,
        enumerable=True,
        provides_posted_at=True,
        requires_credentials=False,
        verified_on="2026-11-05",
    )

    def __init__(self, tenants: Iterable[str], client: Optional[JobHttpClient] = None,
                 tenant_url_builder=None):
        self.tenants = [str(tenant).strip() for tenant in tenants if str(tenant).strip()]
        self.client = client or JobHttpClient()
        #: How a source_id becomes a public URL. Personio feeds carry no url, so
        #: the caller supplies the pattern; without it the job still normalises,
        #: with an empty url rather than an invented one.
        self.tenant_url_builder = tenant_url_builder

    def feed_url(self, tenant: str) -> str:
        return f"https://{tenant}.jobs.personio.de/xml"

    def search(self, query: SearchQuery) -> Iterator[Job]:
        yielded = 0
        for tenant in self.tenants:
            if yielded >= query.limit:
                return
            xml_text = self.client.get_text(self.feed_url(tenant), self.name)
            for job in iter_personio(xml_text, self.name):
                if self.tenant_url_builder:
                    built = self.tenant_url_builder(tenant, job.source_id)
                    if built:
                        job.url = built
                if not matches_local_filters(job, query):
                    continue
                if not matches_keywords(job, query.keywords):
                    continue
                yield job
                yielded += 1
                if yielded >= query.limit:
                    return
    def fetch_one(self, source_id: str) -> Optional[Job]:
        return None


@dataclass
class AtsBoard:
    """One employer's board on one ATS platform."""

    platform: str
    token: str
    company: str = ""


class AtsSource(JobSource):
    """One connector for the ATS family: Lever, Greenhouse and Ashby.

    These three share a shape rather than merely a category -- each is a
    per-employer public JSON endpoint requiring no credentials -- so they share one
    class and differ only by which normaliser runs. Consolidating them means adding
    an employer is a configuration line, not a new connector.

    Per-employer boards are the cost of this family: there is no global directory,
    so coverage follows the employers configured. That is why the ATS family
    complements rather than replaces the corpus-wide sources.
    """

    name = "ats"
    capabilities = SourceCapabilities(
        server_side_keywords=False,
        server_side_location=False,
        enumerable=True,
        provides_posted_at=True,
        requires_credentials=False,
        verified_on="2026-11-05",
    )

    #: The platforms this connector understands.
    PLATFORMS = ("lever", "greenhouse", "ashby")

    def __init__(self, boards: Iterable[AtsBoard], client: Optional[JobHttpClient] = None):
        self.boards = [
            board if isinstance(board, AtsBoard) else AtsBoard(**board)
            for board in boards
        ]
        for board in self.boards:
            if board.platform not in self.PLATFORMS:
                raise ValueError(
                    f"Unknown ATS platform {board.platform!r}. Supported: "
                    f"{', '.join(self.PLATFORMS)}."
                )
        self.client = client or JobHttpClient()

    def board_url(self, board: AtsBoard) -> str:
        """The public listing endpoint for one board."""
        if board.platform == "lever":
            return f"https://api.lever.co/v0/postings/{board.token}?mode=json"
        if board.platform == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{board.token}/jobs"
        return f"https://api.ashbyhq.com/posting-api/job-board/{board.token}"

    def _normalise(self, board: AtsBoard, payload):
        """Dispatch to the right normaliser for this board's platform."""
        if board.platform == "lever":
            return iter_lever(payload, f"{self.name}:lever")
        if board.platform == "greenhouse":
            return iter_greenhouse(payload, f"{self.name}:greenhouse",
                                   company=board.company)
        return iter_ashby(payload, f"{self.name}:ashby", company=board.company)

    def search(self, query: SearchQuery) -> Iterator[Job]:
        yielded = 0
        for board in self.boards:
            if yielded >= query.limit:
                return
            payload = self.client.get_json(self.board_url(board), self.name)
            for job in self._normalise(board, payload):
                if not matches_local_filters(job, query):
                    continue
                if not matches_keywords(job, query.keywords):
                    continue
                yield job
                yielded += 1
                if yielded >= query.limit:
                    return


class ArbeitnowSource(JobSource):
    """Arbeitnow's public job-board API.

    Verified live with no credentials and Germany-first coverage (~5,700 postings
    across ~19 pages). It publishes **free-text** locations (``"Munich HQ"``) and no
    country, so its jobs never claim DACH status -- the honest outcome, since the
    source never states one.

    Whole-corpus enumeration is possible but deliberately not the default: the
    connector pages only as far as ``query.limit`` requires, so a small search does
    not fetch megabytes.
    """

    name = "arbeitnow"
    capabilities = SourceCapabilities(
        server_side_keywords=False,
        server_side_location=False,
        enumerable=True,
        provides_posted_at=True,
        requires_credentials=False,
        verified_on="2026-11-05",
    )

    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, client: Optional[JobHttpClient] = None, max_pages: int = 5):
        self.client = client or JobHttpClient()
        self.max_pages = max_pages

    def page_url(self, page: int) -> str:
        return f"{self.BASE_URL}?page={page}"

    def search(self, query: SearchQuery) -> Iterator[Job]:
        yielded = 0
        for page in range(1, self.max_pages + 1):
            if yielded >= query.limit:
                return
            payload = self.client.get_json(self.page_url(page), self.name)
            records = (payload or {}).get("data") or []
            if not records:
                return
            for job in iter_arbeitnow(payload, self.name):
                if not matches_local_filters(job, query):
                    continue
                if not matches_keywords(job, query.keywords):
                    continue
                yield job
                yielded += 1
                if yielded >= query.limit:
                    return


#: A small, replaceable sample of public boards, so the ATS connector is usable
#: before the owner configures their own employers (their answer to Q3). These are
#: the tenants used during the 2026-10-31 research, chosen because they are public
#: and well known -- not because they are recommended employers.
SAMPLE_ATS_BOARDS = (
    AtsBoard(platform="lever", token="leverdemo", company="Lever (demo board)"),
    AtsBoard(platform="greenhouse", token="greenhouse", company="Greenhouse"),
    AtsBoard(platform="ashby", token="ashby", company="Ashby"),
)

#: Sample softgarden tenants, likewise replaceable.
SAMPLE_SOFTGARDEN_TENANTS = ("softgarden",)

#: Sample Personio tenants, likewise replaceable.
SAMPLE_PERSONIO_TENANTS = ("holidaycheck",)


def build_default_sources(client: Optional[JobHttpClient] = None,
                          ats_boards: Optional[Iterable[AtsBoard]] = None,
                          softgarden_tenants: Optional[Iterable[str]] = None,
                          personio_tenants: Optional[Iterable[str]] = None,
                          include_arbeitnow: bool = True) -> List[JobSource]:
    """The approved source set (owner decision, 2026-11-05).

    Returns the connectors in the recommended order, so a caller that stops early
    has read the highest-value sources first. ``ats_boards`` etc. override the
    samples, which is how a caller configures their own employers.
    """
    shared = client or JobHttpClient()
    sources: List[JobSource] = [
        SoftgardenSource(softgarden_tenants or SAMPLE_SOFTGARDEN_TENANTS, client=shared),
        PersonioSource(personio_tenants or SAMPLE_PERSONIO_TENANTS, client=shared),
        AtsSource(ats_boards or SAMPLE_ATS_BOARDS, client=shared),
    ]
    if include_arbeitnow:
        sources.append(ArbeitnowSource(client=shared))
    return sources
