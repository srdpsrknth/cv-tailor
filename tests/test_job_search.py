"""Tests for the job-search service and the ``cvtailor jobs`` command (item 7).

Offline. The connectors are replaced with a fake source, so these tests exercise
the wiring -- profile resolution, dedupe-before-rank, failure isolation, the sweep
record -- without any network dependency.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cli.context import Console
from cli.main import build_parser, main
from models.job import Job, JobField, JobSource, JobSourceError, SearchQuery
from services.job_search import (
    SearchOutcome,
    collect_jobs,
    load_sweep,
    save_sweep,
    search_jobs,
    summarise,
    sweep_path,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def make_job(title="Data Engineer", company="Acme GmbH", source="fake", source_id="1",
             country="DE", city="Berlin", url="https://example.test/1",
             description="We use dbt.", posted_at=None) -> Job:
    return Job(source=source, source_id=source_id, url=url, title=title, company=company,
               description=description, location_raw=city,
               country=JobField.structured(country) if country else JobField.absent(),
               city=JobField.structured(city) if city else JobField.absent(),
               posted_at=posted_at)


class FakeSource(JobSource):
    """A connector that returns fixed jobs, so tests need no network."""

    name = "fake"

    def __init__(self, jobs, error=None, name="fake"):
        self._jobs = jobs
        self._error = error
        self.name = name

    def search(self, query):
        if self._error:
            raise self._error
        return list(self._jobs)[: query.limit]


class FakeRules:
    home_countries = ["germany", "de"]


class FakeLanguage:
    def __init__(self, name):
        self.name = name
        self.proficiency = "Fluent"


class FakeProfile:
    skills = {"core": ["Advanced SQL", "dbt"]}
    languages = [FakeLanguage("English")]
    rules = FakeRules()


# --- collect_jobs: one broken source must not break the run ------------------------------

def test_a_failing_source_is_recorded_and_the_rest_still_run():
    """ADR 0008: a withdrawn source affects only its own connector."""
    jobs, failures, _notes, consulted = collect_jobs(
        [FakeSource([make_job()], name="good"),
         FakeSource([], error=JobSourceError("bad", "timed out"), name="bad")],
        SearchQuery(),
    )
    assert len(jobs) == 1
    assert failures == {"bad": "timed out"}
    assert consulted == ["good", "bad"]


def test_an_unexpected_exception_from_a_source_is_also_isolated():
    """A connector bug must not take down the search either."""
    jobs, failures, _notes, _consulted = collect_jobs(
        [FakeSource([], error=ValueError("boom"), name="bad")], SearchQuery())
    assert jobs == []
    assert "ValueError" in failures["bad"]


def test_source_limitations_are_reported_as_notes():
    _jobs, _failures, notes, _consulted = collect_jobs(
        [FakeSource([make_job()])], SearchQuery(keywords="data"))
    assert notes and "applied locally" in notes[0]


def test_no_sources_yields_nothing_without_error():
    jobs, failures, notes, consulted = collect_jobs([], SearchQuery())
    assert jobs == [] and failures == {} and notes == [] and consulted == []


# --- search_jobs ---------------------------------------------------------------------------

def test_search_deduplicates_before_ranking():
    """Ranking duplicates would let one vacancy occupy several positions."""
    outcome = search_jobs(
        [FakeSource([make_job(source="a", source_id="1"),
                     make_job(source="b", source_id="2")])],
        FakeProfile(), SearchQuery(), now=NOW,
    )
    assert outcome.jobs_read == 2
    assert len(outcome.results) == 1


def test_search_ranks_best_first():
    strong = make_job(title="Data Engineer", source_id="s", url="https://x.test/s")
    weak = make_job(title="Data Scientist", source_id="w", url="https://x.test/w")
    outcome = search_jobs([FakeSource([weak, strong])], FakeProfile(),
                          SearchQuery(keywords="data engineer"), now=NOW)
    assert outcome.results[0].job.source_id == "s"


def test_search_excludes_keyword_mismatches():
    outcome = search_jobs(
        [FakeSource([make_job(title="Sales Manager")])], FakeProfile(),
        SearchQuery(keywords="data engineer"), now=NOW)
    assert outcome.results == []


def test_search_reports_source_failures_without_losing_good_results():
    outcome = search_jobs(
        [FakeSource([make_job()], name="good"),
         FakeSource([], error=JobSourceError("bad", "HTTP 500"), name="bad")],
        FakeProfile(), SearchQuery(), now=NOW)
    assert len(outcome.results) == 1
    assert outcome.failures == {"bad": "HTTP 500"}


def test_search_output_serialises_to_json():
    outcome = search_jobs([FakeSource([make_job()])], FakeProfile(), SearchQuery(), now=NOW)
    payload = json.loads(json.dumps(outcome.as_dict()))
    assert payload["jobs_read"] == 1
    assert payload["results"][0]["job"]["title"] == "Data Engineer"
    assert payload["dedupe"]["jobs_out"] == 1


def test_search_prefers_the_profiles_own_skills():
    """Preferences come from the profile, not from a hardcoded guess."""
    outcome = search_jobs([FakeSource([make_job(description="We use dbt daily.")])],
                          FakeProfile(), SearchQuery(), now=NOW)
    reasons = [item.reason.value for item in outcome.results[0].evidence]
    assert "skill_in_description" in reasons


def test_explicit_preferences_override_the_profile():
    outcome = search_jobs(
        [FakeSource([make_job(title="Rust Developer", description="Rust.")])],
        FakeProfile(), SearchQuery(),
        preferences=__import__("services.job_match", fromlist=["MatchPreferences"]
                               ).MatchPreferences(skills=("Rust",)),
        now=NOW)
    assert outcome.results


# --- the sweep record ----------------------------------------------------------------------

def test_the_sweep_path_carries_the_candidate_segment(tmp_path):
    """ADR 0003: one candidate's activity is never filed under another's id."""
    path = sweep_path(tmp_path, "analyst_a")
    assert path.parent.name == "analyst_a"
    assert path.name == "sweep.json"


def test_the_sweep_path_fails_closed_on_a_missing_id(tmp_path):
    from services.profile_store import InvalidProfileIdError

    with pytest.raises(InvalidProfileIdError):
        sweep_path(tmp_path, None)


def test_the_sweep_path_rejects_traversal(tmp_path):
    from services.profile_store import InvalidProfileIdError

    with pytest.raises(InvalidProfileIdError):
        sweep_path(tmp_path, "../etc")


def test_a_missing_sweep_record_is_empty_not_an_error(tmp_path):
    assert load_sweep(tmp_path, "analyst_a").seen == {}


def test_a_corrupt_sweep_record_degrades_to_empty(tmp_path):
    """A corrupt file must cost one sweep of accuracy, not fail the search."""
    path = sweep_path(tmp_path, "analyst_a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_sweep(tmp_path, "analyst_a").seen == {}


def test_the_sweep_record_round_trips_on_disk(tmp_path):
    outcome = search_jobs([FakeSource([make_job()])], FakeProfile(), SearchQuery(),
                          store_root=tmp_path, profile_id="analyst_a", now=NOW)
    assert outcome.jobs_read == 1
    reloaded = load_sweep(tmp_path, "analyst_a")
    assert "fake:1" in reloaded.seen


def test_a_disappeared_job_is_dropped_from_the_next_search(tmp_path):
    """The observed-expiry behaviour, end to end through the service."""
    search_jobs([FakeSource([make_job()])], FakeProfile(), SearchQuery(),
                store_root=tmp_path, profile_id="analyst_a", now=NOW)
    later = NOW + timedelta(days=3)
    outcome = search_jobs([FakeSource([])], FakeProfile(), SearchQuery(),
                          store_root=tmp_path, profile_id="analyst_a", now=later)
    assert outcome.results == []
    assert any(v.status.value == "disappeared" for v in outcome.expiry)


def test_an_unswept_source_does_not_expire_its_jobs(tmp_path):
    """Disabling a source must not expire everything it returned."""
    search_jobs([FakeSource([make_job()], name="a")], FakeProfile(), SearchQuery(),
                store_root=tmp_path, profile_id="analyst_a", now=NOW)
    outcome = search_jobs([FakeSource([make_job()], name="b")], FakeProfile(),
                          SearchQuery(), store_root=tmp_path, profile_id="analyst_a",
                          now=NOW + timedelta(days=3))
    verdict = next(v for v in outcome.expiry if v.job_key == "fake:1")
    assert verdict.status.value == "active"


def test_the_sweep_record_is_not_written_without_a_profile_id(tmp_path):
    search_jobs([FakeSource([make_job()])], FakeProfile(), SearchQuery(), now=NOW)
    assert not (tmp_path / "jobs").exists()


def test_persistence_can_be_disabled(tmp_path):
    search_jobs([FakeSource([make_job()])], FakeProfile(), SearchQuery(),
                store_root=tmp_path, profile_id="analyst_a", persist_sweep=False, now=NOW)
    assert load_sweep(tmp_path, "analyst_a").seen == {}


# --- the summary ----------------------------------------------------------------------------

def test_the_summary_reports_failures():
    outcome = SearchOutcome(query=SearchQuery(), failures={"bad": "HTTP 500"})
    assert "bad" in summarise(outcome) and "HTTP 500" in summarise(outcome)


def test_the_summary_mentions_uncertain_jobs():
    from services.job_match import Eligibility, MatchResult

    outcome = SearchOutcome(query=SearchQuery(), results=[
        MatchResult(job=make_job(), eligibility=Eligibility.UNCERTAIN)])
    assert "check" in summarise(outcome).lower()


def test_the_summary_handles_an_empty_outcome():
    assert "No jobs were read" in summarise(SearchOutcome(query=SearchQuery()))


# --- CLI wiring ---------------------------------------------------------------------------

def test_the_jobs_command_is_registered():
    parser = build_parser()
    args = parser.parse_args(["jobs", "search", "--keywords", "data"])
    assert args.command == "jobs"
    assert args.jobs_action == "search"
    assert args.keywords == "data"


def test_the_jobs_action_defaults_to_search():
    args = build_parser().parse_args(["jobs"])
    assert args.command == "jobs"


def test_the_search_command_accepts_its_every_documented_option():
    args = build_parser().parse_args([
        "jobs", "search", "--keywords", "sql", "--country", "DE", "--city", "Berlin",
        "--remote", "--limit", "5", "--max-requests", "9", "--only", "softgarden",
        "--ats", "lever:acme:Acme", "--softgarden-tenant", "t1",
        "--personio-tenant", "t2",
    ])
    assert args.remote is True
    assert args.limit == 5
    assert args.max_requests == 9
    assert args.only_source == ["softgarden"]
    assert args.ats == ["lever:acme:Acme"]


def test_sources_is_available_as_a_subcommand():
    args = build_parser().parse_args(["jobs", "sources"])
    assert args.jobs_action == "sources"


def test_the_guided_menu_mentions_the_new_command(capsys):
    assert main([]) == 0
    assert "jobs search" in capsys.readouterr().out


def test_json_output_survives_a_non_ascii_console(capsys):
    """Regression: a live --json search crashed on an emoji in a job description.

    Job postings routinely contain emoji and typographic quotes, and a Windows
    console's default charmap codepage cannot encode them. --json exists for
    scripting, so it must not fail on the console's codepage.
    """
    Console(as_json=True).json({"title": "Senior Engineer \U0001f44b",
                                "note": "caf\u00e9 \u2014 “quoted”"})
    printed = capsys.readouterr().out
    # It must still parse, and the original characters must round-trip.
    parsed = json.loads(printed)
    assert parsed["title"] == "Senior Engineer \U0001f44b"
    assert parsed["note"] == "caf\u00e9 \u2014 “quoted”"


def test_json_output_is_pure_ascii_so_no_codepage_can_reject_it(capsys):
    Console(as_json=True).json({"emoji": "\U0001f44b"})
    printed = capsys.readouterr().out
    assert printed.isascii()


def test_an_unknown_jobs_action_is_a_usage_error():
    """argparse owns this, raising SystemExit as it does for every subcommand."""
    with pytest.raises(SystemExit) as exit_info:
        main(["jobs", "nonsense"])
    assert exit_info.value.code == 2


def test_the_ats_option_requires_a_platform_and_token(tmp_path, capsys):
    """A malformed --ats must fail with guidance, not a stack trace."""
    store = tmp_path / "store"
    (store / "profiles" / "analyst_a").mkdir(parents=True)
    (store / "profiles" / "analyst_a" / "profile.yaml").write_text(
        Path("tests/fixtures/profiles/synthetic_analyst.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    code = main(["--store", str(store), "--profile-id", "analyst_a",
                 "jobs", "search", "--ats", "justatoken"])
    assert code == 2
    assert "platform:token" in capsys.readouterr().err


def test_an_unknown_source_name_is_a_usage_error(tmp_path, capsys):
    store = tmp_path / "store"
    (store / "profiles" / "analyst_a").mkdir(parents=True)
    (store / "profiles" / "analyst_a" / "profile.yaml").write_text(
        Path("tests/fixtures/profiles/synthetic_analyst.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    code = main(["--store", str(store), "--profile-id", "analyst_a",
                 "jobs", "search", "--only", "linkedin"])
    assert code == 2
    assert "No known source" in capsys.readouterr().err


def test_the_jobs_command_requires_a_profile(tmp_path, capsys):
    """Fail closed (ADR 0003): there is no default profile.

    An empty store must not produce a search. Which exit code appears depends on
    whether a profile id is configured in the environment or .env: with none, the
    command is a usage error (2); with one that the store does not know, it is a
    not-found failure (1). Both are refusals, and this asserts the refusal rather
    than one particular code, because the configured id on this machine comes from
    the repository's own .env and not from the environment variable alone.
    """
    store = tmp_path / "store"
    (store / "profiles").mkdir(parents=True)
    code = main(["--store", str(store), "jobs", "search"])
    assert code != 0
    assert "No profile" in capsys.readouterr().err
