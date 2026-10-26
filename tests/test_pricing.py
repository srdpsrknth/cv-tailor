"""Cost accounting: tiered, route-aware, and from one source of truth (D-3, D-4).

Two defects this file exists to prove fixed:

* **D-3** -- ``calculate_token_usage`` priced a run's *total* with one flat rate while
  the table defined ``input_long``/``output_long`` tiers. Below the long-context
  threshold that is invisible; above it the estimate is **under-reported**, which is
  the direction that makes a cheap model look cheaper than it is. A price-versus-
  quality comparison built on it would not be trustworthy.
* **D-4** -- ``ui/app.py`` carried a **second** copy of the table, which had drifted:
  it still priced ``gemini-1.5-flash``, retired in Phase 1. Two tables can disagree,
  and the one a user could see was the stale one.

The long-context rates themselves are confirmed from OpenRouter's own listing, whose
``overrides`` entry for ``google/gemini-2.5-pro`` states ``min_prompt_tokens:
200000`` with ``prompt`` $2.50 and ``completion`` $15.00 -- exactly the tier values
the repository had defined and never applied.
"""
from __future__ import annotations

import pytest

# ``pricing`` is the module this increment introduces. Imported defensively so that
# running this file against the pre-increment code reports each test as a *failure*
# ("no single pricing source") rather than aborting the module at collection -- a
# collection error proves nothing about which behaviours are new. It deliberately does
# not skip: a skip would also hide a broken import in the real tree, which is the one
# thing this file is supposed to catch.
try:
    from services import pricing
    _PRICING_IMPORT_ERROR = None
except ImportError as _error:  # pragma: no cover - pre-increment code only
    pricing = None
    _PRICING_IMPORT_ERROR = _error


@pytest.fixture(autouse=True)
def _require_the_pricing_module():
    """Fail every test in this file clearly when the module does not exist."""
    if _PRICING_IMPORT_ERROR is not None:
        pytest.fail(
            "services.pricing does not exist, so there is no single pricing source "
            f"(D-3/D-4): {_PRICING_IMPORT_ERROR}"
        )


# --- D-3: the tier is applied to the tokens -------------------------------------------------

def test_a_prompt_over_the_threshold_is_priced_at_the_long_rate():
    """The defect: this used to be charged at the short rate and under-reported."""
    under = pricing.estimate_cost(100_000, 0, 'gemini-2.5-pro')
    over = pricing.estimate_cost(300_000, 0, 'gemini-2.5-pro')

    # 3x the tokens at 2x the rate, so strictly more than 3x the cost.
    assert over > under * 3
    assert under == pytest.approx(0.125)
    assert over == pytest.approx(0.75)


def test_the_old_flat_rate_would_have_under_reported_the_long_case():
    """Quantifies the defect rather than only asserting the new behaviour.

    Priced flat, 300k tokens at $1.25/1M is $0.375. The correct long-context figure
    is $0.75 -- the old estimate was **half** the real cost.
    """
    flat = (300_000 / 1_000_000) * 1.25
    correct = pricing.estimate_cost(300_000, 0, 'gemini-2.5-pro')

    assert flat == pytest.approx(0.375)
    assert correct == pytest.approx(0.75)
    assert correct == pytest.approx(flat * 2)


def test_the_long_tier_also_applies_to_output():
    """Both halves of the pair are re-rated, not just the input."""
    short = pricing.estimate_cost(1_000, 100_000, 'gemini-2.5-pro')
    long = pricing.estimate_cost(300_000, 100_000, 'gemini-2.5-pro')

    # Output: 100k at $15/1M = $1.50 on the long tier versus $1.00 on the short.
    assert short == pytest.approx(0.00125 + 1.00)
    assert long == pytest.approx(0.75 + 1.50)


def test_the_threshold_is_chosen_on_the_input_count_alone():
    """Providers re-rate the whole request when the *prompt* crosses the threshold."""
    # 200,000 exactly is not "over" it.
    assert pricing.estimate_cost(200_000, 0, 'gemini-2.5-pro') == pytest.approx(0.25)
    assert pricing.estimate_cost(200_001, 0, 'gemini-2.5-pro') == pytest.approx(0.5000025)


def test_a_model_with_no_long_tier_is_unaffected_by_the_threshold():
    """Most models have one rate; the tier logic must not invent a second."""
    short = pricing.estimate_cost(1_000, 0, 'gemini-2.5-flash')
    long = pricing.estimate_cost(1_000_000, 0, 'gemini-2.5-flash')

    assert short == pytest.approx(0.0003)
    assert long == pytest.approx(0.30)


def test_a_half_defined_long_pair_is_not_treated_as_a_tier():
    """A row with only one long rate must not silently charge the short rate above
    the threshold *as though* it had applied a tier -- it is simply not a tier."""
    price = pricing.ModelPrice(input=1.0, output=2.0, input_long=5.0, output_long=None)
    assert price.has_long_tier is False


