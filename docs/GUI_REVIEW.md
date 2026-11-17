# GUI review and proposed improvements

Reviewed 2026-11-17 against the running Windows GUI, all four pages, `ui/app.py`,
`ui/services_bridge.py`, generation persistence and provider response handling.
**Implementation status (2026-11-17):** the owner approved this proposal and the
review workflow has been implemented in Streamlit; see ADR 0021 and PROJECT_STATE.
The material below preserves the findings and design rationale. Full Phase 5
submission tracking and provider-catalogue expansion remain out of scope.

## Current experience

Streamlit now calls shared services in process, with four pages: Generate, Find
jobs, Applications and Help. That architecture should stay. This review does not
reopen ADR 0020 or reassess the overall architecture.

The live 1280 x 720 view spends roughly the top half of the main column on the
title, tagline, installation metadata and separators. The primary action falls
below the initial viewport. The sidebar truncates the candidate name while
devoting considerable space to developer-oriented instructions. Applications show
technical folder IDs, filenames and download buttons rather than a review workspace.
The one application visible during inspection lacks editable content; older entries
therefore need honest partial-data states, not assumed explanations or model data.

Useful existing features: shared storage across CLI/GUI, generation progress,
download buttons, token/cost summaries, free search with evidence-based explanations,
and explicit warnings when application files are incomplete.

## Priority 1: an application review workspace

Show the same detail view after generation and when reopening a saved application.
Keep it usable across reruns and navigation, scoped to both profile and application.

Suggested layout: compact company/role heading and status, then a short run summary
and tabs for **Documents**, **What changed**, **Why these changes**, and **Run details**.

- Documents: CV/letter previews with nearby download buttons, page count and letter
  word count. Show only checks actually performed; successful generation does not
  establish exhaustive factual accuracy or visually perfect output.
- What changed: deterministic, section-level comparisons of `profile_snapshot.json`
  with final `content.json`. Support additions, omissions, rewording and skill order.
  Align by employer/role/project rather than array position, and flag ambiguous
  alignment. The cover letter has no original counterpart unless a prior version
  exists. Compare against the saved snapshot, not today's possibly edited profile.
- Why these changes: display the saved `tailoring_explanation` fields for summary,
  bullets, skills, projects and strategy. Label this **Model explanation**; it is
  generated rationale, not independently verified causality, and it does not prove
  another model would have written worse text. Missing rationale stays unavailable;
  viewing an older application must never silently trigger a paid request.
- Run details: provider, requested models per task, tokens, calls/retries, timestamps,
  fresh/cached status and cost with provenance. Existing manifests have requested
  routes and aggregate usage; requested routes are not provider confirmation.

Backend gap: `ProviderResponse` currently retains text, tokens and reported charge,
but not response model or request ID. Preserve those optional response fields and
per-call task/model records before presenting **provider-confirmed model**. Do not
substitute the default model label for task overrides. Persist cache provenance and
cost provenance explicitly; zero tokens alone are not a robust cache indicator.
Distinguish this run's charge from the original generation's charge on a cache hit.

Existing explanation and manifest display can ship first without adding model calls.
Precise comparisons and provider-confirmed attribution require additional work.

## Priority 2: fix workflow and state

- Correct the profile picker: it uses a configured or first index today, contrary to
  ADR 0003 and its own help text. Begin unselected and require a deliberate choice.
  Switching profiles must clear or isolate active application/search/form state.
- Preserve generated results and search results across widget interactions and page
  navigation. Generation returns early unless its button fires; `last_job_id` and
  `last_job_folder` are written but never restored. Search also returns before
  rendering results unless its form is submitted on that rerun.
- Validate the posting before paid work using the shared service boundary. The CLI
  rejects accidental pasted CV Tailor commands, but the UI only checks nonblank text.
- Retain structured failure information and a link to saved drafts. The bridge
  currently sets `drafts_saved=True` for every generation exception without checking
  whether persistence was reached. Show what actually survived and whether a retry
  will make paid calls.
- Replace the fixed '$0.003' progress label with model-aware, clearly estimated
  wording; report observed cost after completion. Do not imply a hard spend cap
  unless the generation path enforces it.

## Priority 3: better page-level functionality

Generate: show a compact preflight strip (selected candidate, task models, PDF
engine and API-key configuration), then posting + company/role/country, optional
curated-model selector, cache choice and a visible primary action. Key configured
and key verified are distinct states. Selecting a model applies to the new run
and must never relabel a saved application's historical model. Keep advanced
per-task routing out of the default view. Use only the existing curated catalogue;
do not invent quality ratings or expose the entire provider catalogue.

Applications: readable company/role/date rows; search and filters; status and
model/cache metadata when present; access beyond the bridge's current 20-entry
limit; select a row to open the common review view. Partial/legacy entries should
still allow downloads. Organising and reviewing applications can precede Phase 5's
full submission/interview tracker.

Find jobs: persist filters/results, add **Use this posting** to transfer known
posting text and provenance to Generate, with user review before any paid action.
Do not silently fabricate or fetch blocked/missing descriptions. Rename **Match**
to **Matching signals**, since the score counts evidence rather than estimating
hire probability. Separate eligibility, unknowns, source failures and freshness.
Replace the instruction to edit `SAMPLE_*` Python constants with readable source
coverage; a source editor is a separate feature.

Settings/help: move store paths and diagnostics here; add a read-only profile
summary, actionable setup checks and concise help. Prefer safe selection and
diagnostics before adding unrestricted profile or credential editors.

## Visual direction

Use a restrained editorial workspace: warm off-white canvas, dark ink text, teal
for primary actions and amber for attention. Keep decoration minimal so document
text remains the focus. A serif page title paired with readable system sans text
can distinguish the app without a framework migration or external font requests.

Use a compact sidebar with navigation and the selected candidate. Replace the
oversized installation panel with a small contextual strip. Hide raw paths and
framework deployment controls from the normal task flow where configuration
allows. Use consistent spacing, labelled icons, descriptive download labels and
short human titles. Avoid long filenames as primary labels. Maintain contrast,
visible keyboard focus and text labels alongside status colours. Stack the input
and review panes on narrow screens; put advanced details behind disclosure controls.

The accompanying [interactive mockup](design/gui-proposal.html) uses entirely
synthetic text and illustrates the proposed application review view. Metrics are
explicitly illustrative, not measurements from a real application.

## Suggested delivery order and acceptance

1. Persistent shared application detail view, saved explanation and honest model/
   token/cost display; fix explicit profile selection and rerun behaviour.
2. Document preview, deterministic comparison and provider/cache/cost provenance.
3. Search-to-generation handoff, searchable application library, curated model
   selection and settings/diagnostics, applying the visual system throughout.

Use synthetic fixtures for fresh/cached/failed/legacy/missing-explanation cases,
including different task models and profile changes. AppTest should prove that
navigation/download interactions do not discard results, crossing profiles never
shows another candidate's state, and viewing application details makes no LLM call.
Verify rendered browser layouts separately from behaviour tests. A green existing
suite does not certify untested behaviours such as deliberate profile selection.

No paid generation, live model comparison or job-source search was made for this
review. No production GUI code was changed.
