# CV Tailor agent instructions

## Start here

Read [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md#current-work) for active work, blockers, and the latest verified state. Check `git status` before editing and preserve existing work. Read only the relevant project references:

- [`docs/ASSESSMENT.md`](docs/ASSESSMENT.md) for implemented architecture and known limitations.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) for planned work.
- [`docs/DECISIONS/`](docs/DECISIONS/) for settled design choices.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for environments, worktrees, ports, and Git workflow.
- [`docs/TESTING.md`](docs/TESTING.md) for test commands, CI coverage, and test limits.
- [`docs/HOW_TO_GENERATE.md`](docs/HOW_TO_GENERATE.md) for the user-facing workflow.
- [`docs/MAC_SETUP.md`](docs/MAC_SETUP.md) for fresh macOS setup.

For setup and user workflows, use [`skills/cv-tailor-setup/SKILL.md`](skills/cv-tailor-setup/SKILL.md). Before generating or revising a real application, read [the application skill](.agents/skills/cv-tailor-application/SKILL.md). Follow the [user guide](docs/HOW_TO_GENERATE.md#confirm-first-suggestions) for the current claim review and CV revision workflow. Use the model-curation skill for model catalogue or evaluation work.

## Privacy and candidate data

Profiles and generated applications belong in the private store, not this public repository (ADR 0002, ADR 0011). Resolve `CVTAILOR_STORE` from the local configuration; the default is `./storage`. Profiles are at `<store>/profiles/<profile_id>/profile.yaml`, outputs at `<store>/outputs/<profile_id>/<job_id>/`, and saved applications at `<store>/applications/<job_id>/source/`.

Never commit real profiles, applications, generated documents, credentials, `.env`, virtual environments, logs, or private-store backups. Use synthetic profiles and portable paths in tracked examples. Never print API keys. Preserve existing profile facts and manual edits; do not fabricate skills, metrics, responsibilities, or work authorization.

Use the candidate's rules and country overrides for work-authorization wording. Employer sponsorship and permit support belong in the cover letter. Standard limits are a two-page CV and a one-page cover letter with four paragraphs and 290–310 body words.

Use `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on macOS/Linux. Do not copy a virtual environment across operating systems. `profile_id` is required in CLI/API/services; pass `--profile-id <id>` or set `CVTAILOR_PROFILE_ID` (ADR 0003). The GUI may restore its last valid profile or select the only usable profile; with multiple profiles and no valid remembered selection, require the user to choose (ADR 0022).

## Work and verification

- Keep changes focused and preserve unrelated local edits. Never overwrite private data or uncommitted work.
- For code or behavior changes, add or update a regression test and run relevant tests, then the full suite when feasible. Follow [`docs/TESTING.md`](docs/TESTING.md); report passed, failed, and unrun checks accurately.
- For documentation-only changes, check changed links, commands, and claims against current source or implementation. Do not run the full test suite unless the documentation change affects executable behavior.
- For generated document changes, inspect rendered pages for clipping, orphan headings, broken bullets, and readability. Review both PDF and DOCX when both are delivered.
- Update the relevant user workflow or skill when a code change changes commands, configuration, output, or troubleshooting. Keep active status in PROJECT_STATE and architecture/plan details in their respective documents.
- Ask before paid AI generation. A doctor key verification contacts the configured provider but does not generate content.
- Never commit, push, merge, rewrite shared history, delete data, or change repository visibility unless the owner explicitly authorizes that action. An authorization for one action does not authorize later actions.

`master` must remain usable for real applications. Do not merge development into `master` without explicit owner approval and a reviewed migration/rollback plan.
