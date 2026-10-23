"""The ``cvtailor`` command-line interface.

Per ADR 0007 the CLI is ``argparse`` plus a thin friendliness layer: a guided
default, clear verb-first subcommands, human-readable output with ``--json`` for
scripting, and honest exit codes with messages that name the fix.

The parsing layer is deliberately separate from the doing layer: each command
module exposes a plain function, so it can be called and tested without going
through ``argparse``.
"""
