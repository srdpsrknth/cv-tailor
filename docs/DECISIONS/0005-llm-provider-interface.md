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

## Consequences

- Enables per-task model routing (cheap models for extraction, stronger for writing).
- Removes the dead structured-output branches, or makes them live.
- Model fallbacks must **never** silently change output requirements or bypass validation.
- Requires an evaluation suite over synthetic profiles and anonymised postings comparing
  accuracy, completeness, relevance, writing quality, structured-output success,
  unnecessary claims, correction attempts and total cost per accepted result.
- Live evaluation stays out of CI: optional, budget-capped and reproducible.
- Provider pricing must be verified against authoritative sources — the in-repo table is
  already stale (`gemini-1.5-*` entries remain).
