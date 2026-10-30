"""The candidate screen: a listing record in, a proposed slate out (Q1, Q3).

The screen is the cheap half of curation. Measuring a candidate costs money; deciding
which ones are *worth* measuring is arithmetic over a listing the repository already
has. These tests pin the properties that make it safe to put in front of a spend
decision:

* **offline and free** -- asserted by running it with the network disabled, not by
  reading the source;
* **deterministic** -- the same record gives the same slate, so a diff between two
  runs reports the catalogue changing rather than the selection wobbling;
* **every rejection reasoned** -- "8 of 267" is not a review artefact; "and here are the
  259 I dropped, and why" is;
* **a shortlisting is not a rejection** -- the two are different claims and the report
  must not conflate them;
* **the spread survives the cap** -- the failure mode this module was rewritten twice
  for, recorded with the measurements that forced it.

Everything here is offline. No network call is made, and none is needed.
"""
from __future__ import annotations

import pytest

# Imported defensively and failed, not skipped, when absent: a broken import in the real
# tree is the thing this file exists to catch.
try:
    from evaluation import screen
    from evaluation.listing import (
        LISTING_URL,
        ListingEntry,
        ListingRecord,
        latest_record,
        load_record,
    )
    from evaluation.screen import (
        MAX_SLATE,
        REJECT_CEILING_TOO_LOW,
        REJECT_NOT_SHORTLISTED,
        REJECT_NOT_STRUCTURED,
        REJECT_NO_DATE,
        REJECT_ROUTING_VARIANT,
        REJECT_TOO_OLD,
        REJECT_UNPRICED,
        REJECTION_REASONS,
        Candidate,
        Rejection,
        Slate,
        dialect_hint_for,
        is_routing_variant,
        screen_record,
    )
except ImportError as error:  # pragma: no cover - only on a broken tree
    pytest.fail(f"evaluation.screen could not be imported: {error}", pytrace=False)


# --- helpers -------------------------------------------------------------------------------

def _entry(model_id, *, prompt=1.0, completion=2.0, created="2026-01-01",
           structured=True, ceiling=8_000):
    return ListingEntry(
        id=model_id, prompt=prompt, completion=completion, created=created,
        structured_outputs=structured, context_length=100_000,
        max_completion_tokens=ceiling,
    )


def _record(*entries):
    return ListingRecord(
        read_on="2026-10-30", source_url=LISTING_URL, source_sha256="A" * 64,
        source_model_count=len(entries), entries=tuple(entries),
    )


# --- the screen is offline and free ---------------------------------------------------------

