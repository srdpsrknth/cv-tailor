# UI redesign build plan

**Status:** Approved by the owner, 2026-11-28. Progress is tracked in [PROJECT_STATE](PROJECT_STATE.md) and the [handoff](HANDOFF-UI-REDESIGN.md).

This plan implements [ADR 0031](DECISIONS/0031-web-ui.md) on the integration branch `ui/redesign`, which was cut from `refactor/architecture-v2`. Design: [design system](design/DESIGN_SYSTEM.md), [tokens](design/tokens.css), [mock-up](design/redesign/bench-mockup.html). Requirements: [capability inventory](design/redesign/CAPABILITIES.md) (section 4 for the API surface, section 5 for the invariants) and [acceptance criteria](design/redesign/ACCEPTANCE.md).

## Ground rules

- Streamlit keeps working at every step. Nothing here touches `master` until the owner approves a reviewed migration and rollback plan.
- Each work package (WP) has its own worktree and branch, cut from `ui/redesign`. It merges back into `ui/redesign` only with the owner's approval. Commits, pushes and merges each need explicit authorization (AGENTS.md).
- Tests use synthetic profiles and a temporary store (`CVTAILOR_STORE`), never real candidate data. No test makes a paid call.
- Each WP ends with its own tests passing, the full deterministic suite passing (`python -m pytest -q`), and a short note added to [PROJECT_STATE](PROJECT_STATE.md).
- A WP that changes commands, configuration or output also updates the user guide and setup docs it affects.

## Work packages

Model guide:
- **Opus** where judgement or risk is high: the paid path, security, the hardest screen, reviews.
- **Sonnet** for building from a clear spec.
- **Haiku** for read-only checks.

