"""Tests for the Job model and the JobSource contract (Phase 4, item 2).

Fully offline: this module is pure data and pure rules, so these tests need no
fixture server and make no network call. That is the point of keeping the model
free of transport concerns.

The behavioural claims under test are the ones that came out of the ADR 0008 §1
source research, where the real payloads disagreed with each other:

* a *published* country and an *inferred* one must not be the same kind of fact;
* a free-text city name must never silently become a country;
* "the source did not say" must be distinct from "the source said on-site".
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.job import (
    DACH_COUNTRIES,
    FieldSource,
    Job,
    JobField,
    JobSource,
    JobSourceError,
    Remote,
    SearchQuery,
    SourceCapabilities,
    normalise_country,
    parse_iso_datetime,
    user_agent,
)


def make_job(**overrides) -> Job:
    """A minimal valid job, overridden per test."""
    base = dict(source="softgarden", source_id="62349294", url="https://example.test/j/1",
                title="Senior Account Executive")
    base.update(overrides)
    return Job(**base)


# --- JobField: value and provenance cannot disagree -------------------------------------

def test_a_field_with_a_value_cannot_claim_to_be_absent():
    """ABSENT means 'no value'. Allowing both would make provenance meaningless."""
    with pytest.raises(ValueError, match="cannot have source=ABSENT"):
        JobField(value="DE", source=FieldSource.ABSENT)


def test_an_absent_field_normalises_a_blank_value_to_none():
    assert JobField(value="   ").value is None
    assert JobField(value="").source is FieldSource.ABSENT


def test_absent_is_forced_when_the_value_is_none():
    """The reverse direction: no value must mean ABSENT, whatever was passed."""
    assert JobField(value=None, source=FieldSource.STRUCTURED).source is FieldSource.ABSENT


@pytest.mark.parametrize("factory,expected", [
    ("structured", FieldSource.STRUCTURED),
    ("parsed", FieldSource.PARSED),
    ("inferred", FieldSource.INFERRED),
])
def test_each_constructor_records_its_own_provenance(factory, expected):
    assert getattr(JobField, factory)("X").source is expected


def test_only_publisher_asserted_fields_count_as_verified():
    """The core distinction of the whole module."""
    assert JobField.structured("DE").is_verified is True
    assert JobField.parsed("DE").is_verified is True
    assert JobField.inferred("DE").is_verified is False
    assert JobField.absent().is_verified is False


def test_stronger_provenance_wins_a_merge_and_equal_strength_does_not():
    structured = JobField.structured("DE")
    inferred = JobField.inferred("AT")
    assert structured.preferred_over(inferred) is True
    assert inferred.preferred_over(structured) is False
    # Equal strength keeps the existing value, so a merge stays deterministic.
    assert structured.preferred_over(JobField.structured("AT")) is False


def test_absent_is_the_weakest_provenance():
    assert JobField.structured("x").preferred_over(JobField.absent()) is True
    assert JobField.absent().preferred_over(JobField.structured("x")) is False


# --- country handling: the rule that a guess must not become a fact ----------------------

@pytest.mark.parametrize("raw,expected", [
    ("DE", "DE"), ("de", "DE"), ("Germany", "DE"), ("deutschland", "DE"),
    ("AT", "AT"), ("Austria", "AT"), ("Österreich", "AT"),
    ("CH", "CH"), ("Switzerland", "CH"), ("Schweiz", "CH"),
])
def test_country_aliases_map_to_iso_codes(raw, expected):
    assert normalise_country(raw) == expected


def test_an_unrecognised_country_is_none_rather_than_echoed_back():
    """Returning the input would put a non-country in a field named country."""
    assert normalise_country("Atlantis") is None
    assert normalise_country("") is None
    assert normalise_country(None) is None


def test_a_free_text_city_never_becomes_a_country():
    """The Arbeitnow case: 'Munich HQ' is a location, not a country assertion."""
    job = make_job(location_raw="Munich HQ")
    assert job.country.value is None
    assert job.country.source is FieldSource.ABSENT
    assert job.is_dach is False


def test_a_structured_country_does_make_a_job_dach():
    job = make_job(country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    assert job.country.value == "DE"
    assert job.is_dach is True


def test_an_inferred_country_does_not_make_a_job_dach():
    """DACH-first must not be driven by our own guess."""
    job = make_job(country=JobField.inferred("DE", note="city looked German"))
    assert job.country.value == "DE"
    assert job.country.is_verified is False
    assert job.is_dach is False


def test_dach_countries_are_the_three_implemented_markets():
    assert set(DACH_COUNTRIES) == {"DE", "AT", "CH"}


def test_a_non_dach_verified_country_is_not_dach():
    job = make_job(country=JobField.structured("US"))
    assert job.country.is_verified is True
    assert job.is_dach is False


# --- date parsing: the four formats the verified sources actually publish ----------------

def test_epoch_seconds_are_read_as_seconds():
    """Arbeitnow publishes seconds."""
    parsed = parse_iso_datetime(1793439622)
    assert parsed == datetime.fromtimestamp(1793439622, tz=timezone.utc)


def test_epoch_milliseconds_are_detected_and_read_as_milliseconds():
    """Lever publishes milliseconds; the same instant must parse identically."""
    seconds = 1788199939
    from_seconds = parse_iso_datetime(seconds)
    from_millis = parse_iso_datetime(seconds * 1000)
    assert from_seconds == from_millis


def test_an_iso_string_with_an_offset_is_converted_to_utc():
    """softgarden publishes '2026-09-23T10:37:06.121+02:00'."""
    parsed = parse_iso_datetime("2026-09-23T10:37:06.121+02:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.hour == 8  # 10:37+02:00 is 08:37Z


def test_a_z_suffixed_iso_string_parses():
    """Ashby publishes 'Z'-suffixed timestamps."""
    parsed = parse_iso_datetime("2026-10-01T00:00:00Z")
    assert parsed == datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_the_same_instant_in_two_offsets_parses_equal():
    """Regression: fromisoformat keeps the source offset, so it must be converted.

    Two sources publishing one instant as '+02:00' and 'Z' have to compare equal,
    or deduplication and expiry windows would treat them as different times.
    """
    local = parse_iso_datetime("2026-09-23T10:37:06.121+02:00")
    utc = parse_iso_datetime("2026-09-23T08:37:06.121Z")
    assert local == utc
    assert local.utcoffset().total_seconds() == 0


def test_a_naive_iso_string_is_treated_as_utc():
    parsed = parse_iso_datetime("2026-10-01T12:00:00")
    assert parsed == datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["", None, "not a date", "23/09/2026", [], {}])
def test_an_unparseable_date_is_none_rather_than_guessed(bad):
    """A wrong date is worse than no date: it would corrupt expiry detection."""
    assert parse_iso_datetime(bad) is None


def test_a_datetime_object_is_returned_as_utc():
    naive = datetime(2026, 10, 1, 12, 0)
    assert parse_iso_datetime(naive).tzinfo is timezone.utc


# --- remote resolution: 'unknown' is not 'onsite' ---------------------------------------

@pytest.mark.parametrize("flag,expected", [
    ("true", Remote.REMOTE), ("True", Remote.REMOTE), ("1", Remote.REMOTE),
    ("false", Remote.ONSITE), ("0", Remote.ONSITE),
])
def test_a_structured_remote_flag_is_honoured(flag, expected):
    job = make_job(remote_flag=JobField.structured(flag))
    assert job.resolved_remote() is expected


def test_a_source_that_says_nothing_reports_unknown_not_onsite():
    """Claiming on-site from silence would be inventing a fact."""
    assert make_job().resolved_remote() is Remote.UNKNOWN


def test_remote_is_inferred_from_the_location_text_when_no_flag_exists():
    assert make_job(location_raw="Berlin (Remote)").resolved_remote() is Remote.REMOTE
    assert make_job(location_raw="Homeoffice").resolved_remote() is Remote.REMOTE


def test_hybrid_is_recognised_from_text():
    assert make_job(location_raw="Berlin (Hybrid)").resolved_remote() is Remote.HYBRID


def test_an_explicit_false_flag_beats_contradictory_text():
    """The source's own structured claim outranks our reading of its prose."""
    job = make_job(remote_flag=JobField.structured("false"), location_raw="Remote team")
    assert job.resolved_remote() is Remote.ONSITE


