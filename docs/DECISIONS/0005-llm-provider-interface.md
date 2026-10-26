# 0005 — Thin LLM provider interface; benchmark before switching

**Status:** Approved (2026-10-23)
**Date:** 2026-10-23
**Related:** [ASSESSMENT.md](../ASSESSMENT.md) §3 D-1, D-3, §5

## Context

Gemini is hardwired: `backend/services/gemini_service.py` is imported directly by
`tailor_service.py:21`, configuration is read at import time (`gemini_service.py:21-24`), and
there is no way to vary the model per task or per profile.

Verified defects in the current integration:

- **structured output is dead code** — `response_schema` is never passed by any caller, so
  JSON mode is never enabled and all parsing relies on brace-scanning
  (`_parse_json_response`, `tailor_service.py:33`);
- **cost is under-reported** — `calculate_token_usage` applies one flat rate while `PRICING`
  defines separate `input_long`/`output_long` tiers (`gemini_service.py:100-122` vs `:35-40`);
- **pricing is duplicated** in the UI (`ui/app.py:239-246`).

An OpenRouter key is available. Relevant operations differ in difficulty: job-posting
extraction and requirement classification are routine; CV tailoring, cover-letter drafting
and factual review are not.

## Decision

Introduce a **thin provider interface** (a single `generate(prompt, *, schema, max_tokens,
model)` contract) with Gemini as the default and OpenRouter as a second implementation.
Allow model-per-task configuration. Keep pricing in **one** module.

**Do not** adopt a large LLM orchestration framework, and **do not** switch providers or
models before benchmarking.

**Keep Gemini's latest Flash model as the default.** Benchmark cost, performance and output
quality before switching anything. Before any paid evaluation: agree the method and a
spending budget with the owner.

### Model curation (owner requirement, 2026-10-26)

OpenRouter exposes a **very large** model catalogue. When the OpenRouter implementation
lands, it must offer a **small curated set of named options** — one that spans different
performance and cost levels — and **not** a passthrough of the catalogue. Surfacing every
model would push a decision onto the user that the tool is better placed to make.

Selecting that set is **research**, judged on **price against content quality for CV and
cover-letter generation specifically**, using the evaluation method below. A model that
tops a general leaderboard is not thereby suited to producing a two-page CV that passes the
factual gate, keeps every employer and date, and returns schema-valid JSON. Curation is
therefore part of item 6's deliverable, not a follow-up: the interface is only useful once
the options it exposes are chosen deliberately.

## Consequences

- Enables per-task model routing (cheap models for extraction, stronger for writing).
- Removes the dead structured-output branches, or makes them live. **Structured output is
  now live and scoped per call** — Phase 3 increment 3; see
  [0012](0012-structured-output-scope.md). The provider interface must keep the same
  per-call contract, including the option of sending **no** schema on a call whose response
  is not a document.
- Model fallbacks must **never** silently change output requirements or bypass validation.
- Requires an evaluation suite over synthetic profiles and anonymised postings comparing
  accuracy, completeness, relevance, writing quality, structured-output success,
  unnecessary claims, correction attempts and total cost per accepted result. **This suite
  does not exist yet** and is the gating prerequisite for choosing the curated set.
- Live evaluation stays out of CI: optional, budget-capped and reproducible.
- Provider pricing must be verified against authoritative sources. The `gemini-1.5-*` rows
  this ADR originally flagged as stale were **pruned in Phase 1** (D-5), verified against
  ai.google.dev on 2026-10-23; **OpenRouter prices must be verified the same way, from
  OpenRouter's own listing — do not carry a figure over from a secondary source.**
- A curated set is a **maintenance obligation**: providers add, deprecate and reprice models
  constantly, so the list needs a documented review cadence and a stated fallback when a
  chosen model is withdrawn.
