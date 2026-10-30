# Testing

**Baseline command:** `python -m pytest -q` (run from the repository root)
**Current baseline:** **555 passed, 5 skipped**, 1 warning, ~120 s, fully offline — no paid API calls.
**Fast lane:** `python -m pytest -q -m "not requires_latex"` → **524 passed, 5 skipped**, 31 deselected, ~16 s.

> **The baseline is 555/5, and the five skips are environmental — do not read them as
> regressions.** Two skip because the recorded OpenRouter listing
> (`.tmp/openrouter_models_2026-10-26.json`, 467 models, gitignored) is not in this
> working copy; one because there is no real profile to compare fixtures against; and
> two are unconditionally `@pytest.mark.skip`'d A-1 guards whose reasons are in the file.
> **A previous handoff recorded this as "540 passed, 3 skipped"** — the count drifted
> when the listing fixture left the working copy. Verify against **555/5**.

**The default is now `openai/gpt-6-luna` on OpenRouter** (2026-10-27), selected by the
study and switched in `e53ef8a`. Two consequences for anyone running these tests:

* **The shipped response schema is strict** — `additionalProperties: false`, every
  declared property required, `skills` as an array of `{category, items}`, and
  `tailoring_explanation` required-but-**nullable** (strict mode forbids an optional
  property; null is how "optional" is expressed). `tests/test_structured_output.py`
  asserts all of that, including that the Gemini rendering strips the keyword Gemini
  rejects.
* **A provider-specific model variable no longer leaks across providers.** `GEMINI_MODEL`
  is honoured only when Gemini is selected; `CVTAILOR_MODEL` is the provider-neutral one
  and outranks it. This is a regression guard with a real cause: the owner's existing
  `GEMINI_MODEL=gemini-3.8-flash` silently overrode the new default and ran the old model
  through OpenRouter, where the bare name is not even a priced route.

| | |
|---|---|
| Baseline before Milestone 1.1 | 12 passed, ~2.5 s |
| Baseline after Milestone 1.1 | 141 passed, ~100 s |
| Baseline after Phase 1 | 190 passed, ~110 s |
| Baseline after Phase 2 | 262 passed, ~106 s |
| Baseline after the Phase 2 close-out | 282 passed, ~114 s |
| Baseline after Phase 3 increment 1 | 298 passed, ~112 s |
| Baseline after Phase 3 increment 2 | 309 passed, ~107 s |
| Baseline after Phase 3 increment 1 of the agreed order (targeted layout retry) | 324 passed, ~108 s |
| Baseline after Phase 3 increment 3 (structured output) | 351 passed, ~108 s |
| Baseline after Phase 3 item 6, increment A (provider interface, routing, budget caps) | 390 passed, ~113 s |
| Baseline after Phase 3 item 6, increment B (D-3, D-4 — route- and tier-aware pricing) | 407 passed, ~112 s |
| Baseline after Phase 3 item 6, increment C (evaluation suite, curated set) | 436 passed, ~115 s |
| Baseline after Phase 3 item 5 (validated-generation cache) | 480 passed, ~116 s |
| **Baseline after the cache-bypass fix and the cost/curation increment (2026-10-26)** | **500 passed**, ~116 s |
| Paid API calls | **none** |
| Requires | `pypdf`, `python-docx`; `pdflatex` for the document-level tests (they skip without it) |

The suite grew 12 → 141 in Milestone 1.1, 141 → 190 in Phase 1, 190 → 262 in Phase 2,
262 → 282 in the 2026-10-26 close-out, 282 → 298 in Phase 3 increment 1 (all new files),
298 → 309 in increment 2, 309 → 324 in Phase 3 increment 1 of the agreed order
(targeted layout retry), 324 → **351** in increment 3 (structured output), 351 → **390**
in item 6 increment A, 390 → **407** in increment B, 407 → **436** in increment C, and
436 → **480** in item 5 (one new file, plus one pre-existing test — see below).
The runtime increase is almost entirely `pdflatex`: real rendering is exercised instead of
mocked.

