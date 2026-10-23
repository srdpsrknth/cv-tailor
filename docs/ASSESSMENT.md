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

---

## 1. What CV Tailor currently does

A local, single-user tool that turns a pasted job description into a tailored CV PDF and a
cover letter (DOCX + PDF), grounded in one authoritative YAML profile.

**Verified end-to-end workflow**

```
storage/profile/profile.yaml
        │  load_profile()                      backend/services/profile_loader.py:11
        ▼
   Profile (Pydantic)                          backend/models/profile.py:73
        │  + job_description + company/role/work_country
        ▼
tailor_documents()                             backend/services/tailor_service.py:109
   ├─ CV draft            LLM call 1 ─┐
   ├─ CV editorial review LLM call 2  ├─ GeminiService._call_gemini()
   ├─ Cover letter        LLM call 3  │  backend/services/gemini_service.py:124
   └─ Layout retry loop (≤4) ─────────┘
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
- `backend/main.py` — FastAPI, 4 endpoints (`/health`, `/api/tailor`, 3 downloads).
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
| Multi-profile | **Absent** | hardcoded single path `profile_loader.py:27` |
| Job discovery / matching | **Absent** | — |
| Application tracking | **Absent** | — |
| CLI | **Works** *(Phase 1)* | `cvtailor` — `doctor`, `profile show`, `generate`, `render` |
| Provider abstraction | **Absent** | Gemini hardwired `tailor_service.py:119` |
| Structured output (JSON mode) | **Dead code, removed** | `response_schema` never passed — see §3 D-1 |
| `validate_api_key()` | **Removed** *(Phase 1)* | Superseded by `cvtailor doctor --verify-key` |
| Candidate-scoped rules | **Works** *(Phase 1)* | `rules:` block in the profile; see §2 A-1 |

---

## 2. Architecture review

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
| A-4 | **No service layer between API and logic** | `main.py:41` calls `tailor_documents` directly; `ui/app.py` duplicates cost maths (`ui/app.py:239-252`) vs `gemini_service.py:28` | Partly addressed: a real service layer now exists. The UI still duplicates pricing (D-4). |
| A-5 | ~~**Global config read at import time**~~ **RESOLVED in Phase 1** | `gemini_service.py:21-24` module-level `os.getenv`; `main.py:22` | One `Config` object, resolved at call time; no import-time reads, guarded by a test. See [ADR 0010](DECISIONS/0010-config-object.md). |
| A-6 | **Dates are unvalidated strings** | `profile.py:41-42`; verified: `start_date='not-a-date'` is accepted | Multi-profile data integrity risk. **Still open.** |
| A-7 | **Renderer mutates the caller's model** | `docx_renderer.py:304-307` mutates `cl.paragraphs` in place — **verified** | Re-render/retry yields different output than the first pass. **Still open.** |
| A-8 | **Per-application custom render scripts monkey-patch renderer internals** | `applications/.../delivery_hero/source/render_application.py:10-31` replaces `LaTeXRenderer.__init__` and rewrites template text at runtime | Page-break tuning is unmodelled and unreproducible. **Still open.** |
| A-9 | **`job_id` collision** | `tailor_service.py:200` — slug + ms timestamp of the *posting*, no candidate segment | **Partially addressed:** the generation is unchanged and now isolated in `ApplicationStore.make_job_id`, but it still carries no candidate segment. The real fix is `profile_id` in Phase 2. |
| A-10 | **`--mirror-configured` writes anywhere** | `tailor_service.py:279-294`, `render_application.py:69-80`; `dirs_exist_ok=True` at `:291` | Partly addressed: mirroring is now one method, skips a self-mirror, and the CLI shows the resolved path and confirms before writing outside the job folder. A typo'd absolute path can still write elsewhere. |

---

## 3. Technical debt and bloat

Ranked by impact × confidence. All items **VERIFIED** unless marked.

| ID | Finding | Evidence | Action |
|---|---|---|---|
| **D-1** | ~~`response_schema` / JSON mode is **dead code**~~ **RESOLVED in Phase 1** | Dead branches `gemini_service.py:162-164,187-198,204` | **Deleted**, along with the unused `response_schema` parameter. The comment explaining why `response_mime_type` is not set was kept — that reasoning is still load-bearing. |
| **D-2** | ~~`validate_api_key()` and `create_gemini_service()` never called~~ **RESOLVED in Phase 1** | `gemini_service.py:265,285` | **Deleted.** Key checking now lives in `cvtailor doctor`, which asserts presence only and verifies against Google just with `--verify-key`. |
| **D-3** | **Cost under-reported**: `calculate_token_usage` prices the *total* with one flat rate, ignoring `input_long`/`output_long` tiers it defines | `gemini_service.py:100-122` vs `PRICING` `:35-40` | **Still open.** Fix before trusting cost data. |
| **D-4** | Pricing table duplicated and stale in UI | `ui/app.py:239-246` vs `gemini_service.py:28-71` | **Still open** — single source of truth still needed. |
| **D-5** | ~~Legacy model pricing retained~~ **RESOLVED in Phase 1** | `gemini_service.py:47-70` | **Pruned** after verifying names and prices against ai.google.dev (2026-10-23): `gemini-1.5-*` are delisted and `gemini-3-pro-preview` is shut down; the 2.5-series and `gemini-3.8-flash` prices were confirmed accurate. This exposed a latent `KeyError`: the fallback resolved through the deleted row. It now targets `DEFAULT_MODEL`, asserted by a test. |
| **D-6** | Unused dependencies | grep: no imports in `backend/` | **Pruned:** `pydantic-settings`, `python-multipart`, `tiktoken`, `httpx`, `pytest-asyncio`, `black`, `ruff`. Kept `tzdata` (needed by `ZoneInfo` on Windows), `pytest`, `streamlit` and `requests` (used indirectly). **Correction:** `pandas` is *not* in `requirements.txt` and *is* used at `ui/app.py:231-232`; it arrives transitively via streamlit. |
| **D-7** | ~~`ErrorResponse`, `TailoredOutput` defined and exported, never used~~ **RESOLVED in Phase 1** | `requests.py:44`, `tailored_output.py:71`, `models/__init__.py:19,25` | **Deleted**, including the exports. `TailoringExplanation` was kept — it is still used. |
| **D-8** | `.github/copilot-instructions.md` (646 lines) describes a **different system**: Tectonic (not pdflatex), `gemini-1.5-flash`, `BaseProfile`, `cover_letter_examples/` (87 files, absent), "Python 3.14+", `/api/preview` endpoint that does not exist | `.github/copilot-instructions.md:22,42,45,163,381,604,644` | **Still open.** Rewrite as a pointer to `AGENTS.md`. Highest-value remaining doc fix. |
| **D-9** | Three generated binaries tracked in `outputs/` despite `.gitignore:45` | `git ls-files` shows adjoe CV PDF + CL DOCX + PDF | **Still open** — `git rm --cached` (needs approval). |
| **D-10** | Committed absolute local paths incl. a third-party name | `applications/.../booking.../source/initial_generation_result.json:4-6` | **Still open.** |
| **D-11** | Saved applications have inconsistent schemas (`application_context.txt`/`.json`, `posting.txt`, `job_posting.json`, `application_form.json`, `finalize_booking.py`) | `applications/**` listing | Define one schema; migrate. **Phase 2.** |
| **D-12** | ~~Two near-identical `_escape_latex` and three `_slugify` implementations~~ **RESOLVED in Phase 1** | `latex_renderer.py:349,357`, `docx_renderer.py:130,143`, `tailor_service.py:29` | **Consolidated** into `utils/text.py`. Behaviour was verified identical to both originals across the escaping edge cases — including the pre-existing quirk where the braces in `\textbackslash{}` are themselves escaped — and that is now pinned by a test. |
| **D-13** | `outputs/<job_id>/latex_work/` scratch dir created inside the deliverable folder | `docx_renderer.py:264` | **Still open.** Use a temp dir. |
| **D-14** | Failed generations leave a partial `outputs/<job_id>/` with no `generation_result.json` | verified in master worktree: adjoe dir lacks the manifest | **Partially addressed:** failures write an explicit `status: failed` manifest through `ApplicationStore.save_failure`. Pinning this in a test was deferred — `docx_renderer.py:264` can still leave residue. |
| **D-15** | `except:` bare clauses swallow errors | `latex_renderer.py:294`, `docx_renderer.py:97,376` | **Still open.** Narrow. |

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
| `main.py` endpoints | Zero API tests (incl. the `job_id` containment question) |
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

**LLM calls per application** (VERIFIED from control flow)

| Case | Arithmetic | Logical calls |
|---|---|---|
| Minimum | 1 draft + 1 review + 1 letter | **3** |
| Typical (1 layout retry) | 3 + 1 | **4** |
| Max successful (fits on 4th render) | 3 + 3 | **6** |
| Worst (validation retries exhausted) | 6 `generate` × 3 | **18** |
| HTTP ceiling (`_call_gemini` retries ×3) | 18 × 3 | **54** |

**Estimated cost per application** (`gemini-3.8-flash`, $0.75 / $3.75 per 1M):

| Case | Input tok | Output tok | Cost |
|---|---|---|---|
| Best (3 calls) | 19,145 | 3,322 | **$0.027** |
| Typical (4 calls) | 34,601 | 6,022 | **$0.049** |
| Worst (6 calls) | 65,513 | 11,422 | **$0.092** |

**Dominant inefficiency:** every CV call re-sends ~6,150 tokens of identical
prompt+profile+JD context. The editorial-review pass alone is ~25% of total input tokens,
and each layout retry re-sends the entire context *plus* the full previous CV JSON
(≈7,730 tokens) to produce a shorter variant.

**Optimization opportunities (evidence-based, in priority order)**

1. **Targeted layout retry instead of full regeneration** — send only the sections to shorten
   as a delta. Est. **25–45%** of typical-case input cost.
2. **Remove or merge the editorial-review pass** — fold its instructions into the draft
   prompt. Est. **~25%** of input tokens and one call.
3. **Enable structured output** (`response_schema`) — removes the parse-failure retry loop,
   the dominant tail risk.
4. **Serialize the profile once** per application rather than per call.
5. **Cache validated results** — re-rendering already costs 0 LLM calls; extend that
   principle to "same profile + same JD → reuse".

*Do not add async, concurrency or caching infrastructure before 1–5 are exhausted.*

---

## 6. Security and privacy

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

---

## 7. Documentation consistency

| Document | State |
|---|---|
| `AGENTS.md` (13 lines) | Accurate and concise. **Keep as the single entry point.** |
| `README.md` | Accurate; correctly documents the render path. |
| `docs/MAC_SETUP.md` | Accurate and genuinely portable. |
| `.agents/skills/cv-tailor-application/SKILL.md` | Accurate and detailed. |
| `.github/copilot-instructions.md` | **Largely obsolete/contradictory** (D-8) — describes Tectonic, `gemini-1.5-flash`, a non-existent endpoint and directory. |

There is no `docs/ARCHITECTURE.md`, `ROADMAP.md`, `PROJECT_STATE.md`, or decisions log —
which is why project knowledge currently lives in conversation history.

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
