# Testing

This is the source of truth for test commands, CI coverage, and known limits. Run commands from the repository root with the checkout's virtual environment active. Use `.venv\Scripts\python.exe` on Windows and `.venv/bin/python` on macOS/Linux.

## Baseline

Run the full deterministic suite:

```sh
python -m pytest -q
```

The Windows working tree on `refactor/architecture-v2` passed the full suite with MiKTeX on 2026-11-27. The result was **1,793 passed, 3 skipped**, with one Google SDK deprecation warning. This run included the correction to the layout-retry test for the draft-relative word budget. The earlier PR #1 macOS run with MacTeX passed **1,786 tests with 3 skipped**.

Tests are offline and make no paid provider calls. `requires_latex` tests skip when `pdflatex` is unavailable. To run the fast suite without those tests:

```sh
python -m pytest -q -m "not requires_latex"
```

On Windows, sandbox-launched Python may inherit a Low Mandatory Level and fail writing to the system temp directory. If a LaTeX test reports a compilation failure, first rerun with temporary directories inside the checkout:

```powershell
$env:TEMP = "$PWD\.tmp"
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
$env:TMP = $env:TEMP
python -m pytest -q
```

This is an environment workaround, not a reason to ignore a reproducible product failure. See [DEVELOPMENT.md](DEVELOPMENT.md#windows-python-output-permission-error-windows-only) for diagnosis.

## CI and test layers

CI runs the deterministic suite on Ubuntu, Windows, and macOS; the LaTeX-marked suite runs on Ubuntu. `pytest.ini` enables strict marker checking. The `network` marker is reserved for tests that need network access; CI must not require a paid API.

| Layer | CI | Paid provider calls |
|---|---:|---:|
| Unit and characterization tests | Yes | No |
| Offline integration tests using fixtures or recorded responses | Yes | No |
| CLI and UI tests with stubbed services | Yes | No |
| Document rendering and validation | Yes; LaTeX tests skip without `pdflatex` | No |
| Live model evaluation (`python -m evaluation --live`) | No | Yes, explicit opt-in and budget capped |

Do not run live generation or live evaluation as part of routine verification. Ask the owner before any paid generation. `cvtailor doctor --verify-key` contacts the configured provider but does not generate content.

## Focused checks

Use a focused test while iterating, then run the full suite for code changes:

```sh
python -m pytest -q tests/test_cli.py
python -m pytest -q tests/test_profile_loading.py tests/test_candidate_guidance.py
python -m pytest -q tests/test_suggested_claims.py tests/test_claims_cli.py
python -m pytest -q tests/test_ui_review.py -k claim
python -m pytest -q tests/test_renderers_documents.py tests/test_output_parity.py
python -m pytest -q tests/test_check_saved_applications.py
```

Check the repository's current test filenames before using a focused command; tests may move as the code changes. For paid model curation, the procedure is [the model curation skill](../.agents/skills/cv-model-curation/SKILL.md); this document only records the test boundary. The evaluation module's offline checks are part of pytest. Live evaluation is a separate, budgeted activity described in that skill and [ADR 0016](DECISIONS/0016-per-candidate-inputs-and-one-winner.md).

## What the suite does not establish

- Green tests do not establish that a real user's profile, saved applications, or private store are correct. Use the free `applications check` workflow in [HOW_TO_GENERATE.md](HOW_TO_GENERATE.md#checking-saved-applications-against-the-current-rules).
- Render tests and page-count checks do not replace visual review of a real CV and cover letter. Inspect PDF and DOCX outputs when validating document changes.
- Offline fixtures do not verify live provider availability, pricing, or model quality.
- `tests/test_private_store_sync.py` simulates replication, staged arrival, and conflict recovery with disposable local stores. It does not verify Syncthing transport between two machines. The separate [private-store sync pilot](PRIVATE_STORE_SYNC.md) is a synthetic-only plan; its live two-peer status is recorded there.
- No test establishes universal ATS compatibility.

For the current implementation and task status, see [PROJECT_STATE.md](PROJECT_STATE.md#current-work) and [ASSESSMENT.md](ASSESSMENT.md). This file intentionally avoids a per-test historical inventory and dated milestone chronology; use Git history for those details.
