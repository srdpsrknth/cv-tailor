"""Tests for deterministic matching (Phase 4, item 5).

Offline and synthetic. Two properties carry most of the weight, and both come from
the roadmap's acceptance criterion ("explainable ... no invented scores"):

* **Every point traces to named evidence**, so a score can be re-derived by reading
  the result rather than trusted.
* **Hard eligibility is not a score.** A job the candidate cannot take must be
  excluded as impossible, not ranked low -- and a constraint the data cannot settle
  must be neither hidden nor silently allowed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.job import Job, JobField, Remote
from services.job_match import (
    Blocker,
    Eligibility,
    MatchPreferences,
    MatchResult,
    Reason,
    canonical_language,
    evaluate_eligibility,
    rank_jobs,
    ranking_report,
    score_job,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def job(title="Data Engineer", company="Acme GmbH", description="", country="DE",
        city="Berlin", url="https://example.test/1", source_id="1", posted_at=None,
        remote_flag=None, location_raw=None) -> Job:
    return Job(
        source="softgarden",
        source_id=source_id,
        url=url,
        title=title,
        company=company,
        description=description,
        location_raw=location_raw if location_raw is not None else city,
        country=JobField.structured(country) if country else JobField.absent(),
        city=JobField.structured(city) if city else JobField.absent(),
        remote_flag=(JobField.structured(remote_flag) if remote_flag is not None
                     else JobField.absent()),
        posted_at=posted_at,
    )


# --- the score is a count of named evidence ---------------------------------------------

def test_an_empty_preference_set_scores_zero():
    assert score_job(job(), MatchPreferences()).score == 0


def test_a_title_keyword_match_scores_and_is_named():
    result = score_job(job(title="Senior Data Engineer"),
                       MatchPreferences(keywords=("data", "engineer")))
    assert result.score == 1
    assert result.evidence[0].reason is Reason.TITLE_KEYWORD
    assert "data" in result.evidence[0].detail


def test_the_score_equals_the_number_of_reasons():
    """The invariant that makes the score auditable rather than opaque."""
    result = score_job(
        job(title="Data Engineer", description="We use dbt and Snowflake."),
        MatchPreferences(keywords=("data",), skills=("dbt", "Snowflake"),
                         preferred_cities=("berlin",)),
    )
    assert result.score == len(result.evidence)


def test_a_skill_in_the_title_outranks_one_only_in_the_body():
    """Different evidence, so different named reasons rather than one count."""
    in_title = score_job(job(title="dbt Engineer"), MatchPreferences(skills=("dbt",)))
    in_body = score_job(job(title="Engineer", description="We use dbt."),
                        MatchPreferences(skills=("dbt",)))
    assert in_title.evidence[0].reason is Reason.SKILL_IN_TITLE
    assert in_body.evidence[0].reason is Reason.SKILL_IN_DESCRIPTION


def test_all_keyswords_must_match_to_score_the_title_reason():
    result = score_job(job(title="Data Engineer"),
                       MatchPreferences(keywords=("data", "scientist")))
    assert result.score == 0


def test_keywords_use_the_same_and_rule_as_the_normaliser_filter():
    """Regression: the matcher and the filter must not disagree.

    The normaliser's keyword filter requires every token; an OR here would mean a
    job could pass the filter and then be explained as matching something else --
    two subtly different meanings of "keywords" in one pipeline.
    """
    from services.job_normalize import matches_keywords

    target = job(title="Data Engineer")
    prefs = MatchPreferences(keywords=("data", "scientist"))
    assert matches_keywords(target, "data scientist") is False
    assert score_job(target, prefs).score == 0

    both = job(title="Data Scientist")
    assert matches_keywords(both, "data scientist") is True
    assert score_job(both, MatchPreferences(keywords=("data", "scientist"))).score == 1


def test_a_duplicated_keyword_does_not_make_the_rule_unsatisfiable():
    """('sql','SQL') is one term, so one match must be enough."""
    result = score_job(job(title="SQL Engineer"),
                       MatchPreferences(keywords=("sql", "SQL")))
    assert result.score == 1


def test_keywords_matching_only_the_description_still_score():
    result = score_job(job(title="Engineer", description="A data role."),
                       MatchPreferences(keywords=("data",)))
    assert result.score == 1
    assert "description" in result.evidence[0].detail


def test_scoring_is_deterministic_across_repeated_calls():
    target = job(title="Data Engineer", description="dbt and Snowflake")
    prefs = MatchPreferences(keywords=("data",), skills=("dbt", "Snowflake"))
    first = score_job(target, prefs, now=NOW)
    second = score_job(target, prefs, now=NOW)
    assert first.score == second.score
    assert [e.reason for e in first.evidence] == [e.reason for e in second.evidence]


# --- a missing fact is not a miss --------------------------------------------------------

def test_an_absent_description_is_reported_as_unknown_not_as_a_miss():
    result = score_job(job(description=""), MatchPreferences(skills=("dbt",)))
    assert result.score == 0
    assert any("not" in unknown or "none of" in unknown for unknown in result.unknowns)


def test_an_absent_posted_date_is_an_unknown():
    """Most DACH sources omit the date; that must not read as an old posting."""
    result = score_job(job(), MatchPreferences(recency_days=30), now=NOW)
    assert any("posted" in unknown for unknown in result.unknowns)


def test_an_absent_location_is_an_unknown():
    result = score_job(job(city=None, location_raw=""), MatchPreferences(
        preferred_cities=("berlin",)))
    assert any("location" in unknown for unknown in result.unknowns)


def test_an_unstated_remote_flag_is_an_unknown():
    result = score_job(job(remote_flag=None), MatchPreferences(prefers_remote=True))
    assert any("remote" in unknown for unknown in result.unknowns)


def test_a_missing_fact_does_not_award_a_default_point():
    """The core 'no invented scores' rule."""
    without_description = score_job(job(description=""), MatchPreferences(skills=("dbt",)))
    assert without_description.score == 0


# --- recency ----------------------------------------------------------------------------

def test_a_recent_posting_scores_for_recency():
    result = score_job(job(posted_at=NOW - timedelta(days=3)),
                       MatchPreferences(recency_days=30), now=NOW)
    assert any(item.reason is Reason.RECENCY for item in result.evidence)


def test_an_old_posting_does_not_score_for_recency():
    result = score_job(job(posted_at=NOW - timedelta(days=100)),
                       MatchPreferences(recency_days=30), now=NOW)
    assert not any(item.reason is Reason.RECENCY for item in result.evidence)


def test_an_old_posting_scores_zero_rather_than_negative():
    """Losing points for age would let a stale job outrank a merely sparse one."""
    result = score_job(job(posted_at=NOW - timedelta(days=999)),
                       MatchPreferences(recency_days=30), now=NOW)
    assert result.score == 0


# --- word-boundary matching --------------------------------------------------------------

def test_a_short_skill_does_not_match_inside_a_longer_word():
    """'R' must not match 'React', and 'SQL' must not match 'NoSQL'."""
    result = score_job(job(title="React Developer", description=""),
                       MatchPreferences(skills=("R",)))
    assert result.score == 0


def test_nosql_does_not_satisfy_a_sql_skill():
    result = score_job(job(title="Engineer", description="We use NoSQL databases."),
                       MatchPreferences(skills=("SQL",)))
    assert result.score == 0


def test_sql_still_matches_a_real_whole_word_mention():
    result = score_job(job(title="Engineer", description="Strong SQL required."),
                       MatchPreferences(skills=("SQL",)))
    assert result.score == 1


def test_a_punctuated_skill_matches_by_substring():
    """Word boundaries are meaningless for terms like c++ or ci/cd."""
    result = score_job(job(title="Engineer", description="We write C++ daily."),
                       MatchPreferences(skills=("c++",)))
    assert result.score == 1


# --- eligibility: hard blocks ------------------------------------------------------------

def test_a_verified_foreign_country_is_ineligible():
    """Not a low score -- a job the candidate cannot take."""
    result = score_job(job(country="US"),
                       MatchPreferences(eligible_countries=("DE", "AT", "CH")))
    assert result.eligibility is Eligibility.INELIGIBLE
    assert result.is_visible is False
    assert result.blockers[0][0] is Blocker.COUNTRY_NOT_ELIGIBLE


def test_an_absent_country_is_not_ineligible():
    """Unknown is not a violation; it must not hide a legitimate job."""
    result = score_job(job(country=None),
                       MatchPreferences(eligible_countries=("DE",)))
    assert result.eligibility is not Eligibility.INELIGIBLE


def test_a_stated_language_requirement_the_profile_lacks_is_ineligible():
    result = score_job(
        job(description="We require fluent German for this role."),
        MatchPreferences(languages=("English",)),
    )
    assert result.eligibility is Eligibility.INELIGIBLE
    assert result.blockers[0][0] is Blocker.LANGUAGE_REQUIRED_MISSING


def test_a_satisfied_language_requirement_does_not_block():
    result = score_job(
        job(description="We require fluent German for this role."),
        MatchPreferences(languages=("English", "German")),
    )
    assert result.eligibility is Eligibility.ELIGIBLE


def test_merely_mentioning_a_language_is_not_a_requirement():
    """A German-language posting is not the same as a German-language demand."""
    result = score_job(
        job(description="Unser Team arbeitet mit modernen Werkzeugen."),
        MatchPreferences(languages=("English",)),
    )
    assert result.eligibility is Eligibility.ELIGIBLE


def test_no_eligible_countries_configured_means_no_country_constraint():
    result = score_job(job(country="US"), MatchPreferences(eligible_countries=()))
    assert result.eligibility is Eligibility.ELIGIBLE


# --- eligibility: uncertain is its own answer --------------------------------------------

def test_a_work_authorisation_mention_is_uncertain_not_ineligible():
    """The profile's own permit may satisfy it, so it must not be hidden."""
    result = score_job(
        job(description="You must have a valid work permit for Germany."),
        MatchPreferences(),
    )
    assert result.eligibility is Eligibility.UNCERTAIN
    assert result.is_visible is True
    assert result.blockers[0][0] is Blocker.WORK_AUTHORISATION_UNCLEAR


