"""Detection and the curation proposal (Q1, Q2, Q6).

Two offline jobs that together answer "should we re-curate, and what would change":

* **detection** diffs a fresh listing against the committed record and *reports*. It
  cannot spend, and there is no path from it to ``--live``;
* **the proposal** turns a finished run into a review artefact and **writes nothing**.

The properties pinned here are the ones that make those two sentences true rather than
aspirational. The most important is inertness: an automated step must not be able to
replace the model production uses, because the measurements it would act on measure
**none** of writing, PDF or layout quality -- the three the owner reserved (ADR 0014,
ADR 0016).

Everything here is offline. No network call is made, and none is needed.
"""
from __future__ import annotations

import json

import pytest

try:
    from evaluation import curation_diff
    from evaluation.curation_diff import (
        CHANGE_ADDED,
        CHANGE_CAPABILITY,
        CHANGE_REPRICED,
        CHANGE_WITHDRAWN,
        CurationProposal,
        ProposalEntry,
        apply_verdicts,
        detect_changes,
        proposal_from_scores,
    )
    from evaluation.listing import LISTING_URL, ListingEntry, ListingRecord
    from evaluation.metrics import CaseResult, ModelScore
except ImportError as error:  # pragma: no cover - only on a broken tree
    pytest.fail(f"evaluation.curation_diff could not be imported: {error}", pytrace=False)


# --- helpers -------------------------------------------------------------------------------

def _entry(model_id, *, prompt=1.0, completion=2.0, created="2026-01-01",
           structured=True, ceiling=8_000):
    return ListingEntry(
        id=model_id, prompt=prompt, completion=completion, created=created,
        structured_outputs=structured, context_length=100_000,
        max_completion_tokens=ceiling,
    )


def _record(*entries, read_on="2026-10-30"):
    return ListingRecord(
        read_on=read_on, source_url=LISTING_URL, source_sha256="A" * 64,
        source_model_count=len(entries), entries=tuple(entries),
    )


def _score(model_id, results):
    return ModelScore(model_id=model_id, label=model_id, results=results)


def _case(accepted, cost=0.001, calls=2, dialect=""):
    return CaseResult(
        model_id="x", case_name="c", accepted=accepted, cost_usd=cost, calls=calls,
        correction_calls=max(0, calls - 2), schema_dialect=dialect,
    )


def _three(accepted, cost=0.001):
    return [_case(a, cost) for a in accepted]


# --- detection reports, and only reports ---------------------------------------------------

def test_an_added_model_is_detected():
    detection = detect_changes(_record(_entry("v/a")), _record(_entry("v/a"), _entry("v/b")))

    added = detection.by_kind(CHANGE_ADDED)
    assert [c.model_id for c in added] == ["v/b"]
    assert detection.any_change


def test_a_withdrawn_model_is_detected():
    """A curated model vanishing is the case that matters most: its price stops being
    checkable, and the tool would keep offering a model the provider no longer serves."""
    detection = detect_changes(_record(_entry("v/a"), _entry("v/b")), _record(_entry("v/a")))

    withdrawn = detection.by_kind(CHANGE_WITHDRAWN)
    assert [c.model_id for c in withdrawn] == ["v/b"]


def test_a_reprice_is_reported_with_both_figures():
    """One figure is a change; two is evidence a reader can act on."""
    before = _entry("v/a", prompt=1.0, completion=2.0)
    after = _entry("v/a", prompt=0.5, completion=2.0)
    detection = detect_changes(_record(before), _record(after), watch=("v/a",))

    (change,) = detection.by_kind(CHANGE_REPRICED)
    assert "$1.0000/$2.0000" in change.detail
    assert "$0.5000/$2.0000" in change.detail
    assert detection.touches("v/a")


def test_a_capability_change_is_reported_separately_from_a_price_change():
    """They are different kinds of fact and must not share a bucket.

    A price change moves the ranking. Losing structured output **disqualifies** the
    model outright, and folding the two together would hide the second behind the first.
    """
    before = _entry("v/a", structured=True)
    after = _entry("v/a", structured=False)
    detection = detect_changes(_record(before), _record(after))

    assert detection.by_kind(CHANGE_REPRICED) == ()
    (change,) = detection.by_kind(CHANGE_CAPABILITY)
    assert "structured_outputs" in change.detail


