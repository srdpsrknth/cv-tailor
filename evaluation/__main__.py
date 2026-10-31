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
    parser.add_argument(
        "--detect", nargs="?", const="", default=None, metavar="NEW_LISTING_JSON",
        help=(
            "diff a freshly read listing against the most recent committed record: "
            "models added, repriced, withdrawn. Offline and REPORT-only -- it cannot "
            "spend and there is no path from it to --live."
        ),
    )
    parser.add_argument(
        "--report", nargs="?", const="", default=None, metavar="SCORES_JSON",
        help=(
            "turn a finished run into a curation proposal: the ranked table, the "
            "disqualifications, and the diff it WOULD make. Writes nothing."
        ),
    )
    parser.add_argument(
        "--packet", nargs="?", const="", default=None, metavar="RANKING_JSON",
        help=(
            "build a reading packet for the owner's writing/PDF/layout judgement: one "
            "folder per model per case holding the rendered documents, plus a "
            "VERDICTS.md to fill in. Offline; reads only a run's output tree."
        ),
    )
    parser.add_argument(
        "--packet-destination", default=None, metavar="DIR",
        help="where --packet writes (default: .tmp/reading-packet)",
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
    print("Curated OpenRouter models")
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
    # Two different facts, and conflating them is how a measurement starts looking like
    # a verdict: `measured` means the OWNER read the rendered documents and judged them;
    # an unmeasured entry awaits that reading, not a run. The old wording promised a
    # "budgeted live run" for every unmeasured entry, which stopped being true the
    # moment the study ran -- the run had happened, the reading had not.
    pending = unmeasured_entries()
    if pending:
        names = ", ".join(model.id for model in pending)
        print(
            f"  {len(pending)} of {len(curated_models())} entries are UNMEASURED "
            f"({names}):\n  no owner has judged their writing, PDF and layout quality, "
            "which this suite\n  does not measure. Nothing there is a quality verdict "
            "yet."
        )
    else:
        print(
            f"  all {len(curated_models())} entries are measured: the owner has read "
            "the rendered\n  documents and judged their writing, PDF and layout "
            "quality. The suite measures\n  none of that; the marker records a human "
            "verdict, not a score."
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


def _run_detect(argument: str) -> int:
    """Report what changed in the catalogue. Offline: no key, no spend, no writes.

    Deliberately **not** wired to ``--live`` in any direction. Detection could have been
    automatic, and it is not: a provider's routine catalogue churn would then be able to
    trigger spending without anyone deciding to. The two are separate commands so the
    separation is structural rather than a convention someone has to remember.
    """
    from pathlib import Path

    from evaluation.curation_diff import detect_changes
    from evaluation.listing import latest_record, load_record

    previous_path = latest_record()
    if previous_path is None:
        raise SystemExit(
            "No committed listing record in evaluation/, so there is nothing to diff "
            "against. Commit a screened record first."
        )
    current_path = Path(argument) if argument else None
    if current_path is None:
        raise SystemExit(
            "Pass the freshly read listing to diff against the committed record:\n"
            "  python -m evaluation --detect path/to/new_listing.json\n"
            "Reading a new listing is a network call this command deliberately does "
            "not make for you."
        )
    if not current_path.exists():
        raise SystemExit(f"No such listing record: {current_path}")

    from evaluation.curated_models import CURATED_MODELS

    watch = tuple(m.id for m in CURATED_MODELS)
    print(f"Committed record: {previous_path}")
    print(f"New record:       {current_path}")
    print()
    detection = detect_changes(
        load_record(previous_path), load_record(current_path), watch=watch
    )
    print(detection.describe())
    return 0


def _run_report(argument: str) -> int:
    """Render a curation proposal from a finished run. Reads only; writes nothing."""
    import json
    from pathlib import Path

    if not argument:
        raise SystemExit(
            "Pass the run's scores to report on:\n"
            "  python -m evaluation --report path/to/scores.json\n"
            "See evaluation/curation_diff.py for the shape this expects."
        )
    path = Path(argument)
    if not path.exists():
        raise SystemExit(f"No such scores file: {path}")

    from evaluation.curation_diff import proposal_from_scores
    from evaluation.metrics import CaseResult, ModelScore

    payload = json.loads(path.read_text(encoding="utf-8"))
    scores = []
    # The dialect a candidate was asked in, collected from the constructed results rather
    # than from the raw payload. Reading it off the dicts was the first version and it
    # raised AttributeError on the first run -- the payload is JSON, so its "results" are
    # dicts, and only the CaseResult objects have the attribute.
    dialects: dict = {}
    for row in payload.get("models", []):
        results = [
            CaseResult(
                model_id=row["model_id"],
                case_name=case.get("case_name", ""),
                accepted=bool(case.get("accepted")),
                cost_usd=float(case.get("cost_usd", 0.0)),
                calls=int(case.get("calls", 0)),
                correction_calls=int(case.get("correction_calls", 0)),
                schema_dialect=case.get("schema_dialect", ""),
            )
            for case in row.get("results", [])
        ]
        scores.append(ModelScore(model_id=row["model_id"], label=row.get("label", ""),
                                 results=results))
        observed = next((r.schema_dialect for r in results if r.schema_dialect), "")
        if observed:
            dialects[row["model_id"]] = observed

    proposal = proposal_from_scores(
        scores,
        current_model=payload.get("current_model", ""),
        minimum_rate=float(payload.get("minimum_rate", 2 / 3)),
        dialects=dialects,
        run_reference=payload.get("run_reference", str(path)),
        run_notes=tuple(payload.get("run_notes", ())),
    )

    verdicts = payload.get("verdicts") or {}
    if verdicts:
        from evaluation.curation_diff import apply_verdicts

        proposal = apply_verdicts(proposal, verdicts)

    print(proposal.describe())
    print()
    print(proposal.diff_for_curated_models())
    print()
    print(proposal.diff_for_candidate_inputs())
    return 0


def _run_packet(argument: str, destination: Optional[str]) -> int:
    """Build a reading packet. Offline: reads a run's output tree and copies documents.

    The ranking is supplied rather than derived, because it comes from the run's measured
    cost per accepted result -- and this module deliberately does not re-derive it. Two
    orderings of the same run would be a way for the folder numbers to disagree with the
    table the recommendation rests on.
    """
    import json
    from pathlib import Path

    from evaluation.reading_packet import build_packet

    if not argument:
        raise SystemExit(
            "Pass the run's ranking, best first:\n"
            "  python -m evaluation --packet ranking.json\n"
            '  where ranking.json is {"ranking": ["vendor/model", ...], "notes": [...]}\n'
            "The ranking comes from the run; this command does not re-derive it."
        )
    path = Path(argument)
    if not path.exists():
        raise SystemExit(f"No such ranking file: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    ranking = tuple(payload.get("ranking") or ())
    if not ranking:
        raise SystemExit(f"{path} names no models in a 'ranking' list")

    sandbox = (
        Path(__file__).resolve().parents[1] / ".tmp" / "evaluation-store" / "outputs"
    )
    if not sandbox.is_dir():
        raise SystemExit(
            f"No evaluation output tree at {sandbox}.\n"
            "A reading packet is built from a completed live run's documents; there is "
            "nothing to read until one has been made.\n"
            "Clear the sandbox and run one with --live --cap-usd N."
        )

    target = Path(destination) if destination else (
        Path(__file__).resolve().parents[1] / ".tmp" / "reading-packet"
    )
    packet = build_packet(
        sandbox, target, ranking=ranking, notes=tuple(payload.get("notes") or ())
    )
    print(packet.describe())
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

    if args.detect is not None:
        return _run_detect(args.detect)

    if args.report is not None:
        return _run_report(args.report)

    if args.packet is not None:
        return _run_packet(args.packet, args.packet_destination)

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
