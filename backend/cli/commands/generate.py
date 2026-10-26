"""``cvtailor generate`` -- tailor a CV and cover letter from a posting.

The posting can come from ``--job-file``, ``--job`` (inline text) or stdin, so
the command is usable both interactively and in a pipeline. This is the only
command that calls a paid API.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cli.context import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    CliError,
    Console,
    human_pages,
)

#: TailorRequest enforces this; check it first so the message is the CLI's own.
MIN_JOB_DESCRIPTION = 50


def _load(path: Path):
    """Load a loose profile file named explicitly with ``--profile``."""
    from services.profile_loader import load_profile

    return load_profile(str(path))


def read_job_description(args, console: Console) -> str:
    """Read the posting from a file, an inline argument, or stdin."""
    if getattr(args, "job_file", None):
        path = Path(args.job_file).expanduser()
        if not path.exists():
            raise CliError(f"Job description file not found: {path}", EXIT_NOT_FOUND)
        return path.read_text(encoding="utf-8")

    if getattr(args, "job", None):
        return args.job

    if not sys.stdin or sys.stdin.isatty():
        raise CliError(
            "No job description given.",
            EXIT_USAGE,
            hint="Pass --job-file <path>, --job 'text', or pipe the posting on stdin.",
        )
    return sys.stdin.read()


def run(args, console: Console, config) -> int:
    from services.profile_store import (  # noqa: F401
        InvalidProfileIdError,
        UnknownProfileError,
    )
    from services.tailor_service import tailor_documents

    # Resolve the candidate before anything else: a missing id must fail before any
    # paid API call, and before a folder exists to write into (ADR 0003).
    store = config.store
    if getattr(args, "profile_path", None):
        profile_id = None
        profile_path = Path(args.profile_path)
    else:
        try:
            profile_id = config.require_profile_id()
        except InvalidProfileIdError as error:
            raise CliError(str(error), EXIT_USAGE,
                           hint="Run `cvtailor profile list` to see the ids you have.")
        profile_path = store.profile_path(profile_id)

    try:
        # A store id goes through the store; a loose --profile file is loaded directly.
        profile = _load(profile_path) if profile_id is None else store.load(profile_id)
    except UnknownProfileError as error:
        raise CliError(str(error), EXIT_NOT_FOUND,
                       hint="Run `cvtailor profile list` to see the available ids.")
    except FileNotFoundError:
        raise CliError(f"Profile not found: {profile_path}", EXIT_NOT_FOUND)
    except ValueError as error:
        raise CliError(f"Profile is invalid: {error}", EXIT_NOT_FOUND)

    job_description = read_job_description(args, console).strip()
    if len(job_description) < MIN_JOB_DESCRIPTION:
        raise CliError(
            f"Job description is too short ({len(job_description)} characters).",
            EXIT_USAGE,
            hint=f"Paste the full posting; at least {MIN_JOB_DESCRIPTION} characters.",
        )

    if not config.has_api_key:
        raise CliError(
            "GEMINI_API_KEY is not set, so generation cannot run.",
            EXIT_CONFIG,
            hint=f"Add it to {config.project_root / '.env'}, then run `cvtailor doctor`.",
        )

    if not console.as_json:
        label = profile_id or str(profile_path)
        console.out(f"Profile:  {profile.identity.full_name}  [{label}]")
        console.out(f"Model:    {config.model}")
        if getattr(args, "company", None):
            console.out(f"Company:  {args.company}")
        if getattr(args, "role", None):
            console.out(f"Role:     {args.role}")
        console.out("")
        console.out("Generating. This makes several paid API calls...")

    def status(message: str) -> None:
        if not console.as_json:
            console.out(f"  {message}")

    try:
        result = tailor_documents(
            job_description=job_description,
            profile=profile,
            company_name=getattr(args, "company", None),
            role_title=getattr(args, "role", None),
            status_callback=None if console.as_json else status,
            work_country=getattr(args, "country", None),
            config=config,
            # Explicit, so the output folder is keyed to the candidate even when the
            # config carries no id because a loose --profile file was used.
            profile_id=profile_id,
            # A repeat of one profile against one posting is served from the store's
            # cache, so it costs nothing. --no-cache forces a fresh draft (and still
            # stores it), which is the escape hatch when the stored one is unwanted.
            use_cache=not getattr(args, "no_cache", False),
        )
    except ValueError as error:
        raise CliError(f"Generation failed: {error}")

    if console.as_json:
        console.json(result.model_dump())
        return 0

    console.out("")
    console.out(f"Done: {result.job_id}")
    console.out(f"  CV:            {human_pages(result.cv_page_count)}  {result.cv_path}")
    console.out(f"  Cover letter:  {human_pages(result.cover_letter_page_count)}  {result.cover_letter_path}")
    if result.cl_pdf_path:
        console.out(f"  Cover PDF:     {result.cl_pdf_path}")
    console.out(f"  Editable copy: {result.source_path}")
    usage = result.token_usage
    console.out("")
    console.out(
        f"  Tokens: {usage.total_tokens:,} "
        f"(CV {usage.cv_attempts} call(s), letter {usage.cl_attempts}) "
        f"~${usage.estimated_cost_usd:.4f}"
    )
    if result.tailoring_explanation:
        strategy = result.tailoring_explanation.get("overall_strategy")
        if strategy:
            console.out("")
            console.out(f"  Strategy: {strategy}")
    console.out("")
    console.out(f"Revise the text in {result.source_path}, then: cvtailor render --content \"{result.source_path}\"")
    return 0
