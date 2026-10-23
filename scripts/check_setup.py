"""Check local prerequisites without sending data to Gemini.

Kept as a thin, script-shaped entry point for people (and documentation) that
already call it. The real implementation now lives in ``cvtailor doctor``, which
checks the same things plus the venv, the output path and the templates, and
reports the fix for anything that fails.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    # Delegate so there is exactly one set of setup checks to maintain.
    raise SystemExit(subprocess.call(
        [sys.executable, str(ROOT / 'cvtailor.py'), 'doctor'],
        cwd=str(ROOT),
    ))
