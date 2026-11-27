# Initialize CV Tailor on a Mac

This guide is for a user (and any LLM assisting them) setting up CV Tailor on a fresh Mac. It is the macOS peer of the Windows instructions in `docs/DEVELOPMENT.md`; Linux works the same way with your package manager in place of Homebrew. Build the environment natively on the Mac: do not copy a `.venv` from another operating system or reuse Windows drive paths.

## What is included

The repository contains the FastAPI backend, Streamlit UI, templates, prompts, tests, locked Python dependencies and a reusable agent skill. It does **not** contain the real profile or the reviewed application sources — since Phase 2 those live in the **private profile store** (`CVTAILOR_STORE`), which is not this repository. API credentials are likewise never committed. If you are moving an existing user's real work to the Mac, transfer the store as well as the clone: either copy the store directory, or clone its own private Git repository (ADR 0011).

## Prerequisites

Install Git, Python 3.12, and **MacTeX**. MacTeX supplies the full TeX Live distribution and fonts needed for the CV and cover-letter templates. The project runs `pdflatex`; Tectonic is not used. Official installer: https://www.tug.org/mactex/ . MacTeX places TeX commands at `/Library/TeX/texbin`; restart the terminal after installation.

> **TeX on PATH, and why it usually doesn't matter any more.** The TeX installer adds
> `/Library/TeX/texbin` to PATH only for *login* shells, so a script, an IDE or a CI
> runner may not see `pdflatex` even on a correct installation. The renderer now
> searches `/Library/TeX/texbin/pdflatex` (plus `/opt/homebrew/bin` and
> `/usr/local/bin`) explicitly, so this should work without further configuration.
> If it still cannot be found, set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` in
> `.env` and re-run `cvtailor doctor`.

If Homebrew is already installed, `brew install python@3.12 git` can provide Python/Git. Homebrew's supported prefixes differ on Apple Silicon and Intel; use `brew --prefix` rather than hardcoding `/opt/homebrew` or `/usr/local`. Official Homebrew installation instructions: https://docs.brew.sh/Installation . Ask the user to complete system installer/password prompts when necessary.

Optional visual QA tools: LibreOffice (render DOCX independently) and Poppler (`pdftoppm`, `pdfinfo`). `brew install poppler` and the LibreOffice official installer can provide these. PDF generation itself uses LaTeX and does not need LibreOffice.

## Clone and initialize

```bash
git clone --branch refactor/architecture-v2 https://github.com/srdpsrknth/cv-tailor.git
cd cv-tailor
python3.12 scripts/setup.py
```

If `python3.12` is not found after Homebrew installation, use `$(brew --prefix python@3.12)/bin/python3.12`. Setup creates `.venv`, installs `requirements.lock.txt`, and creates `.env` from `.env.example` without overwriting existing settings.

> **Use a native Python on Apple Silicon.** An Intel (x86_64) Python running under Rosetta,
> for example an old Anaconda install, cannot install some locked wheels (`cryptography` 50.x has
> no macOS x86_64 wheel). `scripts/setup.py` checks an existing `.venv`'s Python version and CPU
> architecture and stops with a message if they don't match the machine. Move `.venv` aside
> and rerun setup with a native arm64 Python 3.12 (Homebrew `python@3.12`, the python.org
> universal installer, or an arm64 conda environment). Setup never deletes `.venv` itself.

### Credentials and paths

Set the provider key directly in the local `.env`. See [the configuration template](../.env.example) for provider-specific keys, model overrides and the cost limit. OpenRouter requires credit. The [user guide](HOW_TO_GENERATE.md) explains the cost summary and which actions make a provider call.

Start with `OUTPUTS_DIR=outputs`. If mirroring to OneDrive, ask for the actual local Mac folder; Windows OneDrive paths are invalid. A relative outputs path resolves against the clone. Set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` if the shell does not find the compiler.

Point the project at the transferred private store and set a candidate ID for commands run from this terminal:

```bash
export CVTAILOR_STORE="$HOME/cv-tailor-data"   # wherever the store was transferred
export CVTAILOR_PROFILE_ID='<profile_id>'
```

To make these permanent rather than per-terminal, put them in `.env`:

```
CVTAILOR_STORE=/Users/<you>/cv-tailor-data
CVTAILOR_PROFILE_ID=<profile_id>
```

`cvtailor profile list` shows the available ids; `cvtailor doctor` reports whether the store was found.
The default setup check reads the selected provider's configuration locally. To
verify the configured credential with that provider, run
`.venv/bin/python scripts/check_setup.py --verify-key`.

```bash
.venv/bin/python scripts/check_setup.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/start.py
```

Open the UI URL printed by `start.py`. The API's interactive documentation is at `/docs` on the printed API URL. Use Ctrl+C from the startup terminal or `scripts/start.py --stop` with the checkout's virtual environment. See the [user guide](HOW_TO_GENERATE.md) for daily CLI and GUI workflows.

### Check the free paths before anything that costs money

Job search and re-rendering are **free** — no API key, no AI call, no LaTeX cost beyond
the local compiler. Run these first; if they work, the installation is sound:

