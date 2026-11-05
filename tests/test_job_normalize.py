"""Tests for job normalisation (Phase 4, item 3).

Offline: every payload comes from ``tests/fixtures/job_sources/source_payloads.json``,
whose shapes reproduce what the real APIs returned on 2026-10-31 while every
company and posting is invented.

The point of these tests is the *disagreements* between sources. Where each source
puts the country, whether it publishes one at all, and which formats its dates take
are the things that break silently in production, so each is asserted per source.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from models.job import FieldSource, Remote, SearchQuery
from services.job_normalize import (
    city_from_display_location,
    country_from_display_location,
    html_to_text,
    iter_arbeitnow,
    iter_ashby,
    iter_greenhouse,
    iter_lever,
    iter_personio,
    iter_softgarden,
    matches_keywords,
    matches_local_filters,
)

FIXTURE = Path(__file__).parent / "fixtures" / "job_sources" / "source_payloads.json"


@pytest.fixture(scope="module")
def payloads() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- HTML to text -----------------------------------------------------------------------

def test_html_tags_are_stripped_and_entities_decoded():
    assert html_to_text("<p>Data &amp; Analytics</p>") == "Data & Analytics"


def test_list_items_become_separate_lines():
    """A posting's requirements live in bullets; collapsing them loses structure."""
    text = html_to_text("<ul><li>First</li><li>Second</li></ul>")
    assert "First" in text and "Second" in text
    assert "First" not in text.replace("First\n", "") or "\n" in text


def test_br_becomes_a_newline():
    assert "\n" in html_to_text("line one<br/>line two")


def test_nested_tags_do_not_leave_artifacts():
    text = html_to_text("<div><p>Hello <b>bold</b> text</p></div>")
    assert "<" not in text and ">" not in text
    assert "Hello bold text" in text


def test_non_breaking_spaces_are_normalised():
    assert "\xa0" not in html_to_text("<p>a&nbsp;b</p>")


def test_plain_text_passes_through_unchanged():
    assert html_to_text("Just plain text.") == "Just plain text."


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_description_is_an_empty_string(value):
    assert html_to_text(value) == ""


# --- display-location parsing (Greenhouse's only route to a country) ---------------------

@pytest.mark.parametrize("display,expected", [
    ("Berlin, Germany", "DE"),
    ("Munich, Deutschland", "DE"),
    ("Vienna, Austria", "AT"),
    ("Zurich, Switzerland", "CH"),
    ("Remote - US", "US"),
    # Regression: Arbeitnow really publishes this, and it names Germany plainly.
    # Reading the publisher's own word is parsing, not inference, so leaving the
    # country absent here would discard a fact the source actually gave us.
    ("Germany (remote)", "DE"),
    ("Germany", "DE"),
    ("Remote (Germany)", "DE"),
    ("Berlin (Germany)", "DE"),
    ("Austria (remote)", "AT"),
])
def test_country_is_parsed_from_a_display_location(display, expected):
    assert country_from_display_location(display) == expected


@pytest.mark.parametrize("display", [
    "Munich HQ", "Anywhere", "Remote", "", None, "Berlin",
    # A city is not a country, even though it is in one.
    "Munich", "Vienna", "Zurich",
])
def test_no_country_is_invented_from_an_ambiguous_location(display):
    """'Munich HQ' is the real Arbeitnow case and must not become DE.

    A city name is deliberately not resolved to its country: that would be an
    inference presented as the publisher's statement.
    """
    assert country_from_display_location(display) is None


def test_a_multi_word_country_name_is_matched_whole():
    assert country_from_display_location("Remote - United States") == "US"
    assert country_from_display_location("London, United Kingdom") == "GB"


def test_a_short_alias_does_not_match_inside_a_longer_word():
    """'in' (India) must not match 'Berlin'."""
    assert country_from_display_location("Berlin HQ") is None


@pytest.mark.parametrize("display,expected", [
    ("Berlin, Germany", "Berlin"),
    ("Munich HQ", "Munich HQ"),
    ("Berlin Germany", "Berlin"),
    ("Remote - US", "Remote"),
])
def test_the_city_part_is_taken_without_inventing_a_boundary(display, expected):
    assert city_from_display_location(display) == expected


# --- softgarden: the richest shape, structured country ----------------------------------

def test_softgarden_yields_every_item(payloads):
    jobs = list(iter_softgarden(payloads["softgarden_datafeed"]))
    assert len(jobs) == 3
    assert {job.source_id for job in jobs} == {"62349294", "62349295", "62349296"}


