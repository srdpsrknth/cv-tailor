# 0021 — Read saved applications; distinguish requested models from provider replies

**Status:** Approved and implemented (2026-11-17), following the owner's approval
of the GUI review and mockup. Extends ADR 0020; keeps Streamlit and the shared services.

## Decision

One read-only review view is shared by generation and the application library.
It reads the saved manifest, final content and profile snapshot. Comparisons use
that snapshot, not the current profile. Roles match by company, role and dates;
projects match by name. Duplicate identities are marked ambiguous; renamed or
consolidated projects are not guessed into a match. The saved model explanation
is labelled as generated rationale, not proof of quality or complete edit history.

Saved `models` remain the requested task routes. Optional provider response model
and request ID are retained in per-reply `calls`, alongside task, tokens, cost and
cost source. They are provider-reported evidence, not independent attestation.
Only received replies are itemised; transport retries are not counted as separate
document attempts. Legacy files without this data remain explicitly unrecorded.

The manifest adds `created_at`, `cache_hit`, `calls`, `cost_source`, `original_usage`
and `original_calls`. A cache hit separates current-run usage from original-generation
usage. Repeated cache hits preserve original usage rather than overwriting it with
zero. These fields are additive; old applications need no migration or new API call.
Failure audit trails retain raw drafts even before renderable content exists.

Candidate selection begins empty, including single-profile stores. Switching
candidates clears draft, search and review state. Reading a saved application,
comparing it, or viewing its rationale never initiates generation. Model selection
applies only to a new run and uses the existing curated catalogue.

**Superseded GUI selection detail (2026-11-17):** the owner subsequently requested
single-profile defaults and last-profile memory, implemented in ADR 0022. The
other isolation and read-only review guarantees above are unchanged.

## Consequences

The interface can distinguish configuration, historical requested models and actual
provider replies. Historical fields cannot be reconstructed reliably and are not
backfilled. Rendering previews adds `streamlit-pdf==2.1.0`; Streamlit stays pinned in
the lockfile and the minimum requirement now matches the verified 1.53.1 runtime.
Full application/submission tracking remains Phase 5; this change provides review,
search and downloads without inventing that workflow.