def test_an_over_senior_title_is_uncertain_not_ineligible():
    """Seniority words are a judgement, so the candidate decides."""
    result = score_job(job(title="Head of Data Engineering"), MatchPreferences())
    assert result.eligibility is Eligibility.UNCERTAIN
    assert result.is_visible is True


def test_uncertain_jobs_remain_visible():
    result = score_job(job(title="Director of Data"), MatchPreferences())
    assert result.is_visible is True


def test_eligible_is_the_default():
    assert score_job(job(), MatchPreferences()).eligibility is Eligibility.ELIGIBLE


# --- eligibility is never a score --------------------------------------------------------

def test_eligibility_does_not_change_the_score():
    """A blocked job scores the same as an unblocked one with equal evidence.

    Eligibility and ranking answer different questions; conflating them is how a
    tool quietly shows someone a job they cannot take, or hides one they can.
    """
    prefs = MatchPreferences(keywords=("data",))
    eligible = score_job(job(title="Data Engineer"), prefs)
    blocked = score_job(job(title="Data Engineer", country="US"),
                        MatchPreferences(keywords=("data",), eligible_countries=("DE",)))
    assert eligible.score == blocked.score
    assert eligible.eligibility is not blocked.eligibility


# --- explanations are human-readable -----------------------------------------------------

