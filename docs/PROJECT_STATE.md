# Project state

**Last updated:** 2026-10-23
**Branch:** `refactor/architecture-v2`
**Worktree:** `D:\coding\cv-tailor-next`
**Latest commit:** `c3839da` — *docs: record approved architecture decisions and agent continuity workflow*
**Stable branch:** `master` (`D:\coding\cv-tailor`) at `1416177` — **usable for real applications**

---

## Active task

**Phase 0 — architecture assessment. COMPLETE. Decisions APPROVED 2026-10-23.**

The full assessment is in [`ASSESSMENT.md`](ASSESSMENT.md); the nine approved decisions are in
[`DECISIONS/`](DECISIONS/README.md). The assessment was a read-only audit: no production code
was changed, no data was migrated, no paid API calls were made, and `master` was not touched.

**Next action: implement Milestone 1.1 — test baseline and golden fixtures**
(see `ASSESSMENT.md` §12). It changes **no production behaviour**: it adds synthetic
fixtures, characterization tests and `docs/TESTING.md` coverage, so later refactoring can be
proven safe.

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
| Dev branch | 2 commits ahead of `master` — documentation only, no code changes |
| Dev worktree runnable? | **Yes** — `.venv` with all 91 locked deps, `.env` (ports 8001/8502) |
| Test baseline | **12 passed** in the new dev venv |
| Assessment | Complete and committed — `docs/ASSESSMENT.md` |
| Decisions | 9 approved and committed — `docs/DECISIONS/` |
| Roadmap | Approved — `docs/ROADMAP.md` |

### Verified baseline facts

- `.venv\Scripts\python.exe -m pytest -q` → **12 passed, 1 warning** (2.45 s), offline.
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
3. **Sandbox caveat:** 8 of 12 tests error under the DSH `workspace-write` sandbox because
   pytest cannot set ACLs on its temp trees. Environment artifact, not a code fault. Also:
   `git commit` in this worktree needs unconfined access, because its git metadata lives in
   `D:\coding\cv-tailor\.git`, outside the sandbox. Recorded in `TESTING.md` and `DEVELOPMENT.md`.
4. **Renderers are mocked** in the only integration test, so real LaTeX/DOCX output is not
   regression-protected. This is exactly what Milestone 1.1 addresses.
5. **`docx_renderer.py:304-307` mutates the caller's model** — verified real bug, unfixed.

---

## Known-important findings (do not lose)

- `.github/copilot-instructions.md` describes a **different system** (Tectonic, `gemini-1.5-flash`,
  a non-existent `/api/preview` endpoint). It is the most misleading document in the repo.
- Candidate-specific rules are **hardcoded** in `tailor_service.py:73-92,154-167` — the main
  structural blocker to multi-profile.
- `response_schema` / JSON-mode support in `gemini_service.py` is **dead code**; no caller passes it.
- Generated PDFs/DOCX are **tracked** in `outputs/` despite `.gitignore`.
- `initial_generation_result.json:4-6` leaks absolute local paths incl. a third-party name.

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
