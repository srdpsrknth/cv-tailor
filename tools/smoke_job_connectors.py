"""Live smoke check: run the real connectors against the real endpoints.

This is the check tests cannot perform. The suite proves the connectors work
against *recorded* payloads; only this proves the recorded payloads still match
what the sources serve. It is read-only, free, and makes a handful of requests
against public endpoints with an honest User-Agent and a small budget.

    .venv\\Scripts\\python.exe tools\\smoke_job_connectors.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from models.job import JobSourceError, SearchQuery  # noqa: E402
from services.job_connectors import (  # noqa: E402
    ArbeitnowSource,
    AtsBoard,
    AtsSource,
    PersonioSource,
    SoftgardenSource,
)
from services.job_http import JobHttpClient  # noqa: E402


def check(label, source, query):
    """Run one connector and report what actually came back."""
    print(f"\n=== {label} ===")
    try:
        jobs = list(source.search(query))
    except JobSourceError as error:
        print(f"  FAILED: {error}")
        return None
    except Exception as error:  # noqa: BLE001 - a smoke check reports, never raises
        print(f"  FAILED ({type(error).__name__}): {error}")
        return None
    print(f"  {len(jobs)} job(s)")
    for job in jobs[:3]:
        country = job.country.value or "-"
        city = job.city.value or "-"
        posted = job.posted_at.date().isoformat() if job.posted_at else "-"
        print(f"    [{country}/{city}] {job.title[:56]}")
        print(f"      company={job.company[:40]!r} posted={posted} dach={job.is_dach}")
    for note in source.capabilities.limitations_for(query):
        print(f"    note: {note}")
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=25)
    args = parser.parse_args()

    client = JobHttpClient(request_budget=args.max_requests, min_interval=0.5)
    query = SearchQuery(limit=args.limit)
    results = {}

    results["softgarden"] = check(
        "softgarden (official schema.org DataFeed)",
        SoftgardenSource(["softgarden"], client=client), query)

    results["personio"] = check(
        "Personio (official XML feed)",
        PersonioSource(["holidaycheck"], client=client,
                       tenant_url_builder=lambda t, i: f"https://{t}.jobs.personio.de/job/{i}"),
        query)

    # One real board per platform, so all three normalisers are exercised live.
    results["ats"] = check(
        "ATS family (Lever + Greenhouse + Ashby)",
        AtsSource([AtsBoard("lever", "leverdemo", "Lever"),
                   AtsBoard("greenhouse", "stripe", "Stripe"),
                   AtsBoard("ashby", "ashby", "Ashby")], client=client), query)

    results["arbeitnow"] = check(
        "Arbeitnow (public job board API, Germany-first)",
        ArbeitnowSource(client=client, max_pages=1), query)

    print("\n=== summary ===")
    for name, jobs in results.items():
        status = f"{len(jobs)} job(s)" if jobs is not None else "FAILED"
        print(f"  {name:12} {status}")
    print(f"\n  requests made: {client.requests_made} / {client.request_budget}")
    print("  cost: $0.00 (all endpoints are free and require no credentials)")
    return 0 if any(jobs for jobs in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
