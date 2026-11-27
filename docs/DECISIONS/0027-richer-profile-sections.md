# ADR 0027 — Richer, optional profile sections and tailorable standalone projects

**Status:** Approved, 2026-11-27 (multi-candidate cleanup, PR #1).
**Related:** ADR 0012, ADR 0015, ADR 0025.

## Context

An early-career candidate's CV relies on content the profile could not represent:
independent projects with dates and technologies, publications with detail bullets,
education highlights, and structured certifications. Standalone projects were selected by
name only and rendered verbatim, and the model sometimes dropped them, even though they were
the candidate's strongest evidence.

## Decision

All new fields are **optional**. They are omitted from the serialised profile while at their
defaults, so existing profiles produce identical prompt bytes, cache keys and snapshots.

- `standalone_projects_policy: select | all` (default `select`). `all` requires every project, in
  profile order, unless the Projects section is hidden.
- `TailoredCV.standalone_projects` accepts either names (rendered verbatim, as before) or
  `{name, bullets}` objects, where the bullets are reworded toward the posting using **only**
  facts in that project's profile bullets. The name must match the profile, and the bullets go
  through the same fact checks as employer project bullets (ADR 0026), including the no-new-numbers
  check. Layout retries may shorten them but never drop a project.
- Project `dates`, `technologies`, `context`; `education[].highlights`; `certifications` entries as
  a string or `{name, issuer, year}`.
- `publications` / `activities` entries as a string or `{text, bullets}`. A publication's `text` is
  the citation and is always rendered verbatim.
- `experience[].optional` (may be omitted) and `experience[].display_name` (short name in compact
  places). A role consisting of a single project renders it as a subheading with no
  "Selected Projects:" label.
- Optional `letter: {salutation, sign_off}` overrides the cover-letter defaults.

The CV response schema uses `anyOf` (name | object) for standalone projects. This was verified
against OpenRouter (`openai/gpt-6-luna`) on a live run.

## Consequences

- The CV response-schema digest changed (it is a cache-key ingredient), so existing cached drafts
  miss once.
- Older custom LaTeX templates that only read `publications` / `activities` as plain lists keep
  working but do not show the new bullets.
