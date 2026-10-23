# Project state

**Last updated:** 2026-10-23
**Branch:** `refactor/architecture-v2`
**Worktree:** `D:\coding\cv-tailor-next`
**Latest commit:** `179bd83` — *feat: add the cvtailor CLI*
**Stable branch:** `master` (`D:\coding\cv-tailor`) at `1416177` — **usable for real applications**

---

## Active task

**Phase 1 — core refactoring and CLI foundations. COMPLETE (code + tests + docs).**

All six increments are implemented, tested and committed as six focused commits on
`refactor/architecture-v2` (`edb6efc`..`179bd83`). `master` is untouched.

**Next action: begin Phase 2 — multi-profile architecture**
(see [`ROADMAP.md`](ROADMAP.md) §Phase 2). Phase 1 removed the blocker: candidate-specific
validation rules are now profile-scoped data (A-1), so a second profile can be added without
inheriting the first candidate's rules.

Start Phase 2 by re-confirming the decisions listed under "Re-confirm each decision when its
phase begins", then introduce `ProfileStore` keyed by `profile_id`.

### What Phase 1 delivered

| Increment | Commit | Outcome |
|---|---|---|
| Bug fix | `edb6efc` | `tailoring_explanation` is read from a nested `cv` as well as the top level |
| Dead code | `b568990` | D-1, D-2, D-5, D-6, D-7, D-12 removed; a latent `KeyError` in pricing fixed |
| Config | `ef500b6` | **No import-time env reads**; one `Config` object resolved at call time (A-5) |
| Service layer | `dfe03ec` | `tailor_documents` split into `generation` + `application_store` (A-3) |
| Profile rules | `e05562e` | Candidate rules are profile-scoped data, not hardcoded (A-1) |
| CLI | `179bd83` | `cvtailor` with `doctor`, `profile show`, `generate`, `render` (ADR 0007) |

### Acceptance criteria — verified

| Criterion | Result |
|---|---|
| All 141 baseline tests pass **unchanged** | **Yes** — no existing test was modified at any point |
| CLI reproduces a `content.json` render, same page count | **Yes** — asserted against `scripts/render_application.py`, byte-identical extracted text |
| No import-time environment reads | **Yes** — guarded by a test that fails if one is reintroduced |
| Behaviour preserved: same documents, page counts, costs | **Yes** — full suite green including real LaTeX/DOCX output |
| `pytest -q` green and fully offline | **190 passed** in ~110 s, no paid API calls |

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
| Dev branch | 10 commits ahead of `master` — Phase 1 complete |
| Dev worktree runnable? | **Yes** — `.venv`, `.env` (ports 8001/8502) |
| Test baseline | **190 passed** (~110 s); fast lane `-m "not requires_latex"` → 160 passed (~5 s) |
| CLI | **Working** — `python cvtailor.py <command>` (or `backend/cli/__main__.py`) |
| Fixtures | Synthetic only — `tests/fixtures/`, verified free of real personal data |
| Assessment | Complete and committed — [`ASSESSMENT.md`](ASSESSMENT.md) |
| Decisions | 9 approved; **ADR 0010** added for the config object |
| Roadmap | Phase 0, 1.1 and **1 complete**; Phase 2 next |

### Verified baseline facts

- `.venv\Scripts\python.exe -m pytest -q` → **190 passed**, 1 warning (~110 s), offline.
- Fully offline: verified with `GEMINI_API_KEY` unset; no paid API calls in the suite.
- **No existing test has been modified since `325c4d1`.** The suite grew 141 → 190.
- `tests/test_renderers_documents.py` renders **real** LaTeX and DOCX.
- `tests/test_cli.py` asserts the CLI's page count equals `render_application.py`'s.
- `cvtailor render` needs no API key; `cvtailor doctor` checks the key for *presence* only
  unless `--verify-key` is passed.
- Backend `import main` ≈ **1.9 s**; `load_profile()` ≈ **169 ms**.
- LLM calls per application: **3 min / 4 typical / 6 max-successful / 18 worst**.
- Estimated cost per application (`gemini-3.8-flash`): **$0.027 / $0.049 / $0.092**.
- Pricing verified against ai.google.dev on 2026-10-23 (see ADR 0010 and D-5 below).

