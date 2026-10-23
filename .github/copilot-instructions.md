# Copilot instructions for cv-tailor

**This file is intentionally a pointer.** The project previously kept a long, tool-specific
instruction set here. It had drifted badly out of date — it described Tectonic instead of
`pdflatex`, `gemini-1.5-flash` instead of the configured model, a `BaseProfile` model that no
longer exists, a `/api/preview` endpoint that was never implemented, and a
`cover_letter_examples/` directory that is not in the repository.

Do not recreate it. There must be **one** set of project instructions, and it is
tool-independent.

## Read these instead, in order

1. **[`AGENTS.md`](../AGENTS.md)** — the single authoritative entry point for all coding
   agents, including session start/end and documentation rules.
2. **[`docs/PROJECT_STATE.md`](../docs/PROJECT_STATE.md)** — active task, next action,
   blockers, verified baseline. **Read this first in any session.**
3. **[`docs/ASSESSMENT.md`](../docs/ASSESSMENT.md)** — the current implemented architecture,
   technical debt, performance and cost measurements, privacy findings.
4. **[`docs/ROADMAP.md`](../docs/ROADMAP.md)** — proposed phases, MVP and dependencies.
5. **[`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md)** — worktrees, environment isolation,
   ports, Git workflow, cross-machine sync.
6. **[`docs/TESTING.md`](../docs/TESTING.md)** — test baseline, the Windows sandbox caveat,
   and the regression strategy.
7. **[`docs/DECISIONS/`](../docs/DECISIONS/)** — settled architecture decisions.
8. **[`docs/MAC_SETUP.md`](../docs/MAC_SETUP.md)** — fresh macOS setup.
9. **[`.agents/skills/cv-tailor-application/SKILL.md`](../.agents/skills/cv-tailor-application/SKILL.md)** —
   generating and revising real applications.

## Quick reference

- Development branch: `refactor/architecture-v2` (worktree `cv-tailor-next`).
  Stable branch: `master` (worktree `cv-tailor`) — keep it usable, never merge without approval.
- Interpreter: `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS).
- Tests: `python -m pytest -q`.
- Never commit credentials, `.env`, virtual environments, logs, or generated PDFs/DOCX.
- Never commit real candidate data into fixtures — use synthetic profiles.
