# 0031 — Replace the Streamlit UI with a Svelte web UI served by FastAPI

**Status:** Approved (2026-11-28), owner decision, together with the [build plan](../UI_REDESIGN_PLAN.md).
**Related:** [0003](0003-profile-identity.md) (explicit `profile_id`), [0009](0009-interfaces-and-archive.md) (keep FastAPI + Streamlit), [0020](0020-streamlit-refactor.md) (Streamlit refactored onto the service layer), [0021](0021-application-review-and-provenance.md), [0022](0022-gui-profile-memory.md), [0028](0028-confirm-first-suggested-claims.md), [0030](0030-job-search-redesign.md)
**Supersedes, once the switch in step 7 below happens:** the "Streamlit" half of 0009, and decision 5 of 0020 ("Streamlit is kept").

## Context

ADR 0020 kept Streamlit only because NiceGUI could not be installed at the time. The framework was never chosen on its merits. The redesign research in [`docs/design/redesign/`](../design/redesign/) found:

- **What the product can do is mostly not in the GUI** ([capability inventory](../design/redesign/CAPABILITIES.md), section 3). Editing and re-rendering CV or letter text, editing a profile, regenerating an application, seeing a cost estimate before a paid run, and configuring job sources are CLI-only or hand-edited files.
- **Those missing features need what Streamlit does worst:** inline editing with live validation, keyboard-driven review, focus that survives an action, and a long paid run you can cancel while watching its progress. Streamlit reruns the whole script on every interaction and holds state in the browser session. Custom styling depends on its internal `data-testid` selectors.
- **The service boundary already exists.** `ui/services_bridge.py` imports no UI framework, and a test enforces that. A different frontend can reuse it without moving business rules.
- The stack comparison scored a Svelte 5 SPA highest, then React, then htmx (30, 29 and 28 out of 35), with Streamlit at its limit at 25. These are the research agent's judgement, not measurements.

## Decision

1. **A new web UI in `web/`**, built with Svelte 5, Vite and TypeScript as a plain single-page app (no SvelteKit server). Its built files are served by the existing FastAPI app at `/app/`.
2. **A versioned JSON API under `/api/v2`** in a new router module that only delegates to `ui/services_bridge.py` and the services. It contains no business rules. The existing `/api/tailor` and `/api/download/*` routes are unchanged.
   - `profile_id` is a path segment on every candidate-specific route, and is validated and fail-closed (ADR 0003).
   - Every paid operation (generation, regeneration, AI wording drafts, portal-answer drafts) requires an explicit `confirm_paid: true` field. Without it the API returns an error and makes no provider call.
   - Long operations return a run id and stream progress as server-sent events. A reloaded page reattaches to the run. A cancel request is honoured between provider calls.
   - Limits, validation results and display labels come from the API. The frontend never re-implements page limits, word budgets, work-authorization wording or pricing. A source-scan test enforces this, as the existing "no second pricing table" test does.
3. **Running the app needs Python only.** The built `web/dist` is committed, and a CI check fails if rebuilding produces a diff. Node (version pinned in `web/.nvmrc` and `engines`) is needed only to change the frontend.
4. **Local-only security.** The server binds to `127.0.0.1`. The UI is served same-origin, with no permissive CORS. A per-launch token or a Host-header check guards against DNS rebinding. Artifacts are served by whitelisted name only, with no path traversal and no symlinks or sync-conflict copies. Fonts and all assets are self-hosted, so the UI makes no request to any third-party host.
5. **Strangler migration, and Streamlit keeps working throughout.** The steps are in the [build plan](../UI_REDESIGN_PLAN.md). Streamlit stays the default until the new UI covers every behaviour in the existing `test_ui_*` tests. After that, `scripts/start.py` opens the new UI, and Streamlit remains available with `--legacy-ui` for one release before removal.
6. **Visual direction.** The layout is "Bench" with the Proof Desk palette, as recorded in the [design system](../design/DESIGN_SYSTEM.md) and [tokens](../design/tokens.css).
7. **UI vocabulary.** "Suggested additions" (shown as S1, S2 …), "Profile changes", "Cost and model" and "Tailoring" are the UI labels. Code, services and earlier ADRs keep "claim" (ADR 0028).
8. **Version 1 scope.** It covers today's GUI features plus:
   - inline editing and free re-rendering of CV and letter text
   - regenerating an application
   - a cost estimate and cache check before a paid run
   - progress and cancel for generation
   - a profile editor

   Deferred to later versions: application tracking (status, dates, notes), creating an application from a posting URL, and per-profile job sources. The last of these waits for the ADR 0030 redesign; the UI reserves space for it.

## Consequences

- **New backend work that also benefits the CLI and Streamlit:**
  - move the answers-editor, layout-preview and word-diff logic out of `ui/*.py` into the services and bridge
  - turn the CLI `render` logic into a service
  - progress events and a cancel check in the generation pipeline
  - a cost estimate and a cache-hit check
  - validated, backed-up and atomic profile edits
- **Two UIs exist during the overlap.** Streamlit receives fixes only, no new features, from the moment the API skeleton lands.
- **The UI gains its own test layers:** API tests with FastAPI's `TestClient` against a synthetic store, component tests, and Playwright end-to-end tests. These include keyboard-only and screen-reader-semantics checks from [ACCEPTANCE.md](../design/redesign/ACCEPTANCE.md). CI runs them on Ubuntu first, then on macOS and Windows.
- **`master` is unaffected** until the owner approves a reviewed migration and rollback plan (AGENTS.md). Rollback before the switch means not opening `/app/`. After the switch it means `scripts/start.py --legacy-ui`.
- **If the first spike (suggestion review plus PDF preview) shows Svelte costs more than it gives,** the fallback is server-rendered HTML with htmx on the same `/api/v2` and the same tokens. That change would be recorded as an amendment to this ADR.
