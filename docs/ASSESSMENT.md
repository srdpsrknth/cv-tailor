# CV Tailor — Architecture Assessment (Phase 0)

**Date:** 2026-10-23
**Branch:** `refactor/architecture-v2` (worktree `cv-tailor-next`)
**Base commit assessed:** `1416177` — *Improve application tailoring and add portable Mac setup workflow*
**Status:** Assessment complete. **Decisions approved 2026-10-23** (§11). Phase 1 implemented
and complete; this document is retained as the Phase 0 record of what was found.

> This document describes the system **as implemented today**, verified against source.
> Findings are labelled **VERIFIED** (read or executed) or **HYPOTHESIS** (reasoned, not proven).
>
> **Status note (2026-10-23, after Phase 1):** this assessment describes the system as it was
> at `1416177`. Phase 1 resolved several items below; each affected row is annotated in place
> rather than deleted, so the record of what was found stays intact. Resolved in Phase 1:
> **A-1** (rules are now profile-scoped), **A-3** (`tailor_documents` split),
> **A-5** (single `Config`, no import-time reads), **A-9** (partially: see the row), and
> **D-1, D-2, D-5, D-6, D-7, D-12**. See [`PROJECT_STATE.md`](PROJECT_STATE.md) §"Resolved in
> Phase 1" and [`ROADMAP.md`](ROADMAP.md) §Phase 1 for the evidence.
>
> **Status note (2026-10-24, after Phase 2):** Phase 2 added profile identity and implemented
> the privacy split. Newly resolved: **A-9** (the candidate segment is now in the output path),
> **D-9** (generated documents are untracked) and the committed-data half of §6. Still open
> after Phase 2: **A-6** (dates), **A-7** (renderer mutation), **A-8** (custom render scripts),
> **A-10** (`--mirror-configured`), **D-4**, **D-8**, **D-10**, **D-11**, **D-13**, **D-14**.
> **§6's recommendation is implemented but its history warning is not resolved**: the data
> already committed remains in the public repository's history.
>
> **Status note (2026-10-26, Phase 2 close-out):** a clean-up pass over the stale/new-system
> inconsistencies. **`backend/main.py` is now multi-profile aware and tested** — it no longer
> resolves a profile by default, which was the last single-profile path in the codebase (see
> blocker 7 in [`PROJECT_STATE.md`](PROJECT_STATE.md), now closed). Newly resolved: **D-8**
> re-confirmed, **D-9** re-verified as already done, **D-10** and **D-11** decided by the owner
> (both recorded in §3). Removed as dead code: `backend/validate_profile.py` and two
> self-referential `Config` path aliases. The suite is **282 passed**. Still open: **A-6**,
> **A-7**, **A-8**, **A-10**, **D-3**, **D-4**, **D-13**, **D-14**, **D-15**.
>
> **Status note (2026-10-26, Phase 3 increment 1):** §5's optimisation **4 — "Serialize the
> profile once per application rather than per call" — is implemented**. The prompt bytes sent
> to the model are unchanged (it is a de-duplication of work, not a prompt change), so the
> token figures in the §5 table are unchanged too; what fell is the *CPU* cost of building
> them. Optimisations 1, 2, 3 and 5 remain open and are deliberately kept separate, because
> each changes the call-count baseline the others are verified against. The suite is
> **298 passed**.
>
> **Status note (2026-10-26, Phase 3 increment 2):** §5's optimisation **2 — "Remove or merge
> the editorial-review pass" — is implemented**. The requirements were folded into the draft
> prompt and the second CV call was deleted, so the *prompt* did change this time and the §5
> tables below are updated to the measured values. Call counts are **2 / 3 / 5**; the happy
> path sends **41% fewer input tokens**. Optimisations 1, 3 and 5 remain open, and 1 is now
> the largest remaining source of repeated input. The suite is **309 passed**.
>
> **Status note (2026-10-26, Phase 3 increment 1 of the agreed order):** §5's optimisation
> **1 — "Targeted layout retry instead of full regeneration" — is implemented**. The retry
> sends a targeted brief and the current CV instead of the whole context, and accepts a delta
> merged onto the validated CV; retry input fell 3,488 → **740** tokens on the recorded
> fixture and the whole typical run fell **33%**. Call counts are **unchanged at 2 / 3 / 5**
> — this lowers tokens per retry, not the number of retries. Because the CV call's input is
> now lower but the draft call is untouched, the §5 cost rows for the typical and
> max-successful cases are **upper bounds**, as the note under that table says. Optimisation
> **3 — structured output — is now the top opportunity and the next increment**; 5 stays
> deferred until 1–4 have settled. The suite is **324 passed**.
>
> **Status note (2026-10-26, Phase 3 increment 3):** §5's optimisation **3 — "Enable
> structured output" — is implemented, scoped per call**. JSON mode and a `response_schema`
> now go on the CV draft and the cover letter; the **layout retry is deliberately left
> unconstrained**, because since increment 1 its response may be a delta, which a schema
> requiring `cv` cannot express. The schema constrains the response *envelope* and leaves the
> document body open — no `required` inside it, no `additionalProperties: false` anywhere —
> which is what keeps the premature truncation that D-1 records from returning. See
> [ADR 0012](DECISIONS/0012-structured-output-scope.md). **Call counts are unchanged at
> 2 / 3 / 5**; the schema is request metadata, not prompt content, so no prompt byte changed
> and the §5 token and cost figures are unchanged. Truncation on **real** documents was not
> observed either way — that needs a budgeted live run. **Phase 3 item 6 built the suite that
> would answer it** (offline by default, projected at $1.68 against a $5 cap) and preserved the
> per-call contract that makes the answer meaningful, but **the live run has still not been
> made**. The suite is **436 passed** (351 after increment 3 alone).
>
> **Status note (2026-10-26, Phase 3 item 5):** §5's optimisation **5 — "Cache validated
> results" — is implemented, and that closes the list.** The generation cache stores a
> **validated** result under `<store>/cache/<profile_id>/` and serves an identical request from
> disk: **0 LLM calls** and byte-identical accepted documents. Its key is a digest of the bytes
> the model was shown — the serialized profile, the posting plus company/role/country, both
> prompt files read and hashed per call, the schema, the provider and both routed models — so a
> prompt, model, provider, country or profile change is a **miss** rather than a stale document.
> Only a validated result is ever stored, the store is derived data whose deletion is always
> safe, and a stored document is re-validated on read because the cache is an editable file on
> disk. See [ADR 0015](DECISIONS/0015-generation-cache.md). **Call counts on a cold cache are
> unchanged at 2 / 3 / 5, worst 12** — the item adds a lookup and a write, not a request. The
> suite is **480 passed**.
>
> **Owner requirement recorded 2026-10-26 (scopes Phase 3 item 6).** OpenRouter exposes a very
> large catalogue of models. **The tool must not surface all of them.** Phase 3 item 6 must
> research and select a **small curated set** — the model(s) genuinely best suited to CV and
> cover-letter generation on **price against content quality** — and offer users a **mix of
> options spanning different performance and cost levels**, so the choice is theirs. This is a
> selection-and-research deliverable, not a passthrough of the catalogue. See
> [`ROADMAP.md`](ROADMAP.md) §Phase 3 and [`PROJECT_STATE.md`](PROJECT_STATE.md) §"Phase 3,
> item 6".

---

## 1. What CV Tailor currently does

A local, single-user tool that turns a pasted job description into a tailored CV PDF and a
cover letter (DOCX + PDF), grounded in one authoritative YAML profile.

**Verified end-to-end workflow**