# --- verified vs inferred field reporting -----------------------------------------------

def test_verified_and_inferred_fields_are_reported_separately():
    job = make_job(
        country=JobField.structured("DE"),
        city=JobField.structured("Berlin"),
        region=JobField.inferred("Berlin", note="copied from city"),
    )
    assert job.verified_fields() == {"country": "DE", "city": "Berlin"}
    inferred = job.inferred_fields()
    assert set(inferred) == {"region"}
    assert inferred["region"]["value"] == "Berlin"
    assert inferred["region"]["note"] == "copied from city"


def test_a_field_cannot_appear_in_both_reports():
    job = make_job(country=JobField.structured("DE"), city=JobField.inferred("Berlin"))
    assert set(job.verified_fields()).isdisjoint(job.inferred_fields())


# --- identity and construction rules ----------------------------------------------------

def test_the_natural_key_is_source_plus_source_id():
    assert make_job().key == "softgarden:62349294"


def test_a_job_without_a_title_is_rejected():
    with pytest.raises(ValueError, match="has no title"):
        make_job(title="   ")


def test_a_job_without_a_source_id_is_rejected():
    with pytest.raises(ValueError, match="requires a source_id"):
        make_job(source_id="")


def test_a_job_without_a_source_is_rejected():
    with pytest.raises(ValueError, match="requires a source"):
        make_job(source="  ")


def test_whitespace_in_text_fields_is_collapsed():
    job = make_job(title="  Senior   Account\n Executive ", company="  softgarden  GmbH ")
    assert job.title == "Senior Account Executive"
    assert job.company == "softgarden GmbH"


