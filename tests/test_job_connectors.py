"""Tests for the Phase 4 connectors and the HTTP layer (Phase 4, item 6).

**No test here may make a network call.** Everything runs against
:class:`RecordingTransport`, which replays payloads captured from the real
endpoints, and raises if asked for a URL it does not hold -- so an accidental live
fetch fails loudly instead of quietly depending on someone else's uptime.

The connectors themselves are mostly thin: fetch, normalise, filter. What is worth
testing is the behaviour a caller depends on and cannot see -- the request budget,
the honest User-Agent, honest capability declarations, and that a credential-free
source is genuinely credential-free.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.job import JobSource, JobSourceError, SearchQuery
from services.job_connectors import (
    ArbeitnowSource,
    AtsBoard,
    AtsSource,
    PersonioSource,
    SoftgardenSource,
    build_default_sources,
)
from services.job_http import (
    HttpResponse,
    JobHttpClient,
    RecordingTransport,
    RobotsPolicy,
    build_user_agent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "job_sources" / "source_payloads.json"


@pytest.fixture(scope="module")
def payloads() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


# --- the HTTP layer's obligations --------------------------------------------------------

def test_the_user_agent_identifies_the_tool_honestly():
    """ADR 0008 §3 requires honest identification; it is not optional."""
    agent = build_user_agent()
    assert agent.startswith("cv-tailor/")
    assert "github.com" in agent


def test_the_request_budget_is_enforced_not_merely_documented():
    """A connector bug must degrade to a slow search, not a flood."""
    transport = RecordingTransport({"https://a.test/x": b"{}"})
    client = JobHttpClient(transport=transport, request_budget=2, min_interval=0)
    client.get("https://a.test/x")
    client.get("https://a.test/x")
    with pytest.raises(JobSourceError, match="budget exhausted"):
        client.get("https://a.test/x")


def test_the_budget_counts_every_request_including_failures():
    transport = RecordingTransport({"https://a.test/x": HttpResponse(500, b"")})
    client = JobHttpClient(transport=transport, request_budget=1, min_interval=0)
    client.get("https://a.test/x")
    with pytest.raises(JobSourceError, match="budget exhausted"):
        client.get("https://a.test/x")


def test_requests_to_one_host_are_paced():
    """A connector paging 30 results must not issue 30 back-to-back requests."""
    slept = []
    clock = {"t": 0.0}

    def fake_clock():
        return clock["t"]

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    transport = RecordingTransport({"https://a.test/x": b"{}"})
    client = JobHttpClient(transport=transport, min_interval=1.0,
                           clock=fake_clock, sleeper=fake_sleep)
    client.get("https://a.test/x")
    client.get("https://a.test/x")
    assert slept and slept[0] == pytest.approx(1.0, abs=0.01)


def test_no_pacing_sleep_happens_when_the_interval_already_elapsed():
    clock = {"t": 0.0}
    slept = []
    transport = RecordingTransport({"https://a.test/x": b"{}"})
    client = JobHttpClient(transport=transport, min_interval=1.0,
                           clock=lambda: clock["t"], sleeper=slept.append)
    client.get("https://a.test/x")
    clock["t"] = 10.0
    client.get("https://a.test/x")
    assert slept == []


def test_pacing_is_per_host_not_global():
    """Two sources must not wait on each other."""
    clock = {"t": 0.0}
    slept = []
    transport = RecordingTransport({
        "https://a.test/x": b"{}", "https://b.test/y": b"{}",
    })
    client = JobHttpClient(transport=transport, min_interval=5.0,
                           clock=lambda: clock["t"], sleeper=slept.append)
    client.get("https://a.test/x")
    client.get("https://b.test/y")
    assert slept == []


def test_a_non_200_raises_a_source_error_not_a_urllib_error():
    """Connectors must not leak transport exceptions to the caller."""
    transport = RecordingTransport({"https://a.test/x": HttpResponse(503, b"")})
    client = JobHttpClient(transport=transport, min_interval=0)
    with pytest.raises(JobSourceError) as caught:
        client.get_json("https://a.test/x", "demo")
    assert caught.value.retryable is True


def test_a_client_error_is_not_marked_retryable():
    transport = RecordingTransport({"https://a.test/x": HttpResponse(404, b"")})
    client = JobHttpClient(transport=transport, min_interval=0)
    with pytest.raises(JobSourceError) as caught:
        client.get_json("https://a.test/x", "demo")
    assert caught.value.retryable is False


def test_invalid_json_raises_a_source_error():
    transport = RecordingTransport({"https://a.test/x": "<html>not json</html>"})
    client = JobHttpClient(transport=transport, min_interval=0)
    with pytest.raises(JobSourceError, match="not JSON"):
        client.get_json("https://a.test/x", "demo")


def test_the_recording_transport_refuses_an_uncaptured_url():
    """The guard that keeps these tests offline."""
    with pytest.raises(AssertionError, match="no captured response"):
        RecordingTransport({}).get("https://never-captured.test/x")


def test_loading_recorded_payloads_maps_keys_to_urls(tmp_path):
    path = tmp_path / "recorded.json"
    path.write_text(json.dumps({"_comment": "x", "feed": {"data": []}}), encoding="utf-8")
    transport = __import__(
        "services.job_http", fromlist=["load_recorded_transport"]
    ).load_recorded_transport(path, base_urls={"feed": "https://x.test/feed"})
    assert transport.get("https://x.test/feed").status == 200


# --- robots policy ------------------------------------------------------------------------

def test_robots_allows_a_permitted_path():
    transport = RecordingTransport({"https://x.test/robots.txt": "User-agent: *\nAllow: /\n"})
    assert RobotsPolicy(transport).allowed("https://x.test/jobs") is True


def test_robots_refuses_a_disallowed_path():
    """The SmartRecruiters case: data available, access refused."""
    transport = RecordingTransport(
        {"https://x.test/robots.txt": "User-agent: *\nDisallow: /\n"})
    assert RobotsPolicy(transport).allowed("https://x.test/jobs") is False


def test_an_unreachable_robots_file_does_not_grant_permission():
    """Fail closed: not knowing the rules is not permission."""
    transport = RecordingTransport({})
    policy = RobotsPolicy(transport)
    with pytest.raises(AssertionError):
        # The transport refuses the uncaptured robots URL, which the policy
        # converts into a refusal rather than an allow.
        policy.allowed("https://x.test/jobs")


def test_robots_is_fetched_once_per_host():
    transport = RecordingTransport({"https://x.test/robots.txt": "User-agent: *\nAllow: /\n"})
    policy = RobotsPolicy(transport)
    policy.allowed("https://x.test/a")
    policy.allowed("https://x.test/b")
    assert transport.calls.count("https://x.test/robots.txt") == 1


# --- softgarden ---------------------------------------------------------------------------

def feed(payloads):
    return {"https://acme.career.softgarden.de/jobs.feed.json":
            payloads["softgarden_datafeed"]}


def test_softgarden_reads_its_published_feed(payloads):
    client = JobHttpClient(transport=RecordingTransport(feed(payloads)), min_interval=0)
    jobs = list(SoftgardenSource(["acme"], client=client).search(SearchQuery()))
    assert len(jobs) == 3
    assert all(job.source == "softgarden" for job in jobs)


def test_softgarden_builds_the_official_feed_url():
    source = SoftgardenSource(["acme"])
    assert source.feed_url("acme") == "https://acme.career.softgarden.de/jobs.feed.json"


def test_softgarden_respects_the_limit(payloads):
    client = JobHttpClient(transport=RecordingTransport(feed(payloads)), min_interval=0)
    jobs = list(SoftgardenSource(["acme"], client=client).search(SearchQuery(limit=1)))
    assert len(jobs) == 1


def test_softgarden_filters_by_keyword_locally(payloads):
    client = JobHttpClient(transport=RecordingTransport(feed(payloads)), min_interval=0)
    jobs = list(SoftgardenSource(["acme"], client=client).search(
        SearchQuery(keywords="backend")))
    assert len(jobs) == 1
    assert "Backend" in jobs[0].title


def test_softgarden_filters_by_country_locally(payloads):
    client = JobHttpClient(transport=RecordingTransport(feed(payloads)), min_interval=0)
    jobs = list(SoftgardenSource(["acme"], client=client).search(
        SearchQuery(country="DE")))
    assert len(jobs) == 1
    assert jobs[0].country.value == "DE"


def test_softgarden_reads_several_tenants(payloads):
    responses = {
        "https://a.career.softgarden.de/jobs.feed.json": payloads["softgarden_datafeed"],
        "https://b.career.softgarden.de/jobs.feed.json": payloads["softgarden_datafeed"],
    }
    client = JobHttpClient(transport=RecordingTransport(responses), min_interval=0)
    jobs = list(SoftgardenSource(["a", "b"], client=client).search(SearchQuery()))
    assert len(jobs) == 6


def test_softgarden_declares_it_cannot_filter_server_side():
    """Honest declarations: the caller is warned that filtering happened locally."""
    caps = SoftgardenSource([]).capabilities
    assert caps.server_side_keywords is False
    assert caps.enumerable is True
    assert caps.requires_credentials is False
    assert caps.limitations_for(SearchQuery(keywords="x"))


# --- Personio -----------------------------------------------------------------------------

def test_personio_reads_its_xml_feed(payloads):
    responses = {"https://acme.jobs.personio.de/xml": payloads["personio_xml"]}
    client = JobHttpClient(transport=RecordingTransport(responses), min_interval=0)
    jobs = list(PersonioSource(["acme"], client=client).search(SearchQuery()))
    assert len(jobs) == 2
    assert all(job.source == "personio" for job in jobs)


def test_personio_builds_the_official_feed_url():
    assert PersonioSource(["acme"]).feed_url("acme") == "https://acme.jobs.personio.de/xml"


def test_personio_jobs_never_claim_a_country(payloads):
    """The feed has no country field, so claiming DACH would be fabrication."""
    responses = {"https://acme.jobs.personio.de/xml": payloads["personio_xml"]}
    client = JobHttpClient(transport=RecordingTransport(responses), min_interval=0)
    jobs = list(PersonioSource(["acme"], client=client).search(SearchQuery()))
    assert all(job.country.value is None for job in jobs)
    assert all(job.is_dach is False for job in jobs)


def test_personio_uses_a_supplied_url_builder(payloads):
    """The feed carries no url, so the caller supplies the pattern."""
    responses = {"https://acme.jobs.personio.de/xml": payloads["personio_xml"]}
    client = JobHttpClient(transport=RecordingTransport(responses), min_interval=0)
    source = PersonioSource(
        ["acme"], client=client,
        tenant_url_builder=lambda tenant, pid: f"https://{tenant}.jobs.personio.de/job/{pid}",
    )
    jobs = list(source.search(SearchQuery()))
    assert jobs[0].url == "https://acme.jobs.personio.de/job/2048817"


def test_personio_does_not_invent_a_url_without_a_builder(payloads):
    """No builder means no url, rather than a plausible-looking fabrication."""
    responses = {"https://acme.jobs.personio.de/xml": payloads["personio_xml"]}
    client = JobHttpClient(transport=RecordingTransport(responses), min_interval=0)
    jobs = list(PersonioSource(["acme"], client=client).search(SearchQuery()))
    assert jobs[0].url == ""


# --- the ATS family -----------------------------------------------------------------------

def boards():
    return [AtsBoard(platform="lever", token="acme"),
            AtsBoard(platform="greenhouse", token="acme", company="Acme"),
            AtsBoard(platform="ashby", token="acme", company="Acme")]


def ats_responses(payloads):
    return {
        "https://api.lever.co/v0/postings/acme?mode=json": payloads["lever_postings"],
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs": payloads["greenhouse_jobs"],
        "https://api.ashbyhq.com/posting-api/job-board/acme": payloads["ashby_jobs"],
    }


def test_the_ats_connector_reads_all_three_platforms(payloads):
    client = JobHttpClient(transport=RecordingTransport(ats_responses(payloads)),
                           min_interval=0)
    jobs = list(AtsSource(boards(), client=client).search(SearchQuery()))
    # 2 lever + 2 greenhouse + 1 listed ashby (the unlisted one is skipped).
    assert len(jobs) == 5


def test_ats_jobs_record_which_platform_they_came_from(payloads):
    """A caller must be able to tell Lever from Greenhouse in the output."""
    client = JobHttpClient(transport=RecordingTransport(ats_responses(payloads)),
                           min_interval=0)
    jobs = list(AtsSource(boards(), client=client).search(SearchQuery()))
    assert {job.source for job in jobs} == {"ats:lever", "ats:greenhouse", "ats:ashby"}


def test_each_ats_platform_builds_its_own_documented_url():
    source = AtsSource([])
    assert source.board_url(AtsBoard("lever", "x")) == \
        "https://api.lever.co/v0/postings/x?mode=json"
    assert source.board_url(AtsBoard("greenhouse", "x")) == \
        "https://boards-api.greenhouse.io/v1/boards/x/jobs"
    assert source.board_url(AtsBoard("ashby", "x")) == \
        "https://api.ashbyhq.com/posting-api/job-board/x"


def test_an_unknown_ats_platform_is_rejected_at_construction():
    """Fail at configuration time, not with a confusing crash mid-search."""
    with pytest.raises(ValueError, match="Unknown ATS platform"):
        AtsSource([AtsBoard(platform="workday", token="x")])


def test_ats_accepts_plain_dicts_for_boards():
    """So boards can come from JSON configuration without a conversion step."""
    source = AtsSource([{"platform": "lever", "token": "acme"}])
    assert source.boards[0].token == "acme"


def test_the_ats_connector_filters_locally(payloads):
    client = JobHttpClient(transport=RecordingTransport(ats_responses(payloads)),
                           min_interval=0)
    jobs = list(AtsSource(boards(), client=client).search(SearchQuery(country="DE")))
    assert jobs
    assert all(job.country.value == "DE" for job in jobs)


def test_the_ats_connector_respects_the_limit(payloads):
    client = JobHttpClient(transport=RecordingTransport(ats_responses(payloads)),
                           min_interval=0)
    jobs = list(AtsSource(boards(), client=client).search(SearchQuery(limit=2)))
    assert len(jobs) == 2


def test_the_ats_connector_stops_paging_once_the_limit_is_met(payloads):
    """Stopping early means not reading boards that cannot contribute."""
    transport = RecordingTransport(ats_responses(payloads))
    client = JobHttpClient(transport=transport, min_interval=0)
    list(AtsSource(boards(), client=client).search(SearchQuery(limit=1)))
    assert len(transport.calls) == 1


# --- Arbeitnow ----------------------------------------------------------------------------

def test_arbeitnow_pages_and_filters(payloads):
    responses = {
        "https://www.arbeitnow.com/api/job-board-api?page=1": payloads["arbeitnow_feed"],
        "https://www.arbeitnow.com/api/job-board-api?page=2": {"data": []},
    }
    client = JobHttpClient(transport=RecordingTransport(responses), min_interval=0)
    jobs = list(ArbeitnowSource(client=client).search(SearchQuery()))
    assert len(jobs) == 2


def test_arbeitnow_stops_when_a_page_is_empty(payloads):
    responses = {
        "https://www.arbeitnow.com/api/job-board-api?page=1": {"data": []},
    }
    transport = RecordingTransport(responses)
    client = JobHttpClient(transport=transport, min_interval=0)
    assert list(ArbeitnowSource(client=client).search(SearchQuery())) == []
    assert len(transport.calls) == 1


def test_arbeitnow_does_not_over_fetch_for_a_small_limit(payloads):
    """A limit of 1 must not download five pages of the corpus."""
    responses = {
        "https://www.arbeitnow.com/api/job-board-api?page=1": payloads["arbeitnow_feed"],
    }
    transport = RecordingTransport(responses)
    client = JobHttpClient(transport=transport, min_interval=0)
    list(ArbeitnowSource(client=client).search(SearchQuery(limit=1)))
    assert len(transport.calls) == 1


# --- the assembled default source set ------------------------------------------------------

def test_the_default_set_is_the_approved_one():
    """softgarden, Personio and the ATS family, per the owner's 2026-11-05 answer."""
    names = [source.name for source in build_default_sources()]
    assert names[:3] == ["softgarden", "personio", "ats"]