> **Superseded by Phase 2 (2026-10-24) and Phase 2 close-out (2026-10-26).** The diagram below is
> the *pre-Phase-2* flow, kept as the Phase 0 record. The profile is no longer read from
> `storage/profile/profile.yaml`: it is resolved by `profile_id` through `ProfileStore`
> (ADR 0003, ADR 0011), and outputs are written to `<store>/outputs/<profile_id>/<job_id>/`.
> As of 2026-10-26 the FastAPI adapter resolves the same way — it no longer calls
> `load_profile()` with no argument.

```
storage/profile/profile.yaml
        │  load_profile()                      backend/services/profile_loader.py:11
        ▼
   Profile (Pydantic)                          backend/models/profile.py:73
        │  + job_description + company/role/work_country
        ▼
tailor_documents()                             backend/services/tailor_service.py:109
   ├─ CV draft (editorial requirements folded in)  LLM call 1 ─┐
   ├─ Cover letter                                 LLM call 2  ├─ LLMService._call_provider()
   └─ Layout retry loop (≤4) ──────────────────────────────────┘  backend/services/llm_service.py:124
        │  validate: _validate_cv / _validate_cover_letter
        ▼
   Render: LaTeXRenderer.render_cv()  → CV PDF   backend/renderers/latex_renderer.py:67
           DocxRenderer.render_cover_letter() → DOCX + PDF
                                                  backend/renderers/docx_renderer.py:48
        │  page-count gate: CV ≤2, letter ==1
        ▼
   outputs/<job_id>/  (finals) + source/ (content.json, drafts, snapshots)
        │  optional mirror to $OUTPUTS_DIR
        ▼
   FastAPI download endpoints                  backend/main.py:60,83,106
        │
        ▼
   Streamlit UI                                ui/app.py
```

**Interfaces**
- `backend/main.py` — FastAPI, 4 endpoints (`/health`, `/api/tailor`, 3 downloads). **As of
  2026-10-26** `/api/tailor` and the download routes take an explicit `profile_id` and resolve
  through the store, failing closed (ADR 0003). Tested by `tests/test_api.py`.
- `ui/app.py` — Streamlit, single-page form; calls the API over HTTP.
- `scripts/render_application.py` — re-renders saved `content.json` **without** an LLM call.
- `.agents/skills/cv-tailor-application/SKILL.md` — agent workflow for manual applications.

### Functional inventory

| Capability | State | Evidence |
|---|---|---|
| Profile load + validate | **Works** | `profile_loader.py`; `extra="forbid"` rejects unknown keys (verified) |
| CV tailoring + factual validation | **Works** | `_validate_cv` `tailor_service.py:61` |
| Cover letter + word/paragraph gate | **Works** | `_validate_cover_letter` `tailor_service.py:95` |
| LaTeX CV → PDF, ≤2-page enforcement | **Works** | `latex_renderer.py`; gate `tailor_service.py:221-246` |
| DOCX cover letter + PDF | **Works** | `docx_renderer.py:48` |
| Deterministic re-render from JSON | **Works** | `scripts/render_application.py` |
| Token/cost accounting | **Works, partly wrong** | `calculate_token_usage` — see §3 D-3 |
| Saved application archive | **Works, ad-hoc** | 8 dirs in `applications/`, inconsistent schemas |
| Streamlit UI | **Works, thin** | `ui/app.py` — one form, no history/browse |
| Multi-profile | **Works** *(Phase 2)* | `ProfileStore` keyed by `profile_id`, fail-closed (ADR 0003); CLI and API both resolve through it |
| Job discovery / matching | **Absent** | — |
| Application tracking | **Absent** | — |
| CLI | **Works** *(Phase 1)* | `cvtailor` — `doctor`, `profile show`, `generate`, `render` |
| Provider abstraction | **Absent** | Gemini hardwired `tailor_service.py:119` |
| Structured output (JSON mode) | **Live, scoped per call** | `generation.RESPONSE_SCHEMAS` selects the schema; the draft and the letter are constrained, the layout retry is not (its response may be a delta) — [ADR 0012](DECISIONS/0012-structured-output-scope.md) |
| Generation cache | **Live** *(Phase 3 item 5)* | `services/cache_store.py` — a validated generation is stored under `<store>/cache/<profile_id>/` and an identical request costs **0** LLM calls; keyed by the bytes the model was shown, so a prompt, model, provider or profile change is a miss ([ADR 0015](DECISIONS/0015-generation-cache.md)) |
| `validate_api_key()` | **Removed** *(Phase 1)* | Superseded by `cvtailor doctor --verify-key` |
| Candidate-scoped rules | **Works** *(Phase 1)* | `rules:` block in the profile; see §2 A-1 |

---

## 2. Architecture review

**Stage B (2026-10-30) — the generation pipeline is now six modules.** `A-3` split
`tailor_documents` into `services/generation.py` plus `application_store.py`, but
`generation.py` then grew to **1,465 lines** holding five unrelated concerns — the
schema dialect, the response schemas, prompt construction, response parsing and the
layout delta, the validation rules and gates, and the generator — against 516 for the
next biggest backend file. Nothing failed while it grew, which is why it did.

It is now split along those seams, with `generation.py` kept as a thin **facade** so no
call site moved:

| Module | Lines | Owns |
|---|---|---|
| `services.schema_dialect` | 270 | The one schema-dialect conversion, shared with the study |
| `services.response_schemas` | 217 | The response contract sent per document kind |
| `services.prompts` | 226 | Context, draft briefs, retry briefs, prompt paths |
| `services.validation` | 240 | `ProfileRules` and the document gates |
| `services.cv_delta` | 183 | Response parsing and the layout retry's delta |
| `services.pipeline` | 310 | `DocumentGenerator`: call, validate, retry |
| `services.generation` | 118 | The facade — imports and `__all__`, no logic |

The split was **proven mechanical**: every top-level statement was moved by AST boundary
and compared byte-for-byte against the original (61 of 61, none edited, dropped or
duplicated), and every public re-export is the *same object* as its home rather than a
copy. `tests/test_generation_split.py` pins the facade's completeness, the alias
property, a per-module line ceiling, and the response-schema digests.

**One seam genuinely moved and is worth knowing.** A test observed the validation gate by
patching `generation.validate_cv`; that no longer intercepts, because a rebind on an
aliasing module cannot affect what `pipeline` resolves at call time. The gate is now
called through `services.validation`, and the test patches there. **No assertion
changed.**

**The schema dialect is one implementation, not two.** `generation._to_strict_dialect`
and `evaluation/candidate_inputs.to_dialect` both converted schemas, and only
production's was exercised end to end. Collapsing them **found that they had already
drifted**: production built `SKILLS_AS_ARRAY` inline without `description` fields on
`category`/`items`, while the evaluation's copy had them. Production's bytes were kept,
which is what makes the collapse a pure refactor — the schema digest is an ingredient of
the generation cache key (ADR 0015), so the other choice would have silently invalidated
every cached generation.

**Strengths worth preserving**
- Clean separation of *models / services / renderers / prompts*; renderers are genuinely
  independent of the LLM and of the UI.
- `content.json` as the editable text authority plus a deterministic re-render path is a
  strong design: revisions cost **zero** LLM calls.
- The page-count gate is a real quality gate, not a JSON-shape check.
- Tests exist and pass (see §4) and already mock the LLM properly.

**Core structural problems**

