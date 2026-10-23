# 0001 — Modular redesign, executed incrementally

**Status:** Approved (2026-10-23)
**Related:** [ASSESSMENT.md](../ASSESSMENT.md) §8, §9

## Context

Three directions were compared: incremental refactoring (A), modular redesign (B), and
substantial replacement (C).

The existing renderers, LaTeX/DOCX templates, prompts and the `content.json` deterministic
re-render path are genuinely good and represent real accumulated value — notably the
page-count quality gate and the zero-LLM-cost revision route.

The actual problems are *concentration* and *missing boundaries*:

- candidate-specific rules are hardcoded in the validation layer
  (`backend/services/tailor_service.py:73-92,154-167`);
- orchestration, validation, persistence and mirroring live in one 296-line function;
- there is no profile identity, no service layer and no persistence model.

Option A cannot deliver multi-profile, because profile identity must be threaded through
every layer — a structural change by definition. Option C would discard working layout logic
for no proven gain.

## Decision

Adopt **Option B — modular redesign, executed incrementally**: keep the renderers,
templates, prompts, the `content.json` contract and the page-count gate, and introduce
profile identity, a service layer and a persistence model around them.

Each step is a small, independently tested increment that preserves existing behaviour.

## Consequences

- Multi-profile becomes achievable without rewriting the document pipeline.
- The stable `master` branch remains usable throughout.
- Refactoring proceeds behind a regression baseline; see `docs/TESTING.md`.
- Some transitional duplication (old `backend/` paths alongside the new package) is
  accepted during migration and must be removed by the end of Phase 1.