---

## Blockers and unresolved issues

1. **`GEMINI_API_KEY` is not set in this worktree's `.env`.** `cvtailor doctor` reports it as
   the only real blocker. The owner must enter it directly — never paste it into a chat. Live
   generation in this worktree is blocked until then; rendering, the CLI and all tests are not.
2. **Privacy model not yet implemented** ([ADR 0002](DECISIONS/0002-privacy-model.md)). Real
   personal data — including immigration status — is still committed to a **public** repo.
   This must be implemented before a second real candidate is added, which is exactly what
   Phase 2 introduces. **Resolve this at the start of Phase 2, not after.**
3. **Sandbox caveat:** under the DSH `workspace-write` sandbox, pytest's `tmp_path` tests error
   on ACL operations, and this session additionally saw the venv Python denied **write** access
   to `outputs/` and `storage/profile/profile.yaml` while PowerShell could write both. That is
   an environment artifact, not a code fault — recorded in [`TESTING.md`](TESTING.md).
   `git commit` in this worktree needs unconfined access, because its git metadata lives in
   `D:\coding\cv-tailor\\.git`, outside the sandbox.
4. **`docx_renderer.py:304-307` mutates the caller's model** — verified real bug, still
   unfixed and **still untested** (deliberately: pinning it would bless it). Its practical
   impact is bounded by `test_docx_contains_every_body_paragraph`.
5. **`backend/main.py` has no tests.** The service layer now exists, so this is a contained
   piece of work — it was left out of Phase 1 to keep the increments focused.
6. **`render_application.py` and the CLI's `render` now duplicate render logic.** The CLI's
   `render` does not yet add the `\needspace` project-heading pagination tweak that the script
   applies, so a CV that depends on that tweak could paginate differently. Tracked below.

### Resolved in Phase 1

- ~~Dead code: `response_schema`, `validate_api_key`, `create_gemini_service`, `ErrorResponse`,
  `TailoredOutput`~~ — removed (D-1, D-2, D-7).
- ~~Import-time env reads~~ — `Config` object, guarded by a test (A-5).
- ~~296-line `tailor_documents`~~ — split into `generation` + `application_store` (A-3).
- ~~Candidate-specific rules hardcoded in the validator~~ — now profile-scoped (A-1).
- ~~No CLI~~ — `cvtailor` with four commands (ADR 0007).
- ~~Nested `tailoring_explanation` silently yields `None`~~ — fixed and tested.
- ~~Two `_escape_latex` and three `_slugify` copies~~ — consolidated into `utils/text.py` (D-12).
- ~~Stale pricing rows and unused dependencies~~ — pruned, with the model/prices verified (D-5, D-6).

---

## Known-important findings (do not lose)

- `.github/copilot-instructions.md` describes a **different system** (Tectonic, `gemini-1.5-flash`,
  a non-existent `/api/preview` endpoint). It is the most misleading document in the repo (D-8).
  **Still unfixed.**
- Generated PDFs/DOCX are **tracked** in `outputs/` despite `.gitignore` (D-9). **Still unfixed.**
- `initial_generation_result.json:4-6` leaks absolute local paths incl. a third-party name (D-10).
- **Removing a stale pricing row is only safe while the fallback target still exists.** The old
  fallback was `PRICING["gemini-1.5-flash"]`, so deleting that row would have raised `KeyError`
  for any unlisted model. The fallback is now `PRICING[DEFAULT_MODEL]`, and a test asserts
  `DEFAULT_MODEL in PRICING`. Keep that invariant when editing the table.
- **A tool named in `rules.banned_tools` must not count as evidence the candidate used it.**
  The check serializes the profile with the `rules` block excluded; without that, declaring a
  tool banned would silently un-ban it.
- `outputs/2026_adjoe_senior_data_analyst_1769343142/` has **no `source/content.json`** — the
  D-14 partial-folder case. Do not assume `outputs/*/source/` exists.
- `docx_renderer.py:264` writes a `latex_work/` scratch dir inside the deliverable folder (D-13).

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