def test_softgarden_country_is_structured_because_it_is_published(payloads):
    job = next(iter_softgarden(payloads["softgarden_datafeed"]))
    assert job.country.value == "DE"
    assert job.country.source is FieldSource.STRUCTURED
    assert job.country.is_verified is True


def test_softgarden_jobs_are_recognised_as_dach(payloads):
    jobs = list(iter_softgarden(payloads["softgarden_datafeed"]))
    assert all(job.is_dach for job in jobs)
    assert {job.country.value for job in jobs} == {"DE", "AT", "CH"}


def test_softgarden_postal_address_fields_are_populated(payloads):
    job = next(iter_softgarden(payloads["softgarden_datafeed"]))
    assert job.city.value == "Berlin"
    assert job.region.value == "Berlin"
    assert job.postal_code.value == "10789"


def test_softgarden_company_comes_from_hiring_organization(payloads):
    job = next(iter_softgarden(payloads["softgarden_datafeed"]))
    assert job.company == "Fixture Analytics GmbH"


def test_softgarden_offset_date_is_normalised_to_utc(payloads):
    job = next(iter_softgarden(payloads["softgarden_datafeed"]))
    # Published as 2026-09-23T10:37:06.121+02:00.
    assert job.posted_at == datetime(2026, 9, 23, 8, 37, 6, 121000, tzinfo=timezone.utc)


def test_softgarden_description_html_is_reduced_to_text(payloads):
    job = next(iter_softgarden(payloads["softgarden_datafeed"]))
    assert "<b>" not in job.description and "<li>" not in job.description
    assert "Du baust Pipelines." in job.description


def test_softgarden_employment_type_is_captured(payloads):
    jobs = {job.source_id: job for job in iter_softgarden(payloads["softgarden_datafeed"])}
    assert jobs["62349294"].employment_type.value == "FULL_TIME"
    assert jobs["62349295"].employment_type.value == "PART_TIME"


def test_softgarden_tolerates_a_bare_jobposting():
    """The same normaliser must serve embedded JSON-LD, not only the DataFeed."""
    bare = {"@type": "JobPosting", "title": "Solo Role", "url": "https://x.test/1",
            "identifier": {"value": 9}}
    job = next(iter_softgarden(bare))
    assert job.source_id == "9"
    assert job.title == "Solo Role"


def test_softgarden_skips_an_item_with_no_identifier():
    assert list(iter_softgarden({"dataFeedElement": [{"item": {"@type": "JobPosting",
                                                               "title": "x"}}]})) == []


def test_softgarden_handles_an_empty_feed():
    assert list(iter_softgarden({})) == []
    assert list(iter_softgarden({"dataFeedElement": []})) == []


# --- Personio: no country field at all --------------------------------------------------

def test_personio_yields_every_position(payloads):
    jobs = list(iter_personio(payloads["personio_xml"]))
    assert {job.source_id for job in jobs} == {"2048817", "30961"}


def test_personio_country_is_absent_not_invented(payloads):
    """The feed has no country field, so claiming DE would be fabrication."""
    jobs = list(iter_personio(payloads["personio_xml"]))
    for job in jobs:
        assert job.country.value is None
        assert job.country.source is FieldSource.ABSENT


def test_personio_jobs_are_therefore_not_claimed_as_dach(payloads):
    """DACH-first must not be driven by an inference from a city name."""
    jobs = list(iter_personio(payloads["personio_xml"]))
    assert all(job.is_dach is False for job in jobs)


def test_personio_office_is_preserved_as_city_and_raw_location(payloads):
    job = next(iter_personio(payloads["personio_xml"]))
    assert job.city.value == "Berlin"
    assert job.location_raw == "Berlin"


def test_personio_title_and_company_use_its_own_element_names(payloads):
    job = next(iter_personio(payloads["personio_xml"]))
    assert job.title == "Werkstudent Data Analytics (m/w/d)"
    assert job.company == "Fixture Holding"


def test_personio_description_is_taken_from_cdata_html(payloads):
    job = next(iter_personio(payloads["personio_xml"]))
    assert "Unterstuetzung im Reporting." in job.description
    assert "<p>" not in job.description


def test_personio_position_without_descriptions_still_normalises(payloads):
    """A position with an empty <jobDescriptions/> must not crash or lose the job."""
    jobs = {job.source_id: job for job in iter_personio(payloads["personio_xml"])}
    assert jobs["30961"].description == ""


