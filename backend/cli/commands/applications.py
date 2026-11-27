"""``cvtailor applications check`` -- re-check saved applications against today's validators.

No network, no LLM, and the store is never modified. With ``--render`` each application is
re-rendered into a temporary folder (deleted afterwards) to report page counts.
"""
from __future__ import annotations

from cli.context import (
    EXIT_FAILED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    CliError,
    Console,
)

ACTIONS = ("check",)


def run(args, console: Console, config) -> int:
    action = getattr(args, "applications_action", None)
    if action not in ACTIONS:
        raise CliError("Choose an action: check.", EXIT_USAGE,
                       hint="cvtailor --profile-id <id> applications check [--render]")
    return _check(args, console, config)


def _pages(value) -> str:
    return "n/a" if value is None else str(value)


def _check(args, console: Console, config) -> int:
    from services.application_check import check_applications
    from services.profile_store import InvalidProfileIdError, UnknownProfileError

    try:
        profile_id = config.require_profile_id()
        profile = config.store.load(profile_id)
    except InvalidProfileIdError as error:
        raise CliError(str(error), EXIT_USAGE,
                       hint="Pass --profile-id <id> before the command, or set CVTAILOR_PROFILE_ID.")
    except UnknownProfileError as error:
        raise CliError(str(error), EXIT_NOT_FOUND,
                       hint="Run `cvtailor profile list` to see the available ids.")
    except (FileNotFoundError, ValueError) as error:
        raise CliError(f"Profile could not be loaded: {error}", EXIT_NOT_FOUND)

    render = bool(getattr(args, "render", False))
    outputs = config.store.outputs_dir(profile_id)

    def show(check) -> None:
        if console.as_json:
            return
        line = f"{check.status}  {check.job_id}"
        if check.render is not None and not check.render_error:
            line += (f"  [CV {_pages(check.render['cv_pages'])} page(s), "
                     f"cover letter {_pages(check.render['cover_letter_pages'])}]")
        console.out(line)
        for message in check.messages:
            console.out(f"      {message}")
        if check.render_error:
            console.out(f"      render error: {check.render_error}")

    if not console.as_json:
        console.out(f"Profile: {profile_id}   Store: {config.store.root}")
        console.out("Offline check with the current validators"
                    + (" and a temporary re-render" if render else "") + ".\n")

    results = check_applications(
        profile, outputs, render=render, timezone_name=config.timezone_name, progress=show
    )
    failed = [r for r in results if not r.passed]
    summary = {
        "profile_id": profile_id,
        "checked": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
    }
    if console.as_json:
        console.json({**summary, "applications": [r.as_dict() for r in results]})
    elif not results:
        console.out(f"No saved applications under {outputs}.")
    else:
        console.out(f"\n{summary['checked']} checked: {summary['passed']} passed, "
                    f"{summary['failed']} failed.")
    return EXIT_FAILED if failed else EXIT_OK