| # | Problem | Evidence | Impact |
|---|---|---|---|
| A-1 | ~~**Candidate-specific business rules hardcoded in the validation layer**~~ **RESOLVED in Phase 1** | `tailor_service.py:73-83`, `:90`, `:154-167` | Rules are now a profile-scoped `rules` block, resolved by `ProfileRules.from_profile()`; the validator reads data, not constants. The authoritative profile declares them, with a test asserting they match the previous defaults. |
| A-2 | **Same candidate facts duplicated across prompts, validators and skill docs** | `tailor_cv_prompt.md:49-86`, `tailor_cl_prompt.md:44-51`, `tailor_service.py:73-92`, `SKILL.md:25-29` | Four places to edit per fact; they already drift. Partly addressed: the validator no longer holds them. The prompts and `SKILL.md` remain. |
| A-3 | ~~**Orchestration, validation, persistence and mirroring in one 296-line function**~~ **RESOLVED in Phase 1** | `tailor_documents` `tailor_service.py:109-296` | Split into `services/generation.py` (prompts, LLM, validation, retries) and `services/application_store.py` (folders, manifests, mirroring); `tailor_documents` is now a thin facade with an unchanged signature. |
| A-4 | **No service layer between API and logic** | `main.py:41` calls `tailor_documents` directly; `ui/app.py` duplicates cost maths (`ui/app.py:239-252`) vs `llm_service.py:28` | Partly addressed: a real service layer now exists. The UI still duplicates pricing (D-4). |
| A-5 | ~~**Global config read at import time**~~ **RESOLVED in Phase 1** | `llm_service.py:21-24` module-level `os.getenv`; `main.py:22` | One `Config` object, resolved at call time; no import-time reads, guarded by a test. See [ADR 0010](DECISIONS/0010-config-object.md). |
| A-6 | **Dates are unvalidated strings** | `profile.py:41-42`; verified: `start_date='not-a-date'` is accepted | Multi-profile data integrity risk. **Still open** — deliberately deferred out of the Phase 2 increment. Two tests pin the current (wrong) behaviour as tripwires. |
| A-7 | **Renderer mutates the caller's model** | `docx_renderer.py:304-307` mutates `cl.paragraphs` in place — **verified** | Re-render/retry yields different output than the first pass. **Still open.** |
| A-8 | **Per-application custom render scripts monkey-patch renderer internals** | `applications/.../delivery_hero/source/render_application.py:10-31` replaces `LaTeXRenderer.__init__` and rewrites template text at runtime | Page-break tuning is unmodelled and unreproducible. **Still open.** |
| A-9 | ~~**`job_id` collision**~~ **RESOLVED in Phase 2** | `tailor_service.py:200` — slug + ms timestamp of the *posting*, no candidate segment | Fixed by `outputs/<profile_id>/<job_id>/`: the candidate segment is now part of the path, so two profiles on one posting cannot collide. The slug itself stays candidate-free because the render filename convention depends on it; the folder carries the identity. Verified by `test_profile_isolation.py`. |
| A-10 | **`--mirror-configured` writes anywhere** | `tailor_service.py:279-294`, `render_application.py:69-80`; `dirs_exist_ok=True` at `:291` | Partly addressed: mirroring is now one method, skips a self-mirror, and the CLI shows the resolved path and confirms before writing outside the job folder. A typo'd absolute path can still write elsewhere. |

---

## 3. Technical debt and bloat

Ranked by impact × confidence. All items **VERIFIED** unless marked.

| ID | Finding | Evidence | Action |
|---|---|---|---|
| **D-1** | ~~`response_schema` / JSON mode is **dead code**~~ **RESOLVED in Phase 1; made live in Phase 3 increment 3** | Dead branches `llm_service.py:162-164,187-198,204` | **Deleted** in Phase 1, along with the unused `response_schema` parameter; the comment explaining why `response_mime_type` was not set was kept, because that reasoning was load-bearing. **Phase 3 increment 3 made structured output live, on the terms that comment demanded**: scoped per call (draft and letter only — the layout retry may return a delta), and constraining the response *envelope* rather than the document body. See [ADR 0012](DECISIONS/0012-structured-output-scope.md). |
| **D-2** | ~~`validate_api_key()` and `create_llm_service()` never called~~ **RESOLVED in Phase 1** | `llm_service.py:265,285` | **Deleted.** Key checking now lives in `cvtailor doctor`, which asserts presence only and verifies against Google just with `--verify-key`. |
| **D-3** | ~~**Cost under-reported**: `calculate_token_usage` prices the *total* with one flat rate, ignoring `input_long`/`output_long` tiers it defines~~ **RESOLVED in Phase 3 item 6** | was `llm_service.py:100-122` vs `PRICING` `:35-40` | **Fixed.** Pricing moved to `services/pricing.py`, which applies the long-context tier to the *tokens*, selected on the input count alone — how the providers bill. For `gemini-2.5-pro` at 300k input tokens the old flat figure was **$0.375 against a real $0.75: half**. The tier rates were confirmed from OpenRouter's own listing, whose `overrides` entry for `google/gemini-2.5-pro` states `min_prompt_tokens: 200000` with prompt $2.50 / completion $15.00 — exactly the values this repository had defined and never applied. **No published figure moves**: `gemini-3.8-flash` has no long tier and its prompts are ~6.4k tokens, so the §5 rows are unchanged. |
| **D-4** | ~~Pricing table duplicated and stale in UI~~ **RESOLVED in Phase 3 item 6** | was `ui/app.py:239-246` vs `llm_service.py:28-71` | **Fixed.** `services/pricing.py` is the one source; the UI reads it. The duplication had drifted — the UI's copy still priced `gemini-1.5-flash`, retired in Phase 1 — so the user could be shown a rate the backend disagreed with. `llm_service.PRICING` remains as a **derived view** of that one table, not a second copy. Two tests fail if a model-keyed table grows back in the UI, and one parses every `PRICING = {...}` dict literal in `backend/` and `ui/` to prove only `pricing.py` defines one. |
| **D-5** | ~~Legacy model pricing retained~~ **RESOLVED in Phase 1** | `llm_service.py:47-70` | **Pruned** after verifying names and prices against ai.google.dev (2026-10-23): `gemini-1.5-*` are delisted and `gemini-3-pro-preview` is shut down; the 2.5-series and `gemini-3.8-flash` prices were confirmed accurate. This exposed a latent `KeyError`: the fallback resolved through the deleted row. It now targets `DEFAULT_MODEL`, asserted by a test. |
| **D-6** | Unused dependencies | grep: no imports in `backend/` | **Pruned:** `pydantic-settings`, `python-multipart`, `tiktoken`, `httpx`, `pytest-asyncio`, `black`, `ruff`. Kept `tzdata` (needed by `ZoneInfo` on Windows), `pytest`, `streamlit` and `requests` (used indirectly). **Correction:** `pandas` is *not* in `requirements.txt` and *is* used at `ui/app.py:231-232`; it arrives transitively via streamlit. |
| **D-7** | ~~`ErrorResponse`, `TailoredOutput` defined and exported, never used~~ **RESOLVED in Phase 1** | `requests.py:44`, `tailored_output.py:71`, `models/__init__.py:19,25` | **Deleted**, including the exports. `TailoringExplanation` was kept — it is still used. |
| **D-8** | ~~`.github/copilot-instructions.md` (646 lines) describes a **different system**~~ **RESOLVED in `c3839da`** | was `.github/copilot-instructions.md:22,42,45,163,381,604,644` | **Rewritten as a short pointer** to `AGENTS.md`, which is the single tool-independent instruction set. The old text (Tectonic, `gemini-1.5-flash`, `BaseProfile`, `cover_letter_examples/`, `/api/preview`) is gone. Re-confirmed 2026-10-26: nothing regressed, and no second instruction file has grown back. |
| **D-9** | ~~Three generated binaries tracked in `outputs/` despite `.gitignore:45`~~ **RESOLVED in Phase 2** | `git ls-files` showed adjoe CV PDF + CL DOCX + PDF | **Untracked** via `git rm --cached` and gitignored; the repository's `outputs/` now holds only `.gitkeep`. `tests/test_privacy_boundary.py` fails if real data is re-tracked. Still present in already-published history — not rewritten ([ADR 0011](DECISIONS/0011-private-store-location.md)). **Re-verified 2026-10-26:** `git ls-files outputs` → `outputs/.gitkeep` only; no further untracking is owed. The three untracked files left on disk by the pre-Phase-2 layout were deleted after confirming each was byte-identical (SHA-256) to its copy in the private store. |
| **D-10** | Committed absolute local paths incl. a third-party name | `applications/.../booking.../source/initial_generation_result.json:4-6` | **Owner decision 2026-10-26: leave history as-is.** The file is untracked and gitignored with the rest of `applications/`, so it cannot be re-committed; it remains retrievable from past commits of the public remote. This is the same accepted limitation [ADR 0011](DECISIONS/0011-private-store-location.md) records, and no rewrite or force-push is approved. |
| **D-11** | Saved applications have inconsistent schemas (`application_context.txt`/`.json`, `posting.txt`, `job_posting.json`, `application_form.json`, `finalize_booking.py`) | `applications/**` listing | **Owner decision 2026-10-26: deferred to Phase 5**, not done in Phase 2. [ADR 0009](DECISIONS/0009-interfaces-and-archive.md) named Phase 2, but the archive left the public repository in Phase 2 and now lives in the private store, so the migration is a Phase 5 concern (Application management owns application schemas). The old archive stays readable as-is until then. |
| **D-12** | ~~Two near-identical `_escape_latex` and three `_slugify` implementations~~ **RESOLVED in Phase 1** | `latex_renderer.py:349,357`, `docx_renderer.py:130,143`, `tailor_service.py:29` | **Consolidated** into `utils/text.py`. Behaviour was verified identical to both originals across the escaping edge cases — including the pre-existing quirk where the braces in `\textbackslash{}` are themselves escaped — and that is now pinned by a test. |
| **D-13** | ~~`outputs/<job_id>/latex_work/` scratch dir created inside the deliverable folder~~ **RESOLVED 2026-10-30** | was `docx_renderer.py:247` | **Fixed** (`c937440`). ~~Use a temp dir.~~ The directory now comes from `tempfile.mkdtemp()` — outside the deliverable folder, and unique per render — and removal moved to a `finally`, so it happens on every exit path. **The defect was on the failure path, not the happy one:** a successful render removed the directory at the end of the `try`, so it looked cosmetic; when the compile raised, the cleanup never ran and `main.tex` plus the copied `setup/` survived inside the folder handed to an employer. Two tests added — the failure-path one **fails against the pre-fix code** with `['latex_work']`. |
| **D-14** | Failed generations leave a partial `outputs/<job_id>/` with no `generation_result.json` | verified in master worktree: adjoe dir lacks the manifest | **Partially addressed:** failures write an explicit `status: failed` manifest through `ApplicationStore.save_failure`. Pinning this in a test was deferred. **Update 2026-10-30: the residue half is now fixed** — D-13's `latex_work/` no longer appears in the deliverable folder on the failure path, verified. **The missing-manifest half remains open.** |
| **D-15** | `except:` bare clauses swallow errors | `latex_renderer.py:294`, `docx_renderer.py:97,376` | **Still open, but narrower than the register says — re-verified 2026-10-30.** **One** bare clause remains, `latex_renderer.py:295`; the `docx_renderer.py` pair are gone (the second was removed with D-13, where `try/except: pass` cleanup became `finally: rmtree(ignore_errors=True)`). **The recorded line numbers are stale; re-locate before fixing.** |
| **D-16** | **`_resolve_pdflatex_path` returns a bare command name, which fails from a different working directory** | `latex_renderer.py` `_resolve_pdflatex_path`: returns `"pdflatex"`, and `docx_renderer.py:326` passes it to `subprocess.run(..., cwd=work_dir)` | **NEW, found 2026-10-30 while verifying D-13. Pre-existing, not introduced by that fix** — the function is unchanged at `f7635ea`. `shutil.which("pdflatex")` proves the binary is *on PATH* and returns the bare name rather than the resolved absolute path, so any call whose `cwd` is not the invoking directory raises `FileNotFoundError: [WinError 2]`. It is latent in production because the CLI runs from the repository root, and it surfaced only when a render ran with a scratch dir on another drive. **Fix: return the resolved path from `shutil.which`, not the candidate string.** Two consequences worth noting: the `else` branch of D-13's fallback is *unreachable* in this state, and `_pdflatex_candidates`/`LATEX_COMPILER` override behaviour should be re-checked when it is fixed. |