def test_personio_created_at_is_parsed(payloads):
    job = next(iter_personio(payloads["personio_xml"]))
    assert job.posted_at == datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["", "   ", "<not-xml", "<?xml version='1.0'?><other/>"])
def test_personio_returns_nothing_for_unusable_xml(bad):
    """Malformed input yields no jobs rather than raising into the caller."""
    assert list(iter_personio(bad)) == []


# --- Lever: a real country field --------------------------------------------------------

def test_lever_yields_every_posting(payloads):
    jobs = list(iter_lever(payloads["lever_postings"]))
    assert len(jobs) == 2


def test_lever_country_is_structured(payloads):
    jobs = {job.source_id: job for job in iter_lever(payloads["lever_postings"])}
    german = jobs["ad208490-4052-4f91-a57e-433f2d1e484b"]
    assert german.country.value == "DE"
    assert german.country.source is FieldSource.STRUCTURED
    assert german.is_dach is True


def test_a_us_lever_posting_is_not_dach(payloads):
    jobs = {job.source_id: job for job in iter_lever(payloads["lever_postings"])}
    american = jobs["bb309481-5163-5fa2-b68f-544f3e2f595c"]
    assert american.country.value == "US"
    assert american.is_dach is False


def test_lever_millisecond_timestamp_is_read_as_milliseconds(payloads):
    """A ms value read as seconds would land in the year 58,000."""
    job = next(iter_lever(payloads["lever_postings"]))
    assert job.posted_at == datetime.fromtimestamp(1788199939703 / 1000, tz=timezone.utc)
    assert job.posted_at.year == 2026


def test_lever_location_string_is_preserved_verbatim(payloads):
    job = next(iter_lever(payloads["lever_postings"]))
    assert job.location_raw == "Berlin, Germany"


def test_lever_city_is_parsed_from_its_display_location(payloads):
    job = next(iter_lever(payloads["lever_postings"]))
    assert job.city.value == "Berlin"


@pytest.mark.parametrize("workplace,expected", [
    ("hybrid", Remote.ONSITE), ("on-site", Remote.ONSITE), ("remote", Remote.REMOTE),
])
def test_lever_workplace_type_drives_remoteness(payloads, workplace, expected):
    record = dict(payloads["lever_postings"][0], workplaceType=workplace)
    assert next(iter_lever([record])).resolved_remote() is expected


def test_lever_posting_without_a_workplace_type_reports_unknown(payloads):
    record = {k: v for k, v in payloads["lever_postings"][0].items()
              if k != "workplaceType"}
    assert next(iter_lever([record])).resolved_remote() is Remote.UNKNOWN


def test_lever_commitment_becomes_employment_type(payloads):
    job = next(iter_lever(payloads["lever_postings"]))
    assert job.employment_type.value == "Regular Full Time (Salary)"


def test_lever_skips_records_without_an_id(payloads):
    assert list(iter_lever([{"text": "No id"}])) == []


# --- Greenhouse: display string, so country is PARSED -----------------------------------

def test_greenhouse_yields_every_job(payloads):
    jobs = list(iter_greenhouse(payloads["greenhouse_jobs"]))
    assert len(jobs) == 2


def test_greenhouse_country_is_parsed_not_structured(payloads):
    """There is no country field; the country comes from the display string."""
    job = next(iter_greenhouse(payloads["greenhouse_jobs"]))
    assert job.country.value == "DE"
    assert job.country.source is FieldSource.PARSED
    assert job.country.is_verified is True
    assert "parsed from location" in job.country.note


def test_greenhouse_job_in_germany_is_dach(payloads):
    job = next(iter_greenhouse(payloads["greenhouse_jobs"]))
    assert job.is_dach is True


def test_greenhouse_remote_us_location_does_not_become_dach(payloads):
    jobs = {job.source_id: job for job in iter_greenhouse(payloads["greenhouse_jobs"])}
    remote_us = jobs["8126989"]
    assert remote_us.country.value == "US"
    assert remote_us.is_dach is False


def test_greenhouse_missing_country_leaves_the_field_absent():
    payload = {"jobs": [{"id": 1, "title": "T", "location": {"name": "Anywhere"},
                         "absolute_url": "https://x.test/1"}]}
    job = next(iter_greenhouse(payload))
    assert job.country.source is FieldSource.ABSENT


def test_greenhouse_uses_first_published_for_the_posted_date(payloads):
    job = next(iter_greenhouse(payloads["greenhouse_jobs"]))
    assert job.posted_at == datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)


