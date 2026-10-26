# 0012 — Structured output is scoped per call, not enabled globally

**Status:** Approved (2026-10-26) — implemented in Phase 3, increment 3
**Related:** [ASSESSMENT.md](../ASSESSMENT.md) §5 optimisation 3, §3 D-1;
[ADR 0005](0005-llm-provider-interface.md)

## Context

`_call_gemini` did **not** set `response_mime_type="application/json"`, and the comment
there recorded the reason: it *caused premature truncation of long document responses*.
That single fact is why the original `response_schema` code was deleted as dead code in
Phase 1 (**D-1**). ASSESSMENT §5 lists "enable structured output" as the top remaining
optimisation, described as removing "the parse-failure retry loop, the dominant tail
risk" — so the item cannot be discharged by simply setting the flag that was removed for
cause.

Three properties of the pipeline constrain the shape of any answer:

1. **The document response is long.** A draft CV is ≈1,350 output tokens and a cover
   letter ≈620. The truncation that killed the first attempt was a *length* effect.
2. **One call's response is not a document at all.** Since Phase 3 item 1 the layout
   retry may return a **delta** — an object of unit ids such as
   `{"experience[0].bullets[1]": "..."}` with no document key, merged by
   `apply_cv_delta`. A schema requiring `cv` cannot express that shape.
3. **`extract_explanation` accepts two envelopes.** It reads `tailoring_explanation` at
   the top level *and* nested inside `cv`. A strict schema decides, silently, which one
   the model may return.

## Decision

**Enable structured output, scoped by call, with the anti-truncation property designed
into the schema rather than hoped for.**

| Call | Contract | Schema |
|---|---|---|
| CV draft | one complete document, always | **required** |
| Cover letter | one complete document, always | **required** |
| Layout retry | complete CV **or** delta | **not sent** |

The schema constrains the **envelope**, not the document body:

- `required: ["cv"]` (or `["cover_letter"]`) and nothing else — the response is a JSON
  object carrying the expected document key, so the brace-scan in `parse_json_response`
  stops being the failure path. That is the guarantee this increment actually buys.
- **No `required` inside the document, and no `additionalProperties: false` anywhere.**
  Enumerating and requiring every field of a ~1,350-token document is what makes a
  constrained response long and cut-off-prone — the failure D-1 records. The body's
  properties are *described* so the contract is not vacuous, and left optional so the
  response stays short enough to finish.
- `tailoring_explanation` is permitted at the top level **and** inside `cv`, and is
  required in neither, so tightening the envelope does not decide which of the two
  shapes `extract_explanation` receives, nor turn a harmless omission into a failed run
  and a wasted paid call.

`generation.RESPONSE_SCHEMAS` maps document kind to schema and
`generation.response_schema_for(kind, allow_delta=...)` selects it. A kind absent from the
mapping gets **no** schema: a future document type must not inherit the CV's constraints
by accident. `_call_gemini` sets `response_mime_type` and `response_schema` **together**,
so a call that is not schema-constrained keeps both unset and the tolerant parser remains
the path it always was.

## Consequences

- **No silent fallback, and none was introduced.** A schema-constrained response is still
  parsed by `parse_json_response` and still gated by `validate_cv`; JSON mode is a
  *request* to the provider, never a substitute for validation. A response that does not
  parse is retried only through the unchanged 3-attempt correction loop and then raises.
  A truncated response is invalid JSON and `parse_json_response` never repairs truncated
  document data — so if truncation ever returns, the suite fails at the parser instead of
  shipping a half-length CV.
- **The delta path is untouched.** `apply_cv_delta`, `looks_like_cv_delta` and
  `parse_json_response(accept_delta=True)` keep working because the one call that may
  return a delta is the one call sent no schema.
- **Call counts are unchanged at 2/3/5** (12 worst): the schema adds no call. A schema
  that failed often would show up as a *rise* in count on the happy path, which is
  asserted, so the increment cannot hide a new retry loop.
- **Token and cost figures are unchanged.** The schema is request metadata, not prompt
  content, so no prompt byte changes.
- **Scope, not permanence.** If a budgeted live evaluation (Phase 3 item 6) shows the
  provider handles a strict body schema without truncation on real documents, the body
  constraints can be tightened then. That is a measured decision, not a guess, and it
  belongs with benchmarking.