> **Register note (2026-10-30).** D-16 was filed, not fixed: it is outside Stage B's scope
> and the owner's order was leanness and accuracy before new work. It is recorded here
> because it was found by running code rather than by reading it, and because D-13's
> verification is what exposed it.

---

## 4. Testing and regression baseline

**Measured baseline (this machine, 2026-10-23):**

```
python -m pytest -q   →   12 passed, 1 warning   (2.45 s)
```

> **Sandbox note:** under the DSH `workspace-write` sandbox, 8 of 12 tests error with
> `PermissionError` because pytest's `tmp_path` cleanup cannot set ACLs on temp trees.
> That is an environment artifact, **not** a code failure; the suite passes unconfined.
> Record the correct invocation in `docs/TESTING.md`.

**What is covered** — `tests/test_tailor_service.py` (mocks Gemini and both renderers):
layout retry + fenced-JSON acceptance, 3-page CV never reported as success, short-letter
correction, truncated-JSON and unreadable-PDF rejection, country-context propagation,
invented-tool and altered-date rejection, sign-off in body rejection.
Plus `test_docx_renderer.py` (XML-sensitive text) and `test_portability.py` (compiler discovery).

**What is NOT covered — the gaps that matter before refactoring**

| Gap | Why it matters |
|---|---|
| `profile_loader` validation & migration | No test for malformed/legacy profiles; multi-profile depends on it |
| Real renderer output (LaTeX & DOCX) | Both renderers are **mocked** in the only integration test; page-count logic is tested against blank PDFs |
| Factual-accuracy regressions on real content | The `_validate_cv` rules are only spot-checked |
| ~~`main.py` endpoints~~ **CLOSED 2026-10-26** | `tests/test_api.py` (20 tests): fail-closed resolution, the legacy-path decoy, `job_id` containment, download isolation between two profiles. 16 of the 20 fail against the previous `main.py`. |
| `render_application.py` | The deterministic re-render path — the most-used revision route — is untested |
| Cross-profile contamination | No second profile exists to test against |
| Cost/token accounting | `calculate_token_usage` untested; D-3 would not be caught |
| DocxRenderer mutation (A-7) | Untested side effect |
| Page/word enforcement on real documents | Gate tested only with synthetic blank PDFs |

**Required before any structural change**

1. **Golden fixtures** — ≥2 synthetic profiles (obviously fake data), 3 anonymised job
   descriptions, and recorded LLM responses as JSON. Enables deterministic, offline runs.
2. **Characterization tests** for the 8 workflows in §1, asserting *behaviour*, not internals.
3. **Document-level assertions** — extract text (`pypdf`), assert page count, required
   sections, no clipping, no orphan headings; word counts for the letter.
4. **A determinism test** for `render_application.py`: same `content.json` → same page count.
5. **An offline end-to-end test** driving `tailor_documents` with a recorded-response fake.
6. **Performance harness** recording LLM call count, tokens and wall time per run, so
   regressions are measurable (see §5).

**LLM testing split** — deterministic tests must never call a paid API (matches the existing
CI, `.github/workflows/tests.yml`). Live quality evaluation stays a separate, opt-in,
budget-capped suite.

---

## 5. Performance and cost

**Measured on this machine**

