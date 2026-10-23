"""Entry point so ``python -m cli`` works from the backend directory."""
import sys
from pathlib import Path

# Allow running this file directly, before backend/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.main import run  # noqa: E402

if __name__ == "__main__":
    run()
