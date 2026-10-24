"""``cvtailor profile`` -- list, inspect and manage candidate profiles.

Phase 1 shipped ``show`` only, against a single hardcoded path. With the store in
place (ADR 0004) there can be more than one candidate, so every action resolves an
explicit ``--profile-id`` and **fails closed** when it is missing (ADR 0003).

``list`` is the one command that needs no id: it is how a caller discovers the ids.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from cli.context import CliError, Console, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from services.profile_store import (  # noqa: E402  (backend is on sys.path by now)
    InvalidProfileIdError,
    ProfileStoreError,
    UnknownProfileError,
    validate_profile_id,
)

ACTIONS = ("list", "show", "new", "import", "export")


def run(args, console: Console, config) -> int:
    """Dispatch a ``profile`` subcommand."""
    action = getattr(args, "profile_action", None) or "show"
    if action == "list":
        return list_profiles(args, console, config)
    if action == "show":
        return show(args, console, config)
    if action == "new":
        return new(args, console, config)
    if action == "import":
        return import_profile(args, console, config)
    if action == "export":
        return export_profile(args, console, config)
    raise CliError(f"Unknown profile action: {action}", EXIT_USAGE,
                   hint=f"Try one of: {', '.join(ACTIONS)}.")


def _require_id(args, console, config) -> str:
    """Resolve the id for this action, or explain exactly how to supply one.

    Deliberately strict: with more than one profile in the store, guessing is how
    the wrong candidate's data gets read or overwritten. Never returns a value the
    caller did not ask for.
    """
    explicit = getattr(args, "profile_id", None)
    candidate = explicit or getattr(config, "profile_id", None)
    if not candidate:
        known = config.store.list_ids()
        hint = "Pass --profile-id <id>, or set CVTAILOR_PROFILE_ID in .env."
        if known:
            hint = f"Known profiles: {', '.join(known)}. " + hint
        else:
            hint = "No profiles exist yet. Create one with `cvtailor profile new <id>`."
        raise CliError(
            "Which profile? cv-tailor never picks one for you.",
            EXIT_USAGE,
            hint=hint,
        )
    try:
        return validate_profile_id(candidate)
    except InvalidProfileIdError as error:
        raise CliError(str(error), EXIT_USAGE)


# --- list -----------------------------------------------------------------------------

def list_profiles(args, console: Console, config) -> int:
    """List every profile in the store. Never needs an id -- it discovers them."""
    store = config.store
    entries = []
    for profile_id, path in store.iter_profiles():
        # A broken profile must show up as broken, not disappear from the list.
        try:
            from services.profile_loader import load_profile

            profile = load_profile(str(path))
            name, roles, status = profile.identity.full_name, len(profile.experience), "ok"
        except Exception as error:
            name, roles, status = "", 0, f"invalid: {error}"
        entries.append({"profile_id": profile_id, "name": name,
                        "roles": roles, "status": status, "path": str(path)})

    if console.as_json:
        console.json({"store": str(store.root), "profiles": entries})
        return EXIT_OK

    console.out(f"Store: {store.root}")
    if not entries:
        console.out("")
        console.out("No profiles yet.")
        console.out("  Create one:  cvtailor profile new <id>")
        console.out("  Or migrate:  cvtailor profile import <path> --profile-id <id>")
        return EXIT_OK

    console.out("")
    console.table(
        [[e["profile_id"], e["name"], e["roles"], e["status"]] for e in entries],
        ["profile_id", "name", "roles", "status"],
    )
    return EXIT_OK


# --- show -----------------------------------------------------------------------------

def show(args, console: Console, config) -> int:
    """Print one profile, or a summary of it."""
    store = config.store

    # An explicit --profile <file> still works and is still explicit.
    explicit_path = getattr(args, "profile_path", None)
    if explicit_path and not getattr(args, "profile_id", None):
        return _show_loaded(console, Path(explicit_path), str(explicit_path),
                            source="--profile")

    profile_id = _require_id(args, console, config)
    path = store.profile_path(profile_id)
    try:
        profile = store.load(profile_id)
    except UnknownProfileError as error:
        raise CliError(str(error), EXIT_NOT_FOUND,
                       hint="Run `cvtailor profile list` to see the available ids.")
    except ValueError as error:
        raise CliError(f"Profile is invalid: {error}", EXIT_NOT_FOUND,
                       hint=f"Fix the YAML at {path}.")
    return _show_loaded(console, path, profile_id, profile=profile)


def _show_loaded(console: Console, path: Path, label: str, profile=None, source=None) -> int:
    """Render one profile for a human or for ``--json``."""
    if profile is None:
        from services.profile_loader import load_profile

        if not Path(path).exists():
            raise CliError(
                f"Profile not found: {path}",
                EXIT_NOT_FOUND,
                hint="Pass --profile-id <id>, or --profile <path> for a loose file.",
            )
        try:
            profile = load_profile(str(path))
        except ValueError as error:
            raise CliError(f"Profile is invalid: {error}", EXIT_NOT_FOUND)

    if console.as_json:
        console.json({"profile_id": label, "path": str(path), "profile": profile.model_dump()})
        return EXIT_OK

    identity = profile.identity
    console.out(f"Profile: {label}")
    console.out(f"  Path      {path}")
    console.out(f"  Name      {identity.full_name}")
    if identity.tagline:
        console.out(f"  Tagline   {identity.tagline}")
    console.out(f"  Email     {identity.email}")
    if identity.phone:
        console.out(f"  Phone     {identity.phone}")
    if identity.location:
        console.out(f"  Location  {identity.location}")
    if identity.visa_status:
        console.out(f"  Visa      {identity.visa_status}")

    console.out("")
    console.out(f"Experience ({len(profile.experience)}):")
    for exp in profile.experience:
        dates = f"{exp.start_date} - {exp.end_date}"
        console.out(f"  {exp.role} @ {exp.company}  ({dates})")
        console.out(f"    {len(exp.bullets)} bullets, {len(exp.selected_projects)} projects")

    if profile.education:
        console.out("")
        console.out(f"Education ({len(profile.education)}):")
        for edu in profile.education:
            console.out(f"  {edu.degree} -- {edu.institution} ({edu.start_year}-{edu.end_year})")

    if profile.certifications:
        console.out("")
        console.out(f"Certifications ({len(profile.certifications)}):")
        for cert in profile.certifications:
            console.out(f"  {cert}")

    if profile.skills:
        total = sum(len(values) for values in profile.skills.values())
        console.out("")
        console.out(f"Skills: {total} across {len(profile.skills)} categories")

    rules = profile.rules
    console.out("")
    console.out(f"Validation rules: {'declared in profile' if rules else 'built-in defaults'}")
    if rules:
        if rules.employers:
            console.out(f"  Employer rules: {', '.join(sorted(rules.employers))}")
        if rules.banned_tools:
            console.out(f"  Banned tools:   {', '.join(rules.banned_tools)}")
        if rules.visa_label:
            console.out(f"  Visa label:     {rules.visa_label}")
    return EXIT_OK


# --- new ------------------------------------------------------------------------------

def new(args, console: Console, config) -> int:
    """Create a minimal, valid profile for a new candidate."""
    from models.profile import Identity, Profile

    profile_id = getattr(args, "profile_id", None)
    try:
        profile_id = validate_profile_id(profile_id)
    except InvalidProfileIdError as error:
        raise CliError(str(error), EXIT_USAGE)

    profile = Profile(
        version="1.0",
        identity=Identity(
            full_name=getattr(args, "name", None) or "New Candidate",
            email=getattr(args, "email", None) or "candidate@example.com",
        ),
    )
    try:
        path = config.store.create(profile_id, profile, overwrite=getattr(args, "force", False))
    except ProfileStoreError as error:
        raise CliError(str(error), EXIT_USAGE)

    if console.as_json:
        console.json({"profile_id": profile_id, "path": str(path), "created": True})
        return EXIT_OK
    console.out(f"Created profile {profile_id}")
    console.out(f"  {path}")
    console.out("")
    console.out("Edit that file to add experience, education and skills.")
    console.out(f"Then use it with: --profile-id {profile_id}")
    return EXIT_OK


# --- import ---------------------------------------------------------------------------

def import_profile(args, console: Console, config) -> int:
    """Copy an existing profile.yaml into the store, byte for byte."""
    source = Path(getattr(args, "source", "")).expanduser()
    if not source.is_file():
        raise CliError(f"Profile to import not found: {source}", EXIT_NOT_FOUND)

    raw_id = getattr(args, "import_profile_id", None) or getattr(args, "profile_id", None)
    if not raw_id:
        # The containing directory is the conventional id, and it is derived from the
        # file the caller named -- not from the environment or from other profiles.
        raw_id = source.parent.name
    try:
        profile_id = validate_profile_id(raw_id)
    except InvalidProfileIdError as error:
        raise CliError(str(error), EXIT_USAGE,
                       hint="Pass --profile-id <id> to choose the id explicitly.")

    try:
        path = config.store.import_file(
            source, profile_id, overwrite=getattr(args, "force", False)
        )
    except ProfileStoreError as error:
        raise CliError(str(error), EXIT_USAGE)
    except ValueError as error:
        raise CliError(f"That profile is invalid, so it was not imported: {error}", EXIT_USAGE)

    if console.as_json:
        console.json({"profile_id": profile_id, "path": str(path),
                      "source": str(source), "imported": True})
        return EXIT_OK
    console.out(f"Imported {source}")
    console.out(f"     -> {path}")
    console.out("")
    console.out("The file was copied verbatim; nothing was reformatted.")
    return EXIT_OK


# --- export ---------------------------------------------------------------------------

def export_profile(args, console: Console, config) -> int:
    """Copy a profile out of the store, for backup or for another machine."""
    profile_id = _require_id(args, console, config)
    source = config.store.profile_path(profile_id)
    if not source.is_file():
        raise CliError(
            f"No profile {profile_id!r} in {config.store.profiles_dir}",
            EXIT_NOT_FOUND,
            hint="Run `cvtailor profile list` to see the available ids.",
        )

    destination = Path(getattr(args, "destination", "")).expanduser()
    if destination.is_dir():
        destination = destination / f"{profile_id}.yaml"
    if destination.exists() and not getattr(args, "force", False):
        raise CliError(
            f"{destination} already exists.",
            EXIT_USAGE,
            hint="Pass --force to overwrite, or choose another path.",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

    if console.as_json:
        console.json({"profile_id": profile_id, "source": str(source),
                      "destination": str(destination)})
        return EXIT_OK
    console.out(f"Exported {profile_id}")
    console.out(f"  {source}")
    console.out(f"  -> {destination}")
    console.out("")
    console.warn("This file contains personal data. Do not commit it to a public repository.")
    return EXIT_OK