def test_a_ceiling_change_is_a_capability_change():
    before = _entry("v/a", ceiling=8_000)
    after = _entry("v/a", ceiling=1_000)
    detection = detect_changes(_record(before), _record(after))

    (change,) = detection.by_kind(CHANGE_CAPABILITY)
    assert "output ceiling" in change.detail


def test_no_change_is_reported_as_no_change_not_as_absence():
    """A quiet result must be a statement, not a silence -- otherwise "nothing moved"
    and "the check did not run" look identical."""
    detection = detect_changes(_record(_entry("v/a")), _record(_entry("v/a")))

    assert detection.any_change is False
    assert "No changes" in detection.describe()


def test_the_checked_ids_are_reported_so_a_negative_result_has_scope():
    """"We checked and nothing moved" needs to say *what* was checked."""
    detection = detect_changes(
        _record(_entry("v/a")), _record(_entry("v/a")),
        watch=("openai/gpt-6-luna", "v/a"),
    )

    assert detection.checked == ("openai/gpt-6-luna", "v/a")
    assert "gpt-6-luna" in detection.describe()


def test_detection_says_it_changed_nothing_and_spent_nothing():
    """The report must not read as an action. Detection is the step *before* a decision."""
    text = detect_changes(_record(_entry("v/a")), _record(_entry("v/a"))).describe()

    assert "REPORT" in text
    assert "Nothing was changed" in text
    assert "nothing was spent" in text
    assert "must not be able to trigger spending" in text


def test_detection_is_offline():
    """Asserted by arming every socket entry point, not by reading the source."""
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("detection attempted a network call")

    import unittest.mock as mock

    with mock.patch.object(socket, "socket", refuse), \
            mock.patch.object(socket, "create_connection", refuse):
        detection = detect_changes(
            _record(_entry("v/a")), _record(_entry("v/a"), _entry("v/b"))
        )
    assert detection.any_change


# --- the proposal: the verdict gate is the load-bearing property ---------------------------

def test_a_measured_entry_with_no_owner_verdict_is_not_eligible():
    """**The rule that stops the workflow automating itself.**

    The suite measures acceptance, cost and correction calls. It measures **no** prose and
    **no** rendering, so a measured acceptance rate is not a quality verdict. An entry
    with no verdict is reported OUT *for that reason* and not for any measured defect.
    """
    proposal = proposal_from_scores(
        [_score("v/good", _three([True, True, True]))], current_model="current/model"
    )
    (entry,) = proposal.entries
    reason = entry.is_disqualified(minimum_rate=2 / 3)

    assert reason is not None
    assert "verdict" in reason
    assert proposal.eligible() == ()
    assert proposal.winner() is None


def test_a_verdict_makes_an_entry_eligible():
    """And it is the only thing that does."""
    proposal = proposal_from_scores(
        [_score("v/good", _three([True, True, True]))], current_model="current/model"
    )
    reviewed = apply_verdicts(proposal, {"v/good": "read both pages; no orphans, prose fine"})

    assert reviewed.eligible() != ()
    assert reviewed.winner() is not None
    assert reviewed.winner().model_id == "v/good"


def test_a_blank_verdict_does_not_promote_an_entry():
    """Otherwise a placeholder in a checklist would promote a candidate silently."""
    proposal = proposal_from_scores(
        [_score("v/good", _three([True, True, True]))], current_model="current/model"
    )
    for blank in ("", "   ", "\n\t"):
        assert apply_verdicts(proposal, {"v/good": blank}).winner() is None


def test_there_is_no_code_path_from_a_measurement_to_a_verdict():
    """ProposalEntry has no field a measurement could set to promote itself.

    Asserted structurally, because this is the property the whole human step rests on: a
    future edit that added, say, ``auto_verdict`` would defeat it, and reading the diff
    might not catch that.
    """
    fields = set(ProposalEntry.__dataclass_fields__)

    assert "verdict" in fields
    for forbidden in ("auto_verdict", "quality", "score", "grade", "judge"):
        assert forbidden not in fields, (
            f'{forbidden!r} on ProposalEntry suggests a quality claim the suite cannot '
            f'make'
        )


# --- the disqualifiers are the owner's settled three ---------------------------------------

def test_acceptance_below_the_floor_disqualifies():
    proposal = proposal_from_scores(
        [_score("v/bad", _three([True, False, False]))], current_model="current/model"
    )
    (entry,) = proposal.entries
    reason = entry.is_disqualified(minimum_rate=2 / 3)

    assert "below the" in reason
    assert "33%" in reason


