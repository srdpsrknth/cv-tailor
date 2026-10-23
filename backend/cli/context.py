"""Shared helpers for the CLI: output, exit codes and path resolution.

Kept separate from the commands so every command behaves consistently and so
formatting can be tested without invoking a command.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

#: Exit codes, chosen so a caller can distinguish the failure classes.
EXIT_OK = 0
EXIT_USAGE = 2          # argparse's own code for bad arguments
EXIT_FAILED = 1         # the operation ran and failed
EXIT_CONFIG = 3         # configuration is missing or unusable
EXIT_NOT_FOUND = 4      # a requested profile, application or artifact is absent


class CliError(Exception):
    """A failure the CLI should report cleanly rather than as a traceback."""

    def __init__(self, message: str, code: int = EXIT_FAILED, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


class Console:
    """Minimal output helper.

    ``--json`` switches every command to machine-readable output, so the same
    code path serves both a human and a script.
    """

    def __init__(self, as_json: bool = False, stream=None):
        self.as_json = as_json
        self.stream = stream or sys.stdout
        #: Warnings are collected so --json output stays pure JSON on stdout.
        self.warnings: list[str] = []

    def out(self, message: str = "") -> None:
        if not self.as_json:
            print(message, file=self.stream)

    def warn(self, message: str) -> None:
        if self.as_json:
            self.warnings.append(message)
        else:
            print(f"warning: {message}", file=sys.stderr)

    def error(self, message: str, hint: Optional[str] = None) -> None:
        print(f"error: {message}", file=sys.stderr)
        if hint:
            print(f"  fix: {hint}", file=sys.stderr)

    def json(self, payload) -> None:
        """Print a JSON document, including any warnings collected so far."""
        if isinstance(payload, dict) and self.warnings:
            payload = {**payload, "warnings": self.warnings}
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str), file=self.stream)

    def table(self, rows, headers) -> None:
        """Print a simple aligned table, or a list of objects under --json."""
        if self.as_json:
            self.json([dict(zip(headers, row)) for row in rows])
            return
        widths = [
            max(len(str(headers[i])), *(len(str(r[i])) for r in rows)) if rows else len(str(headers[i]))
            for i in range(len(headers))
        ]
        print("  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)), file=self.stream)
        print("  ".join("-" * w for w in widths), file=self.stream)
        for row in rows:
            print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)), file=self.stream)


def resolve_project_root(explicit: Optional[str] = None) -> Path:
    """Find the repository root, or fail with a clear message."""
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not root.is_dir():
            raise CliError(f"--project is not a directory: {root}", EXIT_USAGE)
        return root
    # backend/cli/context.py -> backend/cli -> backend -> repo
    root = Path(__file__).resolve().parents[2]
    if not (root / "backend").is_dir():
        raise CliError(
            "Could not locate the project root. Pass --project <path>.",
            EXIT_CONFIG,
        )
    return root


def ensure_backend_on_path(root: Path) -> None:
    """Make ``backend/`` importable, matching how the scripts do it."""
    backend = str(root / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def human_pages(count: Optional[int]) -> str:
    if count is None:
        return "unknown"
    return f"{count} page" + ("" if count == 1 else "s")