def test_the_screen_makes_no_network_call(monkeypatch):
    """The property that makes it safe to run before a spend decision.

    Enforced by making every network entry point raise, then screening a real record.
    Asserted behaviourally rather than by reading the source: a future edit could import
    a client without this test noticing a source-level check.
    """
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("the screen attempted a network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    slate = screen_record(load_record(latest_record()), control_id="openai/gpt-6-luna")
    assert slate.candidates, "the screen returned nothing, so this proves nothing"


def test_the_screen_is_deterministic():
    """Same record, same slate. A wobbling selection would make every diff unreadable."""
    record = load_record(latest_record())
    first = screen_record(record, control_id="openai/gpt-6-luna")
    second = screen_record(record, control_id="openai/gpt-6-luna")

    assert [c.id for c in first.candidates] == [c.id for c in second.candidates]
    assert first.rejected_ids() == second.rejected_ids()


# --- the cap, and the spread the cap must not destroy ---------------------------------------

def test_the_slate_is_capped():
    entries = [_entry(f"vendor/model-{i:03d}", prompt=0.1 + i, completion=1.0 + i)
               for i in range(40)]
    slate = screen_record(_record(*entries), cap=MAX_SLATE)

    assert len(slate.candidates) == MAX_SLATE
    assert slate.cap == MAX_SLATE


def test_the_cap_is_a_shortlisting_and_not_a_rejection():
    """**The distinction the first implementation got wrong.**

    It labelled every model outside the cheapest eight as ``over-slate-cap``, which
    reads as a finding about the model when it is a decision about the slate. 258 of 266
    models were reported that way against the real record. They now carry
    ``not-shortlisted``, and the reason says so in as many words, because a person
    reading the report must be able to tell "this model cannot do the job" from "I
    looked at the cheap end first".
    """
    entries = [_entry(f"vendor/model-{i:03d}", prompt=0.1 + i, completion=1.0 + i)
               for i in range(20)]
    slate = screen_record(_record(*entries), cap=4)

    not_shortlisted = [r for r in slate.rejections if r.rule == REJECT_NOT_SHORTLISTED]
    assert len(not_shortlisted) == 16
    for rejection in not_shortlisted:
        assert "SHORTLISTING decision" in rejection.reason
        assert "viable candidate" in rejection.reason


def test_the_spread_guard_keeps_one_expensive_candidate():
    """**The second failure mode, measured against the real record.**

    Taking simply the cheapest ``cap`` returned eight models inside the bottom 0.2% of
    the price range and reported ``cost spread NO``. The fix is not a round-robin over
    cost bands -- that was the third attempt and it filled half the slate with
    ``*-pro`` models at roughly 200x the selected model's cost per run. It is a
    cheapest-first fill with **one** guard: if the dearest band is unrepresented, its
    cheapest member replaces the slate's dearest entry.
    """
    cheap = [_entry(f"vendor/cheap-{i}", prompt=0.02, completion=0.10) for i in range(6)]
    dear = [_entry("vendor/dear", prompt=100.0, completion=500.0)]
    slate = screen_record(_record(*cheap, *dear), cap=4)

    ids = [c.id for c in slate.candidates]
    assert "vendor/dear" in ids, 'the expensive end was dropped, so the spread is gone'
    # And it did not take over the slate: exactly one expensive entry.
    assert len([i for i in ids if "dear" in i]) == 1
    assert slate.has_cost_spread()


def test_the_spread_guard_does_not_fire_when_the_band_is_already_represented():
    """A guard that always fires is not a guard, it is a rule about slate shape."""
    entries = [
        _entry("vendor/a", prompt=1.0, completion=1.0),
        _entry("vendor/b", prompt=10.0, completion=10.0),
        _entry("vendor/c", prompt=1000.0, completion=1000.0),
    ]
    slate = screen_record(_record(*entries), cap=3)

    # All three fit, so nothing is swapped and no entry is invented.
    assert [c.id for c in slate.candidates] == ["vendor/a", "vendor/b", "vendor/c"]


def test_a_slate_with_no_expensive_band_does_not_crash():
    """Every survivor in one band: the guard must be a no-op, not an IndexError."""
    entries = [_entry(f"vendor/same-{i}", prompt=1.0, completion=1.0) for i in range(9)]
    slate = screen_record(_record(*entries), cap=4)

    assert len(slate.candidates) == 4
    assert slate.has_cost_spread() is False, (
        'a slate of identical prices must report no spread rather than claim one'
    )


def test_cost_spread_uses_the_run_not_the_input_rate():
    """Ranking by input price misranks this pipeline, which is output-heavy.

    ``vendor/b`` is dearer on input and *cheaper* per run, so a spread computed from
    input rates would sort it the wrong way round.
    """
    a = _entry("vendor/a", prompt=1.0, completion=100.0)
    b = _entry("vendor/b", prompt=10.0, completion=0.1)
    slate = screen_record(_record(a, b), cap=2)

    costs = {c.id: c.typical_run_cost for c in slate.candidates}
    assert costs["vendor/b"] < costs["vendor/a"]


# --- routing variants are routes, not models ------------------------------------------------

def test_routing_variants_are_recognised():
    """``:batch`` and ``~latest`` are ways to reach a model, not other models.

    The 2026-10-30 screen found 55 ``:batch`` entries and 18 tilde aliases among its
    survivors. A ``:batch`` route is often *cheaper* than the model it shadows, so a
    cheapest-first slate filled up with routes this pipeline cannot even call -- and
    displaced the models that would have been proposed on merit.
    """
    assert is_routing_variant("openai/gpt-5:batch")
    assert is_routing_variant("vendor/model:free")
    assert is_routing_variant("vendor/model:extended")
    assert is_routing_variant("~vendor/model-latest")

    assert not is_routing_variant("openai/gpt-6-luna")
    assert not is_routing_variant("z-ai/glm-5.3-flash")
    # An unrecognised suffix is left alone: it may be the model's own versioning, and
    # guessing would silently drop real candidates.
    assert not is_routing_variant("vendor/model:v2.1")


def test_a_routing_variant_is_rejected_with_its_own_reason():
    slate = screen_record(
        _record(_entry("vendor/real"), _entry("vendor/real:batch")), cap=8
    )

    assert [c.id for c in slate.candidates] == ["vendor/real"]
    rejected = {r.model_id: r for r in slate.rejections}
    assert rejected["vendor/real:batch"].rule == REJECT_ROUTING_VARIANT


def test_the_real_record_contains_routing_variants_and_they_are_dropped():
    """Stated against the committed record, so the rule is not tested on a fiction."""
    record = load_record(latest_record())
    variants = [e.id for e in record.entries if is_routing_variant(e.id)]

    assert variants, (
        'no routing variants in the committed record; if the catalogue stopped '
        'exposing them the rule could be deleted, and this assertion is what notices'
    )
    slate = screen_record(record, control_id="openai/gpt-6-luna")
    assert not (set(variants) & {c.id for c in slate.candidates})


# --- each structural filter, and the value behind its rejection -----------------------------

def test_a_model_without_structured_output_is_rejected():
    slate = screen_record(_record(_entry("vendor/no-schema", structured=False)), cap=8)
    (rejection,) = slate.rejections
    assert rejection.rule == REJECT_NOT_STRUCTURED
    assert "structured_outputs absent" in rejection.observed


def test_a_model_with_a_ceiling_too_small_is_rejected():
    slate = screen_record(_record(_entry("vendor/tiny", ceiling=100)), cap=8)
    (rejection,) = slate.rejections
    assert rejection.rule == REJECT_CEILING_TOO_LOW
    assert "100" in rejection.observed


def test_an_unpriced_model_is_rejected():
    slate = screen_record(_record(_entry("vendor/free", prompt=0.0)), cap=8)
    (rejection,) = slate.rejections
    assert rejection.rule == REJECT_UNPRICED


def test_a_model_below_the_recency_floor_is_rejected_with_its_date():
    """The observed value is what makes a rejection arguable rather than a verdict."""
    slate = screen_record(_record(_entry("vendor/old", created="2024-10-22")), cap=8)
    (rejection,) = slate.rejections
    assert rejection.rule == REJECT_TOO_OLD
    assert "2024-10-22" in rejection.observed
    assert "2024-10-22" in rejection.describe()


def test_a_model_with_no_date_is_rejected_rather_than_assumed_recent():
    """A defaulted date would satisfy the floor silently -- the failure it exists for."""
    slate = screen_record(_record(_entry("vendor/no-date", created="")), cap=8)
    (rejection,) = slate.rejections
    assert rejection.rule == REJECT_NO_DATE


def test_every_rejection_rule_has_a_reason_sentence():
    """A rule added without an explanation would print its own identifier at a reader."""
    slate = screen_record(load_record(latest_record()), control_id="openai/gpt-6-luna")
    for rejection in slate.rejections:
        assert rejection.rule in REJECTION_REASONS, rejection.rule
        assert rejection.reason.strip()
        assert rejection.reason != rejection.rule


def test_the_first_failing_rule_is_the_one_recorded():
    """A model failing three rules is not listed three times.

    Order matters for readability, not correctness, but a model appearing under four
    headings would inflate the rejection count and make the report unreadable.
    """
    entry = _entry("vendor/everything-wrong", prompt=0.0, created="2020-01-01",
                   structured=False, ceiling=10)
    slate = screen_record(_record(entry), cap=8)

    assert len(slate.rejections) == 1


# --- the control ---------------------------------------------------------------------------

def test_the_control_is_identified_and_not_proposed():
    """The shipped model is the thing challengers are measured *against*.

    Measuring it again prices the incumbent, which is a different question from "what
    should replace it" -- so it is reported separately rather than counted as a
    candidate.
    """
    slate = screen_record(load_record(latest_record()), control_id="openai/gpt-6-luna")

    assert slate.control is not None
    assert slate.control.id == "openai/gpt-6-luna"
    assert "openai/gpt-6-luna" not in [c.id for c in slate.candidates]


def test_an_absent_control_is_reported_as_absent_not_invented():
    slate = screen_record(_record(_entry("vendor/other")), control_id="openai/gpt-6-luna")
    assert slate.control is None


def test_considered_counts_candidates_and_rejections():
    """The arithmetic a reader checks the report against."""
    entries = [_entry(f"vendor/m-{i}", prompt=1.0 + i, completion=1.0)
               for i in range(5)]
    slate = screen_record(_record(*entries), cap=2)
    assert slate.considered == 5
    assert slate.library_size == 5


# --- dialect hints are labelled guesses, never measurements ---------------------------------

def test_dialect_hints_cover_the_three_measured_families():
    """The errors ADR 0016 records are per *family*, so the hint is keyed by family."""
    for model_id, expected in (
        ("openai/gpt-6-luna", "strict"),
        ("anthropic/claude-haiku-5.5", "anthropic-vertex"),
        ("google/gemini-3.8-flash", "gemini"),
    ):
        hint = dialect_hint_for(model_id)
        assert hint is not None, model_id
        assert hint.dialect == expected
        assert hint.basis.strip(), 'a hint with no basis is an assertion'


def test_an_unknown_family_gets_no_hint_rather_than_the_default():
    """``None`` is the honest answer: "we do not know" beats "this needs no adaptation".

    Defaulting would assert something about a family nobody has measured, which is a
    stronger claim than the absence of one.
    """
    assert dialect_hint_for("z-ai/glm-5.3-flash") is None
    assert dialect_hint_for("nex-agi/nex-n2.5-mini") is None


def test_a_hint_is_marked_assumed_and_cannot_pose_as_measured():
    """**The rule ADR 0016 makes load-bearing.**

    ``candidate_inputs.CandidateInputs`` refuses a non-default dialect with no rationale,
    exactly so a tuning cannot be silent. A hint derived from a vendor name cannot supply
    that rationale, and the flag is what stops one being pasted in as though it could.
    """
    hint = dialect_hint_for("openai/gpt-6-luna")
    assert hint.is_assumed() is True
    assert hint.assumed is True


def test_a_proposed_candidate_labels_its_hint_as_assumed():
    slate = screen_record(
        _record(_entry("openai/gpt-6-luna-2", prompt=1.0, completion=1.0)), cap=8
    )
    (candidate,) = slate.candidates
    assert candidate.dialect_hint is not None
    assert "assumed" in candidate.describe()


# --- the shape of the report ---------------------------------------------------------------

def test_rejections_group_by_rule():
    entries = [
        _entry("vendor/old", created="2020-01-01"),
        _entry("vendor/no-schema", structured=False),
        _entry("vendor/fine"),
    ]
    grouped = screen_record(_record(*entries), cap=8).rejections_by_rule()

    assert set(grouped) == {REJECT_TOO_OLD, REJECT_NOT_STRUCTURED}
    assert all(len(items) == 1 for items in grouped.values())


def test_describe_says_nothing_here_is_a_quality_ranking():
    """The report must not read as a verdict. Only a measured run can rank."""
    slate = screen_record(load_record(latest_record()), control_id="openai/gpt-6-luna")
    text = slate.describe()

    assert "quality ranking" in text
    assert "ordered by price" in text


def test_describe_truncates_a_long_rejection_list_rather_than_printing_hundreds():
    """A report nobody can read is not a review artefact."""
    entries = [_entry(f"vendor/m-{i:03d}", prompt=0.1 + i, completion=1.0) for i in range(200)]
    text = screen_record(_record(*entries), cap=2).describe()

    assert "... and" in text
    assert len(text.splitlines()) < 60


# --- the committed record is the input this was built for ----------------------------------

def test_the_real_record_produces_a_usable_slate():
    """An end-to-end reading of the committed record, so the numbers are on the record.

    On 2026-10-30: 267 models in the record, 266 considered, 8 proposed, spread yes.
    """
    slate = screen_record(load_record(latest_record()), control_id="openai/gpt-6-luna")

    assert len(slate.candidates) == MAX_SLATE
    assert slate.has_cost_spread() is True, (
        'the real slate lost its cost spread; the guard in _select_across_costs is '
        'what keeps this true and this is the assertion that would notice'
    )
    assert slate.library_size > 100
    for candidate in slate.candidates:
        assert candidate.entry.created >= slate.floor
        assert candidate.entry.structured_outputs
        assert candidate.typical_run_cost > 0


def test_a_shortlisting_leaves_enough_for_a_later_run():
    """The screen must not claim the catalogue is exhausted.

    If the real record has far more viable candidates than the cap, that is the expected
    state and the report should say so -- which the ``not-shortlisted`` reason does.
    """
    slate = screen_record(load_record(latest_record()), control_id="openai/gpt-6-luna")
    not_shortlisted = [r for r in slate.rejections if r.rule == REJECT_NOT_SHORTLISTED]

    assert not_shortlisted, (
        'no model was left unshortlisted against the real catalogue, which would mean '
        'the screen is either very strict or the cap is not binding'
    )


# --- the screen agrees with the curated set where they overlap ------------------------------

def test_the_screen_prices_a_model_the_same_way_the_curated_set_does():
    """Two copies of one formula is how this project's dialects drifted apart.

    ``ListingEntry.cost_for`` and ``CuratedModel.cost_for`` are deliberately the same
    one-line arithmetic. This asserts they agree on a shared id rather than trusting that
    they do -- a drift would make the screen's slate price differently from the study
    that follows it.
    """
    from evaluation import cases
    from evaluation.curated_models import CURATED_MODELS

    record = load_record(latest_record())
    for model in CURATED_MODELS:
        entry = record.find(model.id)
        if entry is None:
            continue
        tokens = (cases.CV_INPUT_TOKENS + cases.CL_INPUT_TOKENS,
                  cases.CV_OUTPUT_TOKENS + cases.CL_OUTPUT_TOKENS)
        assert entry.cost_for(*tokens) == pytest.approx(model.cost_for(*tokens))


# --- the CLI verb --------------------------------------------------------------------------

def test_the_cli_screens_without_spending(capsys):
    """``--screen`` is the step *before* a spend is approved, so it must not need a key.

    It is deliberately not reachable from ``--live`` and shares no code path with it: a
    person who has not decided to spend anything must be able to run the step that
    informs that decision.
    """
    from evaluation.__main__ import main

    assert main(["--screen"]) == 0
    output = capsys.readouterr().out

    assert "Candidate screen:" in output
    assert "cost spread" in output
    assert "Nothing here is a quality ranking" in output
    assert "No paid call has been made" not in output, (
        'the screen is not the dry run; conflating them would suggest it prices a run'
    )


def test_the_cli_screen_honours_the_slate_cap(capsys):
    from evaluation.__main__ import main

    assert main(["--screen", "--cap-slate", "3"]) == 0
    assert "slate cap 3" in capsys.readouterr().out


def test_the_cli_refuses_a_missing_record_with_a_usable_message():
    """A missing file must name the fix rather than raising a bare traceback."""
    from evaluation.__main__ import main

    with pytest.raises(SystemExit, match="No such listing record"):
        main(["--screen", "does/not/exist.json"])


def test_the_cli_screen_reports_the_control(capsys):
    """The shipped model is identified so challengers are measured against something real."""
    from evaluation.__main__ import main

    assert main(["--screen"]) == 0
    assert "Control (currently shipped" in capsys.readouterr().out
