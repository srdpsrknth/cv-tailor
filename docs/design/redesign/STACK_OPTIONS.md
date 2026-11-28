# 03 - UI stack options for the CV Tailor redesign

Branch `ui/redesign`. Researched 2026-11-28. Nothing in `.venv`, `requirements*.txt` or private data was touched. NiceGUI/Reflex were tested only with `pip install --dry-run` in a throwaway scratch venv.

## 1. Facts about the current code that drive the choice

- `ui/` is about 1,900 lines. `ui/services_bridge.py` (674 lines) is framework-free and a test asserts it imports no UI framework (ADR 0020). This is the asset to protect: every option below keeps it as the single logic layer.
- Generation runs in process. `run_generation(..., status=callable)` is a blocking call that reports progress through a callback. In Streamlit this feeds `st.status`. Any other stack must run it in a worker thread and push the callback messages to the browser (SSE or WebSocket).
- Three UI modules bypass the bridge and import services or models directly: `ui/answers.py` (`models.portal_answers`, `services.portal_answers`, 369 lines of editor state), `ui/layout_preview.py` (`services.application_layout_preview`, `renderers`), and `ui/review.py` computes a word diff with `difflib` and builds HTML (`<ins>/<del>`). That is presentation-adjacent logic that would be duplicated or lost in a JS UI. **Step 0 of any migration is moving these into the bridge/services** so they return JSON (diff segments, layout rows, answer-editor state).
- `backend/main.py` (191 lines, FastAPI 0.128) has only `/health`, `POST /api/tailor` and three download endpoints. It resolves `profile_id` itself (ADR 0003) and is started by `scripts/start.py` alongside Streamlit. Uvicorn is already a dependency and `start.py` already launches uvicorn.
- ADR 0022: GUI profile memory lives in `<store>/preferences/gui.json`, scoped to the store, not the browser. A new UI must call the same bridge functions (`initial_gui_profile`, `remember_gui_profile`), never use localStorage as the source of truth.
- Streamlit is pinned `1.53.1` in the lock file; latest on PyPI is **1.67.0**. `streamlit-pdf==2.1.0` provides PDF preview.
- Tests: 77 UI tests in `tests/test_ui_*.py` use `streamlit.testing.v1.AppTest` (headless, executes the script, no browser). ADR 0020: screenshots of Streamlit are unreliable (websocket-drawn page shows the skeleton loader).
- Setup is Python-only on both OSes (`scripts/setup.py` creates `.venv`, installs `requirements.lock.txt`). `grep -i node|npm docs/*.md README.md` finds **no Node assumption anywhere**; Windows docs (DEVELOPMENT.md, shortcuts via `windows_gui.ps1`) are PowerShell + Python only. CI runs Ubuntu/Windows/macOS Python-only. Node v26.13.1/npm 11.20.0 are on this Mac only, so the owner's Windows machine must not need Node to run the app.
- Current versions found (npm/pip, 2026-11-28): Vite 8.4.0, Svelte 5.59.2, React 19.3.1, Solid 2.0.4 (a fresh major), htmx 2.0.11, Alpine 3.17.5, NiceGUI 4.1.0, Reflex 0.11.0, Playwright (Python) 1.65.2.

## 2. Options

### A. Streamlit pushed to its limit

What 1.5x/1.6x allows (from the Streamlit docs and release notes; versions are those the docs state):
- Theme in `.streamlit/config.toml`: colours, `font`, `codeFont`, heading font, border radius, separate sidebar theme, custom web fonts via `[[theme.fontFaces]]`. The repo already uses a theme file plus `ui/theme.py` CSS (about 25 lines of CSS keyed on `data-testid` attributes).
- CSS injection and `st.html` (not iframed; sanitised with DOMPurify; JavaScript only when `unsafe_allow_javascript=True`). Streamlit's own docs say targeting internal class names is fragile and the HTML structure is not guaranteed between versions; a widget `key` gives a stable `st-key-<key>` class. The docs themselves recommend theming over CSS.
- Custom components v2 (`st.components.v2`, introduced 1.51, still being changed in 1.53 (style isolation moved to the component definition), 1.64 (type renames), 1.66 (AppTest registration), 1.67). It gives frameless components with bidirectional data and allows any JS, so a single hard widget (a diff-and-edit claim card) can be built in Svelte/React and embedded. The API is young and has churned every minor release.
- `st.fragment` (partial reruns), `st.dialog`, `st.status`, `st.write_stream`, `st.navigation`, `st.query_params`.

