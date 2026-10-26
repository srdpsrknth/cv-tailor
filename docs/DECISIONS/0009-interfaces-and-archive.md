# 0009 — Keep FastAPI and Streamlit; keep `applications/` read-only until Phase 2

**Status:** Approved (2026-10-23)
**Related:** [ROADMAP.md](../ROADMAP.md) Phase 6, Phase 2

## Context

Two questions were open.

**Interfaces.** The repository already contains FastAPI (`backend/main.py`) and Streamlit
(`ui/app.py`). Both work. The CLI-first direction does not require removing them, and the
owner prefers to keep them and reassess at Phase 6.

**Existing archive.** `applications/` holds 8 reviewed applications with inconsistent schemas
(`application_context.txt` vs `.json`, `posting.txt` vs `job_posting.json`, plus one-off
scripts such as `finalize_booking.py`). They are real, reviewed work and are the only
existing evidence of what good output looks like.

## Decision

**Keep FastAPI and Streamlit.** They are retained as **thin adapters over the new service
layer** — they must not contain business rules. Reassess their future at Phase 6, once the
CLI and multi-profile work have settled what the interfaces actually need.

**Keep `applications/` read-only until Phase 2.** Do not edit, restructure or delete these
folders in the meantime. They are the reference corpus for:

- characterizing expected document quality (fixtures for Milestone 1.1);
- validating that the new schema can express everything the old one did.

Migrate them to the new schema in Phase 2, preserving reviewed content exactly.

### Amendment (2026-10-26) — the migration moves to Phase 5

Phase 2 is closed. It moved the archive out of the public repository into the private store at
`<store>/applications/<job_id>/` ([0011](0011-private-store-location.md)), but it did **not**
migrate the schemas. The owner has decided the migration is deferred to **Phase 5**, not
abandoned: Phase 5 (Application management) is the phase that owns application schemas, and the
archive is now private data that no longer sits in this repository at all.

The instruction above that reads "migrate them to the new schema in Phase 2" is therefore
**superseded**: read it as Phase 5. Nothing in the archive is deleted, rewritten or restructured
before then, and the schema variation still has to be handled explicitly rather than assumed —
the original reason for this decision is unchanged.

## Consequences

- No interface work is thrown away, and users keep a working UI during the refactor.
- The service layer becomes the single home for business rules, removing the current
  duplication where `ui/app.py:239-246` re-implements pricing from `gemini_service.py:28`.
- The archive stays a trustworthy reference during the refactor — but note it currently sits
  in the **public** repo and must move to the private store under
  [0002](0002-privacy-model.md).
- Phase 2 migration must handle the schema variation explicitly rather than assuming one shape.