def test_as_dict_keeps_provenance_visible():
    job = make_job(country=JobField.structured("DE"), city=JobField.structured("Berlin"),
                   remote_flag=JobField.structured("true"))
    payload = job.as_dict()
    assert payload["country"] == {"value": "DE", "source": "structured", "note": None}
    assert payload["remote"] == "remote"
    assert payload["is_dach"] is True
    assert payload["key"] == "softgarden:62349294"


# --- content fingerprint: for dedupe across sources -------------------------------------

def test_identical_vacancies_from_different_sources_share_a_fingerprint():
    """The dedupe premise: the same vacancy must be recognisable across boards."""
    first = make_job(source="softgarden", source_id="1", company="Acme GmbH",
                     title="Data Engineer", country=JobField.structured("DE"),
                     city=JobField.structured("Berlin"))
    second = make_job(source="lever", source_id="abc", company="Acme GmbH",
                      title="Data Engineer", country=JobField.structured("DE"),
                      city=JobField.structured("Berlin"))
    assert first.content_fingerprint() == second.content_fingerprint()


@pytest.mark.parametrize("variant", [
    "Data Engineer (m/w/d)", "Data Engineer - Full Time", "data engineer",
    "Data  Engineer!", "Data Engineer (all genders)",
])
def test_boilerplate_and_punctuation_do_not_change_the_fingerprint(variant):
    """Boilerplate suffix differences are the common real-world case."""
    base = make_job(title="Data Engineer", company="Acme GmbH",
                    country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    other = make_job(title=variant, company="Acme GmbH",
                     country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    assert base.content_fingerprint() == other.content_fingerprint()


def test_genuinely_different_postings_do_not_collide():
    base = make_job(title="Data Engineer", company="Acme GmbH",
                    country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    other = make_job(title="Data Scientist", company="Acme GmbH",
                     country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    assert base.content_fingerprint() != other.content_fingerprint()


def test_the_same_title_at_different_companies_does_not_collide():
    base = make_job(title="Data Engineer", company="Acme GmbH",
                    country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    other = make_job(title="Data Engineer", company="Globex AG",
                     country=JobField.structured("DE"), city=JobField.structured("Berlin"))
    assert base.content_fingerprint() != other.content_fingerprint()


# --- SearchQuery ------------------------------------------------------------------------

def test_a_query_country_is_normalised_to_a_code():
    assert SearchQuery(country="Germany").country == "DE"


def test_an_unknown_query_country_becomes_none_rather_than_a_bad_filter():
    assert SearchQuery(country="Atlantis").country is None


def test_a_limit_below_one_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        SearchQuery(limit=0)


def test_describe_is_human_readable():
    described = SearchQuery(keywords="analyst", country="Germany", remote=True).describe()
    assert "analyst" in described and "DE" in described and "remote=True" in described


# --- SourceCapabilities: honest warnings, not silent filtering ---------------------------

def test_a_source_without_keyword_search_warns_that_filtering_was_local():
    caps = SourceCapabilities(server_side_keywords=False)
    notes = caps.limitations_for(SearchQuery(keywords="analyst"))
    assert len(notes) == 1
    assert "applied locally" in notes[0]


def test_a_capable_source_produces_no_warnings():
    caps = SourceCapabilities(server_side_keywords=True, server_side_location=True,
                              server_side_remote=True)
    query = SearchQuery(keywords="analyst", city="Berlin", remote=True)
    assert caps.limitations_for(query) == []


def test_each_unhonourable_constraint_is_reported_separately():
    caps = SourceCapabilities()
    notes = caps.limitations_for(SearchQuery(keywords="x", city="Berlin", remote=True))
    assert len(notes) == 3


def test_no_constraints_means_no_warnings():
    assert SourceCapabilities().limitations_for(SearchQuery()) == []


# --- JobSource contract -----------------------------------------------------------------

def test_the_base_contract_is_abstract():
    with pytest.raises(NotImplementedError):
        JobSource().search(SearchQuery())


def test_the_base_class_reports_it_cannot_fetch_one():
    assert JobSource().can_fetch_one is False
    with pytest.raises(NotImplementedError):
        JobSource().fetch_one("123")


def test_a_connector_that_implements_fetch_one_advertises_it():
    class Connector(JobSource):
        name = "test"

        def search(self, query):
            return []

        def fetch_one(self, source_id):
            return None

    assert Connector().can_fetch_one is True


def test_a_source_error_names_the_source_that_failed():
    """A broken source must be attributable, so it degrades alone (ADR 0008)."""
    error = JobSourceError("softgarden", "timed out", retryable=True)
    assert error.source == "softgarden"
    assert error.retryable is True
    assert "softgarden" in str(error)


def test_the_user_agent_identifies_the_tool_honestly():
    """ADR 0008 §3: a connector must identify itself."""
    agent = user_agent()
    assert agent.startswith("cv-tailor/")
    assert "github.com" in agent
    # It must not leak a personal address into a public repository.
    assert "@" not in agent.split("(+")[0]