| WP | What | Depends on | Model | Done when |
|---|---|---|---|---|
| **0** | **Bridge consolidation.** Move the answers-editor, layout-preview and word-diff logic from `ui/*.py` into services and the bridge, as plain data. Extract CLI `render` into a service: edit `content.json`, run the existing validators, re-render with a preset, save as a new revision, never overwrite. Streamlit uses the moved code. | — | Sonnet | Streamlit behaviour unchanged; `test_ui_*` pass; new service tests; the "no UI framework import" test covers the new modules |
| **1** | **Generation progress, cancel and estimate.** Structured progress events from the pipeline: stage, layout attempt, spend so far, cache reuse. A cancel flag checked between provider calls. `estimate_generation()` (range, cap, price freshness) and `would_hit_cache()`. | — | **Opus** | Events and cancel covered by offline tests with stub providers; cache keys unchanged (ADR 0015/0029); CLI output unchanged |
| **2** | **Profile edits.** Validated, backed-up, atomic edits to profile sections, section order, rules and country overrides, following the claim-acceptance write path. Read-only status for writing voice and guidance. | — | Sonnet | Round-trip and rollback tests; manual YAML edits preserved; no fabricated fields |
| **3** | **API v2.** `/api/v2` router over the bridge, as in [inventory §4](design/redesign/CAPABILITIES.md#4-api-surface-a-new-frontend-needs): `profile_id` in the path, `confirm_paid`, typed errors mapped to status codes, SSE runs that reattach and cancel, artifact whitelist, a localhost token or Host check, no CORS. OpenAPI schema used to generate TypeScript types. | 0, 1, 2 | **Opus** | `TestClient` tests for every route, including fail-closed profile ids, a paid call refused without confirmation, path traversal refused, and an SSE run with reattach |
| **4** | **Frontend shell.** `web/` (Vite, Svelte 5, TS): tokens, self-hosted fonts, routing, the header with measured stacking, the candidate switcher (ADR 0022 rules), status line, command palette, shortcut sheet, theme. Built `web/dist` committed and served at `/app/`. CI check that the build is current. `start.py` prints the new URL. | — (uses a mock API until 3 lands) | Sonnet, with Opus review | Shell matches the mock-up from 360px to 5120px; header acceptance items pass; the dist check works on CI |
| **5** | **Spike: workspace review.** Suggestion review (plan, edit, add to profile, dismiss/restore, approve CV revision), the sheet with page-fit ruler, leader lines, PDF/Word preview, and layout zones including Inspector and spreads. | 3, 4 | **Opus** | Keyboard-only pass; the two approvals stay separate; "lines spare" is equal at every width. **Gate:** owner go/no-go on Svelte, with the htmx fallback otherwise |
| **6** | **New application.** Paste, parsed fields, work-authorization rule shown from the profile (not hard-coded), estimate and cache line, paid confirm, SSE progress, cancel, reattach after reload. | 3, 4, 5 | Sonnet | Paid confirm focus rules; run failed / cap reached / cancelled states designed and tested |
| **7** | **Edit and re-render.** Inline CV and letter editing with limits, free re-render, revision history, density preset, and regenerate as a confirmed paid action. | 0, 3, 5 | Sonnet | Validators run on edits; originals never overwritten; revisions listed |
| **8** | **Library and Desk.** Sortable table, filter, link cells, preview pane at ≥ 1600px, health from `applications check`, and the Desk "needs you" list. | 3, 4 | Sonnet | Table acceptance items; empty and filtered-zero states |
| **9** | **Portal answers.** Question list, editor with counters, evidence, paid drafting with confirm, save with conflict states (ADR 0021/answer store rules). | 0, 3, 5 | Sonnet | Conflict states block save; counters accessible; nothing lost on reload |
| **10** | **Profile and Settings.** Profile editor on top of WP2; Settings with provider and model, key verification (free), cost cap, setup checks including fonts, LaTeX and LibreOffice. | 2, 3, 4 | Sonnet | Edits back up and validate; key status never prints the key |
| **11** | **Jobs.** Today's search over the API, with sample sources labelled honestly, and space reserved for per-profile sources (ADR 0030). | 3, 4 | Sonnet | Results show eligibility evidence; sample boards never look like real results |
| **12** | **Hardening.** Playwright e2e on a synthetic store (Ubuntu, then macOS and Windows); remaining ACCEPTANCE items; a parity checklist against each `test_ui_*` behaviour; the source-scan test that no limits or pricing live in `web/src`. | 5–11 | Sonnet, final review by Opus with `/code-review` | Parity checklist complete; CI green on three OSes |
| **13** | **Switch the default.** `start.py` and the launchers open the new UI; `--legacy-ui` keeps Streamlit for one release; update the docs (HOW_TO_GENERATE, DEVELOPMENT, TESTING, MAC_SETUP, setup and application skills). | 12, plus owner approval | Sonnet | Owner verifies a real application end to end on macOS and Windows |

## Waves and parallel sessions

Packages in one wave touch different files, so they can run as separate sessions in separate worktrees at the same time. Shared files, such as the route registry in `web/src` and `backend/main.py`, are changed only by the integration session (this one), which merges each finished WP into `ui/redesign` after the owner approves it.

| Wave | Run in parallel | Notes |
|---|---|---|
| 1 | WP0, WP1, WP2, WP4 | Three backend packages in separate service modules, and the frontend shell against a mock API |
| 2 | WP3, then WP5 | The API needs wave 1 merged. The spike is the go/no-go gate |
| 3 | WP6, WP7, WP8, WP9, WP10, WP11 | Each owns its own screen folder and API tests |
| 4 | WP12, then WP13 | WP13 needs owner approval and a real end-to-end check |

Each session starts with a short brief naming its WP row in this table, the files it owns, the "done when" column, and the ground rules above.

## Verification at every merge

1. The WP's own tests, then `python -m pytest -q` (and `-m "not requires_latex"` where LaTeX is missing).
2. For frontend packages: `npm run check`, `npm run test`, the Playwright tests for the screen, the dist-current check, and a screenshot sweep at 360, 900, 1440, 2560 and 3440 in both themes.
3. A design review against the anti-generic checklist in DESIGN_SYSTEM.md, and an accessibility pass with the review skills.
4. A report of what passed, what failed and what was not run, in PROJECT_STATE.

## Rollback

- **Before WP13:** don't open `/app/`; Streamlit is unchanged.
- **After WP13:** `scripts/start.py --legacy-ui`.
- **At any point:** the `ui/redesign` branch can be abandoned without affecting `refactor/architecture-v2` or `master`.
