# Project state

**Last updated:** 2026-10-23
**Branch:** `refactor/architecture-v2`
**Worktree:** `D:\coding\cv-tailor-next`
**Latest commit:** `1416177` — *Improve application tailoring and add portable Mac setup workflow*
**Stable branch:** `master` (`D:\coding\cv-tailor`), same commit — **usable for real applications**

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
| Stable app on `master` | Working, untouched, has its own `.venv` and `.env` |
| Dev branch | Created from `master`; **no commits yet** — identical to `master` |
| Dev worktree runnable? | **No** — missing `.venv` and `.env` (see Blockers) |
| Test baseline | **12 passed** (unconfined); see `TESTING.md` for the sandbox caveat |
| Assessment | Complete — `docs/ASSESSMENT.md` |
| Roadmap | Proposed — `docs/ROADMAP.md` |

### Verified baseline facts

- `python -m pytest -q` → **12 passed, 1 warning** (2.45 s), offline, no API calls.
- Backend `import main` ≈ **1.9 s**; `load_profile()` ≈ **169 ms**.
- LLM calls per application: **3 min / 4 typical / 6 max-successful / 18 worst**.
- Estimated cost per application (`gemini-3.8-flash`): **$0.027 / $0.049 / $0.092**.
- pdflatex present; ≈ **2.9 s** per run, run twice per compile.

---

## Blockers and unresolved issues

1. **Dev worktree cannot run.** `cv-tailor-next` has no `.venv` and no `.env`. Required
   before any milestone. Fix documented in [`DEVELOPMENT.md`](DEVELOPMENT.md).
2. **Privacy model undecided** (assessment §11-1). Real personal data — including
   immigration status — is committed to a **public** repo, alongside 64 application files.
   Adding a second real candidate before resolving this is not acceptable.
3. **Sandbox caveat:** 8 of 12 tests error under the DSH `workspace-write` sandbox because
   pytest cannot set ACLs on its temp trees. Environment artifact, not a code fault. Run the
   suite unconfined; recorded in `TESTING.md`.
4. **Renderers are mocked** in the only integration test, so real LaTeX/DOCX output is not
   regression-protected. This is why Milestone 1.1 comes first.
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
