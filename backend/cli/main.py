"""``cvtailor`` entry point: argument parsing and dispatch.

Per ADR 0007 this is ``argparse`` with subcommands plus a small friendliness
layer. Running ``cvtailor`` with no arguments prints a short guided menu rather
than an argparse error, so the tool is usable without memorising commands.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from cli.context import (
    CliError,
    Console,
    EXIT_OK,
    EXIT_USAGE,
    ensure_backend_on_path,
    resolve_project_root,
)

PROG = "cvtailor"
DESCRIPTION = "Tailor a CV and cover letter to a job posting, from the terminal."

GUIDED_MENU = """
cvtailor -- tailor a CV and cover letter from the terminal

  Common flows:

    cvtailor doctor                     Check your setup and what to fix
    cvtailor profile show               Show the profile being used
    cvtailor generate --job-file job.txt
                                        Tailor documents for a posting
    cvtailor render                     Re-render the last saved content
                                        (no API calls, no cost)

  Discover more:

    cvtailor --help                     All commands
    cvtailor <command> --help           Options for one command

  Every command accepts --json for scripting.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run `cvtailor` with no arguments for a guided menu.",
    )
    parser.add_argument("--project", help="Project root (defaults to the repository root).")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Machine-readable output.")
    parser.add_argument("--profile", dest="profile_path",
                        help="Profile YAML to use (defaults to the configured one).")
    parser.add_argument("--quiet", action="store_true", help="Suppress informational output.")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # --- doctor -----------------------------------------------------------------------
    doctor = subparsers.add_parser("doctor", help="Check the local setup and what to fix.")
    doctor.add_argument("--verify-key", action="store_true",
                        help="Also check the API key against Google (makes a network call).")

    # --- profile ----------------------------------------------------------------------
    profile = subparsers.add_parser("profile", help="Inspect the configured profile.")
    profile_sub = profile.add_subparsers(dest="profile_action", metavar="<action>")
    profile_sub.add_parser("show", help="Show the profile, its facts and its rules.")

    # --- generate ---------------------------------------------------------------------
    generate = subparsers.add_parser("generate", help="Tailor documents for a posting.")
    source = generate.add_mutually_exclusive_group()
    source.add_argument("--job-file", type=str, help="File containing the job description.")
    source.add_argument("--job", type=str, help="Job description as inline text.")
    generate.add_argument("--company", help="Company name (otherwise inferred).")
    generate.add_argument("--role", help="Role title (otherwise inferred).")
    generate.add_argument("--country", help="Actual country of employment.")
    generate.add_argument("--yes", action="store_true", help="Skip confirmations.")

    # --- render -----------------------------------------------------------------------
    render = subparsers.add_parser("render", help="Re-render saved content. No API calls.")
    render.add_argument("--content", type=str,
                        help="Path to <application>/source/content.json.")
    only = render.add_mutually_exclusive_group()
    only.add_argument("--cv-only", action="store_true", help="Render only the CV.")
    only.add_argument("--cover-letter-only", action="store_true",
                      help="Render only the cover letter.")
    render.add_argument("--mirror-configured", action="store_true",
                        help="Also copy artifacts to OUTPUTS_DIR.")

    return parser


def _dispatch(args, console: Console, config) -> int:
    """Route to the command module, importing it lazily."""
    command = args.command
    if command == "doctor":
        from cli.commands import doctor
        return doctor.run(args, console, config)
    if command == "profile":
        from cli.commands import profile
        return profile.run(args, console, config)
    if command == "generate":
        from cli.commands import generate
        return generate.run(args, console, config)
    if command == "render":
        from cli.commands import render
        return render.run(args, console, config)
    raise CliError(f"Unknown command: {command}", EXIT_USAGE)


def main(argv: Optional[list] = None) -> int:
    """Parse arguments, run the command, and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # The guided default (ADR 0007 rule 1): no command means "show me what I can do".
    if not args.command:
        if args.as_json:
            print('{"commands": ["doctor", "profile show", "generate", "render"]}')
            return EXIT_OK
        print(GUIDED_MENU)
        return EXIT_OK

    if args.command == "render" and args.cv_only:
        args.only = "cv"
    elif args.command == "render" and args.cover_letter_only:
        args.only = "cover-letter"
    else:
        args.only = None

    console = Console(as_json=args.as_json)

    try:
        root = resolve_project_root(args.project)
        ensure_backend_on_path(root)

        from config import Config

        config = Config.from_env(
            env_file=root / ".env",
            overrides={"project_root": root, "profile_path": args.profile_path}
            if args.profile_path
            else {"project_root": root},
        )
        return _dispatch(args, console, config)

    except CliError as error:
        console.error(error.message, error.hint)
        return error.code
    except KeyboardInterrupt:
        console.error("Interrupted.")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as error:  # unexpected: show it, but not as a raw traceback
        if args.as_json:
            console.json({"ok": False, "error": str(error)})
        else:
            console.error(f"Unexpected error: {error}")
        return 1


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    run()
