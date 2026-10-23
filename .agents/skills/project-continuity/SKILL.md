---
name: project-continuity
description: Keep CV Tailor project knowledge in the repository across sessions and across different AI coding agents. Use at the start and end of any development task, when handing work to another agent or machine, or when deciding whether to continue the current chat or start a new one.
---

# Project continuity

Conversation history is **never** the record. A new agent, on a new machine, with no prior
context must be able to continue from the repository alone.

The authoritative workflow lives in `AGENTS.md` ("Keeping project knowledge in the
repository"). This skill applies it. If an agent does not support skills, `AGENTS.md` is
sufficient on its own — do not create a competing copy of these rules.

## Session start

1. Confirm the repository and worktree: `git worktree list`, `git rev-parse --abbrev-ref HEAD`.
   Development must be on `refactor/architecture-v2`, never on `master`.
2. `git status --short --branch` — identify uncommitted work. **Never discard it.**
3. `git fetch` and check whether the branch is behind the remote.
4. Read `AGENTS.md`.
5. Read `docs/PROJECT_STATE.md` — active task, next action, blockers, baseline.
6. Read the relevant part of `docs/ASSESSMENT.md` and `docs/ROADMAP.md`.
7. Read `docs/DECISIONS/` for choices already settled. Do not relitigate them.
8. Review recent commits relevant to the task: `git log --oneline -20`.
9. Run the test baseline (`docs/TESTING.md`) to confirm the starting state.
10. Confirm the acceptance criteria for the assigned task.

Do not repeat the architecture assessment unless the system materially changed.

## During the task

- One task, one clear outcome. Prefer small, focused, independently testable increments.
- Establish or extend tests **before** changing behaviour that tests should protect.
- Do not combine unrelated structural changes in one step.
- Update documentation in the same commit as the code it describes.
- Keep `master` untouched.

## Session end / handoff

### A. Verify completion
- Check each acceptance criterion explicitly.
- Run the relevant tests. Report **what passed, what failed, and what was not run**.
- List any incomplete requirements.
- Never claim success from code inspection alone.

### B. Update documentation
- `docs/PROJECT_STATE.md` — active task, status, blockers, **next recommended action**.
- `docs/ROADMAP.md` — milestone progress, if a milestone moved.
- `docs/ASSESSMENT.md` — only if the implemented architecture actually changed.
- `docs/DECISIONS/` — a new record for any hard-to-reverse choice, with reasoning.
- `docs/TESTING.md` — new tests and how to run them.

### C. Preserve the work
- Inspect `git status`.
- Commit completed, validated changes with a scoped message.
- Push development commits when authorised.
- Report anything left uncommitted or unpushed.
- **Never discard work to produce a clean handoff.**

### D. Prepare the next session
Provide a concise handoff: branch, worktree, latest relevant commit, completed task, current
state, next recommended task, relevant files, test commands, unresolved decisions, risks.
Store the durable parts in `docs/PROJECT_STATE.md` — do not create a new handoff file per
conversation.

## Continue, or start a new chat?

Recommend **continue this chat** when the task is unfinished, debugging relates to it, tests
are failing because of changes just made, or follow-ups are small and in scope.

Recommend **start a new chat** when the current task is complete and validated, the next
objective is distinct, an assessment has been approved and implementation is beginning, a
major phase finished, the conversation holds substantial obsolete context, or a different
agent/machine takes over.

Recommend **handoff required** when context or environment is changing but unfinished work
must first be documented and preserved.

Never use an arbitrary message or token count as the sole criterion.

## Hard rules

- Never merge development into `master` without explicit owner approval.
- Never force-push or rewrite shared history without approval.
- Never delete existing data or change repository visibility without approval.
- Never commit credentials, virtual environments, logs, or new generated PDFs/DOCX.
- Never commit real personal data into test fixtures — use synthetic profiles.