What it cannot do, structurally:
- Every interaction reruns the script top to bottom (fragments narrow this but state still lives in `st.session_state`; `ui/claims_panel.py` has 281 lines of session-state bookkeeping and `answers.py` another 369, evidence that this fights the model).
- Text inputs commit on blur/Ctrl+Enter, so there is no true per-keystroke behaviour; focus can be lost on rerun; no optimistic updates; no inline contenteditable-style editing; no global keyboard shortcuts or focus management without injected JS (and JS is opt-in and unsupported).
- Streaming progress works only inside the running script via `st.status` and blocks that session's script thread; there is no cancel.
- Layout is a column/container grid. Page structure, transitions and anything non-rectangular needs CSS hacks over internal DOM.
- Browser tests of the real UI are unreliable (ADR 0020); `AppTest` verifies logic, not appearance or interaction.
- Version bumps (1.53 to 1.67 is already 14 minors) can break the `data-testid` selectors in `ui/theme.py`.

### B. FastAPI JSON + SSE API and a Vite SPA, with prebuilt static assets served by FastAPI

- API: new `backend/api_v2` router (or `backend/ui_api.py`) wrapping `ui/services_bridge.py` 1:1. Long runs: `POST` starts a job in a thread, `GET .../events` streams SSE (EventSource is built in, no library). One active run at a time is enough for a single-user app.
- SPA: Vite 8 + TypeScript. Plain SPA, not a meta-framework (no SSR needed). `vite build` output (`web/dist`, roughly 100-300 KB gzipped) is served with `StaticFiles` by the same uvicorn process, so the end user needs no Node. TypeScript types can be generated from the FastAPI OpenAPI schema (`openapi-typescript`), which keeps API and UI in step and is a cheap guard that the UI contains no hidden rules.
- Shipping the build: either commit `web/dist` on the branch (simplest for `git pull` users, costs diff noise; mitigate with a CI check "dist is up to date with src") or build in a release workflow. Recommended: commit `dist`, enforce freshness in CI. Node is then a developer-only prerequisite on whichever machine edits the frontend (Mac now; Windows only if the owner edits the frontend there).
- Framework choice:
  - **Svelte 5** (runes): smallest runtime, least boilerplate, forms and `bind:value` are natural for editor-heavy screens, scoped CSS suits a bespoke look. Smaller ecosystem than React, but this app needs few third-party widgets. The PDF preview can be the browser's native viewer in an `<iframe>`/`<object>` (served with `Content-Disposition: inline`), so no PDF library is needed.
  - **React 19**: largest ecosystem and the most documentation/AI-assistant familiarity; more boilerplate, more dependency churn, hooks pitfalls on editors; runtime about 45 KB gzipped vs a few KB for Svelte (irrelevant on localhost, relevant for dependency surface).
  - **Solid 2.0**: fast and React-like in syntax, but 2.0 is brand new and its ecosystem is the thinnest; weakest long-term-maintenance bet for a solo owner.
- Streamlit keeps running unchanged on its own port during the transition.

### C. FastAPI + server-rendered Jinja HTML with htmx/Alpine (no Node build)

- Jinja2 is already a dependency. htmx (2.0.x) and Alpine are single vendored JS files committed under `backend/static/`. SSE via htmx's SSE extension for progress; partial swaps for the claim cards; Alpine for local state (editing, shortcuts).
- No build step at all on either OS: strongest on setup burden and "launchable simply".
- Limits: optimistic updates, keyboard-driven list navigation, drag/resize, undo, and rich inline editing are all possible but become hand-rolled JS inside templates, and editor state (the `answers.py` equivalent) gets awkward. No TypeScript, no component model, HTML fragments are an implicit contract between server routes and templates. Design freedom is full (it is plain CSS), UX ceiling is "good forms and lists", not "app-like workspace".
- Server-side rendering also means the bridge output is rendered by Jinja, so tests can assert on HTML with `TestClient` and an HTML parser, with no browser.

### D. NiceGUI / Reflex