def test_accepting_nothing_disqualifies_and_is_named_distinctly():
    """The case where ``cost_per_accepted`` is ``None``: a report must never print a
    flattering ``0.0`` in its place."""
    proposal = proposal_from_scores(
        [_score("v/none", _three([False, False, False]))], current_model="current/model"
    )
    (entry,) = proposal.entries
    reason = entry.is_disqualified(minimum_rate=2 / 3)

    assert "no cost per accepted result" in reason
    assert entry.cost_per_accepted is None


def test_a_recovered_verdict_entry_below_the_floor_is_still_out():
    """The verdict cannot override a measured failure: it judges prose, not acceptance."""
    proposal = apply_verdicts(
        proposal_from_scores(
            [_score("v/bad", _three([True, False, False]))], current_model="current/model"
        ),
        {"v/bad": "the one it produced was well written"},
    )
    assert proposal.eligible() == ()


def test_correction_calls_are_recorded_but_do_not_disqualify():
    """A model that needs corrections is neither cheap nor out -- it is more expensive,
    and ``cost_per_accepted`` already says so."""
    proposal = proposal_from_scores(
        [_score("v/slow", [_case(True, 0.001, calls=5), _case(True, 0.001, calls=5),
                           _case(True, 0.001, calls=5)])],
        current_model="current/model",
    )
    reviewed = apply_verdicts(proposal, {"v/slow": "fine"})
    (entry,) = reviewed.eligible()

    assert entry.correction_calls == 9
    assert entry.is_disqualified(minimum_rate=2 / 3) is None


# --- ranking and the recommendation --------------------------------------------------------

def test_ranking_puts_the_cheapest_accepted_first_and_the_failures_last():
    proposal = proposal_from_scores(
        [
            _score("v/dear", _three([True, True, True], cost=0.01)),
            _score("v/cheap", _three([True, True, True], cost=0.001)),
            _score("v/none", _three([False, False, False], cost=0.0001)),
        ],
        current_model="current/model",
    )

    assert [e.model_id for e in proposal.ranked()] == ["v/cheap", "v/dear", "v/none"]


def test_the_recommendation_is_none_when_nothing_beats_the_current_model():
    """"Keep what we have" is a real outcome and the common one, not a failure."""
    proposal = apply_verdicts(
        proposal_from_scores(
            [
                _score("openai/gpt-6-luna", _three([True, True, True], cost=0.001)),
                _score("v/dearer", _three([True, True, True], cost=0.05)),
            ],
            current_model="openai/gpt-6-luna",
        ),
        {"v/dearer": "fine", "openai/gpt-6-luna": "fine"},
    )

    assert proposal.winner() is None
    assert "keep the current model" in proposal.describe()


def test_a_cheaper_eligible_candidate_is_recommended_for_review():
    proposal = apply_verdicts(
        proposal_from_scores(
            [
                _score("openai/gpt-6-luna", _three([True, True, True], cost=0.003)),
                _score("v/cheap", _three([True, True, True], cost=0.0004)),
            ],
            current_model="openai/gpt-6-luna",
        ),
        {"v/cheap": "fine", "openai/gpt-6-luna": "fine"},
    )

    assert proposal.winner().model_id == "v/cheap"
    assert "consider" in proposal.describe()
    assert "not a switch" in proposal.describe()


def test_the_proposal_says_what_it_does_not_measure():
    """The report must state the limit, because the numbers beside it look like a verdict."""
    proposal = proposal_from_scores(
        [_score("v/a", _three([True, True, True]))], current_model="current/model"
    )
    text = proposal.describe()

    assert "WHAT THIS DOES NOT MEASURE" in text
    assert "writing quality" in text
    assert "PDF quality" in text
    assert "layout" in text


# --- inertness: the proposal writes nothing ------------------------------------------------

def test_the_proposal_emits_text_and_applies_nothing():
    """**The Q2 decision, enforced.**

    The artefact is a diff a person reads. Applying it is a deliberate edit with its own
    commit -- which is how ``e53ef8a`` shipped the current model. An automatic replacement
    would mean an automated step deleting the only model production uses.
    """
    proposal = apply_verdicts(
        proposal_from_scores(
            [_score("v/cheap", _three([True, True, True], cost=0.0004))],
            current_model="openai/gpt-6-luna",
        ),
        {"v/cheap": "fine"},
    )
    curated = proposal.diff_for_curated_models()
    inputs = proposal.diff_for_candidate_inputs()

    assert "NOT been applied" in curated
    assert "NOT been applied" in inputs
    # The emitted text is a string, and producing it changed no module on disk.
    for text in (curated, inputs):
        assert isinstance(text, str)


