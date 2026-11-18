# ADR 0025 — Deterministic, content-preserving CV layout selection

**Status:** Approved by owner, 2026-11-18; implemented on refactor branch.
**Related:** ADR 0024, `CV_LAYOUT_REVIEW.md`.

## Decision

The primary CV PDF renderer compares readable typography before generation asks a
model to shorten content. Auto is the shared default for GUI, CLI, cache rerenders
and saved-content rendering. Three coordinated presets retain the same hierarchy,
metadata size, margins and single-column main body:

| Preset | Body | Leading | List item spacing | Section spacing |
|---|---:|---:|---:|---:|
| Comfortable | 11pt | 13.2pt | 1.5pt | 8pt |
| Standard | 10.5pt | 12.6pt | 1.5pt | 8pt |
| Compact | 10.5pt | 12.2pt | 1.5pt | 8pt |

Each preset is rendered naturally. If a two-page result separates an employer and
its project, try one additional break before the first eligible split employer.
Do not move the first employer or enumerate every possible break. Explicit
`--layout-preset` on render CLI/script fixes typography but retains quality checks.
Custom templates without preset support remain fixed and are identified as custom.

All candidates must preserve source prose/order and expected fields in two PDF
extractors. Prefer geometry-safe results within two pages; genuine one-page fits
remain valid. Then minimize soft penalties for page endings outside 75–95% of the
printable height, imbalance, internal gaps above 36pt and employer/project splits.
A small readability preference breaks close scores. These are visual heuristics,
not minimum content quotas, ink coverage or ATS scores. Tie-breaking is stable.
Do not shrink below 10.5pt, add filler or vertically stretch content.

Keep headings and their opening content together; preserve individual project
blocks. A project continuing on a later page names its employer and says continued.
Use actual shipped page references, stabilizing them across compiler passes rather
than guessing the current page before a block moves.

When all layouts overflow, return an overflow PDF to the existing page-count/
shortening loop; never hide or discard prose. Defects on overflow are advisory
because it is not a successful generation. Geometry-defective results within the
page cap fail rendering. If no candidate retains the source, fail without replacing
an existing saved PDF. Shortening remains the existing validated model operation.

Embed the chosen preset, measurements, extraction results and candidate summaries
in `/CVLayout` PDF metadata. Record that data in per-artifact provenance, including
layout selector/extraction dependencies in rendering fingerprints. Metadata contains
no copied source prose; absence/corruption means unknown. Show measurements in saved
review as advisory. Word export retains its separate sequential layout and its own
pagination checks.

## Consequences

Rendering takes more local compiler/parser work, with no added model calls for
layout selection. Temporary candidates live outside application folders and are
cleaned on success/failure; replace the final PDF only after successful selection.
Selection is deterministic for the same inputs and renderer environment. Platform
font/compiler differences still require visual verification. Original saved files
are refreshed only when explicitly re-rendered; this implementation does not bulk
rewrite existing applications. Prompt size guidance changes future draft/cache
inputs without changing factual or letter policies.
