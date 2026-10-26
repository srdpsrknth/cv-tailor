"""The evaluation suite and the curated model set (Phase 3, item 6).

The suite itself makes paid calls when asked to. These tests never do, and the point
of most of them is to prove that the *code* cannot either without an explicit,
budgeted instruction:

* **offline by default** -- ``dry_run`` and ``plan`` touch no network, and there is no
  parameter default that spends;
* **out of CI** -- the suite is not collected by pytest, asserted rather than assumed,
  so a test job cannot make a paid call through it;
* **the cap fails closed** -- an over-budget plan is refused *before* the first call, a
  missing cap is a refusal rather than "unlimited", and the cap is re-checked before
  every call rather than once at the start;
* **fixtures stay synthetic** -- the suite reads only ``tests/fixtures/`` and refuses a
  path that escapes it, so a live run cannot send a real profile to a third party;
* **the curated set is honest** -- it is small, it spans cost levels, every entry's
  price and capability come from OpenRouter's own listing, and every entry is marked
  UNMEASURED because no quality run has happened.
"""
from __future__ import annotations

import pytest


# --- the suite cannot spend by accident ---------------------------------------------------

def test_dry_run_makes_no_call_and_says_so():
    from evaluation.runner import dry_run

    output = dry_run()

    assert 'DRY RUN' in output
    assert 'No paid call has been made' in output


def test_the_default_cap_is_the_agreed_budget():
    """The owner set the curation budget at under $5; the default enforces it."""
    from evaluation.runner import DEFAULT_CAP_USD

    assert DEFAULT_CAP_USD == 5.0


def test_the_whole_curated_run_fits_the_agreed_budget():
    """Priced before anything is sent, against every curated model."""
    from evaluation.runner import plan

    budget = plan()

    assert budget.total_usd < 5.0, 'the curated run must fit the agreed budget'
    assert not budget.exceeds()


def test_a_plan_is_refused_before_the_first_call():
    """A cap enforced only while spending has already failed: the money is gone."""
    from evaluation.runner import BudgetExceeded, check_fixtures, plan

    budget = plan(cap_usd=0.01)

    assert budget.exceeds()


def test_live_run_requires_explicit_authorisation():
    """No parameter default spends, so a truthy accident cannot start a paid run."""
    from evaluation.runner import LiveRunNotAuthorised, live_run

    with pytest.raises(LiveRunNotAuthorised, match='authorisation'):
        live_run(authorised=False, run_one=lambda case, model: None)


def test_live_run_refuses_an_over_budget_plan():
    """Refused before the provider is built, so nothing is spent discovering it."""
    from evaluation.runner import BudgetExceeded, live_run

    calls: list = []

    def run_one(case, model):
        calls.append((case, model))
        raise AssertionError('run_one must not be reached on an over-budget plan')

    with pytest.raises(BudgetExceeded):
        live_run(cap_usd=0.01, authorised=True, run_one=run_one)

    assert calls == [], 'an over-budget plan must spend nothing at all'


def test_a_missing_cap_is_a_refusal_not_an_unlimited_budget():
    """Defaulting an absent cap to "unlimited" is the failure this guards."""
    from evaluation.cases import BudgetPlan

    unlimited = BudgetPlan(per_model_usd={'m': 1.0}, cap_usd=None)
    assert unlimited.exceeds() is True


def test_the_cap_is_checked_before_every_call_not_only_at_the_start():
    """A cap checked once at the beginning is a cap the last model walks through.

    The cap is set **above** the plan's projection so the start-check passes, and the
    simulated calls are priced so that crossing it can only be detected mid-run.
    """
    from evaluation.cases import CASES
    from evaluation.curated_models import CURATED_MODELS
    from evaluation.metrics import CaseResult
    from evaluation.runner import plan, live_run

    seen: list = []

    def run_one(case, model):
        seen.append((model.id, case.name))
        # Each accepted case is priced well above a single case's projected share, so
        # the cumulative spend crosses the cap while cases remain.
        return CaseResult(
            model_id=model.id, case_name=case.name, accepted=True, cost_usd=0.50, calls=2,
        )

    models = tuple(sorted(CURATED_MODELS, key=lambda m: m.input_per_1m))
    # Start below the cap, then let spend cross it: 0.50/case crosses 1.75 after 4 cases.
    cap = 1.75
    assert not plan(CASES, models, cap_usd=cap).exceeds(), 'the start-check must pass'

    live_run(cases=CASES, models=models, cap_usd=cap, authorised=True, run_one=run_one)

    total_cases = len(CASES) * len(models)
    assert len(seen) < total_cases, (
        'the run completed every case, so the cap was not enforced mid-run'
    )
    assert len(seen) >= 1