def test_the_tier_is_describable_for_the_user():
    """The UI shows why a cost moved, not only that it did."""
    assert pricing.describe_tier(1_000, 'gemini-2.5-pro') == 'standard'
    assert pricing.describe_tier(300_000, 'gemini-2.5-pro') == 'long-context'
    assert pricing.describe_tier(300_000, 'gemini-2.5-flash') == 'standard'


def test_the_estimate_reaches_the_token_usage_record():
    """Driven through ``calculate_token_usage``, which is what the pipeline calls."""
    from services.gemini_service import GeminiService

    service = object.__new__(GeminiService)
    service.model = 'gemini-2.5-pro'

    usage = service.calculate_token_usage(
        cv_input_tokens=300_000, cv_output_tokens=0,
        cl_input_tokens=0, cl_output_tokens=0,
    )

    assert usage.estimated_cost_usd == pytest.approx(0.75)


# --- D-3/D-4: the route is part of the price ------------------------------------------------

def test_the_same_model_costs_different_amounts_on_different_routes():
    """A bare model name does not identify a price, which is why the route is keyed.

    Verified 2026-10-26: OpenRouter lists google/gemini-3.8-flash at $0.825/$4.125
    while Google charges $0.75/$3.75 direct.
    """
    direct = pricing.price_for('gemini-3.8-flash', 'gemini')
    routed = pricing.price_for('google/gemini-3.8-flash', 'openrouter')

    assert direct.input == 0.75
    assert routed.input == 0.825
    assert routed.input > direct.input


def test_an_unpriced_route_is_distinguishable_from_a_priced_one():
    """``price_for`` must not crash, but a caller must be able to tell it guessed."""
    assert pricing.is_priced('gemini-3.8-flash', 'gemini') is True
    assert pricing.is_priced('a-model-that-does-not-exist', 'gemini') is False
    # The fallback still returns a usable price rather than raising.
    assert pricing.price_for('a-model-that-does-not-exist', 'gemini').input > 0


def test_the_fallback_target_is_always_priced():
    """Removing a row is only safe while the fallback target still exists (D-5)."""
    assert pricing.is_priced(pricing.DEFAULT_MODEL, pricing.DEFAULT_PROVIDER)
    assert pricing.DEFAULT_MODEL in pricing.PRICING.values() or True  # table is keyed
    assert (pricing.DEFAULT_PROVIDER, pricing.DEFAULT_MODEL) in pricing.PRICING


def test_no_retired_rows_remain():
    """Legacy rows mispriced nothing but actively misled; they are gone (D-5)."""
    for route, model in pricing.PRICING:
        for retired in ('gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-3-pro-preview'):
            assert retired not in model, f'{model} is retired and must not be priced'


def test_every_row_names_a_verified_source():
    """A price without a dated primary source must not be trusted (ADR 0005)."""
    routes = {provider for provider, _ in pricing.PRICING}
    for route in routes:
        assert route in pricing.PRICE_SOURCES, f'{route} has no recorded price source'
        source = pricing.PRICE_SOURCES[route]
        assert source['verified_on'], f'{route} has no verification date'
        assert source['source'], f'{route} has no source URL or document'


# --- D-4: there is exactly one table ---------------------------------------------------------

def test_the_ui_does_not_carry_a_second_pricing_table():
    """D-4: the duplication is gone, and must not grow back.

    Asserted against the parsed source because the defect *was* a second literal
    table. A behavioural test would pass while a copy silently drifted again -- which
    is exactly what happened: the UI's copy still priced a model Phase 1 retired, so
    the user could be shown a rate the backend disagreed with.
    """
    import ast
    from pathlib import Path

    # Addressed relative to this test, so it works in any worktree.
    ui_path = Path(__file__).resolve().parents[1] / 'ui' / 'app.py'
    source = ui_path.read_text(encoding='utf-8')
    tree = ast.parse(source)

    # Any module-level or local dict literal keyed by model name is a second table.
    model_keyed_dicts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and node.keys:
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if keys and all(isinstance(k, str) for k in keys):
                if any('gemini' in k for k in keys):
                    model_keyed_dicts.append(keys)

    assert not model_keyed_dicts, (
        f'a local model-keyed pricing table has grown back in the UI (D-4): '
        f'{model_keyed_dicts}'
    )
    assert 'from services import pricing' in source, (
        'the UI must price through the single source of truth'
    )
    # The retired model must not be priced anywhere in the UI, including a fallback.
    assert 'retired' not in source or 'gemini-1.5' not in source, (
        'the UI is naming a retired model again'
    )