| Metric | Value |
|---|---|
| `python -m pytest -q` | 12 passed in 2.45 s |
| `import main` (backend startup) | ~1.7–2.0 s (`import fastapi` alone 0.52 s) |
| `load_profile()` | 169 ms |
| Profile JSON sent to the LLM | 15,163 chars ≈ **3,790 tokens** |
| CV prompt | 7,701 chars ≈ 1,925 tokens |
| CL prompt | 4,153 chars ≈ 1,038 tokens |
| Sample job description | 1,347 chars ≈ 336 tokens |
| **CV call input** | ≈ **6,150 tokens** |
| **CL call input** | ≈ **5,265 tokens** |
| CV output / CL output | ≈ 1,350 / 622 tokens |
| pdflatex per run | ≈ 2.9 s (run twice per compile) |
| CV re-renders, worst case | 4 layout attempts × 2 runs = 8 |

**LLM calls per application** (VERIFIED from control flow; **updated in Phase 3 increment 2**)

The editorial-review pass was removed in increment 2, so every count drops by one CV call.
The *arithmetic* is the same; the second CV call is simply gone. The new figures were
verified by driving the real pipeline with recorded transcripts, not by subtracting.

| Case | Arithmetic | Logical calls |
|---|---|---|
| Minimum | 1 draft + 1 letter | **2** |
| Typical (1 layout retry) | 2 + 1 | **3** |
| Max successful (fits on 4th render) | 2 + 3 | **5** |
| Worst (validation retries exhausted) | 6 `generate` × 2 | **12** |
| HTTP ceiling (`_call_provider` retries ×3) | 12 × 3 | **36** |

**Estimated cost per application** (`gemini-3.8-flash`, $0.75 / $3.75 per 1M) — **measured
after increment 2**

| Case | Input tok | Output tok | Cost | Was |
|---|---|---|---|---|
| Best (2 calls) | 10,927 | 1,972 | **$0.016** | $0.027 |
| Typical (3 calls) | 18,699 | 3,322 | **$0.026** | $0.038 |
| Worst (5 calls) | 34,243 | 6,022 | **$0.048** | $0.060 |

> **These are now confirmed against real billing, and the assumptions behind them were
> too optimistic in two places (2026-10-26).** The evaluation suite ran for real, and
> OpenRouter's own reported charge replaces the estimate for any run that goes through it
> (`usage.cost`, with `cost_details.upstream_inference_cost` — Google-routed calls report
> `cost: 0` and carry the real figure in the latter). Two measured findings change the
> arithmetic above:
>
> 1. **Reasoning tokens are billed as output and consume the majority of the budget.**
>    Measured at 53–58% of completion tokens (646 of 1,220 for `deepseek-v4-flash`; 483 of
>    831 for `gemini-3.8-flash`). The output figures above assume roughly the document's
>    own length, so a reasoning model's real output is materially higher.
> 2. **A single cover-letter call emitted 21,463 output tokens** in one measured run,
>    against the ~622 assumed here — a factor of ~35. The `≈622` figure describes a
>    well-behaved letter, not the worst observed one, and cost per accepted result is what
>    the ranking uses precisely because per-call figures like these mislead.
>
> The measured cost per **accepted** result, which is the figure that matters:
> `openai/gpt-6-luna` **$0.00271**, `deepseek-v4-flash` **$0.00328**,
> `claude-haiku-5.5` **$0.00582**, `gemini-3.8-flash` **$0.11384**, `claude-sonnet-5`
> **$0.15709**. **The default has since changed on this evidence.** The owner selected
> `openai/gpt-6-luna` on 2026-10-27 and the switch shipped in `e53ef8a`, so the table
> above is the *study's comparison* rather than a description of what the tool now uses:
> the previous default was roughly **30-40x** the cheapest model that does the job, and
> it is no longer the default.
>
> **The measured figures for the model now shipped**, end to end through the real CLI:
> **$0.0026** for a synthetic profile (CV 1 page, letter 1 page / 302 words) and
> **$0.0032** for the owner's real profile against a real posting (CV 2 pages, letter 1
> page / 301 words, all six employers with correct dates).

The per-call inputs are recomputed from the actual prompt bytes: the CV call grows from
≈6,150 to ≈6,438 tokens because the draft prompt now carries the editorial requirements
(616 chars ≈ 288 tokens), and the ≈7,772-token review call disappears entirely. On the
happy path that is a **41% reduction in input tokens** and **one fewer call**.

> **A layout retry is no longer priced as a second CV call (Phase 3, increment 1 of the
> agreed order).** The "Typical" and "Max successful" rows above charge each retry a full
> ≈6,438-token CV call plus a full CV JSON. Since that increment a retry sends only the
> targeted brief and the current CV — measured at **740 tokens** on the recorded fixture,
> versus 3,488 before — so those two rows are now **upper bounds**, not estimates. They are
> left as they stand because their per-call inputs come from the fixture transcript rather
> than the 6,438-token production call, and restating a production saving from a fixture
> measurement would be a derived figure presented as a measured one.

> **Correction carried from the pre-increment table.** The old "Typical (4 calls)" row
> stated 34,601 input tokens, which is the arithmetic of *five* calls (draft + review +
> two retries + letter), not four. The call count and the token total disagreed. The rows
> above are derived consistently from the per-call inputs, so a count and its tokens now
> describe the same run. The old `Worst` row was also mislabelled: at 65,513 tokens it
> described 6 calls @ ~10,919, i.e. the max-successful case, not the retry-exhausted one.

**Dominant inefficiency (RESOLVED — Phase 3, increment 1 of the agreed order, 2026-10-26):**
each layout retry used to re-send the entire context *plus* the full previous CV JSON to
produce a shorter variant. With the review pass gone this was the largest single source of
repeated input. See the measured effect below.

**Optimization opportunities (evidence-based, in priority order)**

1. ~~**Targeted layout retry instead of full regeneration**~~ — **DONE — Phase 3, increment 1
   of the agreed order (2026-10-26).** The retry now sends a targeted brief and the current
   CV, and accepts a delta merged onto the validated CV. Measured: retry input 3,488 → **740**
   tokens on the recorded fixture. See the measured effect below.
2. ~~**Remove or merge the editorial-review pass**~~ — **DONE — Phase 3, increment 2
   (2026-10-26).** The requirements were folded into the draft prompt
   (`generation.EDITORIAL_REQUIREMENTS`, injected by `build_cv_prompt`) and the second CV
   call was deleted. See the measured effect below.
3. ~~**Enable structured output** (`response_schema`) — removes the parse-failure retry
   loop, the dominant tail risk.~~ **DONE — Phase 3, increment 3 (2026-10-26), scoped.**
   JSON mode and a `response_schema` are now sent on the CV draft and the cover letter;
   the layout retry is deliberately left unconstrained because its response may be a
   delta. The schema constrains the **envelope** (`cv` / `cover_letter` required) and not
   the document body, which is what keeps the truncation D-1 records from returning. See
   [ADR 0012](DECISIONS/0012-structured-output-scope.md) and the measured effect below.
4. ~~**Serialize the profile once** per application rather than per call.~~
   **DONE — Phase 3, increment 1 (2026-10-26).** The context block is now built once per
   application and reused by the CV prompt, the letter prompt and every layout retry
   (`tailor_service.tailor_documents` → `generation.build_context(..., profile_json=...)`).
   The *token* figures were unchanged by that increment, because the bytes sent to the model
   are byte-identical — it removes repeated work, not content. Measured on this machine:
   `model_dump_json(indent=2)` ≈ 0.044 ms and the banned-tool facts block ≈ 0.23 ms per
   call, against a typical run that rebuilt them 3–4 times and up to 8 times at the
   worst (7 banned tools × one scan each). That is single-digit milliseconds per
   application — real, but **not** a cost saving.