def test_the_explanation_names_each_match_reason():
    result = score_job(job(title="Data Engineer"),
                       MatchPreferences(keywords=("data",)))
    lines = result.explanation()
    assert any("match:" in line for line in lines)


def test_the_explanation_labels_a_hard_block_as_cannot_apply():
    result = score_job(job(country="US"), MatchPreferences(eligible_countries=("DE",)))
    assert any(line.startswith("cannot apply") for line in result.explanation())


def test_the_explanation_labels_uncertainty_as_check_first():
    result = score_job(job(title="Head of Data"), MatchPreferences())
    assert any(line.startswith("check first") for line in result.explanation())


def test_a_job_with_no_evidence_says_so_rather_than_showing_an_empty_list():
    lines = score_job(job(), MatchPreferences()).explanation()
    assert any("no specific match reasons" in line for line in lines)


def test_the_explanation_reports_unknowns():
    result = score_job(job(description=""), MatchPreferences(skills=("dbt",)))
    assert any(line.startswith("not stated by the source") for line in result.explanation())


def test_the_result_serialises_with_its_evidence_and_blockers():
    result = score_job(job(title="Data Engineer", country="US"),
                       MatchPreferences(keywords=("data",), eligible_countries=("DE",)))
    payload = result.as_dict()
    assert payload["score"] == result.score
    assert payload["eligibility"] == "ineligible"
    assert payload["is_visible"] is False
    assert payload["evidence"][0]["reason"] == "title_keyword"
    assert payload["blockers"][0]["severity"] == "ineligible"


# --- ranking ------------------------------------------------------------------------------

def test_ranking_orders_best_score_first():
    strong = job(title="Data Engineer", description="dbt Snowflake",
                 source_id="strong", url="https://x.test/s")
    weak = job(title="Analyst", source_id="weak", url="https://x.test/w")
    ranked = rank_jobs([weak, strong],
                       MatchPreferences(keywords=("data",), skills=("dbt",)))
    assert ranked[0].job.source_id == "strong"


def test_ranking_excludes_ineligible_jobs_by_default():
    ranked = rank_jobs([job(country="US")], MatchPreferences(eligible_countries=("DE",)))
    assert ranked == []


def test_ranking_can_include_ineligible_jobs_on_request():
    ranked = rank_jobs([job(country="US")], MatchPreferences(eligible_countries=("DE",)),
                       include_ineligible=True)
    assert len(ranked) == 1
    assert ranked[0].eligibility is Eligibility.INELIGIBLE


