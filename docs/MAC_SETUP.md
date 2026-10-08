# Initialize CV Tailor on a Mac

This guide is for the owner and the LLM assisting on a fresh Mac. The project was developed on Windows. Recreate its environment on macOS; do not copy `.venv` or use Windows drive paths.

## What is included

The repository contains the latest profile, FastAPI backend, Streamlit UI, templates, prompts, tests, locked Python dependencies, a reusable agent skill, and reviewed application sources under `applications/`. API credentials and generated application PDFs/DOCX are not part of fresh output commits. Three adjoe documents were already tracked historically. Existing output files can also be transferred from OneDrive.

## Prerequisites

Install Git, Python 3.12, and **MacTeX**. MacTeX supplies the full TeX Live distribution and fonts needed for the CV and cover-letter templates. The project runs `pdflatex`; Tectonic is not used. Official installer: https://www.tug.org/mactex/ . MacTeX places TeX commands at `/Library/TeX/texbin`; restart the terminal after installation.

If Homebrew is already installed, `brew install python@3.12 git` can provide Python/Git. Homebrew's supported prefixes differ on Apple Silicon and Intel; use `brew --prefix` rather than hardcoding `/opt/homebrew` or `/usr/local`. Official Homebrew installation instructions: https://docs.brew.sh/Installation . Ask the owner to complete system installer/password prompts when necessary.

Optional visual QA tools: LibreOffice (render DOCX independently) and Poppler (`pdftoppm`, `pdfinfo`). `brew install poppler` and the LibreOffice official installer can provide these. PDF generation itself uses LaTeX and does not need LibreOffice.

## Clone and initialize

```bash
git clone https://github.com/srdpsrknth/cv-tailor.git
cd cv-tailor
python3.12 scripts/setup.py
```

If `python3.12` is not found after Homebrew installation, use `$(brew --prefix python@3.12)/bin/python3.12`. Setup creates `.venv`, installs `requirements.lock.txt`, and creates `.env` from `.env.example` without overwriting existing settings.

Have the owner enter `GEMINI_API_KEY` into `.env` directly. Do not ask them to paste it into chat or log it. The example retains `GEMINI_MODEL=gemini-3.8-flash`, the existing project configuration. Model availability/quota must be checked with the owner's account if a generation fails; do not silently change the model. A fresh installation needs its own credentials.

Start with `OUTPUTS_DIR=outputs`. If mirroring to OneDrive, ask for the actual local Mac folder; Windows OneDrive paths are invalid. A relative outputs path resolves against the clone. Set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` if the shell does not find the compiler.

```bash
.venv/bin/python scripts/check_setup.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/start.py
```

Open http://localhost:8501 . The backend is at http://localhost:8000 and its interactive API docs at `/docs`. Keep the startup terminal open; Ctrl+C stops both services. Logs are in `.runtime/logs/`. Startup checks ports and will not kill unrelated applications. For changed backend ports, set `BACKEND_URL` in `.env` as well.

## Validate rendering before spending API tokens

Restore the reviewed Delivery Hero package:

```bash
cp -R applications/2026_delivery_hero_senior_analytics_engineer_quick_commerce_1791209030470 outputs/
.venv/bin/python outputs/2026_delivery_hero_senior_analytics_engineer_quick_commerce_1791209030470/source/render_application.py
```

Its application-specific script preserves compact technology lists and the deliberate ecoligo continuation heading. The archived script renders both documents. It derives all repository paths from the restored folder. Other packages can be restored in the same way; when no custom script exists:

```bash
.venv/bin/python scripts/render_application.py --project . --content outputs/<job_id>/source/content.json --mirror-configured
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
