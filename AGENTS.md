# CV Tailor agent instructions

**Start every session by reading `docs/PROJECT_STATE.md`.** It names the active task, the next
action, current blockers and the verified baseline. Then read the relevant part of
`docs/ASSESSMENT.md` (current architecture) and `docs/ROADMAP.md`, and check `docs/DECISIONS/`
for settled choices. Do not repeat the architecture assessment unless the system materially changed.

On a new Mac, read `docs/MAC_SETUP.md` first and follow its initialization and validation workflow. Read `.agents/skills/cv-tailor-application/SKILL.md` before generating or revising applications. For setup, worktrees, ports and Git workflow, read `docs/DEVELOPMENT.md`; for the test baseline and its sandbox caveat, read `docs/TESTING.md`.

Derive the project root from the clone. Use `.venv/bin/python` on macOS and `.venv/Scripts/python.exe` on Windows. Never assume this owner's Windows paths or copy an old virtual environment to a different OS. Do not print API keys or commit `.env`.

**Profiles live in the private store, not in this repository** (ADR 0002, ADR 0011). The store is `CVTAILOR_STORE` (default `./storage`; on this machine `D:\coding\cv-tailor-data`), laid out as `<store>/profiles/<profile_id>/profile.yaml` with outputs at `<store>/outputs/<profile_id>/<job_id>/`. Never commit a real profile, application or generated document here — this repository is public. Preserve manual edits, titles, dates, factual ownership and ongoing-project status. Tailor wording and skills to each role without fabricating requirements. Keep sponsorship/support requirements only in overseas cover letters. Default CV limit: two pages; cover letter: four paragraphs, 290–310 body words, one page.

**`profile_id` is required and fails closed** (ADR 0003). Never default a profile, never infer one, never fall back to "the only one". Pass `--profile-id <id>` or set `CVTAILOR_PROFILE_ID`; run `cvtailor profile list` to see the ids.

Saved applications are in `<store>/applications/<job_id>/source/`. Copy the application into `<store>/outputs/<profile_id>/<job_id>/` before regenerating; use its application-specific render script when present. Generic rendering: `python scripts/render_application.py --project . --profile-id <id> --content <store>/outputs/<profile_id>/<job_id>/source/content.json --mirror-configured`. Do not overwrite profile facts to satisfy a posting.

Run `python -m pytest -q` after code changes. Inspect rendered pages after document edits: no orphan headings, broken bullets, clipping, or excessive forced whitespace. Keep actual font size readable. DOCX and LaTeX PDF layouts differ; check both when delivering Word files.

Do not commit credentials, virtual environments, logs or new generated PDFs/DOCX. Reviewed application sources and portable reproduction scripts may be committed when authorized. This is a personal repository containing the owner's CV profile; do not treat it as an anonymous sample dataset.

## Keeping project knowledge in the repository

Conversation history is never the record. A new agent must be able to continue from the
repository alone.

- **Before starting work:** confirm the branch and worktree, read `docs/PROJECT_STATE.md`,
  check `git status` for uncommitted work, and run the test baseline.
- **While working:** prefer small, focused, independently tested increments. Establish or
  extend tests before refactoring behaviour. Do not combine unrelated structural changes.
- **Before finishing a task:** run the relevant tests; update `docs/PROJECT_STATE.md`
  (active task, blockers, next action); update `docs/ARCHITECTURE`-level facts in
  `docs/ASSESSMENT.md` and milestone progress in `docs/ROADMAP.md` if the system changed;
  record hard-to-reverse choices in `docs/DECISIONS/`; then commit code and documentation
  together.
- **Report honestly:** state which tests passed, which failed, and which were not run.
  Never claim success from code inspection alone.

The `.agents/skills/project-continuity/SKILL.md` skill encodes this workflow for agents that
support skills. Agents without skill support must follow this section instead — it is the
authoritative version.

`master` stays usable for real applications. Never merge development into `master`, rewrite
shared history, delete data, or change repository visibility without explicit approval.
