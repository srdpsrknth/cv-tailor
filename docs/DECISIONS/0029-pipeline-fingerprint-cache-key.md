# ADR 0029 — Pipeline fingerprint in the generation cache key

**Status:** Approved, 2026-11-27 (multi-candidate cleanup, PR #1).
**Related:** ADR 0015 (generation cache), ADR 0025.

## Context

ADR 0015 keys cached generations on the bytes the model was shown. Some ingredients that change
the result were missing: `EDITORIAL_REQUIREMENTS` and the prompt-building code in
`services/prompts.py`, the layout budget and attempt constants, and the CV template. Editing them
silently served stale drafts.

## Decision

`cache_key` takes a `pipeline_version` produced by `services/pipeline_fingerprint.py`. It hashes:

- the prompt-building functions' source text and `EDITORIAL_REQUIREMENTS`;
- the layout budget and attempt constants, read at call time;
- the CV template bytes;
- the validation modules' source.

Line endings are normalised (CRLF to LF) so the key is identical on Windows and macOS.
The fingerprint is included only when non-empty, so callers that do not pass it are unaffected.

## Consequences

- Any edit to those ingredients, including a pure refactor, invalidates cached drafts once.
  The cache stays safe to delete (ADR 0015).
- Cache hits are still re-validated, so a stricter validator applies even to an old cached draft.