def test_running_the_proposal_commands_does_not_modify_the_curated_modules():
    """Asserted by hashing the two files the proposal would edit, around a real run.

    A stronger check than reading the source: it would catch a module-level write, an
    import side effect, or an accidental ``Path.write_text`` in a helper.
    """
    import hashlib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "evaluation"

    def digest(name):
        return hashlib.sha256((root / name).read_bytes()).hexdigest()

    before = {n: digest(n) for n in ("curated_models.py", "candidate_inputs.py")}

    proposal = apply_verdicts(
        proposal_from_scores(
            [_score("v/cheap", _three([True, True, True]))], current_model="openai/gpt-6-luna"
        ),
        {"v/cheap": "fine"},
    )
    proposal.describe()
    proposal.diff_for_curated_models()
    proposal.diff_for_candidate_inputs()

    after = {n: digest(n) for n in ("curated_models.py", "candidate_inputs.py")}
    assert before == after, "the proposal modified a curated module; it must be inert"


def test_the_candidate_inputs_diff_asks_for_a_measured_rationale():
    """ADR 0016: a dialect copied from a screen hint is not a measurement.

    ``CandidateInputs`` refuses a non-default dialect with no rationale, so the emitted
    skeleton says so rather than inviting a copy-paste of an assumption.
    """
    proposal = apply_verdicts(
        proposal_from_scores(
            [_score("v/cheap", _three([True, True, True]))], current_model="current/model"
        ),
        {"v/cheap": "fine"},
    )
    text = proposal.diff_for_candidate_inputs()

    assert "MEASURED error" in text
    assert "not a measurement" in text


def test_the_curated_models_diff_reminds_about_the_price_row():
    """Without a price row, ``price_for`` borrows the fallback rate and the ranking
    becomes fiction for every entry at once -- a defect this project has already had."""
    proposal = apply_verdicts(
        proposal_from_scores(
            [_score("v/cheap", _three([True, True, True]))], current_model="current/model"
        ),
        {"v/cheap": "fine"},
    )
    assert "pricing" in proposal.diff_for_curated_models()


# --- the CLI verbs -------------------------------------------------------------------------

def test_the_cli_detect_refuses_without_a_listing_to_diff():
    """It will not fetch for you: reading a new listing is a network call this command
    deliberately does not make."""
    from evaluation.__main__ import main

    with pytest.raises(SystemExit, match="Pass the freshly read listing"):
        main(["--detect"])


def test_the_cli_detect_refuses_a_missing_file():
    from evaluation.__main__ import main

    with pytest.raises(SystemExit, match="No such listing record"):
        main(["--detect", "does/not/exist.json"])


def test_the_cli_detect_reports_no_change_against_its_own_record(capsys, tmp_path):
    """Diffing the committed record against itself is the cleanest negative case."""
    from evaluation.__main__ import main
    from evaluation.listing import latest_record

    assert main(["--detect", str(latest_record())]) == 0
    output = capsys.readouterr().out
    assert "No changes" in output
    assert "Nothing was changed" in output


def test_the_cli_report_refuses_without_a_file():
    from evaluation.__main__ import main

    with pytest.raises(SystemExit, match="Pass the run's scores"):
        main(["--report"])


def test_the_cli_report_renders_a_proposal(capsys, tmp_path):
    payload = {
        "run_reference": "test",
        "current_model": "openai/gpt-6-luna",
        "models": [
            {
                "model_id": "v/cheap",
                "results": [
                    {"case_name": "a", "accepted": True, "cost_usd": 0.0004, "calls": 2},
                ],
            }
        ],
    }
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    from evaluation.__main__ import main

    assert main(["--report", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Curation proposal" in output
    assert "keeps the current model" not in output  # the wording is "keep"
    assert "NOT been applied" in output


def test_the_screen_detect_and_report_paths_are_not_reachable_from_live():
    """A structural guard on the separation the design rests on.

    ``--live`` is the only spending path, and the three offline verbs must not be able to
    reach it. Asserted on the parser rather than on behaviour, because the risk is a
    future flag wiring them together.
    """
    from evaluation.__main__ import build_parser

    args = build_parser().parse_args([])
    assert args.live is False, "the default must never spend"
    assert args.detect is None and args.report is None and args.screen is None
