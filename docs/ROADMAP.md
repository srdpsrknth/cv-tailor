# Roadmap

**Status:** Direction **approved 2026-10-23** ([decisions](DECISIONS/README.md)). Phase 0 is
complete, Milestone 1.1 is complete, **Phase 1 is complete**, **Phase 2 is complete and closed
out**, and **Phase 3 is complete**. Increments 4, 2, 1 and 3 are done, item 5 is done, and
item 6's **study ran, selected a winner, and shipped the switch**: the default is now
**`openai/gpt-6-luna` on OpenRouter** at **$0.00281 per accepted result**, roughly 30-40x
cheaper than the `gemini-3.8-flash` default it replaced, verified end to end on both a
synthetic and the owner's real profile. **The curation skill is complete** (2026-10-30) — the
set can now be refreshed by procedure rather than by a research session; see
[ADR 0017](DECISIONS/0017-curation-skill.md).
See [§Phase 3](#phase-3--llm-and-document-generation-improvements).
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
and those are what increments 1 and 3 were measured against. **Increments 1 and 3 left those
counts unchanged**, as intended.

| # | Item | State |
|---|---|---|
| 4 | Serialise the profile once per application | **DONE** (`refactor:`, 2026-10-26) — byte-identical prompts, one serialisation per run; see §5 of [`ASSESSMENT.md`](ASSESSMENT.md) |
| 2 | Remove or merge the editorial-review pass | **DONE** (`refactor:`, 2026-10-26) — requirements folded into the draft prompt, second CV call removed; calls 3/4/6 → **2/3/5**, best-case input tokens −41% |
| 1 | Targeted layout retry instead of full regeneration | **DONE** (`refactor:`, 2026-10-26) — the retry sends a targeted brief and the current CV instead of re-sending the whole context, and accepts a delta of replacement values merged onto the validated CV; retry input 3,488 → **740** tokens on the recorded fixture, calls unchanged at **2/3/5** |
| 3 | Enable structured output (`response_schema`) | **DONE** (`feat:`, 2026-10-26) — JSON mode and a schema on the CV draft and the cover letter; the layout retry is deliberately left unconstrained because its response may be a delta. The schema requires the response *envelope* and leaves the document body open, which is what keeps D-1's truncation from returning. Calls unchanged at **2/3/5**; see [ADR 0012](DECISIONS/0012-structured-output-scope.md) |
| 6 | Provider interface, model routing, budget caps, and the curated model set | **DONE** (`feat:`/`fix:`, 2026-10-26/27) — the interface, routing, caps and D-3/D-4 landed as increments A–C; the **study then ran**, the owner selected `openai/gpt-6-luna`, and the switch shipped in `e53ef8a`. See the close-out below and [ADR 0016](DECISIONS/0016-per-candidate-inputs-and-one-winner.md) |
| 5 | Cache validated results | **DONE** (`feat:`, 2026-10-26) — a validated generation is stored under `<store>/cache/<profile_id>/`, keyed by the bytes the model was shown; a repeat makes **0** LLM calls and produces byte-identical documents. Cold-cache call counts unchanged at **2/3/5**; see [ADR 0015](DECISIONS/0015-generation-cache.md) |

### The curation skill — re-running the model study (2026-10-30) *(COMPLETE)*

**Objective.** Make the curated set refreshable when new models arrive, without repeating the
manual research the first curation took a full session.

**User value.** The tool keeps using the cheapest model that actually works for this task, as
the catalogue moves under it — rather than drifting onto a model that has been repriced or
superseded. And the refresh is a short, auditable procedure instead of a research session.

**Deliverables, all landed. One commit per item.**

| # | Item | Commit | Outcome |
|---|---|---|---|
| 1 | A portable, committable listing record | `0970c7e` | `evaluation/listing.py` + a 267-model committed record; **two skips retired** |
| 2 | The screen: a proposed slate, with every rejection reasoned | `56b8a4c` | `--screen`, offline and free |
| 3 | Detection, and a curation diff that writes nothing | `6016b5e` | `--detect` reports; `--report` proposes and is **inert** |
| 4 | The reading packet, and the human judgement step | `78b436a` | `--packet` + a `VERDICTS.md`; a candidate is ineligible without a verdict |
| 5 | The curation skill file | `3a9adeb` | `.agents/skills/cv-model-curation/SKILL.md` — the procedure |
| 6 | Documentation and the decision record | *(this commit)* | [ADR 0017](DECISIONS/0017-curation-skill.md) |

**Acceptance criteria, and how each was met.**

* *A re-curation can be run from the repository alone* — **met.** The committed listing record
  carries the fields curation uses plus the full payload's digest, so a price is checkable by
  anyone without a re-fetch.
* *It cannot spend by accident* — **met.** `--detect`, `--screen`, `--report` and `--packet`
  are offline by construction; `live.py` remains the only place a paid call can originate, and
  the skill states that `--live` needs the owner's explicit yes with the projection shown.
* *The owner's reserved judgement is part of the workflow* — **met.** The verdict gate is
  enforced in `curation_diff.apply_verdicts`; a test asserts no field a measurement could set
  can promote an entry.
* *No quality claim can drift ahead of the evidence* — **met, and since closed.** The marker was
  withheld until 2026-10-31, when the owner read the rendered documents and answered "send as-is";
  `verified="measured"` is now set on the shipped entry with the verdict dated in its notes, and
  the guard asserts a marked entry must carry one.

**Not in scope, deliberately:** a monthly spend ledger; automatic default switching;
`cvtailor curate`. Each is recorded with its reasoning in ADR 0017.

### Item 6 close-out — the study ran, and the winner shipped (2026-10-26/27)

**The study is complete and its outcome is in production.** Eight candidates, three cases
each, on live calls; the owner then selected one. **$1.91 was spent in total** across the
whole effort — eleven diagnostic runs, schema verification against three provider
families, and three complete studies — against the owner's $5 cap.

| model | accepted | cost / accepted | outcome |
|---|---|---|---|
| **`openai/gpt-6-luna`** | **3/3** | **$0.00281** | **SELECTED — now the default** |
| `anthropic/claude-haiku-5.5` | 3/3 | $0.00594 | rejected |
| `qwen/qwen3.8-flash` | 3/3 | $0.01269 | rejected — see the correction below |
| `deepseek/deepseek-v4-flash` | 1/3 | $0.02036 | rejected |
| `google/gemini-3.8-flash` | 2/3 | $0.08607 | rejected — was the default |
| `anthropic/claude-sonnet-5` | 3/3 | $0.13743 | rejected |
| `z-ai/glm-5.3-flash` | 0/3 | none | rejected — omits employer dates at any ceiling |
| `mistralai/mistral-small-2603` | 0/3 | none | rejected — rate-limited in all three runs |

**The winner was reproduced three times**: 3/3 accepted with no correction calls every
run, at roughly **30-40x lower cost per accepted result** than the default it replaced.
The switch landed in `e53ef8a` and was verified end to end on a synthetic profile and the
owner's real one.

**One result was corrected, and the error was ours.** `qwen3.8-flash` was first recorded
as 0/3 because it returned an **empty body** at the default 8,000-token ceiling — a
reasoning model spends its budget thinking before it writes. At 32,000 tokens it accepts
3/3. Scoring that as a model failure ranked *this project's ceiling* rather than the
model, which is exactly the error the study's own machinery exists to prevent.
`glm-5.3-flash` had the same symptom and a different cause: it omits `role`,
`start_date` and `end_date` from every employer at any ceiling, and that failure is real.

**The acceptance bar never moved.** Same profiles, same postings, same validation rules,
same word-count gate for every candidate; only the *asking* varied, which is the whole
point of [ADR 0016](DECISIONS/0016-per-candidate-inputs-and-one-winner.md).

**What the study established beyond the ranking:**

1. **Three provider families demand mutually incompatible schemas** — OpenAI requires
   `additionalProperties: false`, Vertex rejects >24 optional parameters, Gemini rejects
   that keyword outright. Ranking against one shared schema would have measured the
   schema, not the models: `gpt-6-luna` and `claude-haiku-5.5` failed *every* call in two
   earlier runs and became the winner and third place once asked properly.
2. **The `structured_outputs` catalogue flag is advertising, not evidence.** Measured:
   Cloudflare advertises it and silently returns an empty body rather than an error; two
   other endpoints rejected the schema outright until the dialect was fixed.
3. **No truncation at `max_tokens: 8000`** (largest constrained CV output 6,286 tokens),
   but **reasoning tokens consume 53–58% of the output budget**, and one cover-letter call
   emitted **21,463** output tokens against an assumed ~620.
4. **Leaderboard position did not predict this task.** `qwen3.8-flash` (81.3% IFBench)
   and `glm-5.3-flash` (27.6% hallucination rate) both accepted nothing; the winner was
   chosen on price and reliability, not reputation.

**Seven defects were found by making real calls, and each one would have been invisible
offline** — the evaluation could not read `.env`, the SDK schema was not serializable, its
type names were UPPERCASE, Gemini rejects `additionalProperties`, evaluation output was
written into the repository under a *real* candidate's profile id, failed runs reported
$0.00, `usage.cost` is 0 for Google-routed calls, and `require_parameters` made three
models unroutable. Recorded here because it is the argument for keeping the paid suite.

The three offline increments that preceded the study, each verified on its own against
the frozen 2/3/5 baseline:

| Increment | Commit | Outcome |
|---|---|---|
| A — provider interface, routing, budget caps | `feat:` `372a7bf` | `services/provider.py` implements `generate(prompt, *, schema, max_tokens, model)`; Gemini default (decision 6), OpenRouter second with its `response_format` envelope **translated** rather than passed through, plus `provider.require_parameters` on schema calls; `schema=None` reaches both providers as "send no constraint", preserving [ADR 0012](DECISIONS/0012-structured-output-scope.md); `Config.model_for(task)` and an optional `CVTAILOR_MAX_COST_USD` that fails closed. No silent fallback. [ADR 0013](DECISIONS/0013-provider-interface-and-routing.md) |
| B — D-3 and D-4 | `fix:` `3cc8da5` | `services/pricing.py` is the one source of truth, keyed by `(provider, model)` and tier-aware. The long-context tier is applied to the tokens: for `gemini-2.5-pro` at 300k tokens the old flat figure was **$0.375 against a real $0.75**. The UI no longer carries a second table |
| C — evaluation suite, curated set | `feat:` `215ba08` | `evaluation/` implements ADR 0005's eight criteria, offline by default, refuses an over-budget plan before the first call, and is not collected by pytest. [ADR 0014](DECISIONS/0014-evaluation-suite-and-curation.md) |

**The two questions item 6 set out to answer are now answered**, both by the study above:

1. **Which model is genuinely best per accepted result** — `openai/gpt-6-luna`, at
   $0.00271. The ranking is recorded; only the owner's quality judgement is outstanding.
2. **Whether structured output truncates on real documents** — **it did not**, at
   `max_tokens: 8000`; the largest constrained CV response was 6,286 output tokens and
   every one finished with `finish_reason: stop`. The real risk turned out to be
   different and is now quantified: reasoning tokens consume 53–58% of the output
   budget, and one cover letter emitted 21,463 tokens against an assumed ~620. See
   [ADR 0012](DECISIONS/0012-structured-output-scope.md), which also records that
   compliance is a **per-endpoint** property and was measured as such.

### Item 5 — cache validated results *(DONE 2026-10-26)*

**Objective:** stop paying twice for work already done.

**What was already true, and shaped the item.** Re-rendering an existing `content.json` costs
**zero** LLM calls today — the render path is already free, and `render_application.py` is the
route real revisions use. So the item was never "make rendering cheap"; it is about the
*generation* path, where the same profile against the same posting re-drafted from scratch.

**What was built.** `services/cache_store.py`. A validated generation is stored under
`<store>/cache/<profile_id>/generations/<key>.json`, and an identical request is served from
disk. See [ADR 0015](DECISIONS/0015-generation-cache.md) for the full reasoning.

| The four decisions | How each is met |
|---|---|
| **What the key is** | A SHA-256 digest over named fields: the serialized profile bytes, the job description, company/role/country, **both prompt files byte-for-byte**, the schema digest, the provider, both routed models, and the resolved `rules`. `job_id` and any timestamp are deliberately absent — `job_id` embeds a millisecond, so keying on it would miss by construction |
| **What is cached** | A **validated** result only. The entry is written after the page-count gate passes and nowhere else, so a draft that failed the gate can never become a permanent answer |
| **When it is invalidated** | Any change to the prompt files, the editorial requirements, the schema, the model, the provider, the country, or the profile. The prompt files are **read and hashed per call** rather than tracked by a version constant, so an edit cannot be served from cache even if nobody bumps anything |
| **Where it lives** | `<store>/cache/<profile_id>/` (ADR 0011), a sibling of `outputs/`, never in the repository. It is derived data, so deleting it is always safe: every read failure — missing, malformed, truncated, wrong format version — is a **miss**, never an error |

**Two guards worth naming.** A stored document is **re-validated** on read through the same
`_build_model` a fresh draft goes through, because the cache is a plain JSON file a person can
edit and "it was validated when it was stored" is a claim about the past; re-validating is free.
And a hit reports **zero** usage rather than replaying the original run's token totals, because
pricing a run that made no call is exactly the dishonesty this item exists to remove. The
original figures are kept in the same file as `original_usage`.

**Acceptance — verified.** A repeat of an identical generation makes **0** LLM calls and produces
byte-identical accepted documents; a changed prompt byte, model, provider, country or profile
makes a fresh call; and the cold-cache call-count baseline is **unchanged at 2/3/5, worst 12** —
item 5 adds a lookup before the first call and a write after the last one, and adds no request.

**Deliberately not built, and recorded as an open follow-up:** there is **no eviction policy**.
One small JSON file per distinct generation, for a single-user tool, is acceptable, and deletion is
documented as always safe — but an eviction or size policy is a real follow-up rather than a solved
problem.

**Effort:** Medium (as estimated).

**Item 6 scope, including an owner requirement recorded 2026-10-26.** Item 6 builds the thin
provider interface, model-per-task routing and optional budget caps. It also owns **model
curation**, and the owner's instruction is explicit:

- OpenRouter provides access to a **very large** model catalogue. **Do not expose all of it**
  — a wall of models is a decision the tool should have already made, not one to hand the
  user.
- **Research which model is genuinely best suited to CV and cover-letter generation**,
  weighed on **price against content quality**. This is measured work, not a popularity
  contest: it needs the evaluation method ADR 0005 already requires (accuracy, completeness,
  relevance, writing quality, structured-output success, unnecessary claims, correction
  attempts and total cost per *accepted* result).
- **Offer users a small curated set spanning different performance and cost levels**, so the
  trade-off is visible and the choice is theirs.

Before any paid evaluation: agree the method and a spending budget with the owner (ADR 0005).
Live evaluation stays out of CI — optional, budget-capped and reproducible.

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