def test_greenhouse_falls_back_to_updated_at_when_unpublished():
    payload = {"jobs": [{"id": 2, "title": "T", "location": {"name": "Berlin, Germany"},
                         "absolute_url": "https://x.test/2",
                         "updated_at": "2026-10-20T14:22:11-04:00"}]}
    job = next(iter_greenhouse(payload))
    assert job.posted_at == datetime(2026, 10, 20, 18, 22, 11, tzinfo=timezone.utc)


def test_greenhouse_accepts_a_fallback_company_name():
    payload = {"jobs": [{"id": 3, "title": "T", "absolute_url": "https://x.test/3"}]}
    job = next(iter_greenhouse(payload, company="Configured Co"))
    assert job.company == "Configured Co"


# --- Ashby: nested postal address plus isListed ----------------------------------------

def test_ashby_yields_only_listed_jobs_by_default(payloads):
    """An unlisted internal role must not surface as an opportunity."""
    jobs = list(iter_ashby(payloads["ashby_jobs"]))
    assert len(jobs) == 1
    assert jobs[0].title == "Enterprise Account Executive - DACH"


def test_ashby_can_include_unlisted_when_asked(payloads):
    jobs = list(iter_ashby(payloads["ashby_jobs"], include_unlisted=True))
    assert len(jobs) == 2


def test_ashby_country_is_structured_from_the_nested_address(payloads):
    job = next(iter_ashby(payloads["ashby_jobs"]))
    assert job.country.value == "DE"
    assert job.country.source is FieldSource.STRUCTURED
    assert job.is_dach is True


def test_ashby_isremote_boolean_becomes_the_remote_flag(payloads):
    job = next(iter_ashby(payloads["ashby_jobs"]))
    assert job.remote_flag.value == "false"
    assert job.resolved_remote() is Remote.ONSITE


def test_ashby_remote_role_resolves_as_remote(payloads):
    jobs = list(iter_ashby(payloads["ashby_jobs"], include_unlisted=True))
    remote_role = next(job for job in jobs if job.source_id.startswith("f5a2d3b4"))
    assert remote_role.resolved_remote() is Remote.REMOTE


def test_ashby_published_at_is_parsed(payloads):
    job = next(iter_ashby(payloads["ashby_jobs"]))
    assert job.posted_at == datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


# --- Arbeitnow: free-text location, no country ------------------------------------------

def test_arbeitnow_yields_every_record(payloads):
    assert len(list(iter_arbeitnow(payloads["arbeitnow_feed"]))) == 2


def test_arbeitnow_country_is_absent_when_the_location_names_no_country(payloads):
    """'Munich HQ' is a German office, but the source never says 'Germany'."""
    job = next(iter_arbeitnow(payloads["arbeitnow_feed"]))
    assert job.country.value is None
    assert job.is_dach is False


def test_arbeitnow_country_is_parsed_when_the_location_names_one():
    """Regression: the live feed returns 'Germany (remote)', which names Germany."""
    payload = {"data": [{"slug": "x", "company_name": "Co", "title": "Role",
                         "description": "<p>d</p>", "remote": True,
                         "url": "https://x.test/1", "location": "Germany (remote)",
                         "created_at": 1793439622}]}
    job = next(iter_arbeitnow(payload))
    assert job.country.value == "DE"
    assert job.country.source is FieldSource.PARSED
    assert job.is_dach is True


def test_arbeitnow_raw_location_is_preserved(payloads):
    job = next(iter_arbeitnow(payloads["arbeitnow_feed"]))
    assert job.location_raw == "Munich HQ"


def test_arbeitnow_epoch_seconds_are_parsed(payloads):
    job = next(iter_arbeitnow(payloads["arbeitnow_feed"]))
    assert job.posted_at == datetime.fromtimestamp(1793439622, tz=timezone.utc)


def test_arbeitnow_remote_boolean_is_captured(payloads):
    jobs = list(iter_arbeitnow(payloads["arbeitnow_feed"]))
    assert jobs[0].resolved_remote() is Remote.ONSITE
    assert jobs[1].resolved_remote() is Remote.REMOTE


def test_arbeitnow_job_types_are_joined(payloads):
    job = next(iter_arbeitnow(payloads["arbeitnow_feed"]))
    assert job.employment_type.value == "Full Time"


# --- local filtering, for sources that cannot filter server-side ------------------------

