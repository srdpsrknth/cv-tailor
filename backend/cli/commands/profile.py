"""``cvtailor profile`` -- inspect the configured profile.

Phase 1 ships ``show`` only. ``list``/``new``/``edit``/``import``/``export``
arrive with the multi-profile store in Phase 2, when there can be more than one
profile to choose between.
"""
from __future__ import annotations

from pathlib import Path

from cli.context import CliError, Console, EXIT_NOT_FOUND


def run(args, console: Console, config) -> int:
    """Dispatch a ``profile`` subcommand."""
    action = getattr(args, "profile_action", None) or "show"
    if action != "show":
        raise CliError(f"Unknown profile action: {action}", 2)
    return show(args, console, config)


def show(args, console: Console, config) -> int:
    """Print the loaded profile, or a summary of it."""
    from services.profile_loader import load_profile

    path = Path(getattr(args, "profile_path", None) or config.profile_path)
    if not path.exists():
        raise CliError(
            f"Profile not found: {path}",
            EXIT_NOT_FOUND,
            hint="Set storage/profile/profile.yaml, or pass --profile <path>.",
        )
    try:
        profile = load_profile(str(path))
    except ValueError as error:
        raise CliError(f"Profile is invalid: {error}", EXIT_NOT_FOUND)

    if console.as_json:
        console.json({"path": str(path), "profile": profile.model_dump()})
        return 0

    identity = profile.identity
    console.out(f"Profile: {path}")
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
    return 0