def test_the_evaluation_suite_is_not_collected_by_pytest():
    """It stays out of CI: the paid path must not be reachable from a test job."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    # Nothing under evaluation/ may be named like a test module.
    offenders = [
        str(path.relative_to(root))
        for path in (root / 'evaluation').rglob('*.py')
        if path.name.startswith('test_') or path.name == 'conftest.py'
    ]
    assert offenders == [], f'the paid suite would be collected by pytest: {offenders}'

    # And pytest, asked to collect the suite's directory, finds nothing.
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', str(root / 'evaluation')],
        capture_output=True, text=True, cwd=root, timeout=120,
    )
    assert 'no tests ran' in completed.stdout or completed.returncode == 5, (
        f'pytest collected something from evaluation/: {completed.stdout[-500:]}'
    )


def test_the_ci_workflow_does_not_invoke_the_evaluation_suite():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'tests.yml'
    )
    if not workflow.exists():
        pytest.skip('no CI workflow to check')
    text = workflow.read_text(encoding='utf-8')

    assert 'evaluation' not in text, 'CI must not run the paid evaluation suite'


# --- fixtures stay synthetic -----------------------------------------------------------------

def test_every_case_fixture_resolves_inside_tests_fixtures():
    from evaluation.runner import check_fixtures

    assert check_fixtures() == []


def test_the_suite_refuses_a_path_outside_the_fixture_directory():
    """A live run sends what it loads, so escaping the fixture root is a leak."""
    from evaluation.cases import fixture_path

    with pytest.raises((ValueError, FileNotFoundError)):
        fixture_path('../../.env')


def test_the_suite_never_reads_the_private_store():
    """Asserted on the source: the store holds real candidates."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / 'evaluation'
    for path in root.rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        assert 'CVTAILOR_STORE' not in text, f'{path.name} reaches for the private store'
        assert 'cv-tailor-data' not in text, f'{path.name} names this machine\'s store'


# --- a measurement must not be served from the cache -------------------------------------------

def test_the_evaluation_bypasses_the_generation_cache():
    """A benchmark answer from a cache measures the cache, not the model.

    ``tailor_documents`` defaults to ``use_cache=True`` and this suite drives the **real**
    pipeline with a loose ``profile_path``, so it shares ``<store>/cache/<profile_id>/``
    with the user's own runs. A hit makes no API call, reports zero usage, and therefore
    scores as an **accepted case costing $0.00 with 0 calls** -- a fabricated best result.

    The whole 15-pair grid has a distinct key, so the exposure is a *repeat* of a pair --
    which is exactly the run whose numbers are being paid for. The bypass is therefore
    asserted on the call rather than left to a default.
    """
    from evaluation import live

    captured: dict = {}

    def fake_tailor_documents(posting, profile, **kwargs):
        captured.update(kwargs)

        class _Result:
            status = 'success'
            cv_page_count = 2

        return _Result()

    import services.tailor_service as tailor_service

    original = tailor_service.tailor_documents
    tailor_service.tailor_documents = fake_tailor_documents
    try:
        from evaluation.cases import CASES
        from evaluation.curated_models import CURATED_MODELS

        live.run_one_case(CASES[0], CURATED_MODELS[0])
    finally:
        tailor_service.tailor_documents = original

    assert captured.get('use_cache') is False, (
        'the evaluation must not read or write the generation cache: a cached answer is '
        'reported as an accepted run costing $0.00, which would top the ranking'
    )


def test_the_evaluation_still_names_a_provider_and_a_model():
    """The bypass must not have been bought by dropping the routing the run measures."""
    from evaluation import live
    from evaluation.cases import CASES
    from evaluation.curated_models import CURATED_MODELS

    captured: dict = {}

    def fake_tailor_documents(posting, profile, **kwargs):
        captured.update(kwargs)

        class _Result:
            status = 'success'
            cv_page_count = 2

        return _Result()

    import services.tailor_service as tailor_service

    original = tailor_service.tailor_documents
    tailor_service.tailor_documents = fake_tailor_documents
    try:
        live.run_one_case(CASES[0], CURATED_MODELS[0])
    finally:
        tailor_service.tailor_documents = original

    config = captured['config']
    assert config.provider_name == 'openrouter'
    assert config.model == CURATED_MODELS[0].id