- **NiceGUI 4.1.0**: the ADR 0020 install failure is **not reproducible now**. In a scratch venv (Python 3.14.6, macOS arm64), `pip install --dry-run nicegui` resolves in about 15 s and would install nicegui-4.1.0 with fastapi 0.165, starlette 1.10, uvicorn 0.54, aiohttp 3.14.5, python-socketio 5.18.1. Also `pip install --dry-run -r requirements.txt nicegui` and `-r requirements.lock.txt nicegui` both exit 0 (no conflict; the lock's fastapi 0.128 / starlette 0.50 are accepted). Not tested: Windows, an actual install, or running the app. It is Python-only (Vue/Quasar bundled), built on FastAPI/Starlette so it can mount next to the existing API, and has a headless `user` test fixture. Limits: Quasar/Material look unless heavily overridden (Tailwind and custom CSS work, but internal class names changed between 3.x and 4.0 per its release notes, so CSS has to be re-checked on majors), per-client server-side state, major version already moved 3 to 4, and the owner already abandoned it once. UX ceiling is above Streamlit (event-driven, no reruns, `ui.keyboard`, inline editing) but below a hand-built SPA.
- **Reflex 0.11.0**: resolves in pip, but it compiles Python to a React/Next app and needs Node/Bun on the machine **at runtime** (it downloads them). That breaks the "no Node for end users" constraint and the Windows docs. Rejected for this project.

## 3. Scored comparison

Scale 1 (poor) to 5 (excellent). For "Dev effort", 5 means least effort; for "Cross-OS setup burden", 5 means least burden. Scores are my judgement from the evidence above, not measurements.

| Criterion | A Streamlit+ | B Svelte 5 SPA | B React SPA | B Solid 2 SPA | C htmx/Alpine | D NiceGUI | D Reflex |
|---|---|---|---|---|---|---|---|
| Design freedom | 2 | 5 | 5 | 5 | 4 | 3 | 3 |
| UX ceiling (inline edit, keyboard, optimistic, streaming, PDF) | 2 | 5 | 5 | 5 | 3 | 3 | 3 |
| Dev effort given services_bridge (5 = least) | 5 | 2 | 2 | 2 | 3 | 4 | 3 |
| Testability (pytest + Playwright, headless) | 3 | 5 | 5 | 4 | 4 | 4 | 3 |
| Cross-OS setup burden (5 = least; end user) | 5 | 4 | 4 | 4 | 5 | 5 | 1 |
| Migration alongside Streamlit | 5 | 5 | 5 | 5 | 5 | 3 | 3 |
| Long-term maintenance | 3 | 4 | 3 | 2 | 4 | 3 | 2 |
| **Total (of 35)** | **25** | **30** | **29** | **27** | **28** | **25** | **18** |

Notes on the less obvious scores:
- Testability B: three layers, all headless. (1) API: pytest + FastAPI `TestClient` (httpx is already installed) over the same bridge, no browser. (2) Components: Vitest + Testing Library (dev-only, needs Node). (3) End-to-end: Playwright for Python against a uvicorn server on a temp store (`CVTAILOR_STORE` env, same isolation mechanism as the current tests; needs `playwright install chromium`, roughly 150 MB, dev/CI only). Unlike Streamlit, screenshots and DOM assertions are reliable because the page is ordinary DOM. Solid scores 4 only for thinner testing-library support.
- Testability C: `TestClient` plus an HTML parser covers most behaviour with zero browser; Playwright only for Alpine interactions.
- Testability A: `AppTest` is fast and already in place, but cannot see layout, focus or CSS.
- Migration for D: possible via `ui.run_with(app)` mounting, but it is a second Python UI framework with a different state model, so there is no code reuse between it and Streamlit and a larger throwaway risk.
- Dev effort for B is highest: about 1,900 lines of Python UI become a new TS frontend, plus the API layer (below). Estimate: API about 400-600 lines Python plus tests; frontend about 3,000-5,000 lines TS/Svelte plus CSS. Treat as rough; the claim-review and answers editor screens dominate.

## 4. Recommendation

**Option B with Svelte 5 + Vite + TypeScript (plain SPA), prebuilt `dist` committed and served by the existing FastAPI app; Streamlit stays untouched until parity (strangler).** Fallback if the owner decides the Node dev dependency or frontend effort is too heavy: **Option C**.

Reasoning:
1. The brief asks for a non-generic look and a high UX ceiling (inline editing of claims, keyboard flow, live progress, PDF preview). Streamlit's rerun model and DOM-coupled CSS cap this regardless of effort (evidence in the repo: 650 lines of session-state bookkeeping in `claims_panel.py` and `answers.py`). NiceGUI improves the model but keeps a Quasar-shaped look and re-adds a framework dependency the owner already got burned by.
2. The architecture already points here: the bridge is framework-free, FastAPI/uvicorn are installed and launched by `start.py`, and ADR 0009 calls both UIs "thin adapters over the service layer". A JSON API is just a second adapter; business rules stay in `services/` and the bridge.
3. End users still need no Node: they run `scripts/start.py`, uvicorn serves `/` from `web/dist`. Node is needed only by whoever edits the frontend (this Mac). No change to `setup.py`, MAC_SETUP.md or the Windows shortcuts beyond a new route.
4. Svelte over React: this is a small, form/editor-centric, single-developer app with few third-party widgets; Svelte's smaller dependency surface and scoped CSS suit a bespoke visual identity and low churn. React's ecosystem advantage matters little here (PDF viewing via native `<iframe>`, no table/chart library needed). Solid 2.0 is too new. If AI-assisted maintenance familiarity is the owner's top priority, React is an acceptable swap with the same API and architecture; the choice is the cheapest to reverse before screen work starts.
5. Testability is the best of the options: real-DOM Playwright tests become possible, which ADR 0020 says was not possible for Streamlit.

Why not C as the primary: it has the best setup story and is credible, scoring only 2 points lower, but the claim-review and answer-editor screens are exactly where hand-rolled Alpine state becomes the `session_state` problem again. If after a one-screen spike (below) Svelte feels like too much, drop to C and keep the same API.

## 5. API endpoints needed (derived from `ui/services_bridge.py`)

All under `/api/v2`, `profile_id` always an explicit path segment (ADR 0003: fail closed; errors map `ProfileStoreError`/`ValueError` to 4xx with a user-safe message, never a traceback). The router calls `config = get_config()` once and delegates to the bridge. Existing `/api/tailor` and `/api/download/*` stay as is.

| Method and path | Bridge function | Notes |
|---|---|---|
| `GET /health/setup` | `setup_checks`, `preflight`, `describe_configuration` | Setup screen and banner; never returns keys. |
| `GET /profiles` | `list_profiles` -> `ProfileOption` (label, usable flag) | |
| `GET /profiles/{pid}` | `load_profile` | Header (name + id, ADR 0022). Consider a summary shape rather than the full profile. |
| `GET /preferences/gui-profile` | `initial_gui_profile(config, available_ids)` | Server computes the start selection (ADR 0022). |
| `PUT /preferences/gui-profile` | `remember_gui_profile` | Returns a warning field on write failure. |
| `GET /models` | `model_options`, `generation_config` | Selection becomes a request field, not server state. |
| `POST /profiles/{pid}/generations` | `run_generation` | Body: job_description, company, role, work_country, use_cache, balance_cv_pages, model. Starts a worker thread, returns `run_id`. 409 if a run is active. |
| `GET /runs/{run_id}/events` (SSE) | `status` callback, then `GenerationOutcome` | Events: `status`, `done` (ok, job_id, summary lines from `format_cost_breakdown`), `failed` (error, drafts_saved). Dead-client safe. |
| `GET /job-sources` | `source_coverage` | |
| `POST /profiles/{pid}/job-search` | `search_from_fields` / `run_job_search` | Free, no LLM. Body: keywords, country, city, remote, limit. |
| `GET /profiles/{pid}/applications` | `list_applications`, `application_library` | Query `limit`. |
| `GET /profiles/{pid}/applications/{job_id}` | `load_application(include_quality=...)`, `list_artifacts`, `posting_handoff` | Artifact list carries `document_label`. |
| `GET /profiles/{pid}/applications/{job_id}/layout-check` | `check_word_layout` | |
| `GET /profiles/{pid}/applications/{job_id}/artifacts/{name}` | `read_artifact` | Whitelisted names only; `?inline=1` for PDF preview, otherwise attachment. Must reject path traversal. |
| `POST /profiles/{pid}/applications/{job_id}/upload-cv` | `export_upload_cv` | |
| `GET`/`PUT /profiles/{pid}/applications/{job_id}/posting` | `saved_posting`, `save_posting_provenance` | |
| `GET /profiles/{pid}/applications/{job_id}/claims` | `claims_for` | |
| `POST .../claims/plan` | `plan_claims` | Body: numbers, edits. Free preview of the effect. |
| `POST .../claims/accept` | `accept_claims` | Writes a saved CV revision. |
| `POST .../claims/reject` | `reject_claims` | |
| `POST .../claims/{n}/draft` | `draft_claim` | **Paid** model call; require an explicit `confirm_paid: true` field to match the project's "ask before paid generation" rule. |

Needed but not yet in the bridge (Step 0 of the migration):
- Word-diff segments for before/after text (today `ui/review.py` uses `difflib` in the UI).
- Layout-preview data: `services.application_layout_preview` is called straight from `ui/layout_preview.py`.
- Portal answers editor: list/add/remove questions, public sources, draft answers, and the "use current profile snapshot" decision (`ui/answers.py` calls `services.portal_answers` and `models.portal_answers` directly, with 369 lines of editor state). Roughly 6-8 further endpoints under `.../answers`.

## 6. Risks

- **Parity effort**: claims review and answers editor are the bulk. Mitigation: migrate screen by screen, behind the strangler split below.
- **Rules leaking into TS**: a rich client makes it easy to re-implement counts/limits/work-authorization wording in the browser. Mitigation: API returns display-ready fields and validation results; generate TS types from OpenAPI; add a source-scan test like ADR 0020's "no second pricing table" for `web/src` (no literals like page limits or word budgets).
- **Committed `dist`**: noise and staleness. Mitigation: CI check that rebuilding yields no diff; `dist` directory excluded from review diffs.
- **Node on two OSes for frontend work**: only if the owner edits the frontend on Windows. Mitigation: document `npm ci && npm run build` in DEVELOPMENT.md as developer-only; pin Node via `.nvmrc`/`engines`.
- **Local API security**: the SPA's API can read and write the private store. Bind to 127.0.0.1 only (already the case in `start.py`), same-origin only (no permissive CORS), a per-launch random token or Host-header check against DNS rebinding, strict artifact-name whitelist, no real-data fixtures in tests (synthetic profiles only, per AGENTS.md).
- **Long-run semantics**: generation is blocking and unkillable; page reload during a run must reattach to the run via `run_id` (SSE replay of buffered events) and the UI must survive a failed run with `drafts_saved`.
- **Windows**: SSE and threads under uvicorn on Windows are fine, but `playwright install` and Vitest need verification on Windows if tests are to run there; CI (windows-latest) will tell.
- **Dependency drift**: `requirements.lock.txt` pins fastapi 0.128 / starlette 0.50; the new router should not require newer features. Streamlit stays at 1.53.1 until retired; do not bump it for this work.
- **Maintenance of two UIs** during the overlap. Mitigation: freeze Streamlit feature work once the API exists.
- **NiceGUI evidence is dry-run only**: not installed or run, and not tested on Windows.

## 7. Migration sketch (strangler)

0. **Prepare (Python only, benefits Streamlit too)**: move diff computation, layout preview and the answers editor logic into the bridge/services; each returns plain data; add bridge-level tests; extend the "no framework import" test to cover the new bridge modules. Streamlit consumes the moved code, so nothing regresses.
1. **API skeleton**: `backend/api_v2` router with `/health/setup`, `/profiles`, preferences, `/applications` (read-only), artifact download. Tests with `TestClient` against a synthetic temp store (`CVTAILOR_STORE`). Streamlit unaffected.
2. **Frontend skeleton**: `web/` (Vite + Svelte + TS), design tokens, app shell with the active-profile header (ADR 0022), served at `/app/` by FastAPI; `scripts/start.py` prints the new URL beside Streamlit's. Streamlit remains the default at its own port; docs unchanged for end users.
3. **Spike on the hardest screen first**: the claims review (plan, edit, accept/reject, revision) plus PDF preview. If it feels right, continue; if it is painful, fall back to C using the same API.
4. **Generation + SSE** (new generation form, progress, cost summary), then job search, then application library/detail, then the answers editor.
5. **Playwright e2e** in CI against a synthetic store (Ubuntu first, then macOS/Windows), including a keyboard-only claims pass.
6. **Parity checklist** against the 77 `test_ui_*` cases: each behaviour covered by an API test, component test, or e2e test, before retiring its Streamlit counterpart.
7. **Switch the default**: `start.py` and the Windows/Mac shortcuts open the new UI; Streamlit moves to `--legacy-ui` for one release; then remove `ui/*.py` except the bridge (rename to `services/ui_facade.py` or keep), `streamlit` and `streamlit-pdf` from requirements, and add a new ADR superseding the "Streamlit" half of ADR 0009/0020. `master` is only touched via the owner-approved reviewed migration/rollback plan required in AGENTS.md; until then the work stays on `ui/redesign`.

Rollback at any step before 7 is "do not open the new URL"; after 7 it is `start.py --legacy-ui`.

## 8. Sources

- Streamlit release notes and docs: https://docs.streamlit.io/develop/quick-reference/release-notes/2026 , https://docs.streamlit.io/develop/api-reference/text/st.html , https://docs.streamlit.io/develop/concepts/design/best-practices
- NiceGUI 4.0.0 release: https://github.com/zauberzeug/nicegui/releases/tag/v4.0.0
- Framework comparison (blog-grade, rough): https://www.pkgpulse.com/guides/solidjs-vs-svelte-5-vs-react-reactivity-2026
- Versions: `npm view` and `pip index versions` run locally, 2026-11-28.
- Limitation claims for Streamlit reruns, focus and keyboard behaviour come from the repo's own code and my knowledge of the framework; the web search returned nothing specific on them, so verify before quoting them externally.
