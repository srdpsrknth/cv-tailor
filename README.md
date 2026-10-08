# CV Tailor

Generate job-specific CV PDFs and cover letters (DOCX and PDF) from the authoritative YAML profile, using Gemini, FastAPI and Streamlit.

**Fresh Mac setup:** read [docs/MAC_SETUP.md](docs/MAC_SETUP.md). The assisting LLM should read [AGENTS.md](AGENTS.md) and the [application skill](.agents/skills/cv-tailor-application/SKILL.md).

## Quick start

Install Python 3.11+ (3.12 recommended), Git, and a full pdflatex distribution: MacTeX on Mac, MiKTeX on Windows, or TeX Live on Linux. Tectonic is not used.

```bash
git clone https://github.com/srdpsrknth/cv-tailor.git
cd cv-tailor
python3.12 scripts/setup.py
# Enter GEMINI_API_KEY in .env
.venv/bin/python scripts/check_setup.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/start.py
```

On Windows, use `python scripts/setup.py` and `.venv/Scripts/python.exe` instead. Setup preserves existing .env files and installs the recorded working versions from requirements.lock.txt. Direct dependencies for intentional upgrades are in requirements.txt. Model availability and quota depend on the Gemini account.

Open http://localhost:8501; API docs: http://localhost:8000/docs. Keep the startup terminal open; Ctrl+C stops both services. Logs stay in .runtime/logs. Credentials are excluded from Git and must be configured per machine. Optional LibreOffice and Poppler are useful for visual QA; cover-letter PDF generation uses LaTeX.

## Generation and revision

Paste the posting and select company, role, and actual country of employment. The flow tailors wording and skills, reviews claims against the profile, renders documents, and retries oversize outputs. Success requires a CV of at most two pages and a one-page letter PDF with four body paragraphs and 290–310 words. Review the factual claims and layouts before applying; these checks do not guarantee screening outcomes.

The source profile is storage/profile/profile.yaml. Country context overrides inferred location. Overseas CVs show German-issued Blue Card status; employer permit support belongs only in the cover letter.

Each application lives in outputs/{year}_{company}_{role}_{timestamp}/. Final documents are at the top level; source/content.json is editable text, alongside the posting, profile snapshot, drafts and generation metadata. OUTPUTS_DIR defaults to outputs; an absolute path can mirror documents and editable sources elsewhere. Relative paths resolve against the repository root. Use a Mac-specific OneDrive path after moving machines.

```bash
.venv/bin/python scripts/render_application.py --project . --content outputs/<job_id>/source/content.json --mirror-configured
```

Add --cv-only or --cover-letter-only for scoped edits. Saved reviewed applications are versioned in applications/<job_id>/source/. Copy a saved application folder into outputs before rendering. If source/render_application.py exists, use it to retain application-specific page breaks and compact technology lists; otherwise use the generic helper. The Mac guide includes a complete restore example.

## Repository contents and checks

Included: profile, code, prompts, Word/LaTeX templates, tests, setup/start scripts, dependency lock, reusable agent skill, and reviewed application sources. Excluded from new commits: API credentials, virtual environments, duplicate profile backups, logs, QA images and generated PDF/DOCX outputs. Three adjoe documents were already tracked historically and remain available.

GitHub Actions runs unit tests on Python 3.12. Tests do not require API calls or LaTeX. Full validation also requires rendering and inspecting both CV pages and letter PDF; render DOCX separately with LibreOffice because its layout differs. Fonts, dates, TeX versions, and model output can vary across environments. The exact Windows outputs are not a guarantee of identical Mac rendering.
