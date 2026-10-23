# 0004 — Files keyed by `profile_id`; no database server

**Status:** Approved (2026-10-23)
**Related:** [0002](0002-privacy-model.md), [0003](0003-profile-identity.md), [0006](0006-remote-profile-access.md)

## Context

Storage options were compared against actual requirements: simplicity, reliability, data
integrity, portability, migration support, multi-profile isolation, backup/recovery and
future web access.

Current usage is modest: one profile, 8 saved applications, a handful of generated
documents. Phase 4 (job discovery) is the only plausible source of high-volume records.

YAML/JSON on disk is already the working format (`profile.yaml`, `content.json`) and is
git-diffable, human-editable and directly consumable by the existing renderers.

Decision [0002](0002-privacy-model.md) requires all real data to live in a private store, and
the owner wants that store reachable from any machine with internet.

## Decision

Use **files on disk keyed by `profile_id`**:

```
<store>/profiles/<profile_id>/profile.yaml
<store>/profiles/<profile_id>/applications/<job_id>/source/content.json
```

**Phased rollout, matching the owner's preference to start local:**

1. **Phase 2 — local only.** `<store>` defaults to a directory outside the repository
   (e.g. `~/.cv-tailor/`), configurable. No network, no sync, no new dependency.
2. **Later, when the remote store is built** ([0006](0006-remote-profile-access.md)) — the
   same layout is served by a remote backend; the CLI gains `--remote` and a local cache.

Adopt **SQLite only if** Phase 4's job-discovery volume makes file scanning genuinely
painful. **No database server.**

## Consequences

- Preserves the current editing workflow and the zero-LLM-cost deterministic re-render path.
- Diffable and trivially backed up; portable across Windows/macOS/Linux.
- The store path is configuration, not code — moving from local to remote does not change
  the on-disk layout, so migration is a copy.
- Requires an explicit migration for incompatible data-model changes rather than ad-hoc edits.
- Validation must be strengthened at the file boundary, since files are hand-editable:
  dates are currently unvalidated strings (`backend/models/profile.py:41-42`) and must be
  validated.
- If SQLite is later adopted, it replaces the *index*, not the document store.
