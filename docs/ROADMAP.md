# Roadmap

**Status:** Direction **approved 2026-10-23** ([decisions](DECISIONS/README.md)). Phase 0 is
complete, Milestone 1.1 is complete, and **Phase 1 is complete**. Phases may be reordered, split
or parallelised when dependencies justify it.

Approved direction: **Option B — modular redesign, executed incrementally.** Keep the
renderers, templates, prompts, the `content.json` contract and the page-count gate; introduce
profile identity, a service layer and a persistence model around them.

Guiding constraints:
- `master` stays usable for real applications throughout.
- No phase merges to `master` without explicit owner approval.
- Every phase must be independently testable and must not break the test baseline.
- Prefer the simplest thing that works: no database server, no queue, no microservices.
- Real candidate data moves to a private store; only synthetic examples are committed.
- Re-confirm the relevant decisions when each phase begins.

---

## MVP definition

**Phase 1 + the first slice of Phase 2**: a CLI that can list, select and generate documents
for a *named* profile, preserving current generation quality. This makes daily use better
without waiting for discovery or tracking.

---

## Phase 0 — Assessment and foundations *(COMPLETE)*

- **Objective:** establish an evidence-based understanding and a safe working setup.
- **User value:** none directly; everything after depends on it.
- **Deliverables:** `ASSESSMENT.md`, `PROJECT_STATE.md`, `ROADMAP.md`, `DEVELOPMENT.md`,
  `TESTING.md`, `DECISIONS/` (9 approved records), `project-continuity` skill, isolated and
  runnable dev worktree.
- **Status:** assessment complete and approved; dev worktree set up.

### Milestone 1.1 — Test baseline and golden fixtures *(COMPLETE 2026-10-23)*

- **Objective:** make it possible to prove behaviour is preserved before any refactor.
- **Scope:** synthetic profiles + anonymised job descriptions + recorded LLM responses in
  `tests/fixtures/`; characterization tests for every workflow in `ASSESSMENT.md` §1;
  a determinism test for `render_application.py`; document-level assertions (page count,
  sections, word counts); extend `docs/TESTING.md`.
- **Changes no production behaviour** — `tests/` and `docs/` only.
- **Acceptance:** `python -m pytest -q` green and fully offline; every §1 workflow has a
  behavioural test; fixtures contain no real personal data.
- **Delivered:** suite grew **12 → 141 tests** (~100 s). Two synthetic profiles, three
  anonymised postings, recorded provider responses; real LaTeX/DOCX output asserted with
  `pypdf` (page count, sections, verbatim bullets, clipping, orphan headings, escaping);
  11 end-to-end determinism tests for `render_application.py`. Fast lane
  `-m "not requires_latex"` runs 113 tests in ~6 s. See [`TESTING.md`](TESTING.md).
- **Effort:** Small–Medium.

---

## Phase 1 — Core refactoring and CLI foundations *(COMPLETE 2026-10-23)*

- **Objective:** make the codebase simple and testable, and give it a real CLI.
- **User value:** generate/re-render from the terminal; no browser, no API server.
- **Scope:** introduce the `cv_tailor` package; extract a service layer from
  `tailor_documents`; single config object (no import-time globals); delete verified dead
  code; consolidate duplicated helpers; one pricing source of truth.
- **Dependencies:** Phase 0 (test baseline).
- **Tasks:** package skeleton; move models/rules; split orchestration from persistence;
  `Config` object; remove D-1/D-2/D-5/D-6/D-7/D-12; `cvtailor` CLI
  (`profile show`, `generate`, `render`, `doctor`).
- **Acceptance:** all Phase-0 tests pass unchanged; CLI reproduces an existing
  `content.json` render byte-comparably in page count; no import-time env reads.
- **Testing:** characterization suite + CLI smoke tests.
- **Risks:** breaking the render path while moving files — mitigated by the baseline.
- **Effort:** Medium.
- **Delivered** (six commits, `edb6efc`..`179bd83`; suite **141 → 190**; **no existing test
  was modified**):
  - **Bug fix** (`edb6efc`) — `tailoring_explanation` is read from a nested `cv` as well as
    the top level; the nested case previously yielded `None` silently.
  - **Dead code** (`b568990`) — D-1, D-2, D-7 removed; D-5 pricing pruned against verified
    ai.google.dev data, which exposed and fixed a latent `KeyError` in the cost fallback;
    D-6 dependencies pruned (a separate audit found `pandas` is *not* in `requirements.txt`
    and *is* used, refuting that part of the assessment); D-12 helper copies consolidated.
  - **Config** (`ef500b6`) — no import-time env reads; see [ADR 0010](DECISIONS/0010-config-object.md).
  - **Service layer** (`dfe03ec`) — `tailor_documents` split into `services/generation.py`
    (prompts, LLM, validation, retries) and `services/application_store.py` (folders,
    manifests, mirroring), leaving a thin orchestration facade.
  - **Profile rules** (`e05562e`) — candidate-specific validation rules moved out of the
    validator into a profile-scoped `rules` block (A-1), the main blocker to Phase 2.
  - **CLI** (`179bd83`) — `cvtailor doctor|profile show|generate|render` per
    [ADR 0007](DECISIONS/0007-cli-framework.md).
