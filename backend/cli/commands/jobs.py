"""``cvtailor jobs`` -- discover and rank postings (Phase 4).

The command is a thin adapter over :mod:`services.job_search`, matching the house
rule that interfaces do not duplicate business rules (the same rule Phase 6's UI
will rely on).

It is **free**: every approved source is a public endpoint requiring no
credentials, and no LLM call is made. Searching therefore does not need the
spend authorisation that a generation run does.
"""
from __future__ import annotations

from cli.context import CliError, Console, EXIT_FAILED, EXIT_OK, EXIT_USAGE
from services.profile_store import resolve_profile_id

ACTIONS = ("search", "sources")


def run(args, console: Console, config) -> int:
    """Dispatch a ``jobs`` subcommand."""
    action = getattr(args, "jobs_action", None) or "search"
    if action == "sources":
        return list_sources(args, console, config)
    if action == "search":
        return search(args, console, config)
    raise CliError(f"Unknown jobs action: {action}", EXIT_USAGE,
                   hint=f"Try one of: {', '.join(ACTIONS)}.")


def _apply_overrides(args, config):
    """Resolve which sources and employers to use, honouring CLI overrides.

    ``--ats`` and ``--softgarden-tenant`` _replace_ the built-in sample list rather
    than adding to it, because the samples are placeholders and a caller naming
    their own employers means those.
    """
    from services.job_connectors import (
        ArbeitnowSource,
        AtsBoard,
        AtsSource,
        PersonioSource,
        SoftgardenSource,
        SAMPLE_ATS_BOARDS,
        SAMPLE_PERSONIO_TENANTS,
        SAMPLE_SOFTGARDEN_TENANTS,
    )
    from services.job_http import JobHttpClient

    client = JobHttpClient(
        request_budget=getattr(args, "max_requests", None) or 60,
        min_interval=0.5,
    )

    ats_specs = getattr(args, "ats", None)
    boards = SAMPLE_ATS_BOARDS
    if ats_specs:
        boards = []
        for spec in ats_specs:
            # "platform:token" or "platform:token:Company Name"
            parts = str(spec).split(":", 2)
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise CliError(
                    f"--ats expects platform:token[:Company], got {spec!r}",
                    EXIT_USAGE,
                    hint="For example: --ats lever:mycompany:My Company",
                )
            boards.append(AtsBoard(platform=parts[0].lower(), token=parts[1],
                                   company=parts[2] if len(parts) > 2 else ""))

    tenants = getattr(args, "softgarden_tenant", None) or list(SAMPLE_SOFTGARDEN_TENANTS)
    personio = getattr(args, "personio_tenant", None) or list(SAMPLE_PERSONIO_TENANTS)

    sources = [
        SoftgardenSource(tenants, client=client),
        PersonioSource(
            personio, client=client,
            tenant_url_builder=lambda tenant, pid: (
                f"https://{tenant}.jobs.personio.de/job/{pid}"
            ),
        ),
        AtsSource(boards, client=client),
        ArbeitnowSource(client=client),
    ]

    only = getattr(args, "only_source", None)
    if only:
        wanted = {name.strip().lower() for name in only}
        sources = [source for source in sources if source.name.lower() in wanted]
        if not sources:
            raise CliError(
                f"No known source matches {', '.join(sorted(wanted))}.",
                EXIT_USAGE,
                hint="Run `cvtailor jobs sources` to see the available names.",
            )
    return sources


def list_sources(args, console: Console, config) -> int:
    """Show which sources are available and what each can do."""
    sources = _apply_overrides(args, config)
    rows = []
    for source in sources:
        caps = source.capabilities
        rows.append({
            "name": source.name,
            "search": source.capabilities.server_side_keywords,
            "enumerable": caps.enumerable,
            "posted_at": caps.provides_posted_at,
            "credentials": caps.requires_credentials,
            "verified": caps.verified_on or "-",
        })

    if console.as_json:
        console.json({"sources": rows})
        return EXIT_OK

    console.out("Job sources (all free; no credentials required)")
    console.out("")
    console.table(
        [[row["name"], "yes" if row["enumerable"] else "no",
          "yes" if row["posted_at"] else "no",
          "yes" if row["credentials"] else "no", row["verified"]]
         for row in rows],
        ["source", "full corpus", "posted date", "needs key", "verified"],
    )
    console.out("")
    console.out("None of these can filter by keyword at the source, so a keyword")
    console.out("search fetches the corpus and filters locally. That is reported")
    console.out("in the results rather than hidden.")
    console.out("")
    console.out("Not built, on the operator's own terms: StepStone, Indeed and")
    console.out("LinkedIn (their robots.txt disallow the paths needed), and")
    console.out("SmartRecruiters (its API host disallows all crawlers).")
    return EXIT_OK


def search(args, console: Console, config) -> int:
    """Run a search, deduplicate, rank, and report the outcome."""
    from models.job import SearchQuery
    from services.job_match import MatchPreferences
    from services.job_search import search_jobs, summarise

    profile_id = resolve_profile_id(config, getattr(args, "profile_id", None))
    try:
        profile = config.store.load(profile_id)
    except Exception as error:
        raise CliError(str(error), EXIT_FAILED,
                       hint="Run `cvtailor profile list` to see the available ids.")

    keywords = getattr(args, "keywords", None)
    query = SearchQuery(
        keywords=keywords,
        country=getattr(args, "country", None),
        city=getattr(args, "city", None),
        remote=(True if getattr(args, "remote", False) else None),
        limit=getattr(args, "limit", None) or 10,
    )

    preferences = MatchPreferences.from_profile(
        profile, keywords=tuple(keywords.split()) if keywords else (),
    )
    sources = _apply_overrides(args, config)

    if not console.as_json:
        console.out(f"Searching for {profile_id}: {query.describe()}")
        console.out(f"Sources: {', '.join(source.name for source in sources)}")
        console.out("")

    outcome = search_jobs(
        sources, profile, query,
        preferences=preferences,
        store_root=config.profile_store_dir,
        profile_id=profile_id,
    )

    if console.as_json:
        console.json(outcome.as_dict())
        return EXIT_OK

    for note in outcome.notes:
        console.warn(note)

    if not outcome.results:
        console.out("No matching jobs.")
        if outcome.failures:
            for name, message in outcome.failures.items():
                console.out(f"  {name} failed: {message}")
        console.out("")
        console.out("Try a broader keyword, or drop --country/--city.")
        return EXIT_OK

    for position, result in enumerate(outcome.results, start=1):
        job = result.job
        place = job.city.value or (job.country.value if job.country.is_verified else None)
        flags = []
        if job.is_dach:
            flags.append("DACH")
        remote = job.resolved_remote().value
        if remote != "unknown":
            flags.append(remote)
        if result.eligibility.value == "uncertain":
            flags.append("CHECK")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        console.out(f"{position:2}. {job.title}{suffix}")
        console.out(f"    {job.company or '(company not stated)'}"
                    f"{'  --  ' + place if place else ''}")
        console.out(f"    {job.source}  {job.url}")
        for line in result.explanation():
            console.out(f"      {line}")
        console.out("")

    console.out(summarise(outcome))
    return EXIT_OK
