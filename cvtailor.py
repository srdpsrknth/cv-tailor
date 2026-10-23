"""Launch the cvtailor CLI from a checkout, using the project interpreter.

    cvtailor                       (guided menu)
    cvtailor doctor
    cvtailor profile show

This wrapper exists so the CLI works from a clone without installing anything:
it puts ``backend/`` on the path and defers to :mod:`cli.main`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from cli.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
