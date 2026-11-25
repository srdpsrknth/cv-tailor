# CV Tailor agent instructions

**Start every session by reading `docs/PROJECT_STATE.md`.** It names the active task, the next
action, current blockers and the verified baseline. Then read the relevant part of
`docs/ASSESSMENT.md` (current architecture) and `docs/ROADMAP.md`, and check `docs/DECISIONS/`
for settled choices. Do not repeat the architecture assessment unless the system materially changed.

On a new Mac, read `docs/MAC_SETUP.md` first and follow its initialization and validation workflow. Read `.agents/skills/cv-tailor-application/SKILL.md` before generating or revising applications. For setup, worktrees, ports and Git workflow, read `docs/DEVELOPMENT.md`; for the test baseline and its sandbox caveat, read `docs/TESTING.md`. **For the user-facing workflow — how to generate, revise and find jobs — read `docs/HOW_TO_GENERATE.md`.**

Derive the project root from the clone. Pick the interpreter by OS: `.venv/bin/python` on macOS/Linux and `.venv/Scripts/python.exe` on Windows (examples below write `python`, meaning that interpreter or an activated venv). Never assume another machine's paths or copy an old virtual environment to a different OS. Do not print API keys or commit `.env`.

**Profiles live in the private store, not in this repository** (ADR 0002, ADR 0011). Resolve `CVTAILOR_STORE` from the current machine's configuration (default `./storage`). Profiles live at `<store>/profiles/<profile_id>/profile.yaml` and outputs at `<store>/outputs/<profile_id>/<job_id>/`. Never commit a real profile, application or generated document here — this repository is public. Preserve manual edits, titles, dates, factual ownership and ongoing-project status. Tailor wording and skills to each role without fabricating requirements. Keep sponsorship/support wording only in cover letters, and only where the selected profile's rules and `country_overrides` require it. Default CV limit: two pages; cover letter: four paragraphs, 290–310 body words, one page.

Keep job-search preferences in the selected private profile and document naming timezones in machine settings. Use synthetic profiles and portable paths in reusable examples.

Use `skills/cv-tailor-setup/SKILL.md` as the entry point for onboarding and all user-facing CV Tailor workflows. Follow its application workflow reference for job-specific generation and revision.

**`profile_id` is required and fails closed in the CLI/API/services** (ADR 0003). Pass `--profile-id <id>` or set `CVTAILOR_PROFILE_ID`; run `cvtailor profile list` to see the ids. **GUI exception approved 2026-11-17:** restore the last valid GUI selection, or select the only usable profile automatically. Show the active name/id prominently and pass that resolved id explicitly to services. With multiple profiles and no valid remembered choice, require selection; never default to the first. See ADR 0022.

Saved applications are in `<store>/applications/<job_id>/source/`. Copy the application into `<store>/outputs/<profile_id>/<job_id>/` before regenerating; use its application-specific render script when present. Generic rendering: `python scripts/render_application.py --project . --profile-id <id> --content <store>/outputs/<profile_id>/<job_id>/source/content.json --mirror-configured`. Do not overwrite profile facts to satisfy a posting.

Run `python -m pytest -q` after code changes. Inspect rendered pages after document edits: no orphan headings, broken bullets, clipping, or excessive forced whitespace. Keep actual font size readable. DOCX and LaTeX PDF layouts differ; check both when delivering Word files.

Do not commit credentials, virtual environments, logs or new generated PDFs/DOCX. Reviewed application sources and portable reproduction scripts may be committed when authorized. This public repository holds no real candidate data: real profiles, applications and outputs live in the private store (ADR 0002, ADR 0011). Use only synthetic profiles in fixtures and examples.

## Keeping project knowledge in the repository

Conversation history is never the record. A new agent must be able to continue from the
repository alone.

- **Before starting work:** confirm the branch and worktree, read `docs/PROJECT_STATE.md`,
  check `git status` for uncommitted work, and run the test baseline.
- **While working:** prefer small, focused, independently tested increments. Establish or
  extend tests before refactoring behaviour. Do not combine unrelated structural changes.
- **Before finishing a task:** run the relevant tests; update `docs/PROJECT_STATE.md`
  (active task, blockers, next action); update architecture-level facts in
  `docs/ASSESSMENT.md` and milestone progress in `docs/ROADMAP.md` if the system changed;
  record hard-to-reverse choices in `docs/DECISIONS/`; then commit code and documentation
  together.
- **For every repo change:** review the CV Tailor skill and its references. When a change
  affects a user workflow, command, configuration, output, feature, or troubleshooting step,
  update `skills/cv-tailor-setup/` and any affected application-skill instructions in the
  same change. Point to the current source of truth and verify any changed examples.
- **Report honestly:** state which tests passed, which failed, and which were not run.
  Never claim success from code inspection alone.

The `.agents/skills/project-continuity/SKILL.md` skill encodes this workflow for agents that
support skills. Agents without skill support must follow this section instead — it is the
authoritative version.

`master` stays usable for real applications. Never merge development into `master`, rewrite
shared history, delete data, or change repository visibility without explicit approval.