def test_the_evaluation_uses_a_synthetic_profile_identity():
    """It must never file output under whatever id the developer's `.env` names.

    ``tailor_documents`` writes the job folder under the resolved ``profile_id``, and a
    real ``.env`` carries the developer's own (this machine's says ``sreedeep``). Left
    alone, an evaluation over *synthetic* fixtures files job folders -- accepted
    documents included -- under a real candidate's profile. It surfaced as a
    ``PermissionError`` on a read-only path, but on a writable one it would have
    silently mixed evaluation output into real candidate data.
    """
    from evaluation import live
    from evaluation.cases import CASES
    from evaluation.curated_models import CURATED_MODELS

    captured: dict = {}

    def fake_tailor_documents(posting, profile, **kwargs):
        captured.update(kwargs)

        class _Result:
            status = 'success'
            cv_page_count = 2

        return _Result()

    import services.tailor_service as tailor_service

    original = tailor_service.tailor_documents
    tailor_service.tailor_documents = fake_tailor_documents
    try:
        live.run_one_case(CASES[0], CURATED_MODELS[0])
    finally:
        tailor_service.tailor_documents = original

    config = captured['config']
    assert config.profile_id, 'the evaluation must name a profile id'
    assert config.profile_id.startswith('eval_'), (
        f'the evaluation resolved {config.profile_id!r}, which is not a synthetic id; '
        f'it would file synthetic output under a real candidate'
    )
    assert config.profile_id != 'sreedeep'


def test_a_failed_case_still_reports_what_it_spent():
    """A failure is measured, not written off as free.

    This is the mirror of the cache bug. ``run_one_case`` used to return a failure
    ``CaseResult`` with the default ``cost_usd=0.0``, discarding every call the case had
    actually paid for -- the spend accumulates on the service, and ``tailor_documents``
    normally creates and discards it. Since the ranking metric is cost per **accepted**
    result, a model that spent money and accepted nothing would have reported $0.00 and
    looked like the cheapest option in the table.
    """
    from evaluation import live
    from evaluation.cases import CASES
    from evaluation.curated_models import CURATED_MODELS

    import services.tailor_service as tailor_service

    def failing_tailor_documents(posting, profile, **kwargs):
        # Simulate a run that made real, paid calls and then failed the gate.
        service = kwargs.get('service')
        assert service is not None, (
            'the evaluation must pass its own service so spend survives a failure'
        )
        service.spent_usd = 0.0123
        service.calls_made = 3
        raise ValueError('Could not produce a valid cover_letter document')

    original = tailor_service.tailor_documents
    tailor_service.tailor_documents = failing_tailor_documents
    try:
        result = live.run_one_case(CASES[0], CURATED_MODELS[0])
    finally:
        tailor_service.tailor_documents = original
    assert result.accepted is False
    assert result.error
    assert result.cost_usd == pytest.approx(0.0123), (
        'a failed case must report the money it actually spent, or failing models '
        'appear free'
    )
    assert result.calls == 3


# --- the curated set --------------------------------------------------------------------------

def test_the_set_is_small():
    """Owner requirement: do NOT expose the catalogue.

    The ceiling moved from 6 to 8 on 2026-10-26 by the owner's instruction, when the
    first five-model draft was rejected for lacking variety ("three google models, one
    claude and one deepseek -- fine but not much variety"). Widening the *ceiling* is
    not the same as abandoning the requirement: the set must still be a decision the
    tool has made, not a catalogue, so the proportion guard below is the one that
    actually holds the line -- 8 of 467 is under 2% of the listing.
    """
    from evaluation.curated_models import CURATED_MODELS, LISTING_MODEL_COUNT

    assert len(CURATED_MODELS) <= 8, 'a wall of models is the thing to avoid'
    assert len(CURATED_MODELS) < LISTING_MODEL_COUNT / 10


def test_the_set_spans_several_families():
    """Owner requirement, recorded 2026-10-26: variety, not five near-copies.

    The rejected draft was three Google models, one Anthropic and one DeepSeek. Five
    entries from three vendors is really two engineering choices wearing five labels,
    and it cannot answer the question the curation exists to ask -- whether a
    non-Google model writes these documents as well.
    """
    from evaluation.curated_models import CURATED_MODELS

    families = {model.id.split('/')[0] for model in CURATED_MODELS}
    assert len(families) >= 5, f'too few distinct families: {sorted(families)}'


