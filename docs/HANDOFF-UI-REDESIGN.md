# Handoff: UI redesign

Read this first to resume the UI redesign on any device or with any coding assistant (Claude Code, another LLM, or a person). It is self-contained. Everything it references is tracked on the branch.

## Where things stand (2026-11-28)

- **Branch:** `ui/redesign` on GitHub (`origin/ui/redesign`), cut from `refactor/architecture-v2`. `master` is untouched.
- **Approved by the owner on 2026-11-28:** [ADR 0031](DECISIONS/0031-web-ui.md) and the [build plan](UI_REDESIGN_PLAN.md).
- **Done:** research, three visual directions, the owner's choice and its revisions (Bench v4), the design system, tokens, the ADR and the build plan.
- **Not started:** any code. Streamlit is unchanged and remains the working UI.
- **Next step:** wave 1 of the build plan, which waits on the owner's go-ahead.

## Read in this order

1. [AGENTS.md](../AGENTS.md): project rules. Privacy, no paid calls without approval, no commit/push/merge without authorization.
2. [ADR 0031](DECISIONS/0031-web-ui.md): what was decided and why.
3. [Build plan](UI_REDESIGN_PLAN.md): work packages WP0–WP13, waves, models, "done when" criteria, rollback.
4. [Design system](design/DESIGN_SYSTEM.md) and [tokens](design/tokens.css): the visual and interaction rules.
5. [Bench mock-up](design/redesign/bench-mockup.html): open it in a browser. Synthetic data only. Screens: `#workspace`, `#new`, `#library`, `#desk`.
6. As needed:
   - [capability inventory](design/redesign/CAPABILITIES.md): what the code can do, the API surface, and the invariants
   - [acceptance criteria](design/redesign/ACCEPTANCE.md): behaviour every screen must pass
   - [stack options](design/redesign/STACK_OPTIONS.md)
   - [design research](design/redesign/DESIGN_RESEARCH.md)

## Decisions already made (don't reopen without the owner)

- **Stack:** Svelte 5 + Vite + TypeScript SPA in `web/`, served by FastAPI at `/app/`. A new `/api/v2` router contains no business rules and delegates to `ui/services_bridge.py` and the services. The built `web/dist` is committed, so running the app needs Python only. htmx is the fallback, chosen only at the WP5 gate.
- **Look:** the Bench layout with the Proof Desk palette. Proof blue is the single accent. The fonts are Archivo, Martian Mono and Source Serif 4, self-hosted.
- **Layout:** container-query zones from 360px to 5120px. Pages scale as a whole and are capped at 820px; extra width becomes more pages. The header stacks rather than hiding links. The candidate name and id are always visible.
- **UI labels:**
  - "Suggested additions" (S1, S2 …)
  - "Profile changes" (was Freshness)
  - "Cost and model" (was Run details)
  - "Tailoring" (was Changes)

  Code keeps the term "claim".
- **Undo:** a dismissed suggestion is restored with "Restore" or the U key. The word "stet" is never used.
- **Version 1 scope:** today's features plus inline edit and re-render, regenerate, a pre-run estimate, progress with cancel, and a profile editor. Deferred: tracking, posting from a URL, per-profile job sources (ADR 0030).

## How to resume on a new machine

```bash
git clone https://github.com/srdpsrknth/cv-tailor.git
```

```bash
cd cv-tailor && git switch ui/redesign
```

Then follow [MAC_SETUP](MAC_SETUP.md) or [DEVELOPMENT](DEVELOPMENT.md) for the Python environment. Point `CVTAILOR_STORE` at your private store, or use a disposable synthetic store for development. Node is needed only from WP4 onward; the version will be pinned in `web/.nvmrc`.

Check the baseline before you change anything:

```bash
python -m pytest -q -m "not requires_latex"
```

## How to run the work (orchestration)

- Work packages in the same wave touch different files, so each can run in its own session and its own git worktree, branched from `ui/redesign`. Name the branches `ui/wp<N>-<slug>`, for example `ui/wp0-bridge`.
- One coordinating session owns the shared files (`backend/main.py`, the web route registry). It merges finished packages into `ui/redesign`, but only after the owner approves each merge.
- Models:
  - **strongest model** (Opus) for WP1 (paid path), WP3 (API security), WP5 (the spike) and final reviews
  - **mid model** (Sonnet) for the other build packages
  - **small model** (Haiku) for read-only checks
- Start each session with the brief below.

### Brief template for a work-package session

> You are implementing WP`<N>` of `docs/UI_REDESIGN_PLAN.md` on a worktree branch `ui/wp<N>-<slug>` cut from `ui/redesign`. Read `AGENTS.md`, `docs/HANDOFF-UI-REDESIGN.md`, ADR 0031 and the WP`<N>` row (its "depends on" and "done when" columns). Touch only the files that WP owns. Use synthetic data and a temporary `CVTAILOR_STORE`; make no paid calls. Add regression tests and run `python -m pytest -q`. Report what passed, failed and was not run. Do not commit, push or merge without the owner's explicit approval.

### Wave 1 (can start in parallel once the owner says go)

| WP | Session brief focus | Model |
|---|---|---|
| WP0 | Move the answers-editor, layout-preview and word-diff logic into services and the bridge; extract CLI `render` into a service | Sonnet |
| WP1 | Pipeline progress events, cancel between provider calls, `estimate_generation`, `would_hit_cache` | Opus |
| WP2 | Validated, backed-up, atomic profile edits | Sonnet |
| WP4 | `web/` shell: tokens, fonts, header, candidate switcher, routing, status line, palette, dist check, against a mock API | Sonnet, with Opus review |

## Not in the repository (intentionally)

- `local/ui-redesign/` on the original Mac: working copies of the research, plus the Proof Desk and Atelier mock-ups that weren't chosen, and `bench-v1`/`bench-v3`. They are git-excluded and not needed: the chosen design and all decisions are in `docs/`.
- Private data: profiles, applications and outputs live in the private store (ADR 0002/0011) and must never be committed.
