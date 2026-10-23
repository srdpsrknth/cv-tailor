# Project state

**Last updated:** 2026-10-23
**Branch:** `refactor/architecture-v2`
**Worktree:** `D:\coding\cv-tailor-next`
**Latest commit:** *(this change)* — *test: establish regression baseline and golden fixtures*
**Stable branch:** `master` (`D:\coding\cv-tailor`) at `1416177` — **usable for real applications**

---

## Active task

**Milestone 1.1 — test baseline and golden fixtures. COMPLETE.**

Synthetic fixtures and a characterization suite now cover every workflow in
[`ASSESSMENT.md`](ASSESSMENT.md) §1. Both renderers are exercised for real instead of being
mocked, and `scripts/render_application.py` has an end-to-end determinism test. **No
production behaviour changed** — `backend/`, `ui/` and `scripts/` are untouched.

**Next action: implement Phase 1 — core refactoring and CLI foundations**
(see [`ROADMAP.md`](ROADMAP.md) §Phase 1). The regression baseline is now in place, which was
the stated prerequisite for all later refactoring.

Start Phase 1 with the safest, highest-value step: **remove verified dead code**
(`response_schema`/JSON-mode branches D-1, `validate_api_key` D-2, unused models D-7, stale
pricing D-5), because the new suite proves those removals change nothing observable.

### Approved decisions (summary)

1. **Privacy** — real profiles/applications/outputs move to a **private store**; commit only
   synthetic examples. Reachability from any machine is handled later by a remote store
   ([0006](DECISIONS/0006-remote-profile-access.md)).
2. **Architecture** — Option B, modular redesign, incrementally.
3. **Storage** — files keyed by `profile_id`, **local first**, no database server.
4. **CLI** — `argparse` plus a friendliness layer (guided default, prompts, `doctor`, `--json`).
5. **FastAPI + Streamlit** — keep both as thin adapters; reassess at Phase 6.
6. **LLM** — provider interface; benchmark cost/performance/quality before switching; keep
   Gemini's latest Flash as default.
7. **Job sources** — ToS-compliant APIs first; scraping only if permitted and necessary.
8. **`applications/`** — read-only reference until Phase 2, then migrate.

Re-confirm each decision when its phase begins.

---

## Current status

| Area | State |
|---|---|
| Stable app on `master` | Working, untouched, own `.venv` and `.env` (ports 8000/8501) |
| Dev branch | 4 commits ahead of `master` — docs + tests only, **no production code changes** |
| Dev worktree runnable? | **Yes** — `.venv` with all 91 locked deps, `.env` (ports 8001/8502) |
| Test baseline | **141 passed** (~100 s); fast lane `-m "not requires_latex"` → 113 passed (~6 s) |
| Fixtures | Synthetic only — `tests/fixtures/`, verified free of real personal data |
| Assessment | Complete and committed — `docs/ASSESSMENT.md` |
| Decisions | 9 approved and committed — `docs/DECISIONS/` |
| Roadmap | Approved — `docs/ROADMAP.md` |

### Verified baseline facts

- `.venv\Scripts\python.exe -m pytest -q` → **141 passed, 1 warning** (~102 s), offline.
- Fully offline: verified with `GEMINI_API_KEY` unset; no paid API calls in the suite.
- The original 12 tests still pass unchanged.
- `tests/test_renderers_documents.py` renders **real** LaTeX and DOCX (~20 s).
- `tests/test_render_application_determinism.py` runs the real script as a subprocess (~73 s).
- `scripts/check_setup.py` → profile, timezone, LaTeX compiler and templates all OK.
- Backend `import main` ≈ **1.9 s**; `load_profile()` ≈ **169 ms**.
- LLM calls per application: **3 min / 4 typical / 6 max-successful / 18 worst**.
- Estimated cost per application (`gemini-3.8-flash`): **$0.027 / $0.049 / $0.092**.
- pdflatex present; ≈ **2.9 s** per run, run twice per compile.

