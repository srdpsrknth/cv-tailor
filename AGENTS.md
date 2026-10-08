# CV Tailor agent instructions

On a new Mac, read `docs/MAC_SETUP.md` first and follow its initialization and validation workflow. Read `.agents/skills/cv-tailor-application/SKILL.md` before generating or revising applications.

Derive the project root from the clone. Use `.venv/bin/python` on macOS and `.venv/Scripts/python.exe` on Windows. Never assume this owner's Windows paths or copy an old virtual environment to a different OS. Do not print API keys or commit `.env`.

The authoritative profile is `storage/profile/profile.yaml`. Preserve manual edits, titles, dates, factual ownership and ongoing-project status. Tailor wording and skills to each role without fabricating requirements. Keep sponsorship/support requirements only in overseas cover letters. Default CV limit: two pages; cover letter: four paragraphs, 290–310 body words, one page.

Saved applications are in `applications/<job_id>/source/`. Copy the application into `outputs/<job_id>/` before regenerating; use its application-specific render script when present. Generic rendering: `python scripts/render_application.py --project . --content outputs/<job_id>/source/content.json --mirror-configured`. Do not overwrite profile facts to satisfy a posting.

Run `python -m pytest -q` after code changes. Inspect rendered pages after document edits: no orphan headings, broken bullets, clipping, or excessive forced whitespace. Keep actual font size readable. DOCX and LaTeX PDF layouts differ; check both when delivering Word files.

Do not commit credentials, virtual environments, logs or new generated PDFs/DOCX. Reviewed application sources and portable reproduction scripts may be committed when authorized. This is a personal repository containing the owner's CV profile; do not treat it as an anonymous sample dataset.