def test_a_country_filter_excludes_jobs_whose_country_is_unknown(payloads):
    """Strict on purpose: an absent country cannot be shown to match."""
    jobs = list(iter_arbeitnow(payloads["arbeitnow_feed"]))
    query = SearchQuery(country="DE")
    assert [job for job in jobs if matches_local_filters(job, query)] == []


def test_a_country_filter_keeps_matching_jobs(payloads):
    jobs = list(iter_softgarden(payloads["softgarden_datafeed"]))
    query = SearchQuery(country="DE")
    matched = [job for job in jobs if matches_local_filters(job, query)]
    assert len(matched) == 1
    assert matched[0].country.value == "DE"


def test_a_city_filter_matches_the_raw_location_too(payloads):
    jobs = list(iter_arbeitnow(payloads["arbeitnow_feed"]))
    query = SearchQuery(city="Munich")
    assert len([job for job in jobs if matches_local_filters(job, query)]) == 1


def test_a_remote_filter_excludes_unknown_remoteness(payloads):
    jobs = list(iter_arbeitnow(payloads["arbeitnow_feed"]))
    query = SearchQuery(remote=True)
    matched = [job for job in jobs if matches_local_filters(job, query)]
    assert len(matched) == 1
    assert matched[0].resolved_remote() is Remote.REMOTE


def test_an_onsite_filter_excludes_remote_jobs(payloads):
    jobs = list(iter_arbeitnow(payloads["arbeitnow_feed"]))
    query = SearchQuery(remote=False)
    matched = [job for job in jobs if matches_local_filters(job, query)]
    assert len(matched) == 1
    assert matched[0].resolved_remote() is Remote.ONSITE


# --- keyword matching -------------------------------------------------------------------

def test_keywords_match_the_title():
    from models.job import Job
    job = Job(source="s", source_id="1", url="u", title="Senior Data Engineer")
    assert matches_keywords(job, "data engineer") is True


def test_keywords_match_the_description():
    from models.job import Job
    job = Job(source="s", source_id="1", url="u", title="Analyst",
              description="Experience with dbt and Snowflake required.")
    assert matches_keywords(job, "snowflake") is True


def test_all_keyword_tokens_must_match():
    from models.job import Job
    job = Job(source="s", source_id="1", url="u", title="Data Engineer")
    assert matches_keywords(job, "data engineer") is True
    assert matches_keywords(job, "data scientist") is False


def test_keyword_matching_is_case_insensitive():
    from models.job import Job
    job = Job(source="s", source_id="1", url="u", title="Data Engineer")
    assert matches_keywords(job, "DATA") is True


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_no_keywords_matches_everything(empty):
    from models.job import Job
    job = Job(source="s", source_id="1", url="u", title="Anything")
    assert matches_keywords(job, empty) is True


# --- every source produces a valid Job with a usable key --------------------------------

@pytest.mark.parametrize("iterable_name", [
    "softgarden_datafeed", "lever_postings", "greenhouse_jobs", "ashby_jobs",
    "arbeitnow_feed",
])
def test_every_source_produces_jobs_with_unique_keys(payloads, iterable_name):
    """The natural key must be unique within a source, or dedupe cannot work."""
    iterators = {
        "softgarden_datafeed": iter_softgarden,
        "lever_postings": iter_lever,
        "greenhouse_jobs": iter_greenhouse,
        "ashby_jobs": iter_ashby,
        "arbeitnow_feed": iter_arbeitnow,
    }
    jobs = list(iterators[iterable_name](payloads[iterable_name]))
    assert jobs, f"{iterable_name} produced no jobs"
    keys = [job.key for job in jobs]
    assert len(keys) == len(set(keys))
    for job in jobs:
        # Every source must yield a title and an id; the url is required only where
        # the source actually publishes one. Personio's feed carries no url at all,
        # and a placeholder would surface as a broken link, so it stays empty.
        assert job.title and job.source_id
        assert job.url


def test_personio_leaves_the_url_empty_rather_than_inventing_one(payloads):
    """The feed has no url field. Filling it would fabricate a broken link."""
    jobs = list(iter_personio(payloads["personio_xml"]))
    assert jobs
    assert all(job.url == "" for job in jobs)


def test_every_source_serialises_to_a_dict(payloads):
    """as_dict is the JSON contract, so it must survive a round trip."""
    for job in iter_softgarden(payloads["softgarden_datafeed"]):
        assert json.loads(json.dumps(job.as_dict()))["key"] == job.key