- **Deferred to a later phase, deliberately:** the `cv_tailor` package rename (the modules are
  reorganised and importable, but `backend/` keeps its name so `master` stays comparable);
  `main.py` tests; the `\needspace` project-heading tweak in the CLI's `render`; D-8, D-9,
  D-10, D-13, D-14.

---

## Phase 2 — Multi-profile architecture

- **Objective:** let several candidates each own their data.
- **User value:** the headline feature; also enables anonymised testing.
- **Scope:** `ProfileStore` keyed by `profile_id`; thread `profile_id` from CLI/API through
  to output paths (`outputs/<profile_id>/<job_id>/`); move hardcoded candidate rules
  (`tailor_service.py:73-92,154-167`) into **profile-scoped configuration**; validate dates;
  migrate the existing profile.
- **Dependencies:** Phase 1.
- **Acceptance:** two profiles generate independently; no cross-contamination; the original
  profile migrates with manual edits, titles, dates and preferences intact.
- **Testing:** isolation tests (A generates → B's files unchanged), migration round-trip,
  contaminated-fixture detection.
- **Risks:** silent data overwrite — mitigate with explicit `profile_id` and fail-closed
  when absent.
- **Effort:** Medium–High.
- **Start here:** [`HANDOFF-PHASE-2.md`](HANDOFF-PHASE-2.md) — entry conditions, order of work,
  worktree hazards, and why the privacy model must land with (or before) the first second
  profile.
- **Unblocked by Phase 1:** candidate rules are already profile-scoped (A-1), so no validator
  change is needed to support a second candidate.

---

## Phase 3 — LLM and document-generation improvements

- **Objective:** cheaper, more reliable, provider-independent generation.
- **User value:** lower cost, fewer failed runs, better documents.
- **Scope:** provider interface (Gemini + OpenRouter); model-per-task routing; enable
  structured output; targeted layout retry instead of full regeneration; merge the editorial
  pass; accurate tiered cost accounting; optional budget caps.
- **Dependencies:** Phase 2 (profile-scoped prompts).
- **Acceptance:** same or better document quality at measurably lower cost; cost figures
  match provider billing; no silent fallback that bypasses validation.
- **Testing:** recorded-response determinism tests; a separate opt-in, budget-capped
  live evaluation suite (never in CI).
- **Risks:** a provider swap degrading quality — mitigate by benchmarking first.
- **Effort:** Medium.

---

## Phase 4 — Job discovery and matching

- **Objective:** find and rank jobs instead of pasting descriptions.
- **User value:** the largest workflow gain after multi-profile.
- **Scope:** modular connectors over **ToS-compliant** sources (public APIs, RSS, official
  career pages); normalise to one `Job` model; dedupe; expiry detection; deterministic,
  explainable matching with explicit hard-eligibility vs preference separation.
- **Dependencies:** Phase 2.
- **Acceptance:** a configured search returns normalised, deduplicated jobs with
  human-readable match explanations; no invented scores.
- **Testing:** recorded API fixtures; matcher unit tests on synthetic profiles.
- **Risks:** ToS/rate limits and source churn — prefer fewer reliable sources.
- **Effort:** High.

---

## Phase 5 — Application management

- **Objective:** track applications end to end.
- **User value:** replaces ad-hoc folders and spreadsheets.
- **Scope:** statuses (saved → shortlisted → preparing → submitted → interview → offer /
  rejected / withdrawn), deadlines, follow-ups, notes, saved document versions, search and
  filtering. **No LLM required** to record or update an application. **No automatic submission.**
- **Dependencies:** Phase 2.
- **Acceptance:** full lifecycle manageable from the CLI with zero LLM calls.
- **Testing:** store round-trips, migration from existing `applications/`.
- **Effort:** Medium.

---

## Phase 6 — UI and deployment

- **Objective:** decide the interface story.
- **Scope:** assess keeping vs replacing Streamlit; multi-profile management; job search and
  application dashboards; document previews; authentication **only if** hosted.
- **Dependencies:** Phases 3–5.
- **Acceptance:** the UI reuses the same services as the CLI — no duplicated business rules.
- **Effort:** Medium–High.

---

## Cross-cutting rules

- Documentation changes ship in the same commit as the code they describe.
- Update `PROJECT_STATE.md` at the end of every meaningful task.
- Record decisions in `docs/DECISIONS/` when they are hard to reverse.
- Keep `master` working; integrate only via an approved pull request.