> **Sandbox caveat.** Under the DSH `workspace-write` sandbox, pytest's `tmp_path` tests error
> on ACL operations ("No usable temporary directory" is the same environment artifact), and
> `tools/build_fixtures.py` is denied writes under `tests/` even though ACLs allow them. Run
> pytest unconfined; build fixtures into a staging root and copy them in (that is what the
> script's `argv[1]` is for).

**No test that existed at `325c4d1` has been modified in behaviour** except where a change of
behaviour was the point of the increment. Every such change is listed below with its reason.

Phase 2's two exceptions, both forced by the layout change that phase exists to make, and both
**stricter** afterwards:

| Test | Change | Why |
|---|---|---|
| `test_tailoring_pipeline.py::test_artifacts_are_persisted_under_the_job_folder` | asserted `outputs/<job_id>/`; now `outputs/<profile_id>/<job_id>/` and additionally asserts the id | The path *is* the feature (ADR 0003); the new claim is stronger, not weaker |
| `test_tailor_service.py` + `test_tailoring_pipeline.py` glob patterns | `outputs/*/source/...` → `outputs/*/*/source/...` | Same reason: one more path segment now exists |

Phase 3 increment 2's exceptions — the first time existing tests were edited **intentionally**,
because removing the editorial-review call is precisely what they pinned:

| Test | Change | Why |
|---|---|---|
| `test_tailoring_pipeline.py:47` | `call_count` 3 → **2** | The review call is gone; this count *is* the increment's headline result |
| `test_tailoring_pipeline.py` saved-content | asserted the **reviewed** summary, now the **draft** one | The draft is the accepted CV; there is no reviewed revision any more |
| 4 explanation tests (`:145-225`) | read `cv_draft` instead of `cv_editorial_review`; fake transcripts reordered | The explanation's source moved with the removed call |
| `:597`, `:765`, `test_tailor_service.py:105` | `cv_attempts` 3 → **2**; token totals 3000/300 → 2000/200 | Same run, one fewer CV call |
| `test_short_letter…`, `test_length_retry…` | dropped the now-nonexistent review response from the fake transcript | The transcript must match the calls the pipeline actually makes |
| `test_profile_serialization.py:101`, `:121` | `call_count` 3 → 2, 4 → 3 | Same removal; the serialization invariant itself is untouched |

Phase 3 increment 1 of the agreed order (targeted layout retry)'s exceptions — four tests
that pinned the *old* retry contract, which is precisely what the increment replaces:

| Test | Change | Why |
|---|---|---|
| `test_tailoring_pipeline.py::test_layout_retry_shortens_the_cv_until_it_fits` | asserted the retry was `offline.last_prompt`; now selects the retry by its marker | The letter is drafted last, so the old assertion was actually inspecting the **letter**; it only passed because the whole context was re-sent to the retry. It now pins the retry itself |
| `test_tailoring_pipeline.py::test_layout_retry_budget_shrinks_with_each_attempt` | selects retries by `LAYOUT RETRY`, not `LAYOUT CORRECTION` | The 650/550 assertions are unchanged; only the marker moved |
| `test_editorial_instructions.py::test_a_layout_retry_also_carries_the_requirements` | inverted — the retry no longer re-sends them; the draft still carries them exactly once | The checks still reach the model; the retry stopped re-sending the context |
| `test_profile_serialization.py::test_a_layout_retry_reuses_the_serialized_profile` | inverted — the profile block is on the draft and letter **only** | Increment 1's invariant was "same bytes every time" *because* the retry re-sent the context; re-sending it is now the regression |

`test_tailor_service.py:114` was not changed: its second clause (`'CURRENT CV:' in ...`) still
holds on the targeted retry.

**Phase 3 item 5 (the validated-generation cache) modified exactly one existing test.** It pins a
run that must now happen on purpose to be a *fresh* run, because the cache would otherwise serve
the identical key:

| Test | Change | Why |
|---|---|---|
| `test_layout_retry.py::test_a_delta_that_breaks_a_profile_rule_is_rejected` | the second `tailor_documents` call passes `use_cache=False` | The test runs the *same* profile against the *same* posting twice, once with an accepted delta and once with a forbidden one. Those two runs share a cache key, so the second was being served from the first's entry and the rejection it asserts never executed. `use_cache=False` restores what the test meant: a fresh draft that must fail the gate. No assertion changed |

That is a genuine finding rather than an inconvenience: it is the first case in the suite where two
runs are deliberately identical, and item 5 is precisely about identical runs no longer being
independent. **No other existing test was modified**, and no assertion was changed.

**Phase 3 increment 3 (structured output) modified no existing test at all.** Every new
assertion lives in `test_structured_output.py`. `tests/support.py`'s `OfflineGemini` gained a
`calls` list recording each call's keyword arguments, because the schema is chosen **per call**
— "was a schema sent here?" is a property of the call, not of the service — and the existing
`prompts` list cannot express it. That is an addition to the double, not a change to any
existing assertion.

Everything else passes unchanged. Rather than edit 32 call sites to thread a `profile_id` they
are not about, `tests/conftest.py` sets `CVTAILOR_PROFILE_ID` and points `CVTAILOR_STORE` at a
throwaway synthetic store once, for the whole suite.

### Phase 3 additions

| File | Tests | Covers |
|---|---|---|
| `test_profile_serialization.py` | 16 | **New in increment 1.** The profile is serialized once per application; the rendered context is **byte-identical** with and without `profile_json` on every country-header branch; the `rules`-excluded facts memo returns the same text without re-serializing, never becomes a profile field, and does not un-ban a banned tool |
| `test_editorial_instructions.py` | 11 | **New in increment 2.** The merged editorial requirements reach the **CV call only** (not the letter), are injected exactly once, and are carried by a layout retry too; the validation gate is unchanged (an invalid draft still fails the run and no letter is drafted from it); the call counts are **2/3/5** on the happy, typical and max-successful paths |
| `test_layout_retry.py` | 15 | **New in Phase 3 increment 1 of the agreed order.** The retry sends the targeted brief and the current CV, with **no** profile, job description or prompt file; the brief reports the document's real body length; a delta response is merged onto the validated CV and **re-gated**, a full-CV response still works, an unknown/unaddressable key raises, a delta cannot write an employer/date/education field or complete an ongoing role, and an unappliable delta fails the run rather than silently keeping the long CV |
| `test_structured_output.py` | 31 | **New in Phase 3 increment 3.** Structured output is **scoped, not global**: the CV draft and the cover letter send `response_mime_type="application/json"` with a per-kind `response_schema`; the layout retry (`allow_delta=True`) and any unknown document kind send **neither**. **The shipped schema is strict since 2026-10-27**: every object requires all its properties with `additionalProperties: false`, `skills` is an array of `{category, items}`, and `tailoring_explanation` is required-but-**nullable** (strict mode forbids an optional property, so null is how "optional" is expressed). Both explanation shapes reach `TailoringExplanation`, an omitted one is still accepted, a truncated constrained response is **rejected** rather than parsed short, `validate_cv` is still the only gate, and the happy/typical paths stay at 2 and 3 calls |
| `test_provider_interface.py` | **49** | **New in Phase 3 item 6, increment A; 10 added 2026-10-26.** The single `generate(prompt, *, schema, max_tokens, model)` contract; `schema=None` reaches **both** providers as "send no constraint", so the layout retry and an unknown kind stay unconstrained while the draft and letter keep theirs; OpenRouter's `response_format` envelope is **translated**, not passed through, and a schema call also sends `provider.require_parameters`; no silent fallback (unknown provider, missing key for the *selected* provider, and provider failure all raise); `ProviderError` is deliberately **not** a `ValueError`, because the correction loop catches `ValueError`; model-per-task routing including the `layout_retry` task; the budget cap refuses a malformed value, stops further calls, and prices a routed model as itself; the 2-call happy path driven through the real pipeline. **Added 2026-10-26:** the provider's own `usage.cost` is carried out as a money figure and needs **no** request parameter; an absent, malformed, null or negative figure degrades to `None` and **never** `0.0`, while a genuine `$0` charge survives as one; Gemini reports no cost and is therefore priced from the table; Gemini's **thinking tokens count as output** (billed as output, excluded from `candidates_token_count`); and a reported cost **replaces** the table in the run total — the guard that matters most, since `calculate_token_usage` previously re-priced the run's totals from the table and silently discarded what the provider actually charged |
| `test_pricing.py` | **22** | **New in item 6, increment B (D-3, D-4); 5 added 2026-10-26.** The long-context tier is applied to the tokens and selected on the input count; the old flat rate would have **halved** the estimate for `gemini-2.5-pro` at 300k tokens; a half-defined long pair is not a tier; the route is part of the price key (Gemini direct $0.75/$3.75 vs OpenRouter $0.825/$4.125); an unpriced route is distinguishable from a priced one and the fallback target always exists; every route records a dated source; the UI carries **no** model-keyed table and prices through `services.pricing`; only `pricing.py` defines the table (parsed with `ast`, not string-matched); the compatibility view in `llm_service` is derived, not a second table. **Added 2026-10-26:** the shipped table is inside its verification window and not stale for either route, so the rule constrains this repository rather than decorating it; a **missing** verification date counts as stale, because "cannot prove it is current" is not "is current"; a date past the window is reported as stale with the date and source named; a fresh table produces no warning; and **every curated model is priced on the OpenRouter route at the rate the table will actually bill** — without a row, `price_for` silently borrows the default route's rate and every unpriced model reports the same invented cost |
| `test_evaluation_suite.py` | **34** | **New in item 6, increment C; 5 added 2026-10-26.** The suite is offline by default and the default cap is the agreed $5; the whole curated run is projected **under** budget; a plan is refused **before** the first call, a missing cap is a refusal rather than "unlimited", and the cap is re-checked before every call rather than only at the start; a live run needs explicit authorisation and an over-budget one spends **nothing**; nothing under `evaluation/` is collected by pytest and CI does not invoke it; cases resolve only inside `tests/fixtures/`, a path that escapes is refused, and the suite never names the private store; the curated set is small, spans three cost tiers cheapest-first, and every entry is **UNMEASURED** with no invented quality claim; recorded rates and structured-output support **match the listing**; cost per **accepted** result is the headline metric and a model that accepts nothing reports `None`, never `0.0`. **Added 2026-10-26:** the suite **bypasses the generation cache**, asserted on the call it actually makes, because a cache hit reports zero usage and would score as an accepted case costing $0.00 — a fabricated best result; the bypass did not cost the run its routing; the set spans at least 5 distinct families; **every entry is created on or after 2025-10-01**; and every entry is priced on the route the run uses |
| `test_generation_cache.py` | 44 | **New in Phase 3 item 5.** The key is the bytes the model was shown: identical inputs give an identical 64-character digest, and each of the 13 ingredients changes it on its own — including `model_cv` and `model_cl` **separately**, because item 6's routing lets two models serve one posting, and the schema digest, because the schema is request metadata and not in either prompt file. A **prompt-file edit is not served from cache** (asserted through the real pipeline: the model is shown the new prompt and a fresh draft is paid for). An identical repeat makes **0** LLM calls and produces byte-identical `content.json`; a hit reports **zero** usage rather than the original run's tokens, while the original figures survive as `original_usage`; a hit still writes a complete job folder with the restored raw responses as `drafts.json`; and a hit uses a new `job_id` rather than overwriting the first application. **Only a validated result is stored**: a failed draft, a CV that never fits, and a failed repeat all store nothing and leave any earlier entry untouched — asserted by counting entries *during* rendering, so a write that happened before the page-count gate would be caught. The store is **always safe to delete**: a deleted cache regenerates, and an empty, malformed, truncated, wrong-format-version, no-longer-validating or wrong-shape entry is a **miss** rather than a failure. `use_cache=False` re-drafts and still stores. The cache lives at `<store>/cache/<profile_id>/`, fails closed without a profile id, cannot be read across candidates, and refuses a key that is not a 64-character lowercase hex digest. Cold-cache call counts stay at **2/3/5**. **Two tests guard the repository boundary** — that a loose `--profile <path>` run (the branch `evaluation/live.py` takes) still caches in the store and leaves the repository root clean; both were verified to **fail** against the first implementation, which put the cache beside the outputs |
| `test_generation_split.py` | **11** | **New in Stage B, 2026-10-30.** `services/generation.py` is a **facade** over six modules, and these pin the properties a behavioural test cannot see. Every public name the old module defined is still reachable from it; every re-export is the **same object** as its home rather than an equal copy, so the two cannot drift; the facade contains nothing but imports, a `logger` and `__all__` (asserted with `ast`, so a helper cannot quietly live there); each module stays under a **420-line ceiling**, because `generation.py` reached 1,465 lines by accumulating five concerns and nothing failed while it did; the **response-schema digests are unchanged** by the split (a cache-key ingredient, ADR 0015); and the prompt files still exist where `prompts.PROMPT_CV_PATH` says. **All 11 fail against `ac1c902`** — verified in a throwaway worktree, not by stashing |

**Two test changes in Stage B, both recorded because a seam moved:**

* `test_layout_retry.py::test_a_merged_cv_still_goes_through_validate_cv` patches
  `services.validation.validate_cv` rather than `generation.validate_cv`. The facade
  re-exports that function, but **rebinding a name in an aliasing module cannot affect
  what `services.pipeline` resolves at call time**, so the old target no longer
  intercepted. **No assertion changed** — the call is still observed, in the module that
  makes it. This was found by running the suite, not by reading the diff.
* `test_renderers_documents.py` gained two tests for D-13. The **failure-path** one is the
  guard: it asserts a failed compile leaves no scratch directory in the deliverable
  folder, and it **fails against the pre-fix code** with `['latex_work']`. The first
  version of this test checked the success path and passed against the unfixed code,
  which is precisely how the defect's real location was found.

`test_profile_serialization.py` was verified to be a real guard: **11 of its 16 tests fail
against the pre-increment-1 code**. `test_editorial_instructions.py` likewise: **9 of its 11
tests fail against the pre-increment-2 code** (checked by stashing `generation.py` and
`tailor_service.py`). `test_layout_retry.py`: **13 of its 15 tests fail against `2a7632d`**,
checked by adding a throwaway `git worktree` at that commit and running the new file there —
no stashing in the working tree. `test_structured_output.py`: **13 of its 27 tests fail against
`85879b5`**, checked the same way, with a throwaway worktree rather than a stash.

**Item 6, checked the same way — a throwaway `git worktree` at `23156b1`, never a stash:**

| File | Result against `23156b1` |
|---|---|
| `test_provider_interface.py` | **39 of 39 fail** — `services.provider` does not exist, so the whole interface is new |
| `test_pricing.py` | **17 of 17 fail** — `services.pricing` does not exist, so there is no single source (D-3/D-4) |
| `test_evaluation_suite.py` | **29 pass, 0 fail — expected, and stated plainly.** The suite and the curated set are new code with no predecessor, so there is no old behaviour to fail against. This file is a guard on the new code's properties (offline by default, cap fails closed, out of CI, unmeasured markers), not a before/after diff |

Both `test_provider_interface.py` and `test_pricing.py` import the new module defensively and
**fail** rather than skip when it is absent, so a broken import in the real tree — the one thing
those files exist to catch — cannot be hidden by a skip. In the real tree both run with **zero
skips**.

**Item 5, checked the same way — a throwaway `git worktree` at `def7fe0`, never a stash:**
`test_generation_cache.py` imports `services.cache_store` defensively and **fails** when it is
absent, so against `def7fe0` the file errors at collection: `services.cache_store could not be
imported`. That is the correct outcome — the module is new — and it is stated plainly rather than
hidden behind a skip. Two mechanical edits are then needed to make the rest of the file runnable
there at all — the import guard, and the three `use_cache` keywords, because that parameter does
not exist at `def7fe0`. With exactly those two neutralised and no assertion relaxed, **39 of the 44
tests fail against `def7fe0`**. The 5 that pass there are named rather than glossed over:
`test_a_model_change_is_not_served_from_cache` and `test_a_profile_change_is_not_served_from_cache`
pass because they assert a *fresh call happens*, which is also what code with no cache does;
`test_a_hit_reports_the_original_explanation`,
`test_a_hit_still_writes_a_complete_job_folder` and
`test_a_hit_uses_a_new_job_folder_and_does_not_overwrite_the_first` pass because a second ordinary
run trivially reproduces the first's documents when there is no cache to differ from.

`tests/test_structured_output.py` needed one seam update in increment A: its monkeypatch target
moved from `llm_service.genai.Client` to `provider.genai.Client`, which is where the request
is now built. **No assertion changed** — the tests still inspect the real
`GenerateContentConfig`, so they remain a check of what is *sent* rather than of how the service
is wired.

### Phase 2 additions

| File | Tests | Covers |
|---|---|---|
| `test_profile_store.py` | 46 | The store layout; fail-closed resolution for missing/blank/malformed/unknown ids; path-traversal rejection; verbatim import; refuse-to-overwrite; listing; `Config` integration |
| `test_profile_isolation.py` | 13 | ADR 0003's five hazards, one test each: separate folders for one posting, A-untouched-when-B-runs, per-candidate snapshots, per-candidate validation, per-candidate mirror paths — plus no cross-contamination in prompts, fail-closed costing no API call, and documents being written into the **store** rather than the repository |
| `test_privacy_boundary.py` | 13 | The real profile, applications and `outputs/` are **not tracked**; they are gitignored; a broad `git add -A` cannot stage them; fixtures stay tracked and contain no real identity; no hardcoded private path in committed code |
| `test_api.py` | 20 | **New 2026-10-26.** `backend/main.py`: fail-closed resolution when no id is given, unknown and malformed ids, an explicit request id beating the configured one, a decoy `storage/profile/profile.yaml` proving the legacy default path is ignored, `job_id` containment, and download isolation between two profiles |

`test_privacy_boundary.py` was verified to **fail** when the real profile is re-tracked, so it
is a real guard rather than a passing formality. `test_api.py` was verified the same way:
**16 of its 20 tests fail against the pre-close-out `main.py`** (checked by stashing the fix).

---

## Sandbox caveat (Windows, DSH)

Under the DSH `workspace-write` sandbox, tests that use pytest's `tmp_path` error with
`PermissionError: [WinError 5]` while pytest sets up or cleans up its temp trees. The
sandbox blocks the ACL operations pytest performs on temp directories.

**This is an environment artifact, not a code failure.** The suite passes when run outside
the sandbox. Do not "fix" the tests for this.

As of Milestone 1.1 this reaches further than before: the sandbox also denied the project
venv write access to anything under `tests/`, which is why fixture JSON files were staged
in a writable directory and copied into place with PowerShell rather than written by the
venv Python. If `tools/build_fixtures.py` fails with `PermissionError` on
`tests/fixtures/...`, that is the same artifact — pass a staging directory
(`.venv\Scripts\python.exe tools\build_fixtures.py .fixture-staging`) and copy the result in.

If you must run confined, point the base temp at the workspace, though the sandbox may
still deny it:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp .runtime/pytest-tmp
```

Leftover `pytest-cache-files-*` and `pytest-of-*` directories in the repo root are sandbox
artifacts and may need an unconfined delete.

---

## How to run

```powershell
# Everything (the baseline)
.venv\Scripts\python.exe -m pytest -q

# Fast lane: no pdflatex, ~5 s
.venv\Scripts\python.exe -m pytest -q -m "not requires_latex"

# Only the characterization suite
.venv\Scripts\python.exe -m pytest -q tests/test_profile_loading.py tests/test_tailoring_pipeline.py

# Only the CLI
.venv\Scripts\python.exe -m pytest -q tests/test_cli.py

# Configuration behaviour
.venv\Scripts\python.exe -m pytest -q tests/test_config.py

# Multi-profile: the store and its fail-closed rule (~0.4 s)
.venv\Scripts\python.exe -m pytest -q tests/test_profile_store.py

# Multi-profile: candidate isolation (~1 s)
.venv\Scripts\python.exe -m pytest -q tests/test_profile_isolation.py

# The public/private data boundary
.venv\Scripts\python.exe -m pytest -q tests/test_privacy_boundary.py

# The FastAPI adapter: fail-closed resolution and job_id containment (~2 s)
.venv\Scripts\python.exe -m pytest -q tests/test_api.py

# Only document output
.venv\Scripts\python.exe -m pytest -q tests/test_renderers_documents.py tests/test_render_application_determinism.py

# One workflow, verbosely
.venv\Scripts\python.exe -m pytest tests/test_tailoring_pipeline.py -q -k "retry or letter"

# Item 6: the provider interface, routing and budget caps
.venv\Scripts\python.exe -m pytest -q tests/test_provider_interface.py

# Item 6: route- and tier-aware pricing (D-3, D-4)
.venv\Scripts\python.exe -m pytest -q tests/test_pricing.py

# Item 6: the evaluation suite and the curated model set (offline)
.venv\Scripts\python.exe -m pytest -q tests/test_evaluation_suite.py

# Item 5: the validated-generation cache (~2 s, offline)
.venv\Scripts\python.exe -m pytest -q tests/test_generation_cache.py
```

### The generation cache — where it lives, and how to clear it

A **validated** generation is stored under `<store>/cache/<profile_id>/generations/<key>.json`,
keyed by a digest of the bytes the model was shown (profile, posting, company/role/country, both
prompt files, the schema, the provider and both routed models). An identical request is served from
disk and makes **zero** LLM calls. See
[ADR 0015](DECISIONS/0015-generation-cache.md).

It is **derived data and always safe to delete** — losing it costs a regeneration, never a
document:

```powershell
# Clear one candidate's cached generations
Remove-Item -Recurse -Force "$env:CVTAILOR_STORE\cache\<profile-id>"

# Or clear every candidate's
Remove-Item -Recurse -Force "$env:CVTAILOR_STORE\cache"

# Or ignore the cache for one run. The fresh result is still stored.
.venv\Scripts\python.exe cvtailor.py generate --profile-id <id> --job-file posting.txt --no-cache
```

`<store>` defaults to `./storage`; on this machine it is `D:\coding\cv-tailor-data`.
**There is no eviction policy** — the directory grows by one small JSON file per distinct
generation — so clearing it by hand is the documented mechanism rather than a fallback.

### The live evaluation suite — opt-in, budget-capped, **never in CI**

`tests/test_evaluation_suite.py` tests the suite *offline*. The suite itself lives in
`evaluation/` and is **not collected by pytest** — nothing there is named `test_*` — so CI
cannot make a paid call through it, which a test asserts.

```powershell
# Default: prices the run and stops. Makes no API call.
.venv\Scripts\python.exe -m evaluation

# Show the set and its verification status
.venv\Scripts\python.exe -m evaluation --list-models

# **Clear the sandbox first**, or an earlier run's artefacts are reused.
Remove-Item -Recurse -Force .tmp\evaluation-store

# A live run. Paid: needs an agreed budget (ADR 0005) and OPENROUTER_API_KEY in .env.
.venv\Scripts\python.exe -m evaluation --live --cap-usd 5
```

The suite now compares **the single selected model**, so a run is a re-measurement rather
than a comparison. To compare candidates again, add them to `CURATED_MODELS` with an
input profile each — `evaluation/candidate_inputs.py` documents the per-family
adaptations a new candidate is likely to need, and `has_cost_spread` is the check that a
re-added set is a meaningful comparison rather than near-identical prices.

A plan whose projection exceeds `--cap-usd` is refused **before** the first call, and the
cap is re-checked before every call.

**The dry run is the screen a spend is approved from, so it also reports price
staleness.** `PRICE_MAX_AGE_DAYS` is 62 (the owner's "re-verify if older than 2 months"
rule) and `pricing.staleness_message` names the date and the source when the table is
due. The guard **fails towards stale**: a missing or unparseable verification date
counts as stale, because "cannot prove it is current" is not "is current".

**What the run does and does not measure**, stated because it bounds what any result may
claim:

| Measured | Not measured |
|---|---|
| Whether each model returned a validated document (the factual gate) | **Writing quality** — no model judges prose; the owner reads the accepted documents |
| Cost per **accepted** result, from OpenRouter's own reported charge | **Layout and PDF quality** — the pipeline renders real LaTeX and the page-count gate runs, but `evaluation/` records `cv_page_count` and nothing else about rendering |
| Calls per case, and correction calls beyond the minimum | Anything about a posting or profile outside `tests/fixtures/` |

Two tests guard the paid path's safety: the suite **bypasses the generation cache**
(`use_cache=False`, asserted on the call the suite makes, because a hit reports zero
usage and would score as an accepted run costing $0.00), and **every curated id has a
price row on the OpenRouter route** (without one, `price_for` silently borrows the
default route's rate and every model reports the same invented cost).

**Per-candidate inputs (ADR 0016).** Three provider families demand mutually
incompatible response schemas — OpenAI requires `additionalProperties: false`, Anthropic
behind Vertex rejects a schema with more than 24 optional parameters, and Gemini rejects
that keyword outright — so each candidate is asked in a dialect its providers accept, and
`evaluation/candidate_inputs.py` records which and why. The **acceptance bar does not
vary**: the same profiles, postings, validation rules and word-count gate for every
candidate. `tests/test_evaluation_inputs.py` asserts both halves — each dialect's hard
constraint structurally, and that no per-candidate success rule exists.

### The study ran on 2026-10-26

**$0.6637 was spent in total for the session**, from OpenRouter's own accounting, against
the owner's $5 cap. All eight candidates ran three cases each. Ranked by cost per
**accepted** result:

| model | accepted | cost / accepted |
|---|---|---|
| **`openai/gpt-6-luna`** | **3/3** | **$0.00271** |
| `deepseek/deepseek-v4-flash` | 2/3 | $0.00328 |
| `anthropic/claude-haiku-5.5` | 3/3 | $0.00582 |
| `google/gemini-3.8-flash` | 3/3 | $0.11384 |
| `anthropic/claude-sonnet-5` | 3/3 | $0.15709 |
| `qwen/qwen3.8-flash` | 0/3 | none accepted |
| `z-ai/glm-5.3-flash` | 0/3 | none accepted |
| `mistralai/mistral-small-2603` | 0/3 | none accepted |

**The `measured` marker is deliberately NOT set.** The results are recorded, but the
owner stated that writing, PDF and layout quality are theirs to judge before a ranking is
final — and this suite measures none of those three. `tests/test_evaluation_suite.py`
asserts precisely that: results are present, the marker is not, and a candidate that
accepted nothing carries **no** cost per accepted result rather than a flattering zero.

**To re-measure**, clear the sandbox first so no earlier run's artefacts are reused:

```powershell
Remove-Item -Recurse -Force .tmp\evaluation-store
.venv\Scripts\python.exe -m evaluation --live --cap-usd 5
```

The accepted documents then land in `.tmp/evaluation-store/outputs/`, one job folder per
accepted run, each with its PDFs and a `generation_result.json` manifest.

Tests needing a TeX compiler carry the `requires_latex` marker and **skip automatically**
when no `pdflatex` can be resolved, so the suite still runs green on a machine without TeX.
`-m "not requires_latex"` deselects them for a ~6 s fast lane.

---

## What is tested now

| File | Tests | Covers |
|---|---|---|
| `test_profile_loading.py` | 14 | Profile loading and validation: happy path, path forms, default-path resolution, missing file, `extra="forbid"`, missing required fields, malformed and unparseable YAML, empty file, the documented unvalidated-date gaps |
| `test_tailoring_pipeline.py` | 84 | CV tailoring, cover-letter generation, LLM response parsing, factual validation, retry handling, error handling, token accounting, cross-profile isolation, **profile-scoped rules (A-1)**, shared helper behaviour (D-12), pricing-table invariants (D-5) |
| `test_renderers_documents.py` | 34 | **Real** LaTeX CV and DOCX cover letters: page geometry, required sections, verbatim bullets, clipping, orphan headings, LaTeX escaping, word counts, page-count gate |
| `test_render_application_determinism.py` | 11 | `scripts/render_application.py` end to end as a subprocess: identical content → identical page count *and* identical text, in-place stability, manifest handling, residue cleanup, failure paths |
| `test_cli.py` | 22 | **New in Phase 1.** Guided default, exit codes, `doctor` (including its refusal to verify the key unless asked), `profile show`, and every `render`/`generate` failure path — plus two LaTeX-gated tests: one rendering without an API key, one asserting the CLI's page count equals the existing script's |
| `test_config.py` | 13 | **New in Phase 1.** Defaults with an empty environment, call-time (not import-time) reads, relative vs absolute `OUTPUTS_DIR`, the placeholder-key case, immutability, override typos failing loudly, and a guard that importing the backend performs no environment read |
| `test_profile_store.py` | 46 | **New in Phase 2.** The store, and the fail-closed rule in ADR 0003 |
| `test_profile_isolation.py` | 13 | **New in Phase 2.** Two candidates cannot contaminate each other; documents land in the store |
| `test_privacy_boundary.py` | 13 | **New in Phase 2.** Real data stays out of the public repository |
| `test_api.py` | 20 | **New 2026-10-26.** The FastAPI adapter resolves like the CLI and fails closed |
| `test_profile_serialization.py` | 16 | **New in Phase 3 increment 1.** One serialization per application; byte-identical prompts; the rules-excluded facts memo |
| `test_editorial_instructions.py` | 11 | **New in Phase 3 increment 2.** The merged editorial requirements reach the CV call only; the gate is unchanged; call counts are 2/3/5 |
| `test_layout_retry.py` | 15 | **New in Phase 3 increment 1 of the agreed order.** The targeted retry, the delta merge, and the fact that a delta cannot bypass the gate |
| `test_generation_cache.py` | 44 | **New in Phase 3 item 5.** The cache key is the bytes the model was shown and no two different inputs share it; only a validated result is stored; a prompt, model, provider, country or profile change is a miss; a hit costs 0 calls and returns byte-identical documents with no reported cost; and the store is derived data, so deletion and corruption both degrade to regenerating |
| `test_tailor_service.py` | 9 | *(pre-existing)* layout retry, fenced JSON, 3-page rejection, short-letter correction, country context, invented tools/dates, sign-off in body, Streamlit selector |
| `test_docx_renderer.py` | 1 | *(pre-existing)* XML-sensitive text preserved in the DOCX |
| `test_portability.py` | 2 | *(pre-existing)* pdflatex discovery and `LATEX_COMPILER` override |

Supporting files: `tests/support.py` (fixture loading, the offline LLM double, PDF/DOCX text
extraction) and `tests/conftest.py` (shared fixtures).

### Workflow coverage (ASSESSMENT.md §1)

Every workflow named in the assessment's functional inventory now has at least one
behavioural test:

| # | Workflow | Covered by |
|---|---|---|
| 1 | Profile loading | `test_profile_loading.py` |
| 2 | Profile validation | `test_profile_loading.py` (valid + 4 rejection paths) |
| 3 | Job-description handling | `test_tailoring_pipeline.py` (empty/whitespace rejection, context propagation) |
| 4 | CV tailoring | `test_tailoring_pipeline.py`, `test_renderers_documents.py` |
| 5 | Cover-letter generation | `test_tailoring_pipeline.py`, `test_renderers_documents.py` |
| 6 | LLM response parsing | `test_tailoring_pipeline.py` (fenced, wrapped, truncated, empty, non-document) |
| 7 | Factual validation | `test_tailoring_pipeline.py` (12 targeted rejection tests) |
| 8 | Retry handling | `test_tailoring_pipeline.py` (layout, correction, capped validation retries) |
| 9 | Error handling | `test_tailoring_pipeline.py` (failed manifest, preserved drafts, no mirroring) |
| 10 | PDF generation | `test_renderers_documents.py` (real LaTeX) |
| 11 | DOCX generation | `test_renderers_documents.py` (real DOCX) |
| 12 | Page-count enforcement | `test_renderers_documents.py`, `test_render_application_determinism.py` |
| 13 | Word-count enforcement | `test_tailoring_pipeline.py`, `test_renderers_documents.py` |
| 14 | Application persistence | `test_tailoring_pipeline.py` (job folder, `content.json`, drafts, manifest) |
| 15 | Saved-application restoration | `test_render_application_determinism.py`, `test_cli.py` (CLI render parity) |
| 16 | Configuration (new in Phase 1) | `test_config.py` |
| 17 | Candidate-scoped validation rules (new in Phase 1) | `test_tailoring_pipeline.py` (7 A-1 tests) |
| 18 | Command-line interface (new in Phase 1) | `test_cli.py` |
| 19 | Profile resolution and the store (new in Phase 2) | `test_profile_store.py` |
| 20 | Cross-profile isolation (new in Phase 2) | `test_profile_isolation.py` |
| 21 | Public/private data boundary (new in Phase 2) | `test_privacy_boundary.py` |
| 22 | HTTP API resolution and downloads (new 2026-10-26) | `test_api.py` |

### Isolation test caveat

`test_profile_isolation.py` needs a genuine `profile_id`↔profile match, so it passes the
candidate explicitly rather than relying on the suite-wide default. The suite-wide default in
`conftest.py` is a convenience for tests that are *not* about identity; the isolation tests
never depend on it, and `test_profile_store.py` removes it entirely so its fail-closed
assertions cannot pass for the wrong reason.

---

## Fixtures

`tests/fixtures/` holds **synthetic-only** data; see its
[README](../tests/fixtures/README.md). Verified free of real personal data.

| Path | Contents |
|---|---|
| `profiles/synthetic_analyst.yaml` | Profile A — includes an employer with no bullets, selected projects, certifications and a visa status. Declares **no** `rules` block, so it exercises the built-in defaults |
| `profiles/synthetic_marketer.yaml` | Profile B — deliberately different shape: no projects, no visa, no certifications, **and its own `rules` block** (different banned tools, no visa label) so A-1 isolation is tested against genuinely divergent candidates |
| `profiles/invalid/*.yaml` | Four rejection fixtures (unknown key, missing identity, malformed, unparseable) |
| `job_descriptions/*.txt` | Three anonymised postings (Berlin / Amsterdam / Dublin) |
| `llm_responses/<session>/*.json` | Recorded provider responses + a `responses.json` manifest; one step is Markdown-fenced |
| `content/valid_content.json` | A `content.json` accepted by both renderers |
| `content/invalid_content.json` | A deliberately malformed `content.json` |

Regenerate the derived fixtures (cover letters are word-count checked against the real
validators before being written):

```powershell
.venv\Scripts\python.exe tools\build_fixtures.py            # writes in place
.venv\Scripts\python.exe tools\build_fixtures.py .staging   # when the sandbox blocks tests/
```

---

## What is NOT tested yet

- ~~**`backend/main.py` endpoints** — zero API tests, including the `job_id` containment
  question (§6).~~ **Closed 2026-10-26** by `test_api.py`: `job_id` containment is now asserted
  (traversal rejected with a 400 rather than resolved), and downloads are shown to be isolated
  between two profiles. `/api/tailor`'s *success* path still needs a paid call, so — like
  `cvtailor generate` — only its resolution and failure paths are covered; the pipeline beneath
  it is covered offline by `test_tailoring_pipeline.py`.
- **`DocxRenderer` in-place mutation** (A-7) — `docx_renderer.py:304-307` mutates
  `cl.paragraphs`. The bug is still real and unfixed; there is no test pinning it.
- **Cost/token accounting correctness** (D-3) — `calculate_token_usage` totals are asserted
  through `tailor_documents`, but the flat-rate pricing error itself is not caught. The
  offline double replaces the real calculator. *(The pricing table's contents and its fallback
  invariant are now tested; the flat-rate arithmetic is not.)*
- **`--mirror-configured` end to end** — mirroring is asserted for the *failure* case (nothing
  is published). The success path was verified manually during Phase 1 but has no test.
- **The CLI's `generate` success path** — it needs a paid API call, so only the failure paths
  (no key, short posting, missing file) are covered. The orchestration underneath is covered by
  `test_tailoring_pipeline.py`.
- **CLI page-count parity for a 2-page CV** — the parity test uses the fixture `content.json`,
  which renders to one page. A 2-page case would exercise more of the render path.
- **Live LLM quality** — deliberately out of scope; see the layers table below.
- **Performance harness** (call count, tokens, wall time) — Milestone 1.1 did not add one.
  The recorded-response suite does assert call counts per scenario, which covers the
  simplest part of it.

---

## Test layers

| Layer | Runs in CI | Calls a paid API |
|---|---|---|
| Unit / characterization | Yes | No |
| Integration (fixtures, offline) | Yes | No |
| CLI smoke tests (`test_cli.py`) | Yes | No |
| Document output validation | Yes (skips without LaTeX) | No |
| **LLM quality evaluation** | **No — opt-in** | **Yes, budget-capped** |

`cvtailor generate` is the only tested entry point whose *success* path needs a paid call, so
its tests cover only the failure paths; the pipeline beneath it is covered offline through
recorded responses. `cvtailor doctor` verifies the API key against Google only with
`--verify-key`; the default run never touches the network, and a test asserts that.

Keep deterministic software testing and LLM quality evaluation strictly separate. CI
(`.github/workflows/tests.yml`) must never require a paid API call.

---

## Reference measurements (2026-10-23)

| Metric | Value |
|---|---|
| `python -m pytest -q` (before M1.1) | 12 passed, 2.45 s |
| `python -m pytest -q` (after M1.1) | 141 passed, ~100 s |
| `python -m pytest -q` (**after Phase 1**) | **190 passed**, ~110 s |
| `python -m pytest -q` (**after Phase 2**) | **262 passed**, ~106 s |
| `python -m pytest -q` (after the 2026-10-26 close-out) | 282 passed, ~114 s |
| `python -m pytest -q` (after Phase 3 increment 1) | 298 passed, ~112 s |
| `python -m pytest -q` (after Phase 3 increment 2) | 309 passed, ~107 s |
| `python -m pytest -q` (after Phase 3 increment 1 of the agreed order) | 324 passed, ~107 s |
| `python -m pytest -q` (**after Phase 3 increment 3** — structured output) | **351 passed**, ~108 s |
| `python -m pytest -q` (after Phase 3 item 6, increment A — provider interface) | 390 passed, ~113 s |
| `python -m pytest -q` (after Phase 3 item 6, increment B — D-3/D-4 pricing) | 407 passed, ~112 s |
| `python -m pytest -q` (**after Phase 3 item 6, increment C** — evaluation suite, curation) | **436 passed**, ~114 s |
| `python -m pytest -q` (**after Phase 3 item 5** — validated-generation cache) | **480 passed**, ~116 s |
| `python -m pytest -q` (**after the cache-bypass fix and the cost/curation increment, 2026-10-26**) | **500 passed**, ~116 s |
| Fast lane `-m "not requires_latex"` (current) | **470 passed**, 30 deselected, ~13 s |
| `test_generation_cache.py` | 44 passed, ~2 s (no LaTeX, no network) |
| `test_api.py` | 20 passed, ~2 s (no LaTeX, no network) |
| `test_renderers_documents.py` | 34 passed, ~20 s |
| `test_render_application_determinism.py` | 11 passed, ~73 s |
| `test_cli.py` | 22 passed (20 offline in ~2 s, 2 LaTeX-gated in ~14 s) |
| Backend `import main` | ≈ 1.7–2.0 s |
| `load_profile()` | 169 ms |
| pdflatex per run | ≈ 2.9 s (run twice per compile) |
| LLM calls: min / typical / max-successful / worst | **2 / 3 / 5 / 12** (was 3 / 4 / 6 / 18 before increment 2; **unchanged** by the targeted layout retry, by structured output, by all three of item 6's increments, by item 5 on a **cold** cache, and by the cost/curation increment — which changes what a call is *charged*, not how many are made) |
| LLM calls on a **cache hit** | **0** — item 5. An identical profile + posting + prompt set + schema + provider + models + rules is served from `<store>/cache/<profile_id>/`. The evaluation suite opts **out** of this, so a live run always measures the model |
| Evaluation suite | **run**, 2026-10-26/27 — eight candidates compared and the winner selected. Total spend for the whole effort **$1.91** of the owner's **$5** cap. Live runs verified end to end at **$0.0026** (synthetic) and **$0.0032** (owner's real profile) per application |
| Cost per application (`gemini-3.8-flash`, priced from the table) | **$0.016 / $0.026 / $0.048** (was $0.027 / $0.038 / $0.060). An OpenRouter run reports the provider's own `usage.cost` instead of this estimate |