def test_every_entry_is_recent_enough():
    """Owner requirement, recorded 2026-10-26: "models from oct 2025 onwards only".

    This is a real constraint rather than a preference, because the cheapest tiers of
    any catalogue are cheap *because* they are old: the first draft's two cheapest
    entries were a 2024 Mistral and a 2025-08 OpenAI model, and both would have been
    dropped by this rule alone.
    """
    from datetime import date

    from evaluation.curated_models import CURATED_MODELS, MIN_CREATED

    floor = date.fromisoformat(MIN_CREATED)
    for model in CURATED_MODELS:
        assert model.created, f'{model.id} records no creation date'
        created = date.fromisoformat(model.created)
        assert created >= floor, (
            f'{model.id} was created {model.created}, older than the {MIN_CREATED} floor'
        )


def test_every_entry_is_priced_on_the_route_the_run_uses():
    """A curated model with no price row is silently priced at the default's rate.

    Asserted here as well as in ``test_pricing.py`` because the two files guard
    different things: that one protects the table, this one protects the set. Either
    alone would let the other drift.
    """
    from evaluation.curated_models import unpriced_entries

    assert unpriced_entries() == (), (
        'a curated model without an OpenRouter price row would report the default '
        "route's rate as its own cost, and the cost ranking would be fiction"
    )


def test_the_set_spans_different_cost_levels():
    """Owner requirement: so the user sees the trade-off and decides."""
    from evaluation.curated_models import curated_models, has_cost_spread

    assert has_cost_spread(), 'the set must span genuinely different cost levels'
    tiers = {model.tier for model in curated_models()}
    assert tiers == {'economy', 'balanced', 'frontier'}


def test_the_set_is_ordered_cheapest_first():
    from evaluation.curated_models import NATURAL_COST_ORDER, curated_models

    tiers = [model.tier for model in curated_models()]
    assert tiers == sorted(tiers, key=NATURAL_COST_ORDER.index)


def test_every_entry_declares_an_unmeasured_ranking():
    """The honest claim, made machine-checkable rather than a sentence in a document.

    No quality run has happened, so no entry may claim a measured ranking. When the
    budgeted run does happen, this test is what forces the marker to be updated
    rather than the claim being quietly made in prose.
    """
    from evaluation.curated_models import CURATED_MODELS, unmeasured_entries

    assert len(unmeasured_entries()) == len(CURATED_MODELS)
    for model in CURATED_MODELS:
        assert model.is_measured is False
        assert model.verified == 'price+capability'
        assert model.measured_notes is None, 'no run has populated notes'


def test_no_entry_carries_an_invented_quality_claim():
    """Guidance may describe what a model is for; it may not rank it on quality."""
    from evaluation.curated_models import CURATED_MODELS

    forbidden = ('best', 'highest quality', 'state of the art', 'outperforms', 'top ')
    for model in CURATED_MODELS:
        lowered = model.guidance.lower()
        for phrase in forbidden:
            assert phrase not in lowered, (
                f'{model.id} claims {phrase!r} without measurement'
            )


def test_every_entry_records_the_listing_it_came_from():
    from evaluation.curated_models import LISTING_SHA256, LISTING_URL, LISTING_VERIFIED_ON

    assert LISTING_URL.startswith('https://openrouter.ai/')
    assert len(LISTING_SHA256) == 64
    assert LISTING_VERIFIED_ON == '2026-10-26'


def test_no_curated_model_lacks_structured_output_support():
    """A model that cannot be relied on for schema-valid JSON is not an option.

    Asserted from the recorded listing rather than from reputation: this is the
    filter that excludes the otherwise-cheapest candidates.
    """
    import json
    from pathlib import Path

    from evaluation.curated_models import CURATED_MODELS

    # The listing is not committed (it is a 467-model JSON blob); when it is absent the
    # test says so rather than passing vacuously.
    listing = Path(__file__).resolve().parents[1] / '.tmp' / 'openrouter_models_2026-10-26.json'
    if not listing.exists():
        pytest.skip(
            'the recorded OpenRouter listing is not present in this working copy; '
            'the curated ids were read from it and hashed in evaluation.curated_models'
        )
    data = json.loads(listing.read_text(encoding='utf-8'))
    by_id = {r['id']: r for r in data['data']}

    for model in CURATED_MODELS:
        assert model.id in by_id, f'{model.id} is no longer in the listing'
        entry = by_id[model.id]
        params = entry.get('supported_parameters') or []
        assert 'structured_outputs' in params, f'{model.id} does not support structured output'


