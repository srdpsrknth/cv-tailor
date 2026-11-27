"""Re-check every saved application of one candidate against the current validators.

Thin wrapper over ``cvtailor --profile-id <id> applications check [--render]``. Offline: no
network or LLM call, and the store is never modified (``--render`` writes to a temporary
folder that is deleted afterwards). Exits non-zero if any application fails.

    python scripts/check_saved_applications.py --profile-id <id> [--store <dir>] [--render]
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from cli.main import main  # noqa: E402


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile-id", default=os.environ.get("CVTAILOR_PROFILE_ID"),
                        help="Candidate to check (or set CVTAILOR_PROFILE_ID).")
    parser.add_argument("--store", default=None,
                        help="Store root (default: CVTAILOR_STORE or ./storage).")
    parser.add_argument("--render", action="store_true",
                        help="Also re-render each application into a temporary folder.")
    args = parser.parse_args(argv)
    if not args.profile_id:
        parser.error("--profile-id is required (or set CVTAILOR_PROFILE_ID)")
    cli = ["--project", str(ROOT), "--profile-id", args.profile_id]
    if args.store:
        cli += ["--store", args.store]
    cli += ["applications", "check"]
    if args.render:
        cli.append("--render")
    return main(cli)


if __name__ == "__main__":
    sys.exit(run())