5. ~~**Cache validated results** — re-rendering already costs 0 LLM calls; extend that
   principle to "same profile + same JD → reuse".~~ **DONE — Phase 3, item 5 (2026-10-26).**
   A **validated** generation is stored under `<store>/cache/<profile_id>/` and an identical
   request is served from disk: **0 LLM calls** and byte-identical accepted documents. The key
   is a digest of the bytes the model was shown — the serialized profile, the posting plus
   company/role/country, both prompt files read and hashed per call, the schema, the provider
   and **both routed models** — so a prompt, model, provider or profile change is a miss rather
   than a stale document. See [ADR 0015](DECISIONS/0015-generation-cache.md) and the measured
   effect below.

**Pricing is now route- and tier-aware (Phase 3, item 6).** `services/pricing.py` is the one
source of truth (D-4) and applies the long-context tier to the tokens (D-3). Price is keyed by
`(provider, model)` because a bare model name does not identify a price — OpenRouter lists
`google/gemini-3.8-flash` at **$0.825/$4.125** per 1M while Google charges **$0.75/$3.75**
direct, both verified from the provider's own listing. The **§5 cost rows above do not move**:
`gemini-3.8-flash` has no long-context tier and its prompts are ~6.4k tokens, well under the
200k threshold, so the figures are identical under the new accounting. Re-derived on
2026-10-26: $0.01559 / $0.026482 / $0.048265 for best / typical / worst.

**The evaluation suite exists and has run (Phase 3, item 6).** `evaluation/` implements the
eight criteria ADR 0005 names, is offline by default, refuses an over-budget plan before the
first call, and is not collected by pytest so CI cannot spend. **It ran on 2026-10-26/27:**
eight candidates were measured on three cases each, the owner selected `openai/gpt-6-luna`, and
the switch shipped — the projection for that study was $1.65 against a $5 cap, and $1.91 was
spent across the whole effort.

**The curation workflow (2026-10-30) is four offline verbs plus one paid one**, and the split is
the design rather than an implementation detail:

| Verb | Offline? | What it does |
|---|---|---|
| `--detect` | yes | Diffs a fresh listing against the committed record. **Reports; cannot spend** — there is no path from it to `--live`, so routine catalogue churn cannot trigger a run |
| `--screen` | yes | A listing record into a proposed slate, with every rejection's rule and failing value |
| `--packet` | yes | One folder per model per case with the rendered documents, plus a `VERDICTS.md` |
| `--report` | yes | A curation proposal: the ranked table, the disqualifications, and the diff it **would** make. Emits text and **writes nothing** |
| `--live` | **no** | The only spending path, unchanged: needs an explicit cap and `authorised=True` |

**`evaluation/listing.py` commits a screened record** (267 models, ~66 KB) alongside the digest
of the full payload, so a recorded price is checkable by anyone. Previously only the digest was
kept and the payload was gitignored, which is why two tests skipped in every fresh working copy.

**The quality judgement is a human step, enforced in code.** `evaluation` records acceptance,
cost and correction calls — and **no** prose, rendering or layout. A candidate is ineligible for
curation until the owner records their own verdict, and `apply_verdicts` is the only route to
eligibility. `verified="measured"` is set on the one shipped entry, and only because the owner
read the rendered documents for all three cases and answered "send as-is" on 2026-10-31; the
verdict is recorded, dated, in that entry's `measured_notes`. The guard was rewritten rather
than dropped: an entry marked `measured` whose notes record no dated owner verdict now fails, so
a marker set from a table of acceptance rates cannot pass silently.

*Do not add async, concurrency or caching infrastructure before 1–5 are exhausted.*

**Item 5 closes that list, and it did not add infrastructure — it removed work.** All five
optimisations are now implemented, so the "do not add caching infrastructure" line above is spent:
the cache exists because one of the five asked for it, not as a general-purpose layer.

**Measured effect of optimisation 5 (2026-10-26).** The item was verified by driving the real
pipeline over the recorded Nordwind transcript, not by inspection:

| Case | Calls | Tokens reported | Cost |
|---|---|---|---|
| First run (cold cache) | **2** | 200 | ~$0.0002 |
| Identical repeat (hit) | **0** | **0** | **$0.00** |
| Cold cache, one layout retry | **3** | — | unchanged |
| Cold cache, max successful | **5** | — | unchanged |

**Call counts on a cold cache are unchanged at 2/3/5, worst 12.** This is stated explicitly
because the item was required to say so if it were not: item 5 adds a lookup **before** the first
call and a write **after** the last one, and adds no request. A test asserts that nothing is
written before the page-count gate, so the cold path is read-free and write-free on the way in.
The saving is exact and total on a repeat — the whole generation is free — and zero on anything
that differs in a single ingredient.

**Measured effect of optimisation 4 (2026-10-26).** The prompt sent to the model was
unchanged: `tests/test_profile_serialization.py` asserts the rendered context is
byte-identical with and without the new `profile_json` argument, and asserts the pipeline
serializes the profile exactly once per application.

**Measured effect of optimisation 2 (2026-10-26).** Call counts 3/4/6 → **2/3/5**, the
numbers now pinned by `tests/test_editorial_instructions.py` against the real pipeline
rather than derived on paper. Both recorded transcripts lost their
`02_cv_editorial_review.json` step (`tools/build_fixtures.py` regenerates them) and
`tailoring_explanation` is read from the **draft** response, which is now the only CV
response. Validation is unchanged: the draft was always the document `validate_cv` gated,
and the review's output was re-validated from scratch anyway — so the pass bought a second
draft, not a stronger gate. Two tests assert that an invalid draft still fails the run and
that no letter is drafted from it.

**Measured effect of optimisation 1 (2026-10-26).** Measured by driving the real pipeline
with the recorded Nordwind transcript and counting the exact bytes each call receives.
Counts use `tiktoken`'s `cl100k_base` as a **local proxy** — Gemini's tokenizer is not
available offline, so these are not billed counts, but every before/after pair is on the
same basis:

| Retry input | Before | After |
|---|---|---|
| Retry prompt | 3,488 tok (16,508 chars) | **740 tok (3,301 chars)** |
| of which context (profile + JD) | 1,408 tok | **0** |
| Whole 3-call run | 8,365 tok | **5,617 tok** |
| Retry output, delta vs whole CV | 386–481 tok | **91–267 tok** |

The retry now sends **fewer input tokens than the draft call** (740 vs 2,886) rather than
more. That is **−79% retry input** against the baseline retry, and **−33%** for the whole
typical run; the run still pays for the draft and the letter, which this increment does not
change. **Call counts are unchanged at 2/3/5** — this lowers tokens per retry, not the
number of retries.

The delta cannot weaken the gate. `validate_cv` runs on the *merged* document; the merge
(`generation.apply_cv_delta`) can address only the summary, bullets, project names/bullets
and existing skills categories, so employers, titles, dates, education, certifications and
`work_authorization` are structurally unreachable and ongoing work cannot be completed by a
retry. An unknown key raises, the retry goes through the unchanged 3-attempt correction
loop, and the run then fails — there is no silent fallback that keeps the unshortened CV.

**Measured effect of optimisation 3 (2026-10-26).** Structured output is **scoped**, not
enabled globally, and the scope is the decision this increment turns on
([ADR 0012](DECISIONS/0012-structured-output-scope.md)):

| Call | Response contract | JSON mode + `response_schema` |
|---|---|---|
| CV draft | one complete document, always | **sent** |
| Cover letter | one complete document, always | **sent** |
| Layout retry | complete CV **or** a delta of unit ids | **not sent** |
| Any unknown/future document kind | unspecified | **not sent** |

