# ADR 0028 — Confirm-first suggested claims

**Status:** Proposed, 2026-11-27 (multi-candidate cleanup, PR #1). Awaiting owner approval.
**Related:** ADR 0002 (privacy), ADR 0003, ADR 0026.

## Context

Early-career profiles often under-describe real work in a posting's vocabulary.
Relaxing the fact rules so the model could "infer plausible achievements" was considered and
**rejected**: invented claims are a misrepresentation risk, especially in regulated fields where
interviews probe each bullet. Instead, a manual process proved useful. The model proposed
plausible reframings of existing work, the candidate confirmed only the true ones, and those were
added to the profile as facts.

## Decision

1. The CV call may return a top-level `suggested_claims` list, at most 8 items. Each item has a
   `requirement`, a `proposed_text` (a past-tense **statement**, never a question), an `attach_to`
   target (experience, experience project, standalone project or skill category, using exact
   profile names) and a `rationale`. The prompt asks for 3-8 items when important requirements are
   uncovered and related activities are plausible.
2. Suggestions are validated: targets must exist in the profile, and question-shaped, duplicate,
   over-long or already-present items are dropped with a log note. They are stored as
   `source/suggested_claims.json` and are **never rendered**.
3. A leak guard rejects a CV containing a suggestion's text (exact or near match) unless the
   profile already states it.
4. Accepting a suggestion is explicit: `cvtailor claims list|accept|reject`, or the review page's
   "Suggested claims (confirm only what is true)" panel with a confirmation step. Accepted text is
   written into the **private** profile by a comment-preserving targeted edit. A timestamped
   backup is taken first, the result is re-validated, and the edit is rolled back on failure. The
   decision is recorded with the application. Regeneration is needed before the claim can appear
   in documents.

## Consequences

- No unconfirmed statement can reach a document. The profile remains the single source of facts.
- Unusual YAML layouts fall back to a full rewrite, which loses comments; the backup is kept and
  the method is reported.
