# 0008 — Job sources: ToS-compliant APIs first, scraping only if justified

**Status:** Approved in principle (2026-10-23) — scope to be determined at Phase 4
**Related:** [ROADMAP.md](../ROADMAP.md) Phase 4

## Context

The product should eventually discover jobs rather than relying on pasted descriptions.
Candidate sources include official company career pages, applicant-tracking systems, public
job APIs, RSS feeds and major job boards (LinkedIn, Indeed, StepStone, Glassdoor and regional
alternatives).

**None of these should be assumed to offer a public API or to permit scraping.** Terms of
service, authentication requirements, rate limits, data freshness and reliability vary
widely, and several major boards actively prohibit automated collection.

The owner's position: research ToS-compliant APIs first, but accepts that **scraping may be
necessary** to get broader coverage. Full scope to be determined when Phase 4 is reached.

## Decision

1. **Research and document ToS-compliant access first**, before writing any connector. For
   each candidate source record: official access method, authentication, ToS position,
   scraping restrictions, rate limits, search capabilities, freshness, reliability, cost and
   maintenance burden.
2. **Prefer, in order:** public/official APIs → RSS and structured feeds → official partner
   programmes → ATS-hosted public endpoints (many expose structured `JobPosting` JSON-LD,
   which the existing application skill already uses successfully).
3. **Scraping is a last resort**, and only where it is permitted. If it is used it must be
   rate-limited, identify itself honestly, respect `robots.txt`, and be isolated behind the
   connector interface so it can be disabled without breaking anything else.
4. **Do not build unreliable scraping workarounds** that break silently or violate terms.
5. **Re-confirm scope with the owner at the start of Phase 4**, including which sources
   matter and what coverage is actually needed.

## Consequences

- Connectors stay modular behind one `JobSource` interface, normalising to a shared `Job` model.
- Fewer, more reliable sources are preferred over broad, brittle coverage.
- Every record preserves its source and distinguishes verified fields from inferred ones.
- A source that changes or withdraws access affects only its own connector.
- Legal and maintenance risk is contained and visible rather than spread through the codebase.
