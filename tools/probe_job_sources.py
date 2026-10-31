"""Probe the candidate job sources and print a verified evidence table.

Read-only: it fetches public endpoints and prints what actually came back.
Nothing is written, nothing is stored. Run it to reproduce the ADR 0008 §1
findings rather than trusting a summary.

    .venv\\Scripts\\python.exe tools\\probe_job_sources.py
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

UA = "cv-tailor-research/1.0 (+personal job-search tool; contact via repo)"

#: (label, method, url, body, content-type)
PROBES = [
    ("BA Jobsuche token endpoint", "POST",
     "https://rest.arbeitsagentur.de/oauth/gettoken_cc",
     b"client_id=jobboerse-jobsuche&client_secret=XY7kmzoNzl100",
     "application/x-www-form-urlencoded"),
    ("BA Jobsuche jobs search", "GET",
     "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
     "?was=Data%20Engineer&wo=Berlin&umkreis=25&size=3",
     None, None),
    ("Adzuna DE search (no creds)", "GET",
     "https://api.adzuna.com/v1/api/jobs/de/search/1?results_per_page=2", None, None),
    ("Jooble (no key)", "POST", "https://jooble.org/api/test",
     b'{"keywords":"data engineer","location":"Berlin"}', "application/json"),
    ("Arbeitnow job board", "GET",
     "https://www.arbeitnow.com/api/job-board-api", None, None),
    ("Arbeitnow page 2", "GET",
     "https://www.arbeitnow.com/api/job-board-api?page=2", None, None),
    ("Lever postings", "GET",
     "https://api.lever.co/v0/postings/leverdemo?mode=json", None, None),
    ("Greenhouse board", "GET",
     "https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs", None, None),
    ("SmartRecruiters postings", "GET",
     "https://api.smartrecruiters.com/v1/companies/SmartRecruiters/postings",
     None, None),
    ("Ashby posting API", "GET",
     "https://api.ashbyhq.com/posting-api/job-board/ashby", None, None),
    ("Personio tenant XML", "GET", "https://join.jobs.personio.de/xml", None, None),
    ("softgarden DataFeed", "GET",
     "https://softgarden.career.softgarden.de/jobs.feed.json", None, None),
    ("Remotive", "GET", "https://remotive.com/api/remote-jobs?limit=2", None, None),
    ("Jobicy", "GET", "https://jobicy.com/api/v2/remote-jobs?count=2", None, None),
    ("Himalayas", "GET", "https://himalayas.app/jobs/api?limit=2", None, None),
    # --- compliance evidence: these decide which sources may be built at all -------
    ("StepStone robots.txt", "GET", "https://www.stepstone.de/robots.txt", None, None),
    ("Indeed DE robots.txt", "GET", "https://de.indeed.com/robots.txt", None, None),
    ("LinkedIn robots.txt", "GET", "https://www.linkedin.com/robots.txt", None, None),
    ("Arbeitnow robots.txt", "GET", "https://www.arbeitnow.com/robots.txt", None, None),
    # SmartRecruiters WORKS (200) but its API host disallows every crawler. Both
    # facts belong here, because "it responds" is not "it is permitted" (ADR 0008 §3).
    ("SmartRecruiters robots.txt", "GET",
     "https://api.smartrecruiters.com/robots.txt", None, None),
    ("softgarden robots.txt", "GET",
     "https://softgarden.career.softgarden.de/robots.txt", None, None),
]

#: Pages probed for embedded JSON-LD. ADR 0008 §2 ranks ATS JSON-LD highly, but it is
#: NOT universal: Greenhouse serves none. These counts are the evidence for that claim,
#: and Lever is kept as a positive control so a zero means "absent", not "probe broken".
LDJSON_PAGES = [
    ("Lever job page (control, expect >=1)", "https://jobs.lever.co/leverdemo/"
     "ad208490-4052-4f91-a57e-433f2d1e484b"),
    ("Greenhouse job-boards page", "https://job-boards.greenhouse.io/greenhouse/jobs/8126988"),
    ("Greenhouse boards page", "https://boards.greenhouse.io/figma/jobs/5426468004"),
]


def probe(label, method, url, body, ctype):
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("User-Agent", UA)
    if ctype:
        request.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read()
            return response.status, response.headers.get("Content-Type", ""), raw
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()
    except Exception as error:  # noqa: BLE001 - a probe reports, it does not raise
        return None, "", str(error).encode()


def top_keys(raw: bytes) -> str:
    try:
        value = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(value, dict):
        return ", ".join(list(value)[:12])
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return "list[%d] of {%s}" % (len(value), ", ".join(list(value[0])[:12]))
    return type(value).__name__


def count_ldjson(raw: bytes) -> tuple:
    """Return ``(ld+json blocks, JobPosting mentions)`` in an HTML page."""
    text = raw.decode("utf-8", "replace")
    return text.count("application/ld+json"), text.count("JobPosting")


def main() -> None:
    print(f"{'source':32} {'status':>6}  {'bytes':>9}  keys / note")
    print("-" * 100)
    for label, method, url, body, ctype in PROBES:
        status, _ctype, raw = probe(label, method, url, body, ctype)
        note = top_keys(raw) or raw[:70].decode("utf-8", "replace").replace("\n", " ")
        print(f"{label:32} {str(status):>6}  {len(raw):>9}  {note[:70]}")

    print()
    print("JSON-LD availability on ATS-hosted job pages (ADR 0008 §2 assumes this is common)")
    print("-" * 100)
    for label, url in LDJSON_PAGES:
        status, _ctype, raw = probe(label, "GET", url, None, None)
        blocks, mentions = count_ldjson(raw)
        print(f"{label:38} {str(status):>6}  ld+json={blocks:<3} JobPosting={mentions}")


if __name__ == "__main__":
    main()