---

## Blockers and unresolved issues

1. **`GEMINI_API_KEY` is not set in this worktree's `.env`.** `scripts/check_setup.py` stops
   there. The owner must enter it directly — never paste it into a chat. Live generation in
   this worktree is blocked until then; rendering and tests are not.
2. **Privacy model not yet implemented** ([ADR 0002](DECISIONS/0002-privacy-model.md)). Real
   personal data — including immigration status — is still committed to a **public** repo,
   alongside 64 application files. This must be implemented before a second real candidate is
   added. Do not rewrite history without approval.
3. **Sandbox caveat:** tests using pytest's `tmp_path` error under the DSH `workspace-write`
   sandbox because pytest cannot set ACLs on its temp trees. Environment artifact, not a code
   fault. In Milestone 1.1 the sandbox additionally denied the project venv write access to
   anything under `tests/`, so fixture JSON was staged in a writable directory and copied in
   with PowerShell. Also: `git commit` in this worktree needs unconfined access, because its
   git metadata lives in `D:\coding\cv-tailor\.git`, outside the sandbox. Recorded in
   `TESTING.md` and `DEVELOPMENT.md`.
4. **`docx_renderer.py:304-307` mutates the caller's model** — verified real bug, still
   unfixed and **still untested** (deliberately: pinning it would bless it). Its practical
   impact is bounded by the new `test_docx_contains_every_body_paragraph` test, which proves
   all four paragraphs survive rendering.
5. **`backend/main.py` has no tests.** The endpoints and the `job_id` containment question
   (§6) remain uncovered; this is now the largest untested surface. Milestone 1.1 did not
   cover it — it is API-layer work, better suited to Phase 1 when the service layer exists.

### Resolved in Milestone 1.1

- ~~Renderers are mocked in the only integration test~~ — real LaTeX and DOCX output is now
  regression-protected (`tests/test_renderers_documents.py`).
- ~~`render_application.py` untested~~ — 11 end-to-end determinism tests.
- ~~No second profile for contamination tests~~ — two synthetic profiles, with an isolation
  test asserting profile A cannot leak into profile B's prompts.
- ~~Page-count gate tested only against blank PDFs~~ — now asserted on real rendered documents.

---

## Known-important findings (do not lose)

- `.github/copilot-instructions.md` describes a **different system** (Tectonic, `gemini-1.5-flash`,
  a non-existent `/api/preview` endpoint). It is the most misleading document in the repo.
- Candidate-specific rules are **hardcoded** in `tailor_service.py:73-92,154-167` — the main
  structural blocker to multi-profile.
- `response_schema` / JSON-mode support in `gemini_service.py` is **dead code**; no caller passes it.
- Generated PDFs/DOCX are **tracked** in `outputs/` despite `.gitignore`.
- `initial_generation_result.json:4-6` leaks absolute local paths incl. a third-party name.
- **New (Milestone 1.1):** `tailor_service.py:195` reads `data.get("tailoring_explanation")`
  from the **top level** of the parsed response, not from inside `cv`. A model that nests it
  under `cv` — the more natural shape, and what `TailoredOutput` models — yields `None`
  silently, so the UI shows no explanation with no error. Worth fixing in Phase 1. The
  fixtures record it at the top level so the existing path stays covered.

---

## Session-start checklist

1. `git rev-parse --abbrev-ref HEAD` → confirm `refactor/architecture-v2`.
2. `git status` → confirm clean; never discard uncommitted work.
3. Read `AGENTS.md`, then this file.
4. Read the relevant section of [`ASSESSMENT.md`](ASSESSMENT.md) and [`ROADMAP.md`](ROADMAP.md).
5. Read `docs/DECISIONS/` for settled choices.
6. `python -m pytest -q` (unconfined) to confirm the baseline still holds.
7. Confirm acceptance criteria for the assigned task; continue from here.

Do **not** re-run the whole assessment unless the architecture materially changed.