- **What the second provider adds to this question, recorded 2026-10-26.** OpenRouter's
  own documentation states that `strict: true` enforcement "varies by provider: some
  guarantee schema-conforming output, while others translate your schema into their own
  structured-output format or **treat it as a strong hint**, so exact compliance is not
  guaranteed on every endpoint", and that support is "determined per endpoint, not just
  per model". The catalogue payload carries **no per-endpoint field** — this was
  verified directly — so a model-level `structured_outputs` flag cannot distinguish
  native enforcement from translation. Two consequences for this record:
  1. **The scoping decision stands and is more clearly right than before.** Because
     compliance cannot be assumed, the schema must never be the only thing standing
     between the model and a malformed document. It is not: `parse_json_response` and
     `validate_cv` are unchanged, and `require_parameters: true` is sent on
     schema-bearing calls so the request is not routed to an endpoint that would ignore
     the parameter entirely.
  2. **"Did it truncate?" is a per-provider question, not one question.** A clean
     result through OpenRouter does not license tightening the body constraints for
     every endpoint behind it, because the endpoint that served the request is one of
     several. Any tightening decision must name the provider **and** the endpoint it
     was measured on, or it is a guess wearing a measurement's clothes.

  **This remained UNVERIFIED until 2026-10-26. It is now measured, and the answer is
  that it did not truncate — but the risk was real for a different reason.**

  A budgeted live study ran eight candidates over three cases each, with real
  schema-constrained calls. **No constrained response truncated at `max_tokens: 8000`**:
  the largest CV response was **6,286 output tokens** against the 8,000 ceiling, and every
  accepted document finished with `finish_reason: stop` and parsed as valid JSON.

  **The truncation concern was nevertheless well founded, and the mechanism turned out
  not to be the schema's length.** Reasoning tokens are billed as output and are emitted
  *before* the document, and they consumed **53–58% of the completion budget** in the
  measured runs — 646 of 1,220 tokens for `deepseek-v4-flash`, 483 of 831 for
  `gemini-3.8-flash`. A one-off reduction to a 700-token ceiling truncated both models
  mid-document during verification, which is the failure this record was worried about,
  reproduced on demand. So the property that protects the pipeline is the **ceiling**
  (8,000) and not primarily the schema's optionality, and lowering `max_tokens` for cost
  reasons would reintroduce D-1 immediately.

  One further correction to this record's reasoning: **the count of 27 optional
  parameters, which is the design this ADR chose, is itself rejected by one provider
  family.** Anthropic's models behind Vertex refuse a schema with more than 24 optional
  parameters outright. That does not invalidate the anti-truncation reasoning — it
  invalidates the assumption that one schema can serve every provider. See
  [ADR 0016](0016-per-candidate-inputs-and-one-winner.md), which supersedes the
  "one schema for all" part of this decision while keeping this ADR's reasoning as the
  reason one candidate's shape is what it is.
- **`kind` is per call, not per service**, so the schema cannot drift from what is being
  asked for; `_call_gemini`'s signature grew two keyword arguments with defaults that
  preserve the previous behaviour for any caller that passes neither.

## Alternatives considered

| Option | Why not |
|---|---|
| Enable JSON mode everywhere, as the deleted code did | That is the change D-1 records as the cause of truncation; re-deriving it without addressing length would repeat a known failure |
| Strict schema over the whole document (`required` every field, `additionalProperties: false`) | Maximises constrained output length on the longest responses — precisely the truncation risk. Also forbids the delta shape and the nested explanation |
| Schema on the retry too, allowing either document or delta | A delta has arbitrary keys (`experience[0].bullets[1]`), which a schema cannot enumerate; admitting both shapes in one schema is effectively unconstrained for the delta case while still forcing the provider down a slower constrained-decode path |
| No schema; keep relying on the brace-scan | Leaves the parse-failure tail risk that ASSESSMENT §5 optimisation 3 exists to remove |
| Validate the response against the schema client-side and reject on mismatch | Duplicates `validate_cv` and creates a second, weaker gate — exactly the "silent fallback" the roadmap's acceptance criteria forbid |