def test_uncertain_jobs_are_ranked_not_dropped():
    ranked = rank_jobs([job(title="Head of Data")], MatchPreferences())
    assert len(ranked) == 1
    assert ranked[0].eligibility is Eligibility.UNCERTAIN


def test_equal_scores_are_broken_by_recency():
    older = job(source_id="a", url="https://x.test/a", posted_at=NOW - timedelta(days=10))
    newer = job(source_id="b", url="https://x.test/b", posted_at=NOW - timedelta(days=1))
    ranked = rank_jobs([older, newer], MatchPreferences(), now=NOW)
    assert [result.job.source_id for result in ranked] == ["b", "a"]


def test_a_missing_date_sorts_after_a_known_one():
    """An undated job must not be treated as brand new."""
    undated = job(source_id="a", url="https://x.test/a", posted_at=None)
    dated = job(source_id="b", url="https://x.test/b", posted_at=NOW - timedelta(days=5))
    ranked = rank_jobs([undated, dated], MatchPreferences(), now=NOW)
    assert [result.job.source_id for result in ranked] == ["b", "a"]


def test_the_tie_break_makes_order_independent_of_input_order():
    """Otherwise two runs over the same sources could present jobs differently."""
    first = job(source_id="aaa", url="https://x.test/a")
    second = job(source_id="bbb", url="https://x.test/b")
    forward = [r.job.source_id for r in rank_jobs([first, second], MatchPreferences())]
    backward = [r.job.source_id for r in rank_jobs([second, first], MatchPreferences())]
    assert forward == backward == ["aaa", "bbb"]


def test_ranking_an_empty_list_is_empty():
    assert rank_jobs([], MatchPreferences()) == []


def test_the_ranking_report_counts_each_outcome():
    results = [
        MatchResult(job=job(), eligibility=Eligibility.ELIGIBLE),
        MatchResult(job=job(country="US"), eligibility=Eligibility.INELIGIBLE),
        MatchResult(job=job(), eligibility=Eligibility.UNCERTAIN),
    ]
    report = ranking_report(results)
    assert report["total"] == 3
    assert report["visible"] == 2
    assert report["ineligible"] == 1
    assert report["uncertain"] == 1


# --- preferences from a profile ----------------------------------------------------------

class FakeRules:
    home_countries = ["germany", "de"]


class FakeLanguage:
    def __init__(self, name):
        self.name = name
        self.proficiency = "Fluent"


class FakeProfile:
    skills = {"core": ["Advanced SQL", "dbt"], "tools": ["Snowflake"]}
    languages = [FakeLanguage("English"), FakeLanguage("German")]
    rules = FakeRules()


def test_preferences_are_read_from_the_profile():
    prefs = MatchPreferences.from_profile(FakeProfile())
    assert set(prefs.skills) == {"Advanced SQL", "dbt", "Snowflake"}
    assert set(prefs.languages) == {"English", "German"}
    assert set(prefs.eligible_countries) == {"germany", "de"}


def test_a_profile_with_no_skills_yields_no_skill_preferences():
    """Fail closed: no declared skills means no skill matching, not a guess."""
    class Bare:
        skills = {}
        languages = []
        rules = None

    prefs = MatchPreferences.from_profile(Bare())
    assert prefs.skills == ()
    assert prefs.languages == ()
    assert prefs.eligible_countries == ()


def test_overrides_win_over_profile_values():
    prefs = MatchPreferences.from_profile(FakeProfile(), keywords=("data",))
    assert prefs.keywords == ("data",)


def test_a_profile_home_country_name_still_matches_a_job_country_code():
    """Profiles write 'germany'; jobs carry 'DE'. Both must resolve."""
    result = score_job(job(country="DE"),
                       MatchPreferences(eligible_countries=("germany",)))
    assert result.eligibility is Eligibility.ELIGIBLE


def test_preferences_serialise():
    payload = MatchPreferences(keywords=("data",), prefers_remote=True).as_dict()
    assert payload["keywords"] == ["data"]
    assert payload["prefers_remote"] is True


# --- language canonicalisation -----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("german", "German"), ("deutsch", "German"), ("German", "German"),
    ("englisch", "English"), ("french", "French"), ("französisch", "French"),
])
def test_language_names_canonicalise_across_spellings(value, expected):
    assert canonical_language(value) == expected


def test_a_german_requirement_phrase_is_recognised():
    result = score_job(job(description="Wir suchen Verhandlungssicher Deutsch."),
                       MatchPreferences(languages=("English",)))
    assert result.eligibility is Eligibility.INELIGIBLE
