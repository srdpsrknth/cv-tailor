"""``cvtailor claims`` -- review the model's confirm-first suggestions for an application.

The CV call may suggest statements that are *plausibly* true of the candidate but are not in
their profile. They are questions: nothing reaches a document until the candidate accepts
the true ones into the private profile and regenerates. No API calls are made here.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cli.context import CliError, Console, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from services import claim_acceptance as acceptance
from services import suggested_claims as claims

ACTIONS = ("list", "accept", "reject")


def _content(args, config) -> Path:
    from cli.commands.render import find_content

    # find_content() falls back to the newest application for the selected profile.
    return find_content(getattr(args, "content", None), config)


def _profile_path(args, config) -> tuple[Path, str | None]:
    explicit = getattr(args, "profile_path", None)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise CliError(f"Profile not found: {path}", EXIT_NOT_FOUND)
        return path, None
    from services.profile_store import InvalidProfileIdError

    try:
        profile_id = config.require_profile_id()
    except InvalidProfileIdError as error:
        raise CliError(str(error), EXIT_USAGE, hint="Pass --profile-id <id> before the command.")
    path = config.store.profile_path(profile_id)
    if not path.is_file():
        raise CliError(config.store.unknown_message(profile_id), EXIT_NOT_FOUND)
    return path, profile_id


def run(args, console: Console, config) -> int:
    action = getattr(args, "claims_action", None)
    if action not in ACTIONS:
        raise CliError("Choose an action: list, accept or reject.", EXIT_USAGE,
                       hint="cvtailor --profile-id <id> claims list --content <app>/source/content.json")
    content = _content(args, config)
    if action == "list":
        return _list(content, console)
    if action == "reject":
        return _reject(args, content, console)
    return _accept(args, content, console, config)


def _list(content: Path, console: Console) -> int:
    record = claims.load_suggestions(content)
    suggestions = record["suggestions"]
    if console.as_json:
        console.json({"content": str(content), "suggestions": [
            {"number": i, **s} for i, s in enumerate(suggestions, 1)
        ], "dropped": record.get("dropped", [])})
        return EXIT_OK
    if not suggestions:
        console.out("No suggested claims for this application.")
        return EXIT_OK
    console.out("Suggested claims -- questions, not facts. Accept only statements that are TRUE.\n")
    for number, item in enumerate(suggestions, 1):
        console.out(f"{number}. [{item.get('status', 'pending')}] {item['proposed_text']}")
        console.out(f"     for: {item.get('requirement', '')}")
        console.out(f"     add to: {claims.describe_target(item['attach_to'])}")
        if item.get("rationale"):
            console.out(f"     why plausible: {item['rationale']}")
    console.out("\nAccept the true ones with: cvtailor --profile-id <id> claims accept "
                f"--content {content} <numbers>")
    return EXIT_OK


def _reject(args, content: Path, console: Console) -> int:
    try:
        done = acceptance.reject_suggestions(content, args.numbers)
    except acceptance.ClaimError as error:
        raise CliError(str(error), EXIT_USAGE)
    if console.as_json:
        console.json({"rejected": done})
    else:
        console.out(f"Marked rejected: {', '.join(map(str, done)) or 'none'}. The profile was not changed.")
    return EXIT_OK


def _accept(args, content: Path, console: Console, config) -> int:
    profile_path, profile_id = _profile_path(args, config)
    category = getattr(args, "category", None)
    try:
        plan = acceptance.accept_suggestions(
            content, profile_path, args.numbers, category=category,
            expected_profile_id=profile_id, dry_run=True,
        )
    except acceptance.ClaimError as error:
        raise CliError(str(error), EXIT_USAGE)

    for number, reason in plan.skipped:
        console.warn(f"Skipping #{number}: {reason}")
    if not plan.changes:
        console.out("Nothing to add.")
        if console.as_json:
            console.json(plan.as_dict())
        return EXIT_OK

    console.out(f"Profile: {profile_path}")
    console.out("These statements will be added to your PRIVATE profile:")
    for change in plan.changes:
        console.out(f"  + {change.description}")
    console.out(f"Method: {plan.approach} (a timestamped backup is saved beside the profile first)")
    for warning in plan.warnings:
        console.warn(warning)

    if not getattr(args, "yes", False):
        if console.as_json or sys.stdin is None or not sys.stdin.isatty():
            raise CliError("Confirmation required.", EXIT_USAGE,
                           hint="Review the changes, then re-run with --yes to confirm they are true.")
        answer = input("Are ALL of these statements true of you? Add them? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            console.warn("Cancelled. Nothing was changed.")
            return EXIT_OK

    try:
        result = acceptance.accept_suggestions(
            content, profile_path, args.numbers, category=category, expected_profile_id=profile_id,
        )
    except acceptance.ClaimError as error:
        raise CliError(str(error), 1)
    if console.as_json:
        console.json(result.as_dict())
        return EXIT_OK
    console.out(f"Added {len(result.changes)} statement(s) using {result.approach}.")
    console.out(f"Backup: {result.backup}")
    for warning in result.warnings:
        console.warn(warning)
    console.out("Regenerate the application so the new claims can appear in the documents:")
    console.out(f"  cvtailor --profile-id {profile_id or '<id>'} generate --job-file "
                f"{content.parent / 'job_description.txt'} --no-cache")
    return EXIT_OK
