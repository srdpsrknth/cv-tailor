# ADR 0030 — Redesign job search rather than patch it

**Status:** Deferred, 2026-11-27 (decision to redesign recorded; the design is not yet written).
**Related:** ADR 0008 (job sources), ADR 0018 (job discovery).

## Context

An audit during the multi-candidate cleanup, and real use by a second candidate (health and
regulatory roles in Berlin, remote in Germany, and Ireland), found that the job-search feature
does not serve a multi-candidate, multi-country user well. Fixing it piecemeal was started and
then stopped in favour of a redesign.

## Requirements for the redesign (from the audit; verified items marked V)

- **Per-profile sources used by both UI and CLI (V).** Today custom boards are CLI flags only, and
  the UI always uses the sample boards, which appear as real results. Validate tenant and token
  strings before building URLs.
- **Eligibility (V).** `rules.home_countries` silently became the eligibility filter, and
  `country_overrides` was ignored. Countries with an override (for example, those needing employer
  support) were hidden, and excluded counts were never shown.
- **Country-less postings (V).** Personio, and some Arbeitnow and Greenhouse postings, have no
  country and were dropped by any country filter. Infer the country, or mark it uncertain.
- **Limit and ranking (V).** `limit` was applied per source before ranking, so later boards were
  never read. One failing board aborted its whole source.
- **Language level (V).** Proficiency was ignored (A2 counted as "has German"); an
  "English postings only" option is needed.
- **Keywords.** AND-only substring matching; OR, phrase and title-only modes are needed.
- **Seniority.** Entry-level (Werkstudent, Praktikum, Intern, Junior, Graduate) preferences are
  needed; "lead" over-matches.
- **Other:** hybrid vs onsite, Greenhouse descriptions, Lever company names, same-source duplicate
  variants, expiry reporting on filtered runs, 429/Retry-After handling, `jobs search --profile`.
- **Coverage:** Workday-based employers (most CROs and large medtech) are unsupported. Document
  this, or design a compliant connector.

## Decision

Do not extend the current implementation further. The previous partial fix attempt is not merged.
Write the redesign as a new ADR before implementation.
