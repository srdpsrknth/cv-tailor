"""Per-candidate input profiles: how each model is asked, so it can be compared fairly.

**Why this exists.** The first live evaluation could not rank anything, and the reason
became the design: three provider families demand mutually incompatible response
schemas, measured against the live API on 2026-10-26.

| Family | Requirement | A Gemini-shaped schema |
|---|---|---|
| OpenAI | ``additionalProperties: false`` **required** | `400 "required to be supplied and to be false"` |
| Anthropic via Vertex | **≤ 24** optional parameters | 27 → `400 "too many optional parameters (27)... limit: 24"` |
| Google Gemini | ``additionalProperties`` **forbidden** | `400 "not supported in the Gemini API"` |

Gemini rejects the keyword OpenAI requires; these are contradictions, not degrees of
strictness. Ranking models against one schema would therefore have measured *this
repository's schema* rather than the models — `gpt-6-luna` and `claude-haiku-5.5` would
have been placed last for a defect of ours.

So each candidate gets **its own schema and prompt**, and is judged on its best
achievable configuration. See [ADR 0016](../../docs/DECISIONS/0016-per-candidate-inputs-and-one-winner.md).

**What does NOT vary, and this is the property that keeps the comparison honest:**

* the **acceptance bar** — the same profiles, postings, validation rules and
  word-count gate for every candidate. Nothing about what *counts as success* changes;
* the **cost metric** — cost per accepted result, from the provider's own reported
  charge;
* the **measured shape** — three cases, the same call budget.

Only the *asking* varies. Every adaptation is recorded on the profile, so a result can
be attributed to the model or to its inputs rather than being an unexplained aggregate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# The schema-dialect conversion is **one implementation**, in `services.generation`, and
# this module delegates to it rather than carrying a second copy. Only production's was
# exercised end to end, so a drift between two copies would have surfaced as the
# evaluation measuring a schema the pipeline never sends -- or approving one a real call
# refuses. The names below are re-exported because they are this module's public surface
# and `evaluation/live.py` and the tests use them by those names.
from services.generation import (  # noqa: F401
    DIALECT_ANTHROPIC_VERTEX,
    DIALECT_GEMINI,
    DIALECT_STRICT,
    SKILLS_AS_ARRAY,
    VERTEX_OPTIONAL_PARAMETER_LIMIT,
    count_optional_parameters,
    reshape_free_form_maps,
    to_dialect,
)

#: Output ceiling for a candidate that spends a large share of its budget on reasoning.
#:
#: **Not a preference -- a measurement.** A reasoning model emits its thinking before
#: the document and is billed for it as output, so an 8,000-token ceiling left
#: `qwen3.8-flash` and `z-ai/glm-5.3-flash` with *nothing*: `finish_reason: length`,
#: 8,000 reasoning tokens, `content_len: 0`. Both produced valid ~5,000-character
#: documents at 32,000. Scoring the empty result as a model failure would have ranked
#: this project's ceiling rather than the models -- and did, in the first study, where
#: both were recorded as 0/3.
#:
#: 32,000 is chosen because qwen needed it: at 16,000 it was still empty. The ceiling is
#: generous rather than tuned, since a budget that is never consumed costs nothing, while
#: one that is too low silently deletes a candidate.
REASONING_MODEL_OUTPUT_TOKENS = 32_000


@dataclass(frozen=True)
class CandidateInputs:
    """How one candidate model is asked, and why.

    ``dialect`` selects the schema shape; ``prompt_overrides`` optionally replaces
    named prompt fragments. Both are part of the candidate's *measurement*, so both are
    reported alongside its result -- a model that only passes because of a tuned prompt
    must not be recorded as though it passed unaided.
    """

    model_id: str
    #: Which schema dialect this candidate needs. See the constants above.
    dialect: str = DIALECT_GEMINI
    #: Free-text note on what was adapted and why. Required to be non-empty when the
    #: dialect is not the default, so an adaptation cannot be silent.
    rationale: str = ""
    #: Prompt fragments replaced for this candidate, by fragment name.
    prompt_overrides: dict = field(default_factory=dict)
    #: Output-token ceiling for this candidate. ``None`` uses the pipeline's configured
    #: ``max_output_tokens`` (8,000), which is the Gemini-shaped default.
    #:
    #: **This is a measurement-fairness parameter, not a tuning knob.** A reasoning model
    #: emits its thinking *before* the document and is billed for it as output, so a
    #: ceiling that suits a non-reasoning model can leave a reasoning one with nothing
    #: left to write in. Measured on 2026-10-27: `qwen3.8-flash` and
    #: `z-ai/glm-5.3-flash` consumed the **entire** 8,000-token budget as reasoning and
    #: returned an empty string -- `finish_reason: length`, `content_len: 0`. Raised to
    #: 32,000 both produced valid 4,900-5,400-character documents.
    #:
    #: That is not a weak model failing a task; it is a ceiling too low for its output
    #: shape, and scoring it as a failure would rank the shape rather than the model.
    #: Every candidate is still judged by the identical acceptance bar.
    max_output_tokens: Optional[int] = None
    #: Why this ceiling, when it is not the default. Required alongside a non-default
    #: value for the same reason as ``dialect``.
    output_rationale: str = ""

    def __post_init__(self) -> None:
        if self.dialect != DIALECT_GEMINI and not self.rationale.strip():
            raise ValueError(
                f"{self.model_id}: a non-default schema dialect must record why it is "
                "needed, or the adaptation is invisible in the results"
            )
        if self.max_output_tokens is not None and not self.output_rationale.strip():
            raise ValueError(
                f"{self.model_id}: a non-default output ceiling must record why it is "
                "needed, or a raised budget is indistinguishable from favouritism"
            )


#: How each candidate is asked. A model absent from this mapping is asked the default
#: (Gemini) way, which is the shape this project has always sent.
#:
#: Each non-default entry records the **measured** error that forced it. An entry
#: without one is an assumption, and `tests/test_evaluation_inputs.py` rejects it.
#: How each candidate is asked. **One entry: the selected model.**
#:
#: The rejected candidates' profiles were removed with them (owner's decision,
#: 2026-10-27). A model absent from this mapping is asked the **shipped** way, which is
#: now the strict dialect -- the shape production sends.
#:
#: The adaptations that were measured during the study, kept for the next curation
#: because each is a property of a *provider family* rather than of one model:
#:
#: * **OpenAI** strict mode requires ``additionalProperties: false`` on every object, and
#:   cannot express a free-form map, so ``skills`` must be an array of ``{category,
#:   items}``. Sending the Gemini-shaped schema returns
#:   ``invalid_json_schema``.
#: * **Anthropic behind Vertex** rejects a schema with more than 24 *optional*
#:   parameters: ``Schemas contains too many optional parameters (27)... (limit: 24)``.
#:   Requiring every field satisfies it, which the strict dialect now does globally.
#: * **Google Gemini** rejects ``additionalProperties`` outright --
#:   ``not supported in the Gemini API`` -- so that keyword must be stripped for it.
#: * **Reasoning models** (`qwen3.8-flash`, `glm-5.3-flash`) spent an entire 8,000-token
#:   budget on reasoning and returned an **empty** body. They need a higher ceiling; see
#:   :data:`REASONING_MODEL_OUTPUT_TOKENS`.
#:
#: Each non-default entry records the **measured** error that forced it. An entry without
#: one is an assumption, and `tests/test_evaluation_inputs.py` rejects it.
CANDIDATE_INPUTS: tuple[CandidateInputs, ...] = (
    CandidateInputs(
        model_id="openai/gpt-6-luna",
        # The selected model, and the reason the shipped schema is strict: its provider
        # refuses anything else, so `evaluation` and production now agree by construction.
        dialect=DIALECT_STRICT,
        rationale=(
            "OpenAI's strict mode requires additionalProperties to be false on every "
            "object: measured 'Invalid schema for response_format: In context=("
            "('properties', 'cv'), 'additionalProperties' is required to be supplied and "
            "to be false'. It also cannot express a free-form map, so `skills` is asked "
            "for as an array of {category, items} rather than an object keyed by "
            "category. The production schema was converted to match, so this entry now "
            "documents the shape the pipeline sends rather than an evaluation-only one."
        ),
    ),
)


def inputs_for(model_id: str) -> CandidateInputs:
    """The input profile for ``model_id``, defaulting to the shape already shipped.

    A model with no entry is asked the default way rather than being refused: the
    mapping is a list of *adaptations*, and its absence means "no adaptation was
    needed", which is the honest default.
    """
    for candidate in CANDIDATE_INPUTS:
        if candidate.model_id == model_id:
            return candidate
    return CandidateInputs(model_id=model_id)


def adapted_candidates() -> tuple[CandidateInputs, ...]:
    """Candidates whose inputs were changed from the default, for reporting."""
    return tuple(c for c in CANDIDATE_INPUTS if c.dialect != DIALECT_GEMINI
                 or c.prompt_overrides)


def schema_for_candidate(model_id: str, base_schema):
    """``base_schema`` rendered the way ``model_id`` needs to be asked.

    The single entry point the evaluation uses, so a dialect cannot be applied to one
    call and forgotten on another.
    """
    candidate = inputs_for(model_id)
    if candidate.dialect == DIALECT_GEMINI:
        return to_dialect(base_schema, DIALECT_GEMINI)
    return to_dialect(reshape_free_form_maps(base_schema), candidate.dialect)
