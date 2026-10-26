# 0013 — Thin provider interface, model routing and budget caps

**Status:** Approved (2026-10-26) — implemented in Phase 3, item 6
**Related:** [0005](0005-llm-provider-interface.md) (the deferral this discharges),
[0012](0012-structured-output-scope.md) (the per-call contract this must preserve),
[0010](0010-configuration-and-environment.md) (no import-time environment reads)

## Context

ADR 0005 decided on a thin provider interface — one
`generate(prompt, *, schema, max_tokens, model)` contract, Gemini as the default,
OpenRouter as a second implementation — plus model-per-task routing and optional
budget caps. It deferred the build. Phase 3 item 6 builds it.

Three facts had to be established before the interface could be written, and were
not available when 0005 was approved:

1. **OpenRouter's structured-output envelope is not Gemini's.** OpenRouter takes
   `response_format={"type": "json_schema", "json_schema": {"name", "strict",
   "schema"}}` (openrouter.ai/docs/features/structured-outputs, 2026-10-26). Gemini
   takes `response_schema`. A "neutral schema passed to both" is therefore a
   translation, not a passthrough — and a passthrough would send **no usable
   constraint** while looking like it had.
2. **`strict` is not a guarantee.** The same page states enforcement "varies by
   provider" and exact compliance "is not guaranteed on every endpoint", and that
   strict modes "may restrict which JSON Schema features you can use".
3. **OpenRouter's catalogue is reachable and large** — 467 models on 2026-10-26, of
   which 389 advertise `structured_outputs`. This is the factual basis for the
   owner's curation requirement in 0005 §"Model curation".

Weighing against those: ADR 0012 made structured output **per call**, and one call —
the layout retry — must send **no** schema because its response may be a delta of
unit ids with no document key. An interface that "always constrains" would break
that silently.

## Decision

**Introduce the interface as a pure indirection, with the per-call schema contract
expressed as an explicit `None` that survives to the provider.**

| Element | Decision |
|---|---|
| Contract | `Provider.generate(prompt, *, schema=None, max_tokens=None, model=None) -> ProviderResponse` |
| Default provider | **Gemini** — decision 6 keeps Gemini's latest Flash as the default |
| Second provider | OpenRouter, translating the neutral schema into its own `response_format` |
| `schema=None` | Means **send no constraint**, and does so on both providers |
| Routing guard | A schema-constrained OpenRouter call also sends `provider.require_parameters: true` |
| Model per task | `Config.model_for(task)`, opt-in; an unrouted task keeps `Config.model` |
| Budget cap | Optional `CVTAILOR_MAX_COST_USD`, enforced *before* the next call |
| Fallback | **None.** An unknown provider, a missing key, or a provider failure raises |

`GeminiService._call_gemini` is kept as the single call site the generation pipeline
uses; it computes the schema via the unchanged `response_schema_for(kind,
allow_delta=...)` and passes the result through. The class name is now historical and
is deliberately **not** renamed in this increment: a rename would touch every call
site and every test at the same time as the behavioural change, which is exactly the
combination that makes an intended change indistinguishable from a regression.

## Why each guard exists

- **`schema=None` is passed through rather than recomputed inside the provider.**
  The scope decision belongs to `response_schema_for`, which knows about deltas and
  document kinds. A provider that decided for itself would be a second, weaker gate
  on the same question.
- **No silent fallback.** A provider error is a `ProviderError`, deliberately **not**
  a `ValueError` — the pipeline's 3-attempt correction loop catches `ValueError`, so
  a provider outage misclassified as one would burn three paid calls re-asking a
  question the provider never answered.
- **The selected provider's key only.** Selecting OpenRouter with no
  `OPENROUTER_API_KEY` raises; it does not fall back to the Gemini key.
- **The cap fails closed.** A malformed `CVTAILOR_MAX_COST_USD` is a `ConfigError`,
  never a silently-absent cap: a budget that fails open is worse than no budget,
  because it looks like one. The cap is checked *after* accumulating a call and
  *before* the next one, so the run stops at the limit rather than reporting the
  overrun afterwards.
- **Cost is priced per routed model.** `_estimate_cost` gained a `model` parameter,
  because routing means one run can bill against several models and pricing them all
  at the service default would misreport the run.

## Consequences

- **Call counts are unchanged at 2/3/5, worst 12.** The interface adds routing, not
  calls. Verified by driving the real pipeline with a recorded transcript, and
  `tests/test_editorial_instructions.py` still pins the counts unchanged.
- **No prompt byte changed**, so the token and cost figures in ASSESSMENT §5 are
  unaffected by this increment.
- **Provider behaviour on real documents remains unverified.** No paid call was made:
  the suite is offline by constraint and this worktree's `.env` still has no
  `GEMINI_API_KEY`. Whether structured output truncates on a real two-page CV — the
  question increment 3 could not settle — still needs the budgeted live run, which
  is the evaluation suite's job.
- **OpenRouter's `strict` is not relied upon.** Validation stays where it always was
  (`parse_json_response` then `validate_cv`), so a provider that treats the schema as
  a hint cannot ship an unvalidated document.
- **Pricing gains a route dimension.** OpenRouter lists `google/gemini-3.8-flash` at
  $0.825/$4.125 per 1M while the repository's `PRICING` holds Google-direct
  $0.75/$3.75. Both are correct *for their route*, so a bare price is ambiguous.
  Route-aware and tiered pricing is the next increment (D-3, D-4).

## Alternatives considered

| Option | Why not |
|---|---|
| A third-party LLM orchestration framework | ADR 0005 rules it out; the whole interface is ~200 lines and a framework would add a dependency and its own abstractions between the pipeline and the provider |
| Keep `response_schema` as the neutral name and translate inside each provider | Hides the fact that the two envelopes differ, and invites a passthrough that silently constrains nothing |
| A single `schema` flag (`structured: bool`) instead of the schema object | The provider would have to look up the schema itself, moving the per-call scope decision out of `generation` where the delta logic lives |
| Always send a schema, and let the retry tolerate rejection | Contradicts ADR 0012: a schema requiring `cv` cannot express a delta, so the delta path would stop working |
| Rename `GeminiService` to `ProviderService` in the same increment | Couples a mechanical rename to the behavioural change, making the call-count and prompt diff unreadable |
| Hard-fail when a config lacks routing/cap methods | These are additive; a config object that predates them means "not configured", which is the documented default behaviour, not an error |
