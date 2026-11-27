# Copilot instructions for cv-tailor

Follow [`AGENTS.md`](../AGENTS.md) as the single source of repository-wide agent instructions.
Start with [`docs/PROJECT_STATE.md`](../docs/PROJECT_STATE.md#current-work), then open only the
references relevant to the task. Do not read every architecture, roadmap, setup, and workflow
document by default.

## Reference map

- Architecture and limits: [`docs/ASSESSMENT.md`](../docs/ASSESSMENT.md)
- Planned work: [`docs/ROADMAP.md`](../docs/ROADMAP.md)
- Local environments, worktrees, ports, Git: [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md)
- Test commands, CI, and limits: [`docs/TESTING.md`](../docs/TESTING.md)
- User-facing generation and review: [`docs/HOW_TO_GENERATE.md`](../docs/HOW_TO_GENERATE.md)
- macOS setup: [`docs/MAC_SETUP.md`](../docs/MAC_SETUP.md)
- Settled design: [`docs/DECISIONS/`](../docs/DECISIONS/)
- Real application work: [application skill](../.agents/skills/cv-tailor-application/SKILL.md)
- Setup and user workflow: [setup skill](../skills/cv-tailor-setup/SKILL.md)

Use the interpreter in the checkout's virtual environment: `.venv/Scripts/python.exe` on
Windows or `.venv/bin/python` on macOS/Linux. Never commit credentials, `.env`, virtual
environments, logs, generated documents, or real candidate data. Ask before paid generation.
