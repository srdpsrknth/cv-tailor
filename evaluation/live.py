"""The single seam where a paid call can originate.

Everything else in :mod:`evaluation` is offline. This module is the only place a real
request is made, which is what makes "the suite cannot spend by accident" a
structural property rather than a convention: there is exactly one function to
audit.

It is imported **lazily**, only from ``--live`` after the plan has been priced and
the cap checked, so an offline run never even loads the provider machinery.

No run has been made yet. That is deliberate and is recorded in the docs: selecting
the curated set's *ranking* requires this code to run with an agreed budget, and
until it does, the set is a shortlist rather than a verdict.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from evaluation.cases import CASES, EvaluationCase, fixture_path
from evaluation.curated_models import CURATED_MODELS, CuratedModel
from evaluation.metrics import CaseResult
from evaluation.runner import live_run, plan


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _sandbox_store() -> str:
    """A scratch store for evaluation output, inside the repository's ``.tmp/``.

    The evaluation must not write a candidate's documents anywhere a real one lives,
    and it must not need write access to the private store at all. ``.tmp/`` is
    gitignored and already used for scratch work, so an evaluated run's job folders
    land somewhere disposable and provably outside both the tracked tree and the real
    store.

    This is not only about privacy: the previous behaviour inherited the developer's
    ``.env`` store, so a run wrote into ``<store>/outputs/<their id>/`` -- and on a
    machine where that path is read-only it failed with a bare ``PermissionError``
    that reads as a benchmark failure rather than a configuration one.
    """
    root = Path(__file__).resolve().parents[1] / ".tmp" / "evaluation-store"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def run_one_case(case: EvaluationCase, model: CuratedModel) -> CaseResult:
    """Drive the real pipeline for one case on one model, and score the outcome.

    Deliberately conservative in what it claims: a run counts as accepted only when
    the pipeline returned a validated document, and every failure is recorded with
    its reason rather than being silently skipped. Cost is read from the pipeline's
    own accounting, so a model that needed corrections pays for them here exactly as
    it would in a real application.
    """
    # Imported here rather than at module scope so that nothing in the offline path
    # pulls in the provider stack.
    from config import Config
    from services.profile_loader import load_profile
    from services import tailor_service

    profile = load_profile(str(fixture_path(case.profile_fixture)))
    posting = _read(fixture_path(case.posting_fixture))

    # ``load_env_file=True``: the live run needs the provider's key, and ``.env`` is
    # where this project keeps it (it is gitignored; see ADR 0011). This was ``False``
    # while the suite was offline-only and made no call, which was correct then and
    # wrong the moment it went live -- with ``False`` the key is invisible and *every*
    # case fails with "OPENROUTER_API_KEY is not set", at zero cost, looking exactly
    # like a benchmark where no model works.
    #
    # ``profile_id`` is overridden **away from whatever ``.env`` names**, and this is
    # the privacy fix rather than tidiness. A developer's ``.env`` carries their own
    # ``CVTAILOR_PROFILE_ID`` (this machine's says ``sreedeep``), and ``tailor_documents``
    # files its output under that id. Left alone, an evaluation of *synthetic* fixtures
    # would write job folders -- accepted documents included -- under a real candidate's
    # profile, which is exactly the boundary ADR 0002/0011 exist to hold. The synthetic
    # id is derived from the fixture so two cases cannot collide, and it is deliberately
    # not a store id, so nothing here can be mistaken for a real candidate.
    synthetic_id = f"eval_{case.name}"
    config = Config.from_env(
        load_env_file=True,
        overrides={
            "provider": "openrouter",
            "model": model.id,
            "profile_path": fixture_path(case.profile_fixture),
            "profile_id": synthetic_id,
            "profile_store_dir": _sandbox_store(),
        },
    )

    # Fail **before** any paid work if the selected provider has no key. Without this
    # the missing key surfaces as a per-case failure caught below and recorded as a
    # metric, which is the one outcome a measurement must never produce: a
    # misconfiguration that reads as a result. Cheap, and it costs nothing to be sure.
    config.require_provider_key()

    try:
        result = tailor_service.tailor_documents(
            posting, profile, config=config,
            company_name=case.name, role_title="Evaluation",
            # The cache is bypassed **on purpose**, and this is the only place in the
            # suite that has to say so. ``tailor_documents`` defaults to
            # ``use_cache=True`` and ``evaluation/live.py`` drives the *real* pipeline
            # with a loose ``profile_path``, so without this the paid run would read and
            # write the same ``<store>/cache/<profile_id>/`` the user's own runs use.
            #
            # A benchmark answer served from cache measures the cache, not the model:
            # a hit makes no API call, reports **zero** usage, and comes back as an
            # accepted case costing $0.00 with 0 calls -- a fabricated "cheapest,
            # perfect" result that would land at the top of the ranking. Only the first
            # run of a pair is at risk, and that is precisely the run whose numbers the
            # owner is paying for, so the bypass is not optional here.
            use_cache=False,
        )
    except Exception as error:  # noqa: BLE001 -- a failure is data for the metrics
        return CaseResult(
            model_id=model.id, case_name=case.name, accepted=False,
            error=f"{type(error).__name__}: {error}",
        )

    usage = getattr(result, "token_usage", None)
    calls = (getattr(usage, "cv_attempts", 1) or 1) + (getattr(usage, "cl_attempts", 1) or 1)

    return CaseResult(
        model_id=model.id,
        case_name=case.name,
        accepted=getattr(result, "status", "") == "success",
        cost_usd=getattr(usage, "estimated_cost_usd", 0.0) or 0.0,
        calls=calls,
        # The minimum for a successful run is 2 calls; anything more is correction or
        # layout retry, which is the cost this metric exists to expose.
        correction_calls=max(0, calls - 2),
        cv_page_count=getattr(result, "cv_page_count", None),
    )


def make_runner(*, models, cases=CASES, cap_usd: Optional[float] = None, progress=None):
    """Price the run, refuse it if over budget, then drive it. The paid entry point.

    The order is the safeguard: :func:`plan` and :func:`live_run`'s own check both
    happen before ``run_one_case`` is called even once, so an over-budget plan cannot
    spend anything to discover that it is over budget.
    """
    budget = plan(cases, tuple(models), cap_usd=cap_usd)
    if budget.exceeds():
        from evaluation.runner import BudgetExceeded

        raise BudgetExceeded(budget.describe())

    if progress is None:
        def progress(message: str) -> None:
            print(f"  {message}", flush=True)

    return live_run(
        cases, tuple(models), cap_usd=cap_usd,
        authorised=True, progress=progress, run_one=run_one_case,
    )
