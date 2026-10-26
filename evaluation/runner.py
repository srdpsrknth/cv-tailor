"""The runner: plans a run, refuses an over-budget one, and drives it only when asked.

The three entry points differ solely in how much they are allowed to do:

* :func:`plan` -- **no network**. Prices the run and returns the plan.
* :func:`dry_run` -- **no network**. Confirms the fixtures load and reports the plan.
  This is the default from the CLI.
* :func:`live_run` -- the only function that can spend money. It refuses unless a cap
  is configured, the plan fits it, and a key is present.

There is deliberately no fourth path that improvises a live run. The suite has never
made a paid call, and the ordering here -- configure cap, price plan, refuse if over,
*then* build a provider -- is what keeps that true by construction rather than by
everyone remembering.
"""
from __future__ import annotations

from typing import Callable, Optional

from evaluation.cases import (
    CASES,
    BudgetPlan,
    EvaluationCase,
    fixture_path,
    project_cost,
)
from evaluation.curated_models import CURATED_MODELS, CuratedModel
from evaluation.metrics import CaseResult, ModelScore, summarise

#: The cap that applies when the caller names none. The owner set the spending
#: budget for this curation at "under $5 total", and the default enforces it even if
#: a caller forgets -- a cap that requires remembering is a cap that will be missed.
DEFAULT_CAP_USD = 5.0


class BudgetExceeded(Exception):
    """A run was refused because its projection is over the cap.

    Raised *before* any request is sent. It is an exception rather than a warning
    because the one thing that must not happen is a run proceeding "carefully" past
    its budget.
    """


class LiveRunNotAuthorised(Exception):
    """A live run was attempted without the explicit authorisation it requires."""


def default_models() -> tuple[CuratedModel, ...]:
    """The models a curation run compares: the curated set, cheapest first."""
    return tuple(sorted(CURATED_MODELS, key=lambda m: m.input_per_1m))


def plan(
    cases: tuple[EvaluationCase, ...] = CASES,
    models: Optional[tuple[CuratedModel, ...]] = None,
    *,
    cap_usd: Optional[float] = None,
    pessimistic: bool = True,
) -> BudgetPlan:
    """Price a run across every model, upper-bound. Makes no network call.

    Pessimistic by default, so the figure the owner approves is the worst realistic
    case rather than the happy path.
    """
    models = models if models is not None else default_models()
    cap = DEFAULT_CAP_USD if cap_usd is None else cap_usd

    per_model = {
        model.id: project_cost(
            model.input_per_1m, model.output_per_1m, len(cases), pessimistic=pessimistic,
        )
        for model in models
    }
    return BudgetPlan(per_model_usd=per_model, cap_usd=cap)


def check_fixtures(cases: tuple[EvaluationCase, ...] = CASES) -> list:
    """Confirm every fixture a case names exists and is inside ``tests/fixtures/``.

    Offline, and a real check rather than a formality: a case pointing at a
    nonexistent posting would otherwise fail *during* a paid run, after the money was
    spent, which is the worst possible time to discover a typo.
    """
    problems = []
    for case in cases:
        for attribute in ("profile_fixture", "posting_fixture"):
            try:
                fixture_path(getattr(case, attribute))
            except (FileNotFoundError, ValueError) as error:
                problems.append(f"{case.name}.{attribute}: {error}")
    return problems


