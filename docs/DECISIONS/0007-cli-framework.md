# 0007 — CLI built on `argparse` with a friendliness layer

**Status:** Approved (2026-10-23)
**Related:** [ROADMAP.md](../ROADMAP.md) Phase 1

## Context

The owner wants a **complete, reliable CLI before significant UI work**, and wants it
**user-friendly and easy to use**. The owner was unsure which framework is best.

Candidates:

| Option | Pros | Cons |
|---|---|---|
| **`argparse`** (stdlib) | Zero dependencies; already used by `scripts/render_application.py`; stable; no install cost | More boilerplate; no built-in colours/prompts |
| `Typer` | Terse; type-hint driven; good help output | Pulls in `click` + `typer`; another dependency to keep current |
| `Click` | Mature; composable; strong ecosystem | Explicit decorators; adds a dependency |
| `Questionary`/`InquirerPy` | Rich interactive prompts | Interactive-first; awkward for scripting and CI |

The tool is a **personal, single-user CLI**. Its hardest usability problems are not argument
parsing — they are *discoverability* (what can I run?) and *safety* (which profile and which
job am I about to overwrite?).

## Decision

Use **`argparse` with subcommands**, and spend the saved effort on the things that actually
make it pleasant:

1. **A guided default.** Running `cvtailor` with no arguments prints a short menu of the
   common flows (select profile → paste posting → generate), so a beginner never needs to
   memorise a command.
2. **An interactive path for every required argument.** If `--profile` is omitted and more
   than one profile exists, prompt for it. Never guess.
3. **Clear, verb-first subcommands** with aliases:
   `profile list|show|new|edit|import|export`, `generate`, `render`, `jobs search|show|save`,
   `applications list|show|update`, `usage`, `doctor`.
4. **`cvtailor doctor`** — one command that checks Python, the venv, the store path, the API
   key, `pdflatex` and the templates, and prints exactly what to fix. Extends the existing
   `scripts/check_setup.py`.
5. **Human-readable output by default, `--json` for scripting**, so the CLI stays usable in
   pipelines and by other agents.
6. **Explicit confirmation before anything destructive**, showing the resolved profile and
   output path.
7. **Honest exit codes** and error messages that name the fix, not just the failure.

If argument parsing genuinely becomes painful once the command surface is real, revisit and
migrate to `Typer` — the subcommand structure carries over, so that is a contained change.

## Consequences

- **No new runtime dependency** for the CLI itself.
- The interactive layer is separate from the parsing layer, so commands stay scriptable and
  testable (CLI smoke tests in CI).
- Consistency with the existing `scripts/` style.
- Some help-text polish is hand-written rather than generated.
