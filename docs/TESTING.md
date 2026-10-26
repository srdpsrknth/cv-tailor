# Testing

**Baseline command:** `python -m pytest -q` (run from the repository root)
**Current baseline:** **324 passed**, 1 warning, ~108 s, fully offline — no paid API calls.
**Fast lane:** `python -m pytest -q -m "not requires_latex"` → **294 passed**, 30 deselected, ~6 s.

| | |
|---|---|
| Baseline before Milestone 1.1 | 12 passed, ~2.5 s |
| Baseline after Milestone 1.1 | 141 passed, ~100 s |
| Baseline after Phase 1 | 190 passed, ~110 s |
| Baseline after Phase 2 | 262 passed, ~106 s |
| Baseline after the Phase 2 close-out | 282 passed, ~114 s |
| Baseline after Phase 3 increment 1 | 298 passed, ~112 s |
| Baseline after Phase 3 increment 2 | 309 passed, ~107 s |
| **Baseline after Phase 3 increment 1 of the agreed order (targeted layout retry)** | **324 passed**, ~108 s |
| Paid API calls | **none** — verified with `GEMINI_API_KEY` unset |
| Requires | `pypdf`, `python-docx`; `pdflatex` for the document-level tests (they skip without it) |

The suite grew 12 → 141 in Milestone 1.1, 141 → 190 in Phase 1, 190 → 262 in Phase 2,
262 → 282 in the 2026-10-26 close-out, 282 → 298 in Phase 3 increment 1 (all new files),
298 → 309 in increment 2, and 309 → **324** in Phase 3 increment 1 of the agreed order
(targeted layout retry). The runtime increase is almost entirely `pdflatex`: real rendering
is exercised instead of mocked.

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

Everything else passes unchanged. Rather than edit 32 call sites to thread a `profile_id` they
are not about, `tests/conftest.py` sets `CVTAILOR_PROFILE_ID` and points `CVTAILOR_STORE` at a
throwaway synthetic store once, for the whole suite.

### Phase 3 additions

| File | Tests | Covers |
|---|---|---|
| `test_profile_serialization.py` | 16 | **New in increment 1.** The profile is serialized once per application; the rendered context is **byte-identical** with and without `profile_json` on every country-header branch; the `rules`-excluded facts memo returns the same text without re-serializing, never becomes a profile field, and does not un-ban a banned tool |
| `test_editorial_instructions.py` | 11 | **New in increment 2.** The merged editorial requirements reach the **CV call only** (not the letter), are injected exactly once, and are carried by a layout retry too; the validation gate is unchanged (an invalid draft still fails the run and no letter is drafted from it); the call counts are **2/3/5** on the happy, typical and max-successful paths |
| `test_layout_retry.py` | 15 | **New in Phase 3 increment 1 of the agreed order.** The retry sends the targeted brief and the current CV, with **no** profile, job description or prompt file; the brief reports the document's real body length; a delta response is merged onto the validated CV and **re-gated**, a full-CV response still works, an unknown/unaddressable key raises, a delta cannot write an employer/date/education field or complete an ongoing role, and an unappliable delta fails the run rather than silently keeping the long CV |

`test_profile_serialization.py` was verified to be a real guard: **11 of its 16 tests fail
against the pre-increment-1 code**. `test_editorial_instructions.py` likewise: **9 of its 11
tests fail against the pre-increment-2 code** (checked by stashing `generation.py` and
`tailor_service.py`). `test_layout_retry.py`: **13 of its 15 tests fail against `2a7632d`**,
checked by adding a throwaway `git worktree` at that commit and running the new file there —
no stashing in the working tree.

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
```

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
| `python -m pytest -q` (**after Phase 3 increment 2**) | **309 passed**, ~107 s |
| Fast lane `-m "not requires_latex"` | **279 passed**, 30 deselected, ~6 s |
| `test_api.py` | 20 passed, ~2 s (no LaTeX, no network) |
| `test_renderers_documents.py` | 34 passed, ~20 s |
| `test_render_application_determinism.py` | 11 passed, ~73 s |
| `test_cli.py` | 22 passed (20 offline in ~2 s, 2 LaTeX-gated in ~14 s) |
| Backend `import main` | ≈ 1.7–2.0 s |
| `load_profile()` | 169 ms |
| pdflatex per run | ≈ 2.9 s (run twice per compile) |
| LLM calls: min / typical / max-successful / worst | **2 / 3 / 5 / 12** (was 3 / 4 / 6 / 18 before increment 2) |
| Cost per application (`gemini-3.8-flash`) | **$0.016 / $0.026 / $0.048** (was $0.027 / $0.038 / $0.060) |