def dry_run(
    cases: tuple[EvaluationCase, ...] = CASES,
    models: Optional[tuple[CuratedModel, ...]] = None,
    *,
    cap_usd: Optional[float] = None,
) -> str:
    """Report what a live run *would* do. Makes no network call and spends nothing.

    This is the default mode, and it is deliberately the one that produces a
    human-readable plan: the owner's approval step needs the numbers, and asking for
    them should not require the ability to spend.
    """
    models = models if models is not None else default_models()
    budget = plan(cases, models, cap_usd=cap_usd)
    problems = check_fixtures(cases)

    lines = [
        "CV Tailor evaluation suite -- DRY RUN (no API calls will be made)",
        "",
        f"Cases: {len(cases)}",
    ]
    for case in cases:
        lines.append(f"  - {case.name}: {case.focus}")
    lines.append("")
    lines.append(budget.describe())
    lines.append("")
    if problems:
        lines.append("FIXTURE PROBLEMS -- a live run would fail on these:")
        for problem in problems:
            lines.append(f"  ! {problem}")
    else:
        lines.append(f"Fixtures OK: all {len(cases)} case pairs resolve inside tests/fixtures/.")
    lines.append("")
    # A projection is only as good as the prices behind it, and the owner's rule is
    # to re-verify a table older than two months. Saying so *here* matters because
    # this is the screen a spend is approved from: a stale figure presented without a
    # warning is a number wearing the confidence of a checked one.
    try:
        from services.pricing import staleness_message

        warning = staleness_message("openrouter")
    except ImportError:  # pragma: no cover - the offline suite does not need pricing
        warning = None
    if warning:
        lines.append(f"PRICE WARNING: {warning}")
        lines.append("")
    lines.append(
        "No paid call has been made. A live run needs --live and an API key, and is "
        "refused outright if its projection exceeds the cap."
    )
    return "\n".join(lines)


def live_run(
    cases: tuple[EvaluationCase, ...] = CASES,
    models: Optional[tuple[CuratedModel, ...]] = None,
    *,
    cap_usd: Optional[float] = None,
    authorised: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    run_one: Optional[Callable[[EvaluationCase, CuratedModel], CaseResult]] = None,
) -> tuple[list, str]:
    """Run the evaluation for real, within the cap.

    Args:
        authorised: must be **explicitly** True. A live run spends money, so it is
            never the default of any parameter and there is no truthy accident.
        run_one: the function that actually drives the pipeline for one case on one
            model. Injected so the budget logic is testable without a network, and so
            the one place a paid call can originate is a single, obvious seam.

    Raises:
        LiveRunNotAuthorised: if ``authorised`` is not True.
        BudgetExceeded: if the projection is over the cap. Before any call.

    Returns:
        ``(scores, summary)``.
    """
    if not authorised:
        raise LiveRunNotAuthorised(
            "A live evaluation run makes paid API calls and requires explicit "
            "authorisation. Agree the method and a spending budget with the owner "
            "first (ADR 0005), then pass authorised=True."
        )

    models = models if models is not None else default_models()
    budget = plan(cases, models, cap_usd=cap_usd)

    # The refusal is here, before the provider exists, so an over-budget plan cannot
    # spend even a fraction of a cent discovering that it is over budget.
    if budget.exceeds():
        raise BudgetExceeded(
            "Refusing to start: the projected cost exceeds the cap.\n" + budget.describe()
        )

    problems = check_fixtures(cases)
    if problems:
        raise BudgetExceeded(
            "Refusing to start: fixtures do not resolve, and a live run must not "
            "discover that after spending.\n  " + "\n  ".join(problems)
        )

    if run_one is None:
        raise LiveRunNotAuthorised(
            "live_run needs a run_one callable to drive the pipeline. This keeps the "
            "single paid-call seam explicit rather than hidden in this module."
        )

    scores: dict[str, ModelScore] = {
        model.id: ModelScore(model_id=model.id, label=model.label) for model in models
    }

    spent = 0.0
    stopped_early = False
    for model in models:
        if stopped_early:
            break
        for case in cases:
            # Checked before every single call, not only at the start: a cap enforced
            # once at the beginning is a cap the last model can walk through.
            if spent >= budget.cap_usd:
                stopped_early = True
                if progress:
                    progress(
                        f"CAP REACHED at ${spent:.4f} of ${budget.cap_usd:.4f}; "
                        "stopping before the next call."
                    )
                break
            if progress:
                progress(f"{model.id} x {case.name}")
            result = run_one(case, model)
            scores[model.id].results.append(result)
            spent += result.cost_usd

    ordered = [scores[model.id] for model in models]
    return ordered, summarise(ordered)