```bash
# Free: job discovery (public APIs, no credentials)
.venv/bin/python cvtailor.py jobs sources
.venv/bin/python cvtailor.py --profile-id "$CVTAILOR_PROFILE_ID" jobs search --keywords "data engineer" --limit 3

# Free: re-render an existing application from its editable text
.venv/bin/python cvtailor.py --profile-id "$CVTAILOR_PROFILE_ID" render \
    --content "$CVTAILOR_STORE/outputs/$CVTAILOR_PROFILE_ID/<job_id>/source/content.json"
```

That render step is the real LaTeX test: it exercises the templates, the compiler and
the page-count gate without spending anything.

After pulling a new version, also run the free post-pull check. It re-validates every saved
application against the current rules, offline, never writes to the store, and exits with
code 1 on any FAIL (add `--render` to re-render into a temporary folder and report page counts):

```bash
.venv/bin/python cvtailor.py --profile-id "$CVTAILOR_PROFILE_ID" applications check
```

## Validate rendering before spending API tokens

Prove the whole render path (templates, LaTeX, DOCX) on your Mac without an API key or any spend. Use either your own profile or the synthetic sample that ships with the tests.

**Option A: your own profile.** Run one free local render (no AI call) from a `content.json` you already have, as in the previous section. If you have none yet, create a minimal one from your own profile: copy `tests/fixtures/content/valid_content.json` to `<store>/outputs/<profile_id>/first_render_check/source/content.json` and replace the placeholder company, role, summary, experience entries and the cover-letter paragraphs and `signature_name` with text drawn from your own profile (the CV must match the facts in `profile.yaml`; the cover letter needs four paragraphs of 290-310 words in total to avoid a review warning).

**Option B: synthetic sample (no personal data).** Import the synthetic profile into a throwaway store and render its fixture content:

```bash
export CVTAILOR_STORE="$PWD/.tmp/sample-store"
.venv/bin/python cvtailor.py --profile-id sample-analyst profile import tests/fixtures/profiles/synthetic_analyst.yaml
mkdir -p "$CVTAILOR_STORE/outputs/sample-analyst/first_render_check/source"
cp tests/fixtures/content/valid_content.json "$CVTAILOR_STORE/outputs/sample-analyst/first_render_check/source/content.json"
.venv/bin/python cvtailor.py --profile-id sample-analyst render \
    --content "$CVTAILOR_STORE/outputs/sample-analyst/first_render_check/source/content.json"
```

`render` writes the CV PDF, an autofill DOCX and the cover letter DOCX and PDF beside `source/`, and reports page counts. Expect a one-page CV for this short sample and a four-paragraph, 300-word, one-page letter. `.tmp/` is disposable; reset `CVTAILOR_STORE` afterwards (`unset CVTAILOR_STORE` or re-source your shell profile) so later commands use your real store.

Other saved applications can be restored the same way: copy `<store>/applications/<job_id>/` into `<store>/outputs/<profile_id>/`, then run its own `source/render_application.py` if it has one (it preserves application-specific layout tweaks), or otherwise the generic renderer:

```bash
.venv/bin/python scripts/render_application.py --project . --profile-id "$CVTAILOR_PROFILE_ID" --content "$CVTAILOR_STORE"/outputs/"$CVTAILOR_PROFILE_ID"/<job_id>/source/content.json --mirror-configured
```

Use `--cv-only` or `--cover-letter-only` for a scoped revision. `content.json` is the reviewed text authority; model drafts are historical evidence, not replacement text. Old result metadata is regenerated locally.

Check the CV has two pages and the letter one page, then visually inspect page breaks, fonts and signatures. If Poppler is installed, `pdftoppm -png <file.pdf> <prefix>` creates page images. Use LibreOffice to separately render the DOCX; its layout is not identical to the LaTeX PDF. Fonts, TeX versions and dates can change rendering, so byte-identical PDFs are not promised.

Only after local rendering succeeds, test one new job through Streamlit. Live AI generation uses internet/API quota and may cost money. Choose actual country of employment. The flow tailors skills and wording, reviews factual claims, and retries oversize documents, but you must review each final application.

## Troubleshooting and handoff

- Missing TeX packages: use the full MacTeX distribution and its TeX Live package manager; do not replace the document templates to work around missing packages.
- `pdflatex` missing: verify `/Library/TeX/texbin/pdflatex` exists, then configure `LATEX_COMPILER` or PATH.
- Missing Python packages: install using `.venv/bin/python -m pip`, never a global pip.
- API authentication/model/quota failure: inspect the error without exposing credentials. Ask for account/model correction if required.
- Word font differences: the DOCX requests Aptos; availability can vary on Mac. Inspect the actual Word/LibreOffice rendering.
- API download failure: verify `OUTPUTS_DIR` uses a Mac path and that the generated job folder exists.

Report setup checks, tests and actual render results. Unit tests alone do not prove that Gemini generation, LaTeX or Word work. Run the validation steps above on each new machine, whatever its OS. Preserve existing application edits and do not submit applications or contact employers during setup.