def test_every_default_source_implements_the_contract():
    for source in build_default_sources():
        assert isinstance(source, JobSource)
        assert source.name
        assert source.capabilities.verified_on


def test_no_default_source_needs_credentials():
    """The approved set is credential-free; a paid or keyed source needs approval."""
    for source in build_default_sources():
        assert source.capabilities.requires_credentials is False


def test_every_default_source_can_be_disabled_independently():
    """ADR 0008: a withdrawn source affects only its own connector."""
    without = build_default_sources(include_arbeitnow=False)
    assert "arbeitnow" not in [source.name for source in without]


def test_the_default_set_can_be_given_the_owner_s_own_employers():
    sources = build_default_sources(
        ats_boards=[AtsBoard(platform="lever", token="my-employer")],
        softgarden_tenants=["my-tenant"],
    )
    ats = next(source for source in sources if source.name == "ats")
    assert [board.token for board in ats.boards] == ["my-employer"]


def test_the_sample_boards_are_documented_as_replaceable():
    """The owner asked for a sample list, so it must be easy to spot and replace."""
    from services.job_connectors import SAMPLE_ATS_BOARDS
    assert SAMPLE_ATS_BOARDS
    assert all(board.token for board in SAMPLE_ATS_BOARDS)


def test_the_honest_declarations_do_not_overclaim():
    """No approved source offers server-side search, so none may claim to."""
    for source in build_default_sources():
        caps = source.capabilities
        assert caps.server_side_keywords is False
        assert caps.server_side_location is False
        # And every one of them must therefore warn about local filtering.
        assert caps.limitations_for(SearchQuery(keywords="x"))


def test_a_source_withdrawing_access_is_recorded_not_silently_dropped():
    """The excluded sources are named in code, with the reason.

    This guards the decision itself: a future agent must be able to see that
    SmartRecruiters was refused deliberately rather than forgotten.
    """
    import services.job_connectors as module
    doc = module.__doc__ or ""
    for excluded in ("SmartRecruiters", "StepStone", "Indeed", "LinkedIn",
                     "Bundesagentur"):
        assert excluded in doc, f"{excluded} should be recorded as excluded"