The schema requires the envelope key (``cv`` / ``cover_letter``) and **nothing else**.
There is no ``required`` inside the document and no ``additionalProperties: false``
anywhere: enumerating and requiring every field of a ~1,350-token document is what makes a
constrained response long and cut-off-prone, and a cut-off response is invalid JSON. That
is the failure D-1 records, so the body's properties are described — keeping the contract
meaningful — and left optional, keeping the response short enough to finish. The
guarantee actually bought is that the response is an object carrying the expected document
key, so **`parse_json_response`'s brace-scan stops being the failure path**.

**What this increment does NOT claim.** It does not claim truncation has been *observed*
not to return on real documents, because no paid call was made — the suite is offline by
constraint. What is established offline is (a) the schema is well-formed and the SDK
serializes it (asserted), (b) a truncated constrained response is *rejected* rather than
parsed into a short document (asserted), and (c) the scope excludes the one call whose
response is not a document (asserted). Confirming the truncation behaviour against the
provider needs a budgeted live run, which belongs to item 6 with the rest of the
benchmarking.

**No silent fallback, and `validate_cv` is not bypassed.** A schema-constrained response
goes through the same `parse_json_response` and the same gate as before; JSON mode is a
request to the provider, never a substitute for validation. Two tests drive a
schema-violating draft and a malformed one through the real pipeline and assert the run
still fails after exactly three attempts.

**Call counts are UNCHANGED at 2/3/5** (12 worst), verified by driving the real pipeline
with recorded transcripts rather than derived on paper. The schema is request metadata,
not prompt content, so no prompt byte changed and the token and cost figures above are
unchanged too. A schema that failed often enough to trigger the correction loop would show
up here as a *rise* on the happy path, which is why the happy path is asserted to stay at
two calls rather than merely left unmeasured.

> **Caveat on extrapolating to production.** The fixture documents are ~80–100 body words,
> so on them the 650/550-word budget is not the binding constraint and a model using the
> delta path has little to shorten. The saving scales with how much the retry actually
> changes, and is therefore *larger* on a real ~650-word CV than the fixture shows. No paid
> live run was made to confirm the delta path's behaviour on real documents; that belongs
> to a budgeted evaluation, not to the offline suite.


---

## 6. Security and privacy

> **Historical audit (pre-Phase 2).** The bullets under "Verified" below describe the repository as
> it stood when this assessment was written. Phase 2 moved all real candidate data out: profiles,
> applications and generated documents are untracked, gitignored, and live in the private store
> ([ADR 0011](DECISIONS/0011-private-store-location.md)), with the boundary asserted by
> `tests/test_privacy_boundary.py`. The *history* below was not rewritten — anything already
> published stays published — so these findings still describe what is retrievable from old commits.

**Verified**
- **No credential was ever committed.** `.env` never in history; secret-pattern scan over
  all refs found nothing. `.gitignore:2-5` covers `.env*`.
- **Substantial personal data is committed to a public repo**: name, personal email, mobile,
  home city, **immigration status**, full employment history, education — `storage/profile/profile.yaml`.
- **64 of 112 tracked files are application data**, including `profile_snapshot.json`
  (a full profile copy per application) and `application_answers.json` (free-text answers
  plus two eligibility attestations).
- **Leaked local paths incl. a third-party name** — `initial_generation_result.json:4-6`.
- **3 generated PDFs/DOCX tracked** in `outputs/` despite `.gitignore`.
- History is short (49 commits) and linear.

**Path traversal (`main.py:63,67,88,111`)** — FastAPI's default `str` converter is `[^/]+`,
so `../../etc/x` is rejected at routing (**verified by inspection**). Encoded/backslash
variants are **HYPOTHESIS**, unproven. The endpoints also return the *first* matching file
in a folder, which would widen any traversal into file disclosure. Fix regardless:
validate `job_id` against `^[A-Za-z0-9_-]+$` and assert the resolved path stays inside `OUTPUTS_DIR`.

**Recommended privacy model**

| Public repo (code only) | Private/local store (gitignored or a second private repo) |
|---|---|
| `backend/`, `renderers/`, `prompts/`, `templates/`, `tests/`, `scripts/`, `docs/`, `.env.example`, a **synthetic** `example.yaml` | all real profiles, `applications/`, `outputs/`, mirrors, form answers, snapshots, drafts, generated documents |

This is the single most important decision for multi-profile. Adding a second real candidate
to a public repo is not acceptable. A second **private** repository preserves versioning and
portable reproduction without exposing anyone's PII — recommended over encrypting in place,
which would break the plaintext UI and grep-ability.

*History rewriting is not required to add profiles, but is required to un-disclose data
already public. Do not rewrite history or change visibility without explicit approval.*

**Implemented 2026-10-24 (Phase 2).** The split above is now real: real profiles,
`applications/` and `outputs/` are untracked and gitignored, and live in a private sibling
repository ([ADR 0011](DECISIONS/0011-private-store-location.md)). A test asserts the boundary
and fails if it regresses.

**The history warning above still stands.** Untracking stops *future* exposure; it does not
un-publish anything. As this document predicted, un-disclosing the data already committed
requires a history rewrite, which has **not** been approved or performed. Anyone who cloned the
public repository before 2026-10-24 still has the profile and the 64 application files.

---

## 7. Documentation consistency

| Document | State |
|---|---|
| `AGENTS.md` | Accurate and concise. **Keep as the single entry point.** |
| `README.md` | Accurate; correctly documents the render path. |
| `docs/MAC_SETUP.md` | Accurate and genuinely portable. |
| `.agents/skills/cv-tailor-application/SKILL.md` | Accurate and detailed. |
| `.github/copilot-instructions.md` | **Fixed** (`c3839da`) — now a short pointer to `AGENTS.md` (D-8). |

When this assessment was written there was no `ROADMAP.md`, `PROJECT_STATE.md` or decisions log,
which is why project knowledge lived in conversation history. All three now exist, and
`docs/DECISIONS/` holds the settled choices. **Keep one instruction set**: `AGENTS.md` is
authoritative for every agent, and `.github/copilot-instructions.md` only points at it.

---

## 8. Recommendation

**Option B — Modular redesign, executed incrementally.** (See §9 for the comparison.)

The existing renderers, templates, prompts and `content.json` re-render path are genuinely
good and represent real accumulated value. The problems are *concentration* (one giant
function, candidate facts smeared across four layers) and *missing boundaries* (no profile
identity, no service layer, no persistence model) — not the technology choices.

A rewrite (Option C) would discard working, hard-won layout logic for no proven gain.
Incremental patching (Option A) cannot deliver multi-profile, because profile identity has
to be threaded through every layer — that is a structural change by definition.

---

## 9. Architecture options compared

| Criterion | A. Incremental | **B. Modular redesign** | C. Replacement |
|---|---|---|---|
| Scope | Small, local fixes | Reorganise responsibilities; keep renderers/templates/models | New codebase |
| Effort | Low | **Medium** | High |
| Regression risk | Low | **Low–Medium** (mitigated by §4 baseline) | High |
| Perf. impact | Minor | **Positive** (removes redundant calls) | Uncertain |
| Migration | None | Profiles + applications need a migration step | Full re-entry of all data |
| Maintainability | Little gain | **Substantial gain** | Good, at high cost |
| Testability | Marginal | **Good** (service layer + fixtures) | Good |
| User disruption | None | Low (master untouched) | High |
| Portability | Unchanged | **Preserved** | Re-verify on all OSes |
| Operating cost | Unchanged | **Lower** | Unknown |

**Recommendation: Option B.** Keep the renderers, templates, prompts, `content.json`
contract and the page-count gate; introduce profile identity, a service layer and a
persistence model around them.

### Proposed package structure

