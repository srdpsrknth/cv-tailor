# Testing

**Baseline command:** `python -m pytest -q` (run from the repository root)
**Current baseline:** **141 passed**, 1 warning, ~100 s, fully offline — no paid API calls.

| | |
|---|---|
| Baseline before Milestone 1.1 | 12 passed, ~2.5 s |
| Baseline after Milestone 1.1 | **141 passed**, ~100 s |
| Paid API calls | **none** — verified with `GEMINI_API_KEY` unset |
| Requires | `pypdf`, `python-docx`; `pdflatex` for the document-level tests (they skip without it) |

The suite grew from 12 to 141 tests in Milestone 1.1. The runtime increase is almost
entirely `pdflatex`: real rendering is now exercised instead of mocked.

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

# Fast lane: no pdflatex, ~6 s
.venv\Scripts\python.exe -m pytest -q -m "not requires_latex"

# Only the new characterization suite
.venv\Scripts\python.exe -m pytest -q tests/test_profile_loading.py tests/test_tailoring_pipeline.py

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
| `test_tailoring_pipeline.py` | 70 | CV tailoring, cover-letter generation, LLM response parsing, factual validation, retry handling, error handling, token accounting, cross-profile isolation |
| `test_renderers_documents.py` | 34 | **Real** LaTeX CV and DOCX cover letters: page geometry, required sections, verbatim bullets, clipping, orphan headings, LaTeX escaping, word counts, page-count gate |
| `test_render_application_determinism.py` | 11 | `scripts/render_application.py` end to end as a subprocess: identical content → identical page count *and* identical text, in-place stability, manifest handling, residue cleanup, failure paths |
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
| 15 | Saved-application restoration | `test_render_application_determinism.py` |

---

## Fixtures

`tests/fixtures/` holds **synthetic-only** data; see its
[README](../tests/fixtures/README.md). Verified free of real personal data.

| Path | Contents |
|---|---|
| `profiles/synthetic_analyst.yaml` | Profile A — includes an employer with no bullets, selected projects, certifications and a visa status |
| `profiles/synthetic_marketer.yaml` | Profile B — deliberately different shape: no projects, no visa, no certifications |
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

- **`backend/main.py` endpoints** — still zero API tests, including the `job_id` containment
  question (§6). The `job_id` collision risk (A-9) is likewise unexercised.
- **`DocxRenderer` in-place mutation** (A-7) — `docx_renderer.py:304-307` mutates
  `cl.paragraphs`. The bug is still real and unfixed; there is no test pinning it.
- **Cost/token accounting correctness** (D-3) — `calculate_token_usage` totals are asserted
  through `tailor_documents`, but the flat-rate pricing error itself is not caught. The
  offline double replaces the real calculator.
- **`--mirror-configured` end to end** — mirroring is asserted only for the *failure* case
  (nothing is published). The success path is untested.
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
| CLI smoke tests | Yes | No |
| Document output validation | Yes (skips without LaTeX) | No |
| **LLM quality evaluation** | **No — opt-in** | **Yes, budget-capped** |

Keep deterministic software testing and LLM quality evaluation strictly separate. CI
(`.github/workflows/tests.yml`) must never require a paid API call.

---

## Reference measurements (2026-10-23)

| Metric | Value |
|---|---|
| `python -m pytest -q` (before M1.1) | 12 passed, 2.45 s |
| `python -m pytest -q` (after M1.1) | **141 passed**, ~100 s |
| Fast lane `-m "not requires_latex"` | 113 passed, 28 deselected, ~6 s |
| `test_renderers_documents.py` | 34 passed, ~20 s |
| `test_render_application_determinism.py` | 11 passed, ~73 s |
| Backend `import main` | ≈ 1.7–2.0 s |
| `load_profile()` | 169 ms |
| pdflatex per run | ≈ 2.9 s (run twice per compile) |
| LLM calls: min / typical / max / worst | 3 / 4 / 6 / 18 |
| Cost per application (`gemini-3.8-flash`) | $0.027 / $0.049 / $0.092 |
