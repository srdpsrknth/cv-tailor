# 0003 — Thread an explicit `profile_id`; never default to a profile

**Status:** Approved (2026-10-23)
**Date:** 2026-10-23
**Related:** [Phase 0 assessment](../ARCHIVE.md#phase-0-assessment)

## Context

Today a single profile is hardcoded: `backend/services/profile_loader.py:27` returns
`storage/profile/profile.yaml` whenever no path is given, and no caller passes one.
`.env.example:25` sets `PROFILE_PATH` as a single process-wide value.

Verified isolation hazards once a second profile exists:

1. both candidates share one profile file;
2. `job_id` is derived only from company/role/timestamp (`tailor_service.py:200`), so two
   candidates applying to the same posting can collide on the same output folder and
   overwrite each other's `content.json`, drafts and PDFs;
3. `profile_snapshot.json` (`tailor_service.py:204`) would be silently replaced by the other
   candidate's identity;
4. `_validate_cv` validates generated text against whichever profile was loaded
   (`tailor_service.py:62-63,99`) — so candidate B's draft can be checked against
   candidate A's facts and wrongly pass;
5. the mirror path has no candidate segment (`tailor_service.py:284`).

## Decision

Make `profile_id` an **explicit, required** parameter, threaded from the CLI/API through the
service layer into every read and write path:

```
storage/profiles/<profile_id>/profile.yaml
outputs/<profile_id>/<job_id>/
```

**Fail closed**: if `profile_id` is missing or unknown, raise. Never fall back to a default
profile and never infer one from context.

**GUI amendment (owner instruction, 2026-11-17):** ADR 0022 permits the GUI to restore
its last valid selection or select the sole usable profile. It prominently displays
the active identity and passes that id explicitly. The rule above remains unchanged
for the CLI, API and services; no backend path guesses a profile.

## Consequences

- Cross-profile contamination becomes structurally impossible rather than merely unlikely.
- Existing single-profile call sites must be updated — a deliberate, visible change.
- `_validate_cv`'s candidate-specific rules move into profile-scoped configuration
  (see [Phase 0 assessment](../ARCHIVE.md#phase-0-assessment)).
- Requires a migration for the existing profile; it must preserve manual edits, titles,
  dates, factual ownership and ongoing-project status.