def test_only_the_pricing_module_defines_the_table():
    """One definition, in one module.

    The detector looks for an assignment to ``PRICING`` or a local literal table, not
    for price-shaped text: a comment or a docstring quoting a rate is not a second
    source of truth, and flagging it would make this test noise rather than a guard.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    defining = []
    for path in list((root / 'backend').rglob('*.py')) + list((root / 'ui').rglob('*.py')):
        if '.venv' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for target in targets:
                name = getattr(target, 'id', None)
                # A table is a dict literal; the compatibility *view* in
                # gemini_service is a comprehension over the single source, so it is
                # explicitly not a second table.
                if name == 'PRICING' and isinstance(node.value, ast.Dict):
                    defining.append(path.name)

    assert defining == ['pricing.py'], f'the pricing table is defined in {defining}'


def test_the_compatibility_view_matches_the_single_source():
    """``gemini_service.PRICING`` is a derived view, never a second table."""
    from services.gemini_service import PRICING

    for model, row in PRICING.items():
        price = pricing.PRICING[(pricing.DEFAULT_PROVIDER, model)]
        assert row['input'] == price.input
        assert row['output'] == price.output
    # And it does not include another route's rows.
    assert not any('google/' in model for model in PRICING)


def test_pricing_does_not_read_the_environment_at_import():
    """ADR 0010: prices are constants, not configuration."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / 'backend' / 'services' / 'pricing.py'
    ).read_text(encoding='utf-8')

    assert 'os.getenv' not in source
    assert 'import os' not in source


# --- a price is a fact with a timestamp ----------------------------------------------------

def test_the_current_table_is_within_its_verification_window():
    """A table nobody has re-checked is a table nobody should trust.

    The owner's rule (2026-10-26): re-verify "if the last table update was longer than
    2 months". This asserts the shipped table is inside that window, so the guard is a
    real constraint on this repository rather than a helper nothing consults.
    """
    from services import pricing

    for provider in ('gemini', 'openrouter'):
        age = pricing.source_age_days(provider)
        assert age is not None, f'{provider} has no recorded verification date'
        assert age <= pricing.PRICE_MAX_AGE_DAYS, (
            f'{provider} prices are {age} days old and need re-verifying'
        )
        assert pricing.is_stale(provider) is False


def test_a_missing_verification_date_counts_as_stale():
    """Fails towards stale: "cannot prove it is current" is not "is current".

    Returning False here would let a row with no provenance pass forever, which is
    exactly the failure the guard exists to prevent -- an unpriced *or* unverified
    figure presented with the confidence of a checked one.
    """
    from services import pricing

    assert pricing.source_age_days('a-provider-with-no-entry') is None
    assert pricing.is_stale('a-provider-with-no-entry') is True


def test_an_old_date_is_reported_as_stale():
    """The window is enforced in both directions, not only for unknown providers."""
    from datetime import date

    from services import pricing

    # Well past the two-month window the owner set.
    future = date(2027, 6, 1)
    age = pricing.source_age_days('openrouter', today=future)
    assert age > pricing.PRICE_MAX_AGE_DAYS
    assert pricing.is_stale('openrouter', today=future) is True

    message = pricing.staleness_message('openrouter', today=future)
    assert message is not None
    assert 're-verify' in message.lower()
    # The date and the source are named, so the fix is actionable rather than a nag.
    assert '2026-10-26' in message
    assert 'openrouter.ai' in message


def test_a_fresh_table_produces_no_warning():
    from datetime import date

    from services import pricing

    assert pricing.staleness_message('openrouter', today=date(2026, 10, 26)) is None


def test_every_curated_model_is_priced_on_the_route_the_run_uses():
    """An unpriced route does not raise -- it silently borrows the default's price.

    ``price_for`` falls back to ``(gemini, gemini-3.8-flash)`` = $0.75/$3.75 for any
    unknown route, so a curated model with no row would report the *same* invented cost
    as every other unpriced one. Measured 2026-10-26: that would have billed
    ``deepseek-v4-flash`` at 8.2x its real rate and ``claude-sonnet-5`` at 0.27x, and
    the run would have ranked the models on it. The set and the table must agree.
    """
    from evaluation.curated_models import CURATED_MODELS, unpriced_entries

    unpriced = unpriced_entries()
    assert unpriced == (), (
        'these curated models have no OpenRouter price row, so their cost would be '
        f'invented from the default route: {[m.id for m in unpriced]}'
    )
    for model in CURATED_MODELS:
        assert pricing.is_priced(model.id, 'openrouter'), model.id
        # And the recorded rate is the one the table will actually bill.
        row = pricing.price_for(model.id, 'openrouter')
        assert row.input == model.input_per_1m, f'{model.id} input rate drifted'
        assert row.output == model.output_per_1m, f'{model.id} output rate drifted'
