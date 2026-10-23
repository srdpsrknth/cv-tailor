# Testing

**Baseline command:** `python -m pytest -q` (run from the repository root)
**Current baseline:** **12 passed**, 1 warning, ~2.5 s, fully offline — no API calls, no LaTeX required.

---

## Sandbox caveat (Windows, DSH)

Under the DSH `workspace-write` sandbox, **8 of the 12 tests error** with
`PermissionError: [WinError 5]` while pytest sets up or cleans up its `tmp_path` trees.
The sandbox blocks the ACL operations pytest performs on temp directories.

**This is an environment artifact, not a code failure.** The same suite passes 12/12 when run
outside the sandbox. Do not "fix" the tests for this.

If you must run confined, point the base temp at the workspace, though the sandbox may still
deny it:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp .runtime/pytest-tmp
```

Leftover `pytest-cache-files-*` directories in the repo root are sandbox artifacts and may
need an unconfined delete.

---

## What is tested today

| File | Covers |
|---|---|
| `tests/test_tailor_service.py` | Layout retry + fenced-JSON acceptance; 3-page CV never reported as success; short-letter correction; truncated JSON and unreadable PDF rejection; country-context propagation; invented-tool and altered-date rejection; sign-off-in-body rejection; Streamlit country selector |
| `tests/test_docx_renderer.py` | XML-sensitive text preserved in the DOCX |
| `tests/test_portability.py` | pdflatex discovery (Windows user paths, `LATEX_COMPILER` override) |

`tests/test_tailor_service.py` **mocks** `GeminiService` and both renderers. That keeps the
suite fast and offline, but it also means **real LaTeX and DOCX output is not
regression-protected** — the page-count gate is only exercised against synthetic blank PDFs.

---

## What is NOT tested (the gaps to close first)

- `profile_loader` validation, malformed profiles, and future migrations
- Real LaTeX and DOCX rendering output
- `backend/main.py` endpoints (including `job_id` containment)
- `scripts/render_application.py` — the deterministic re-render path, i.e. the most-used
  revision route
- Cross-profile contamination (no second profile exists yet)
- Token/cost accounting (`calculate_token_usage`)
- The `DocxRenderer` in-place mutation of `cl.paragraphs`

---

## Required before any structural change

1. **Golden fixtures** — ≥2 synthetic profiles with obviously fake data, 3 anonymised job
   descriptions, and recorded LLM responses as JSON. Never commit real personal data.
2. **Characterization tests** for every workflow in `ASSESSMENT.md` §1, asserting behaviour
   rather than internals.
3. **Document-level assertions** — extract text with `pypdf`; assert page count, required
   sections, word counts, no clipping and no orphan headings.
4. **A determinism test** for `render_application.py`: identical `content.json` → identical
   page count.
5. **An offline end-to-end test** driving the pipeline with a recorded-response fake.
6. **A performance harness** recording LLM call count, tokens and wall time per run.

---

## Test layers

| Layer | Runs in CI | Calls a paid API |
|---|---|---|
| Unit / characterization | Yes | No |
| Integration (fixtures, offline) | Yes | No |
| CLI smoke tests | Yes | No |
| Document output validation | Yes (if LaTeX available) | No |
| **LLM quality evaluation** | **No — opt-in** | **Yes, budget-capped** |

Keep deterministic software testing and LLM quality evaluation strictly separate. CI
(`.github/workflows/tests.yml`) must never require a paid API call.

---

## Reference measurements (2026-10-23)

| Metric | Value |
|---|---|
| `python -m pytest -q` | 12 passed, 2.45 s |
| Backend `import main` | ≈ 1.7–2.0 s |
| `load_profile()` | 169 ms |
| pdflatex per run | ≈ 2.9 s (run twice per compile) |
| LLM calls: min / typical / max / worst | 3 / 4 / 6 / 18 |
| Cost per application (`gemini-3.8-flash`) | $0.027 / $0.049 / $0.092 |