```
cv_tailor/                    # importable package (replaces sys.path hacks)
  domain/        profile.py, job.py, application.py, documents.py   # pure models + rules
  profiles/      store.py, loader.py, migration.py                  # multi-profile
  llm/           base.py, gemini.py, openrouter.py, registry.py     # provider interface
  generation/    pipeline.py, prompts/, validation.py               # orchestration
  rendering/     latex.py, docx.py, templates/                      # kept largely as-is
  jobs/          sources/, normalize.py, dedupe.py, matching.py     # Phase 4
  applications/  store.py, tracker.py                               # Phase 5
  cli/           main.py, commands/                                 # CLI-first
  api/           app.py                                             # thin FastAPI wrapper
```
`backend/`, `ui/` and `scripts/` remain as thin adapters during migration.

### Data flow (target)

```
profile_id ─┐
            ├─► ProfileStore.load(profile_id) ─► Profile
job desc ───┘                                      │
                                                   ▼
                        GenerationPipeline (LLM provider injected)
                                                   │
                        Validation (profile-scoped rules, not hardcoded)
                                                   ▼
                        Renderers ─► ApplicationStore.save(profile_id, job_id)
                                                   ▼
                        CLI  │  API  │  UI   (all call the same services)
```

### Storage

Start with **YAML/JSON on disk keyed by `profile_id`** (`storage/profiles/<id>/profile.yaml`,
`storage/profiles/<id>/applications/<job_id>/`). It preserves git-diffability and the current
editing workflow. Adopt SQLite only when job-discovery volume (Phase 4) makes file scanning
painful — not before. **No database server.**

> **Implemented in Phase 2**, with two deviations from the sketch above:
> - The store is **outside the repository** (`CVTAILOR_STORE`, default `./storage`; on this
>   machine `D:\coding\cv-tailor-data`), because ADR 0002 requires real data not to be committed
>   here. The `<store>/profiles/<id>/profile.yaml` shape is as sketched.
> - Applications are kept **shared** at `<store>/applications/<job_id>/`, not nested under the
>   profile, because `job_id` is posting-derived and candidate-free. Generated documents go to
>   `<store>/outputs/<profile_id>/<job_id>/`, where the candidate segment does isolate them.

---

## 10. Roadmap

| Phase | Objective | Key deliverables | Depends on |
|---|---|---|---|
| **0** | Assessment & foundations | This doc, `PROJECT_STATE.md`, `ROADMAP.md`, decisions log, worktree isolation, test baseline | — |
| **1** | Refactor & CLI core | `cv_tailor` package, service layer, single config, remove dead code, `cvtailor` CLI for profile/render/generate | 0 |
| **2** | Multi-profile | `ProfileStore`, `profile_id` threading, per-profile rules, migration of the existing profile, isolation tests | 1 |
| **3** | LLM & documents | Provider interface (Gemini + OpenRouter), model eval suite, cost tracking, targeted retry, review workflow | 2 |
| **4** | Job discovery & matching | Connectors, normalisation, dedupe, deterministic matching + explainable ranking | 2 |
| **5** | Application tracking | Statuses, history, deadlines, notes, saved document versions, CLI workflow | 2 |
| **6** | UI & deployment | UI decision, multi-profile UI, dashboards, auth *if* hosted | 3–5 |

**MVP (delivers real value earliest): Phase 1 + a slice of Phase 2** — a CLI that can list,
select and generate for a named profile, with the existing generation quality preserved.
This makes daily use *better* without waiting for discovery or tracking.

---

## 11. Decisions — **APPROVED 2026-10-23**

Full records in [`DECISIONS/`](DECISIONS/README.md). Summary of what was decided:

| # | Decision | Outcome |
|---|---|---|
| **1** | **Privacy model** | **Approved** — all real profiles/applications/outputs move to a private store; only synthetic examples are committed. Owner also wants profiles reachable from any machine with internet → deferred to [ADR 0006](DECISIONS/0006-remote-profile-access.md). |
| **2** | **History rewriting** | **Deferred** — fix forward. Revisit only if the public repo keeps accumulating real data. |
| **3** | **Architecture direction** | **Approved** — Option B, modular redesign, incrementally. |
| **4** | **Storage** | **Approved** — files keyed by `profile_id`, **local first**, no database server; remote store later ([0004](DECISIONS/0004-storage.md)). |
| **5** | **CLI framework** | **Approved** — `argparse` + a friendliness layer (guided default, interactive prompts, `doctor`, `--json`) ([0007](DECISIONS/0007-cli-framework.md)). |
| **6** | **FastAPI + Streamlit** | **Approved** — keep both as thin adapters over the service layer; reassess at Phase 6. |
| **7** | **LLM providers** | **Approved** — provider interface; **benchmark cost, performance and output quality before switching**; keep Gemini's latest Flash as default. |
| **8** | **Job sources** | **Approved in principle** — ToS-compliant APIs researched first; scraping only if permitted and necessary; full scope determined at Phase 4. |
| **9** | **`applications/` archive** | **Approved** — read-only reference until Phase 2, then migrate to the new schema. |

These are to be **re-confirmed when their respective phase begins**.

### Privacy model (decision 1, detailed)

| Public repo (code only) | Private store (never public) |
|---|---|
| `backend/`, renderers, `prompts/`, `templates/`, `tests/`, `scripts/`, `docs/`, `.env.example`, a **synthetic** `example.yaml` | all real profiles, `applications/`, `outputs/`, mirrors, form answers, snapshots, drafts, generated documents |

"Access from anywhere" is met by the **remote store** ([0006](DECISIONS/0006-remote-profile-access.md)),
layered on this split — not by committing data. Local use stays fully functional offline.

*History rewriting is not required to add profiles, but is required to un-disclose data
already public. Do not rewrite history or change visibility without explicit approval.*

---

## 12. Proposed first milestone (not started — awaiting approval)

**Milestone 1.1 — Test baseline and golden fixtures (no production behaviour change).**

- **Why first:** every later step depends on being able to prove behaviour was preserved.
  It is also the only milestone that is 100% safe on a shared branch.
- **Scope:** add `tests/fixtures/` with 2 synthetic profiles, 3 anonymised job descriptions
  and recorded LLM responses; add characterization tests for profile loading, validation,
  the pipeline, both renderers and `render_application.py`; add a `docs/TESTING.md`
  recording the sandbox caveat and the exact commands.
- **Components affected:** `tests/` (new files only) and `docs/TESTING.md`. **No** changes to
  `backend/`, `ui/` or `scripts/`.
- **Expected behaviour:** the existing 12 tests still pass; new tests pass; the suite runs
  fully offline.
- **Required tests:** the characterization suite above, incl. a determinism test.
- **Acceptance criteria:** `python -m pytest -q` green offline; every §1 workflow has at
  least one behavioural test; fixtures contain no real personal data.
- **Git:** branch off `refactor/architecture-v2`; commits `test: …` / `docs: …`; no merge to `master`.

---

## 13. Environment findings

- **Development worktree is correctly isolated:** `D:\coding\cv-tailor-next` on
  `refactor/architecture-v2`; `D:\coding\cv-tailor` on `master`. Both clean.
- **`refactor/architecture-v2` is currently identical to `master`** (`1416177`, 0 ahead /
  0 behind) — the branch was created but no work has landed yet.
- **The development worktree has no `.venv` and no `.env`** — it cannot run today. Master has
  both. This must be fixed before any milestone (see `docs/DEVELOPMENT.md`).
- The two worktrees already have separate `outputs/` directories, so generated documents do
  not collide. Master holds the 8 real application folders; the dev worktree holds only the
  tracked adjoe folder.
- Ports: `scripts/start.py:7` reads `BACKEND_PORT`/`UI_PORT` — set different values per
  worktree to run both at once.