def test_the_recorded_rates_match_the_listing():
    """A price that drifted from the listing is worse than no price."""
    import json
    from pathlib import Path

    from evaluation.curated_models import CURATED_MODELS

    listing = Path(__file__).resolve().parents[1] / '.tmp' / 'openrouter_models_2026-10-26.json'
    if not listing.exists():
        pytest.skip('recorded listing not present in this working copy')
    data = json.loads(listing.read_text(encoding='utf-8'))
    by_id = {r['id']: r for r in data['data']}

    for model in CURATED_MODELS:
        pricing = by_id[model.id]['pricing']
        assert model.input_per_1m == pytest.approx(float(pricing['prompt']) * 1e6)
        assert model.output_per_1m == pytest.approx(float(pricing['completion']) * 1e6)


def test_an_uncurated_model_is_not_findable():
    """Offering the catalogue is what the requirement forbids; find() must not do it."""
    from evaluation.curated_models import find

    assert find('some/vendor-model') is None
    assert find('amazon/nova-micro-v1') is None, (
        'Nova does not advertise structured output, so it is not an option here'
    )


def test_the_cli_refuses_an_uncurated_model():
    from evaluation.__main__ import _selected_models

    with pytest.raises(SystemExit, match='not in the curated set'):
        _selected_models(['some/vendor-model'])


def test_the_cli_lists_the_set_without_spending(capsys):
    from evaluation.__main__ import main

    assert main(['--list-models']) == 0
    output = capsys.readouterr().out
    assert 'UNMEASURED' in output
    assert 'not a verdict' in output


def test_the_cli_defaults_to_a_dry_run(capsys):
    """The default must not be the mode that spends."""
    from evaluation.__main__ import main

    assert main([]) == 0
    output = capsys.readouterr().out
    assert 'DRY RUN' in output
    assert 'No paid call has been made' in output


# --- the metrics --------------------------------------------------------------------------------

def test_cost_per_accepted_result_is_the_headline_metric():
    """A cheap model that fails validation and retries three times is not cheap."""
    from evaluation.metrics import CaseResult, ModelScore

    cheap_but_failing = ModelScore(model_id='cheap', results=[
        CaseResult(model_id='cheap', case_name='a', accepted=False, cost_usd=0.03, calls=3),
        CaseResult(model_id='cheap', case_name='b', accepted=False, cost_usd=0.03, calls=3),
    ])
    dearer_but_working = ModelScore(model_id='dear', results=[
        CaseResult(model_id='dear', case_name='a', accepted=True, cost_usd=0.05, calls=2),
        CaseResult(model_id='dear', case_name='b', accepted=True, cost_usd=0.05, calls=2),
    ])

    # Per attempt the failing model looks cheaper...
    assert cheap_but_failing.cost_per_attempt < dearer_but_working.cost_per_attempt
    # ...but it accepted nothing, so it has no cost per accepted result at all.
    assert cheap_but_failing.cost_per_accepted is None
    assert dearer_but_working.cost_per_accepted == pytest.approx(0.05)


def test_a_model_that_accepts_nothing_is_not_reported_as_cheapest():
    """Reporting 0.0 would make the worst performer look like the best value."""
    from evaluation.metrics import CaseResult, ModelScore, rank

    nothing = ModelScore(model_id='nothing', results=[
        CaseResult(model_id='nothing', case_name='a', accepted=False, cost_usd=0.01),
    ])
    working = ModelScore(model_id='working', results=[
        CaseResult(model_id='working', case_name='a', accepted=True, cost_usd=9.99),
    ])

    assert rank([nothing, working])[0].model_id == 'working'


def test_the_summary_shows_both_cost_figures():
    """The gap between them is the finding; showing one would hide it."""
    from evaluation.metrics import CaseResult, ModelScore, summarise

    score = ModelScore(model_id='m', results=[
        CaseResult(model_id='m', case_name='a', accepted=True, cost_usd=0.02, calls=2),
        CaseResult(model_id='m', case_name='b', accepted=False, cost_usd=0.02, calls=3),
    ])
    summary = summarise([score])

    assert '/attempt' in summary
    assert '/ACCEPTED' in summary


def test_the_projection_is_pessimistic_not_flattering():
    """An over-estimate that refuses a run is safe; an under-estimate that overruns is not."""
    from evaluation.cases import CALLS_MAX_SUCCESSFUL, CALLS_WORST, project_cost

    pessimistic = project_cost(1.0, 1.0, 3, pessimistic=True)
    optimistic = project_cost(1.0, 1.0, 3, pessimistic=False)

    assert pessimistic > optimistic
    assert CALLS_WORST > CALLS_MAX_SUCCESSFUL
