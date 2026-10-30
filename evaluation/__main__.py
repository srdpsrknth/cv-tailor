"""Command-line entry point for the evaluation suite.

``python -m evaluation --dry-run`` is the default and makes no call. ``--live`` is
required to spend anything, and it is refused if the projection exceeds ``--cap-usd``.

This script is deliberately **not** named ``test_*`` and does not live under
``tests/``, so pytest never collects it and CI cannot make a paid call through it.
``tests/test_evaluation_suite.py`` asserts both.
"""
from __future__ import annotations

import argparse
import sys

from evaluation.cases import CASES
from evaluation.curated_models import (
    LISTING_SHA256,
    LISTING_VERIFIED_ON,
    curated_models,
    has_cost_spread,
    unmeasured_entries,
)
from evaluation.runner import DEFAULT_CAP_USD, BudgetExceeded, dry_run, plan
from evaluation.screen import MAX_SLATE as DEFAULT_SLATE_CAP


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation",
        description=(
            "Compare models on the CV-tailoring task. Offline by default; a live run "
            "makes paid API calls and requires an explicit budget."
        ),
    )
    parser.add_argument(
        "--live", action="store_true",
        help=(
            "make real, paid API calls. Without this the suite prices the run and "
            "stops. Requires an agreed budget (ADR 0005)."
        ),
    )
    parser.add_argument(
        "--cap-usd", type=float, default=DEFAULT_CAP_USD,
        help=(
            f"spending ceiling in USD (default {DEFAULT_CAP_USD}). A plan whose "
            "projection exceeds it is refused before the first call."
        ),
    )
    parser.add_argument(
        "--models", nargs="*", default=None,
        help="restrict the run to these curated model ids (default: all of them)",
    )
    parser.add_argument(
        "--list-models", action="store_true",
        help="show the curated set and exit",
    )
    parser.add_argument(
        "--screen", nargs="?", const="", default=None, metavar="LISTING_JSON",
        help=(
            "propose a candidate slate from a listing record, offline. With no "
            "argument, uses the most recent committed record in evaluation/. This "
            "makes no API call and spends nothing."
        ),
    )
    parser.add_argument(
        "--cap-slate", type=int, default=None,
        help=f"how many candidates --screen may propose (default {DEFAULT_SLATE_CAP})",
    )
    return parser


def _selected_models(ids):
    """Resolve ``--models`` against the curated set, refusing anything else.

    An uncurated id is refused rather than passed through: offering the catalogue is
    the thing the owner's requirement forbids, and a run is not the place to start.
    """
    if not ids:
        return curated_models()
    by_id = {model.id: model for model in curated_models()}
    unknown = [model_id for model_id in ids if model_id not in by_id]
    if unknown:
        raise SystemExit(
            "These models are not in the curated set: " + ", ".join(unknown) + "\n"
            "Run `python -m evaluation --list-models` to see the offered options. "
            "Adding one is a curation decision, not a flag."
        )
    return tuple(by_id[model_id] for model_id in ids)


def _print_models() -> None:
    print("Curated OpenRouter models (a shortlist, not a verdict)")
    print(f"  read from {LISTING_VERIFIED_ON}; listing sha256 {LISTING_SHA256[:16]}...")
    print()
    header = f"  {'id':34} {'tier':>9} {'in$/1M':>8} {'out$/1M':>8}  verified"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for model in curated_models():
        print(
            f"  {model.id:34} {model.tier:>9} {model.input_per_1m:8.3f} "
            f"{model.output_per_1m:8.3f}  {model.verified}"
        )
    print()
    print(f"  cost spread across the set: {'yes' if has_cost_spread() else 'NO'}")
    pending = unmeasured_entries()
    print(
        f"  {len(pending)} of {len(curated_models())} entries are UNMEASURED: their "
        "quality ranking\n  awaits a budgeted live run. Nothing here is a quality "
        "verdict yet."
    )


def _run_screen(argument: str, cap: int) -> int:
    """Propose a candidate slate. Offline: no key, no network, no spending.

    The ``--live`` path is deliberately not reachable from here. Screening is the step
    *before* a spend is approved, so it must be runnable by someone who has not yet
    decided to spend anything -- which means it cannot share a code path with spending.
    """
    from pathlib import Path

    from evaluation.listing import latest_record, load_record
    from evaluation.screen import screen_record

    path = Path(argument) if argument else latest_record()
    if path is None:
        raise SystemExit(
            "No committed listing record in evaluation/ and no path given.\n"
            "Commit a screened record first, or pass one: "
            "python -m evaluation --screen path/to/listing.json"
        )
    if not path.exists():
        raise SystemExit(f"No such listing record: {path}")

    print(f"Listing record: {path}")
    record = load_record(path)

    # The control is the model actually shipped, so every challenger is measured against
    # something real rather than against a leaderboard position (ADR 0016).
    #
    # Read from the curated set rather than from ``services.pricing.DEFAULT_MODEL``, and
    # that is deliberate: this module runs as ``python -m evaluation`` from the repository
    # root, where ``backend/`` is not on ``sys.path`` -- the tests get it from
    # ``conftest.py``, and the paid path imports the backend lazily inside
    # ``evaluation.live``, after the cap check. Reaching into ``services`` at argument
    # parsing time would make ``--screen`` fail on a machine where the offline half
    # works perfectly well, which is exactly the wrong failure for the step that decides
    # whether to spend anything. The curated set is the record of what ships, and it is
    # asserted equal to ``pricing.DEFAULT_MODEL`` by tests/test_config.py.
    from evaluation.curated_models import CURATED_MODELS

    control = CURATED_MODELS[0].id if len(CURATED_MODELS) == 1 else None
    slate = screen_record(record, control_id=control, cap=cap)

    print(slate.describe())
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_models:
        _print_models()
        return 0

    if args.screen is not None:
        return _run_screen(
            args.screen,
            args.cap_slate if args.cap_slate is not None else DEFAULT_SLATE_CAP,
        )

    models = _selected_models(args.models)

    if not args.live:
        print(dry_run(CASES, models, cap_usd=args.cap_usd))
        return 0

    # A live run is reached only through --live, and the plan is priced and checked
    # before the pipeline is even imported. Importing it lazily keeps the offline
    # path free of any provider dependency.
    budget = plan(CASES, models, cap_usd=args.cap_usd)
    if budget.exceeds():
        print("REFUSED: the projected cost exceeds the cap.\n", file=sys.stderr)
        print(budget.describe(), file=sys.stderr)
        return 2

    from evaluation.live import make_runner  # imported only on the paid path

    try:
        scores, summary = make_runner(
            models=models, cases=CASES, cap_usd=args.cap_usd,
        )
    except BudgetExceeded as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
