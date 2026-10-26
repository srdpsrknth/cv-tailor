# Roadmap

**Status:** Direction **approved 2026-10-23** ([decisions](DECISIONS/README.md)). Phase 0 is
complete, Milestone 1.1 is complete, **Phase 1 is complete**, **Phase 2 is complete and closed
out**, and **Phase 3 is in progress** (increments 4 and 2 of 6 done — see [§Phase 3](#phase-3--llm-and-document-generation-improvements)).
Phases may be reordered, split or parallelised when dependencies justify it.

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

## Phase 2 — Multi-profile architecture *(IMPLEMENTED 2026-10-24)*

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

### Delivered (three commits, `f583349` + `86b1a0d` + the store-outputs fix; suite **190 → 262**)

- **`ProfileStore`** (`f583349`) — the store is the only place that decides where a profile
  lives, keyed by `profile_id` with the layout ADR 0004 approved. `profile_id` is threaded
  through `Config`, `tailor_documents`, `ApplicationStore` and the CLI, and **fails closed**:
  missing, empty, malformed or unknown ids all raise. There is no default and no inference.
- **The private-store split** — real profiles, `applications/` and `outputs/` are no longer
  tracked (ADR 0002 implemented as [ADR 0011](DECISIONS/0011-private-store-location.md)); the
  store lives in a sibling private repository. `tests/test_privacy_boundary.py` asserts the
  boundary and fails if it regresses.
- **A-9 fixed** — `outputs/<profile_id>/<job_id>/`. Two candidates on one posting now write to
  different trees; the mirror path carries the candidate segment too.
- **Documents land in the store** — found while auditing the documentation after Phase 2 was
  declared complete: `ApplicationStore` was still rooted at `PROJECT_ROOT`, so real documents
  were written into the public repository's gitignored `outputs/` rather than the store,
  contradicting [ADR 0011](DECISIONS/0011-private-store-location.md). Now rooted at
  `<store>/outputs/<profile_id>/`, with a regression test that fails if it moves back. `doctor`
  and `render`'s fallback lookup follow the store as well.
- **CLI** — `profile list | new | import | export` beside `show`, and `--profile-id`. `doctor`
  reports the store and which profiles it holds.
- **Migration** — the real profile was copied byte-for-byte (verified by SHA-256) into
  `profiles/sreedeep/profile.yaml`, and loads through the store with all six roles, its two
  degrees, its certifications and its complete `rules:` block intact. All 64 application files
  and the generated `outputs/` artifacts moved with it.
- **Two real defects found by writing the tests**, both silent:
  a well-formed-but-nonexistent id created `outputs/<typo>/` and generated documents for an
  unnamed candidate; and `profile` + `profile_id` could be paired across two different
  candidates, filing the wrong person's documents under the wrong id.
- **Resolved by the same change:** D-9 — generated PDFs/DOCX were tracked in `outputs/` despite
  `.gitignore`; they left the index with the rest of the real data.
- **Deferred to a later increment, deliberately:** date validation (A-6), the `outputs/`
  artifact-filename convention, and the `\needspace` parity gap.

### Close-out (2026-10-26) — suite **262 → 282**

An audit-and-clean-up pass, not a refactor, to remove the last descriptions of the
single-profile system. It closed the largest outstanding functional gap and settled the two
open D-items the owner still had to decide.

- **`backend/main.py` is multi-profile aware and tested** (`a0b431c`) — the API resolved a
  profile with `load_profile()` and no argument, reading the pre-Phase-2 path
  `storage/profile/profile.yaml` and bypassing the store entirely (ADR 0003). On this machine
  that stale duplicate still existed and was byte-identical to the store's copy, so
  `/api/tailor` appeared to work while silently ignoring the store; on a fresh clone it raised.
  `/api/tailor` and all three download routes now take an explicit `profile_id`, resolve through
  the store, and fail closed. `job_id` is validated against `^[A-Za-z0-9_-]+$` before use
  (ASSESSMENT.md §6). `tests/test_api.py` adds the module's first 20 tests; **16 of them fail
  against the previous `main.py`**, verified by stashing the fix.
- **D-9 re-verified as already resolved** — `git ls-files outputs` returns only
  `outputs/.gitkeep`, so no further untracking was owed. The three untracked pre-Phase-2
  PDFs/DOCX still on disk were deleted after each was confirmed byte-identical (SHA-256) to its
  copy in the private store.
- **D-10 decided: leave history as-is.** The file is untracked and gitignored; it remains in
  past commits, which is the limitation [ADR 0011](DECISIONS/0011-private-store-location.md)
  already records. No rewrite or force-push is approved.
- **D-11 deferred to Phase 5**, not Phase 2 — see the Phase 5 entry below.
- **Dead code removed** — `backend/validate_profile.py` (86 lines, unreferenced, hardcoding the
  dead single-profile path) and two self-referential `Config` aliases (`LEGACY_PROFILE_PATH`,
  `DEFAULT_PROFILE_PATH`). No existing test was changed.

**Still open after the close-out:** A-6 (dates), A-7 (renderer mutation), A-8 (custom render
scripts), A-10 (`--mirror-configured`), D-3, D-4, D-13, D-14, D-15, and blocker 8
(`\needspace` parity).

**Not undone:** the data already published in the public repository's history stays published.
Untracking is not un-disclosure; purging it needs a history rewrite and a force-push, which
[ADR 0011](DECISIONS/0011-private-store-location.md) records as a separate unapproved decision.

---

## Phase 3 — LLM and document-generation improvements

**Status 2026-10-26: in progress, deliberately split across several increments.** The agreed
order is **4 → 2 → 1 → 3**, then a new chat for **6**, and **5** only once 1–4 have settled.
Each is verified on its own, because each changes the call-count baseline the others are
measured against; mixing them makes an intended change indistinguishable from a regression.
Increment 2 changed the baseline: the counts are now **2 min / 3 typical / 5 max-successful**
and those are what increment 1 must be measured against.

| # | Item | State |
|---|---|---|
| 4 | Serialise the profile once per application | **DONE** (`refactor:`, 2026-10-26) — byte-identical prompts, one serialisation per run; see §5 of [`ASSESSMENT.md`](ASSESSMENT.md) |
| 2 | Remove or merge the editorial-review pass | **DONE** (`refactor:`, 2026-10-26) — requirements folded into the draft prompt, second CV call removed; calls 3/4/6 → **2/3/5**, best-case input tokens −41% |
| 1 | Targeted layout retry instead of full regeneration | **Next in the agreed order** |
| 3 | Enable structured output (`response_schema`) | Not started |
| 6 | Provider interface, model routing, budget caps | Not started — new chat |
| 5 | Cache validated results | Not started — only after 1–4 have settled |

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
- **Inherited from Phase 2 (owner decision 2026-10-26):** migrate the saved-application archive
  to one schema (**D-11**). [ADR 0009](DECISIONS/0009-interfaces-and-archive.md) originally named
  Phase 2, but the archive left the public repository in Phase 2 and now lives in the private
  store at `<store>/applications/<job_id>/`, so the migration belongs with the phase that owns
  application schemas. The archive stays readable as-is until then; nothing is deleted or
  rewritten in the meantime.
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
