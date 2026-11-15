# Initialize CV Tailor on a Mac

This guide is for the owner and the LLM assisting on a fresh Mac. The project was developed on Windows. Recreate its environment on macOS; do not copy `.venv` or use Windows drive paths.

## What is included

The repository contains the FastAPI backend, Streamlit UI, templates, prompts, tests, locked Python dependencies and a reusable agent skill. It does **not** contain the real profile or the reviewed application sources — since Phase 2 those live in the **private profile store** (`CVTAILOR_STORE`), which is not this repository. API credentials are likewise never committed. If you are moving the owner's real work to the Mac, transfer the store as well as the clone: either copy the store directory, or clone its own private Git repository (ADR 0011).

## Prerequisites

Install Git, Python 3.12, and **MacTeX**. MacTeX supplies the full TeX Live distribution and fonts needed for the CV and cover-letter templates. The project runs `pdflatex`; Tectonic is not used. Official installer: https://www.tug.org/mactex/ . MacTeX places TeX commands at `/Library/TeX/texbin`; restart the terminal after installation.

> **TeX on PATH, and why it usually doesn't matter any more.** The TeX installer adds
> `/Library/TeX/texbin` to PATH only for *login* shells, so a script, an IDE or a CI
> runner may not see `pdflatex` even on a correct installation. The renderer now
> searches `/Library/TeX/texbin/pdflatex` (plus `/opt/homebrew/bin` and
> `/usr/local/bin`) explicitly, so this should work without further configuration.
> If it still cannot be found, set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` in
> `.env` and re-run `cvtailor doctor`.

If Homebrew is already installed, `brew install python@3.12 git` can provide Python/Git. Homebrew's supported prefixes differ on Apple Silicon and Intel; use `brew --prefix` rather than hardcoding `/opt/homebrew` or `/usr/local`. Official Homebrew installation instructions: https://docs.brew.sh/Installation . Ask the owner to complete system installer/password prompts when necessary.

Optional visual QA tools: LibreOffice (render DOCX independently) and Poppler (`pdftoppm`, `pdfinfo`). `brew install poppler` and the LibreOffice official installer can provide these. PDF generation itself uses LaTeX and does not need LibreOffice.

## Clone and initialize

```bash
git clone https://github.com/srdpsrknth/cv-tailor.git
cd cv-tailor
python3.12 scripts/setup.py
```

If `python3.12` is not found after Homebrew installation, use `$(brew --prefix python@3.12)/bin/python3.12`. Setup creates `.venv`, installs `requirements.lock.txt`, and creates `.env` from `.env.example` without overwriting existing settings.

### Credentials and model (current as of Phase 3)

**The default provider is OpenRouter, and the default model is `openai/gpt-6-luna`**
— the model the curation study selected on measured cost per accepted result
(ADR 0016). Have the owner put `OPENROUTER_API_KEY` into `.env` directly; get a key
from https://openrouter.ai/settings/keys, and note that the account **needs credit**.

Do not ask them to paste a key into chat or log it.

* **Gemini still works** but is no longer the default: set
  `CVTAILOR_PROVIDER=gemini` and provide `GEMINI_API_KEY`. Note that the Google-routed
  path reports `cost: 0` and carries the real figure in
  `cost_details.upstream_inference_cost`.
* **`GEMINI_MODEL` is deliberately ignored unless the provider is Gemini.** A leftover
  value cannot redirect the default run — this was a real bug once: an existing
  `GEMINI_MODEL=gemini-3.8-flash` silently overrode the new default and ran the old
  model through OpenRouter, where the bare name is not even a priced route. Use
  `CVTAILOR_MODEL` for the provider-neutral override.
* **Do not silently change the model.** If generation fails, inspect the error and ask
  the owner; a fresh installation needs its own credentials and its own credit.

A generation costs roughly **$0.003** on the default model. Optional guard:
`CVTAILOR_MAX_COST_USD` refuses a run whose *estimated* cost exceeds the cap.

Start with `OUTPUTS_DIR=outputs`. If mirroring to OneDrive, ask for the actual local Mac folder; Windows OneDrive paths are invalid. A relative outputs path resolves against the clone. Set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` if the shell does not find the compiler.

Point the project at the store and name the candidate. Both are required; a missing profile id fails rather than guessing:

