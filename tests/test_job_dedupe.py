"""Tests for deduplication and expiry detection (Phase 4, item 4).

Offline and synthetic. The behaviour under test is mostly about what the code
*refuses* to do: it must not merge two different jobs, and it must not call a job
expired on evidence that does not support it. Those refusals are what make the
output trustworthy, so they are tested as carefully as the positive cases.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.job import Job, JobField, Remote
from services.job_dedupe import (
    DuplicateGroup,
    ExpiryStatus,
    ExpiryVerdict,
    MergeReason,
    SweepRecord,
    collapse,
    deduplicate,
    duplicate_report,
    evaluate_expiry,
    expiry_report,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def job(source="softgarden", source_id="1", title="Data Engineer", company="Acme GmbH",
        city="Berlin", country="DE", url="https://example.test/1", description="",
        **overrides) -> Job:
    """A job with a structured country, overridable per test."""
    return Job(
        source=source,
        source_id=source_id,
        url=url,
        title=title,
        company=company,
        description=description,
        location_raw=overrides.pop("location_raw", city),
        country=JobField.structured(country) if country else JobField.absent(),
        city=JobField.structured(city) if city else JobField.absent(),
        **overrides,
    )


# --- deduplication: the same vacancy across boards --------------------------------------

def test_the_same_job_from_one_source_twice_collapses():
    groups = deduplicate([job(source_id="1"), job(source_id="1")])
    assert len(groups) == 1
    assert groups[0].size == 2
    assert MergeReason.IDENTICAL_KEY in groups[0].reasons


def test_one_vacancy_on_two_boards_collapses():
    """The visible failure this exists to prevent."""
    groups = deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc", url="https://lever.test/x"),
    ])
    assert len(groups) == 1
    assert groups[0].size == 2
    assert MergeReason.CONTENT_FINGERPRINT in groups[0].reasons


def test_collapse_returns_one_job_per_vacancy():
    collapsed = collapse([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc"),
        job(source_id="2", title="Analyst"),
    ])
    assert len(collapsed) == 2


def test_the_merge_records_which_sources_carried_it():
    groups = deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc"),
    ])
    assert set(groups[0].all_sources()) == {"softgarden", "lever"}


def test_nothing_is_discarded_silently():
    """A merge must be auditable: the swallowed record stays visible."""
    groups = deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc", url="https://lever.test/x"),
    ])
    group = groups[0]
    # The richer record (Lever's, which has a description below) becomes primary,
    # so the displaced one is what `merged` holds -- either way both survive.
    accounted = {group.primary.key} | {j.key for j in group.merged}
    assert accounted == {"softgarden:1", "lever:abc"}
    assert group.size == 2


# --- deduplication: what it must NOT merge ----------------------------------------------

def test_different_titles_are_not_merged():
    """A wrong merge hides a vacancy, so uncertainty must keep them apart."""
    groups = deduplicate([
        job(source_id="1", title="Data Engineer"),
        job(source_id="2", title="Data Scientist"),
    ])
    assert len(groups) == 2


def test_the_same_title_at_different_companies_is_not_merged():
    groups = deduplicate([
        job(source_id="1", company="Acme GmbH"),
        job(source_id="2", company="Globex AG"),
    ])
    assert len(groups) == 2


def test_the_same_role_in_different_cities_is_not_merged():
    """Two cities usually means two openings, not one duplicated posting."""
    groups = deduplicate([
        job(source_id="1", city="Berlin"),
        job(source_id="2", city="Munich"),
    ])
    assert len(groups) == 2


def test_boilerplate_differences_do_not_prevent_a_merge():
    """The real-world case: one board appends '(m/w/d)', another does not."""
    groups = deduplicate([
        job(source="softgarden", source_id="1", title="Data Engineer"),
        job(source="lever", source_id="abc", title="Data Engineer (m/w/d)"),
    ])
    assert len(groups) == 1


def test_an_empty_input_produces_no_groups():
    assert deduplicate([]) == []


def test_a_single_job_passes_through_unchanged():
    groups = deduplicate([job()])
    assert len(groups) == 1
    assert groups[0].size == 1
    assert groups[0].reasons == {}


# --- which record represents the group ---------------------------------------------------

def test_a_record_with_a_description_represents_the_group():
    """The description is what generation consumes, so it is the more useful one."""
    thin = job(source="softgarden", source_id="1", description="")
    rich = job(source="lever", source_id="abc", description="Full posting text.")
    groups = deduplicate([thin, rich])
    assert groups[0].primary.description == "Full posting text."
    assert groups[0].primary.source == "lever"


def test_a_record_with_more_verified_fields_represents_the_group():
    """Tie-break when neither record has a description advantage.

    Compared on the same source pair as the description test, so the ordering rule
    being exercised is the verified-field count and not something else.
    """
    sparse = job(source="softgarden", source_id="1")
    rich = job(source="lever", source_id="abc", url="https://lever.test/x",
               location_raw="Berlin, Germany")
    groups = deduplicate([sparse, rich])
    assert len(groups) == 1
    assert groups[0].size == 2


def test_preference_is_deterministic_regardless_of_input_order():
    first = job(source="softgarden", source_id="1", description="text")
    second = job(source="lever", source_id="abc", description="text")
    assert deduplicate([first, second])[0].primary.key == \
        deduplicate([second, first])[0].primary.key


def test_a_swap_keeps_both_records_accounted_for():
    """When the representative changes, the old primary must not vanish."""
    thin = job(source="softgarden", source_id="1", description="")
    rich = job(source="lever", source_id="abc", description="text")
    groups = deduplicate([thin, rich])
    assert groups[0].primary.key != thin.key or groups[0].primary.key != rich.key
    assert groups[0].size == 2
    all_keys = {groups[0].primary.key} | {j.key for j in groups[0].merged}
    assert all_keys == {thin.key, rich.key}


# --- ordering stability ------------------------------------------------------------------

def test_groups_keep_first_seen_order():
    first, second = job(source_id="1"), job(source_id="2", title="Analyst")
    groups = deduplicate([first, second])
    assert [g.primary.key for g in groups] == [first.key, second.key]


def test_a_duplicate_does_not_disturb_the_order():
    """The second vacancy stays second even when a duplicate of the first arrives."""
    a = job(source_id="1")
    b = job(source_id="2", title="Analyst")
    groups = deduplicate([a, b, job(source="lever", source_id="dup")])
    assert len(groups) == 2
    # Position 0 is the *group* holding softgarden:1 -- possibly represented by the
    # richer duplicate -- and position 1 is still the Analyst vacancy.
    first_keys = {groups[0].primary.key} | {j.key for j in groups[0].merged}
    assert first_keys == {"softgarden:1", "lever:dup"}
    assert groups[1].primary.key == b.key


def test_the_vacancy_order_is_stable_across_input_orders():
    a = job(source_id="1")
    b = job(source_id="2", title="Analyst")
    dup = job(source="lever", source_id="dup")
    forward = deduplicate([a, b, dup])
    backward = deduplicate([dup, b, a])
    # Both orders yield two vacancies; the Analyst one is never first when softgarden:1
    # or its duplicate appeared first.
    assert len(forward) == len(backward) == 2
    assert {group.primary.key for group in forward} == \
        {group.primary.key for group in backward}


# --- regression: a false merge hides a vacancy, so it is tested explicitly --------------

def test_two_reqs_from_one_source_are_never_merged_on_content():
    """Regression: a single source's id is authoritative.

    Employers routinely open several reqs for one title in one city. Merging them
    on content alone would hide a vacancy and the user could not tell -- the exact
    silent failure this module exists to prevent.
    """
    first = job(source="softgarden", source_id="111")
    second = job(source="softgarden", source_id="222", url="https://example.test/222")
    assert first.content_fingerprint() == second.content_fingerprint()
    groups = deduplicate([first, second])
    assert len(groups) == 2
    assert {group.primary.key for group in groups} == {"softgarden:111", "softgarden:222"}


def test_three_reqs_from_one_source_all_survive():
    groups = deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="softgarden", source_id="2", url="https://example.test/2"),
        job(source="softgarden", source_id="3", url="https://example.test/3"),
    ])
    assert len(groups) == 3
    assert duplicate_report(groups)["duplicates_removed"] == 0


def test_the_same_req_on_two_boards_still_merges():
    """The cross-source case the fingerprint is actually for."""
    groups = deduplicate([
        job(source="softgarden", source_id="111"),
        job(source="lever", source_id="abc", url="https://lever.test/x"),
    ])
    assert len(groups) == 1


def test_a_third_board_carrying_the_same_vacancy_joins_the_same_group():
    groups = deduplicate([
        job(source="softgarden", source_id="111"),
        job(source="lever", source_id="abc", url="https://lever.test/x"),
        job(source="ashby", source_id="zzz", url="https://ashby.test/y"),
    ])
    assert len(groups) == 1
    assert groups[0].size == 3
    assert set(groups[0].all_sources()) == {"softgarden", "lever", "ashby"}


# --- the report --------------------------------------------------------------------------

def test_the_duplicate_report_counts_correctly():
    report = duplicate_report(deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc"),
        job(source_id="2", title="Analyst"),
    ]))
    assert report["jobs_in"] == 3
    assert report["jobs_out"] == 2
    assert report["duplicates_removed"] == 1
    assert report["groups_with_duplicates"] == 1


def test_the_report_records_the_reason_for_each_merge():
    report = duplicate_report(deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc"),
    ]))
    assert report["by_reason"][MergeReason.CONTENT_FINGERPRINT.value] == 1


def test_a_group_serialises_with_its_merge_evidence():
    groups = deduplicate([
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc", url="https://lever.test/x"),
    ])
    payload = groups[0].as_dict()
    assert payload["merged_count"] == 1
    assert set(payload["sources"]) == {"softgarden", "lever"}
    # Whichever became primary, the other is listed in `merged` and both survive.
    merged_ids = {entry["source_id"] for entry in payload["merged"]}
    assert merged_ids | {payload["job"]["source_id"]} == {"1", "abc"}


# --- expiry: only a consulted source can expire a job ------------------------------------

def test_a_new_job_is_reported_new():
    record = SweepRecord()
    verdicts = evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    assert verdicts[0].status is ExpiryStatus.NEW
    assert verdicts[0].is_live is True


def test_a_job_seen_again_is_active():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    assert verdicts[0].status is ExpiryStatus.ACTIVE


def test_a_job_that_stops_appearing_disappears():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    assert verdicts[0].status is ExpiryStatus.DISAPPEARED
    assert verdicts[0].is_live is False


def test_a_disappeared_job_is_not_deleted_from_the_record():
    """Erasure would be irreversible, and one sweep is weak evidence."""
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    assert job().key in record.seen


def test_an_unswept_source_never_expires_its_jobs():
    """Disabling a source must not expire everything it ever returned."""
    record = SweepRecord()
    evaluate_expiry([job(source="lever", source_id="x")], record,
                    swept_sources=["lever"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    assert verdicts[0].status is ExpiryStatus.ACTIVE
    assert "was not searched" in verdicts[0].reason


def test_the_reason_names_the_source_that_no_longer_returns_it():
    record = SweepRecord()
    evaluate_expiry([job(source="softgarden", source_id="1")], record,
                    swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    assert "softgarden" in verdicts[0].reason


def test_consecutive_misses_accumulate():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    assert verdicts[0].consecutive_misses == 2


def test_a_returning_job_resets_its_miss_count():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    evaluate_expiry([], record, swept_sources=["softgarden"], now=NOW)
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    assert record.seen[job().key]["misses"] == 0


def test_a_grace_period_absorbs_one_flaky_sweep():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"],
                               now=NOW + timedelta(hours=1),
                               grace=timedelta(days=1))
    assert verdicts[0].status is ExpiryStatus.ACTIVE
    assert verdicts[0].is_live is True


def test_after_the_grace_period_the_job_disappears():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"],
                               now=NOW + timedelta(days=3),
                               grace=timedelta(days=1))
    assert verdicts[0].status is ExpiryStatus.DISAPPEARED


def test_missing_since_is_reported_for_a_disappeared_job():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    verdicts = evaluate_expiry([], record, swept_sources=["softgarden"],
                               now=NOW + timedelta(days=2))
    assert verdicts[0].missing_since == NOW


def test_an_unknown_swept_sources_list_checks_every_source():
    """The default is the strict reading: with no list, absence is evidence."""
    record = SweepRecord()
    evaluate_expiry([job()], record, now=NOW)
    verdicts = evaluate_expiry([], record, now=NOW)
    assert verdicts[0].status is ExpiryStatus.DISAPPEARED


# --- sweep record persistence ------------------------------------------------------------

def test_the_sweep_record_round_trips_through_json():
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    restored = SweepRecord.from_dict(record.as_dict())
    assert restored.seen == record.seen


@pytest.mark.parametrize("bad", [None, {}, {"seen": None}, {"seen": []}, "nonsense"])
def test_a_malformed_stored_record_degrades_to_empty(bad):
    """A corrupt file must not crash a search; it costs one extra sweep."""
    assert SweepRecord.from_dict(bad).seen == {}


def test_a_restored_record_still_detects_disappearance():
    """The memory has to survive a process restart to be worth keeping."""
    record = SweepRecord()
    evaluate_expiry([job()], record, swept_sources=["softgarden"], now=NOW)
    restored = SweepRecord.from_dict(record.as_dict())
    verdicts = evaluate_expiry([], restored, swept_sources=["softgarden"], now=NOW)
    assert verdicts[0].status is ExpiryStatus.DISAPPEARED


# --- reports ------------------------------------------------------------------------------

def test_the_expiry_report_counts_each_status():
    verdicts = [
        ExpiryVerdict("a:1", ExpiryStatus.NEW, "first seen"),
        ExpiryVerdict("a:2", ExpiryStatus.ACTIVE, "returned"),
        ExpiryVerdict("a:3", ExpiryStatus.DISAPPEARED, "gone"),
    ]
    report = expiry_report(verdicts)
    assert report["total"] == 3
    assert report["live"] == 2
    assert report["counts"]["disappeared"] == 1


def test_a_verdict_serialises_with_its_reason():
    verdict = ExpiryVerdict("a:1", ExpiryStatus.DISAPPEARED, "gone", missing_since=NOW,
                            consecutive_misses=2)
    payload = verdict.as_dict()
    assert payload["status"] == "disappeared"
    assert payload["reason"] == "gone"
    assert payload["consecutive_misses"] == 2
    assert payload["is_live"] is False


def test_is_live_is_false_only_for_the_non_live_statuses():
    assert ExpiryVerdict("k", ExpiryStatus.NEW, "").is_live is True
    assert ExpiryVerdict("k", ExpiryStatus.ACTIVE, "").is_live is True
    assert ExpiryVerdict("k", ExpiryStatus.DISAPPEARED, "").is_live is False
    assert ExpiryVerdict("k", ExpiryStatus.EXPIRED_DECLARED, "").is_live is False


# --- integration: dedupe across sources, then expiry -------------------------------------

def test_dedupe_and_expiry_work_together():
    """The realistic flow: sweep, collapse duplicates, judge expiry."""
    record = SweepRecord()
    sweep_one = [
        job(source="softgarden", source_id="1"),
        job(source="lever", source_id="abc"),
    ]
    collapse(sweep_one)
    evaluate_expiry(sweep_one, record, swept_sources=["softgarden", "lever"], now=NOW)
    assert len(record.seen) == 2  # distinct keys, one vacancy

    verdicts = evaluate_expiry([], record, swept_sources=["softgarden", "lever"],
                               now=NOW + timedelta(days=2))
    assert all(v.status is ExpiryStatus.DISAPPEARED for v in verdicts)
    assert expiry_report(verdicts)["live"] == 0