```bash
export CVTAILOR_STORE="$HOME/cv-tailor-data"   # wherever the store was transferred
export CVTAILOR_PROFILE_ID=<profile_id>
```

To make these permanent rather than per-terminal, put them in `.env`:

```
CVTAILOR_STORE=/Users/<you>/cv-tailor-data
CVTAILOR_PROFILE_ID=<profile_id>
```

`cvtailor profile list` shows the available ids; `cvtailor doctor` reports whether the store was found.

```bash
.venv/bin/python scripts/check_setup.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/start.py
```

Open http://localhost:8501 . The backend is at http://localhost:8000 and its interactive API docs at `/docs`. Keep the startup terminal open; Ctrl+C stops both services. Logs are in `.runtime/logs/`. Startup checks ports and will not kill unrelated applications. For changed backend ports, set `BACKEND_URL` in `.env` as well.

### The CLI is the supported path today

The Streamlit UI at :8501 is **unrefactored** — it predates multi-profile and does not
send a `profile_id`, so it works only where `.env` happens to set one. **Prefer the
CLI** until Phase 6 lands:

```bash
.venv/bin/python cvtailor.py doctor
.venv/bin/python cvtailor.py --profile-id "$CVTAILOR_PROFILE_ID" generate --job-file job.txt
```

Day-to-day use is documented in [HOW_TO_GENERATE.md](HOW_TO_GENERATE.md); every command
there works on macOS with `.venv/bin/python` in place of `.venv\Scripts\python.exe`.

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

## Validate rendering before spending API tokens

Restore the reviewed Delivery Hero package from the store:

```bash
cp -R "$CVTAILOR_STORE"/applications/2026_delivery_hero_senior_analytics_engineer_quick_commerce_1791209030470 "$CVTAILOR_STORE"/outputs/"$CVTAILOR_PROFILE_ID"/
.venv/bin/python "$CVTAILOR_STORE"/outputs/"$CVTAILOR_PROFILE_ID"/2026_delivery_hero_senior_analytics_engineer_quick_commerce_1791209030470/source/render_application.py
```

Its application-specific script preserves compact technology lists and the deliberate ecoligo continuation heading. The archived script renders both documents. It derives all repository paths from the restored folder. Other packages can be restored in the same way; when no custom script exists:

```bash
.venv/bin/python scripts/render_application.py --project . --profile-id "$CVTAILOR_PROFILE_ID" --content "$CVTAILOR_STORE"/outputs/"$CVTAILOR_PROFILE_ID"/<job_id>/source/content.json --mirror-configured
```

Use `--cv-only` or `--cover-letter-only` for a scoped revision. `content.json` is the reviewed text authority; model drafts are historical evidence, not replacement text. Old result metadata is regenerated locally. Older Booking helper scripts are retained for reference; prefer the current editable JSON and renderer.

Check the CV has two pages and the letter one page, then visually inspect page breaks, fonts and signatures. If Poppler is installed, `pdftoppm -png <file.pdf> <prefix>` creates page images. Use LibreOffice to separately render the DOCX; its layout is not identical to the LaTeX PDF. Fonts, TeX versions and dates can change rendering, so byte-identical PDFs are not promised.

Only after local rendering succeeds, test one new job through Streamlit. Live AI generation uses internet/API quota and may cost money. Choose actual country of employment. The flow tailors skills and wording, reviews factual claims, and retries oversize documents, but the owner must review each final application.

## Troubleshooting and handoff

- Missing TeX packages: use the full MacTeX distribution and its TeX Live package manager; do not replace the document templates to work around missing packages.
- `pdflatex` missing: verify `/Library/TeX/texbin/pdflatex` exists, then configure `LATEX_COMPILER` or PATH.
- Missing Python packages: install using `.venv/bin/python -m pip`, never a global pip.
- API authentication/model/quota failure: inspect the error without exposing credentials. Ask for account/model correction if required.
- Word font differences: the DOCX requests Aptos; availability can vary on Mac. Inspect the actual Word/LibreOffice rendering.
- API download failure: verify `OUTPUTS_DIR` uses a Mac path and that the generated job folder exists.

Report setup checks, tests and actual render results. Unit tests alone do not prove that Gemini generation, LaTeX or Word work. The Windows environment was tested before push; macOS must run the validation steps above. Preserve existing application edits and do not submit applications or contact employers during setup.
