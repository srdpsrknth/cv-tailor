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


# --- the schema dialects that actually work ------------------------------------------------

#: Gemini's ``Schema`` accepts only its own keywords. ``additionalProperties`` is
#: **rejected outright** ("not supported in the Gemini API"), verified against the live
#: API. This is the dialect the project shipped with, and it is what the other two
#: families refuse.
DIALECT_GEMINI = "gemini"

#: OpenAI's strict mode **requires** ``additionalProperties: false`` on every object and
#: every property listed in ``required``. Verified live: omitting it yields
#: ``invalid_json_schema`` rather than a lenient parse.
DIALECT_STRICT = "strict"

#: Anthropic's models behind Vertex cap the number of *optional* parameters and reject
#: the request above it rather than degrading. Measured against the live API at 27:
#: "Schemas contains too many optional parameters (27)... (limit: 24)". Recorded as a
#: constant so the constraint can be asserted rather than rediscovered through a paid
#: 400.
VERTEX_OPTIONAL_PARAMETER_LIMIT = 24

DIALECT_ANTHROPIC_VERTEX = "anthropic-vertex"


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

    def __post_init__(self) -> None:
        if self.dialect != DIALECT_GEMINI and not self.rationale.strip():
            raise ValueError(
                f"{self.model_id}: a non-default schema dialect must record why it is "
                "needed, or the adaptation is invisible in the results"
            )


#: How each candidate is asked. A model absent from this mapping is asked the default
#: (Gemini) way, which is the shape this project has always sent.
#:
#: Each non-default entry records the **measured** error that forced it. An entry
#: without one is an assumption, and `tests/test_evaluation_inputs.py` rejects it.
CANDIDATE_INPUTS: tuple[CandidateInputs, ...] = (
    CandidateInputs(
        model_id="deepseek/deepseek-v4-flash",
        dialect=DIALECT_GEMINI,
    ),
    CandidateInputs(
        model_id="anthropic/claude-haiku-5.5",
        dialect=DIALECT_ANTHROPIC_VERTEX,
        rationale=(
            "Routed to Anthropic models behind Google Vertex, which rejects a schema "
            "with more than 24 optional parameters: measured 'Schemas contains too many "
            "optional parameters (27), which would make grammar compilation inefficient. "
            "Reduce the number of optional parameters (limit: 24)'. The count of 27 is a "
            "consequence of ADR 0012 leaving the document body optional, so satisfying "
            "Vertex means requiring the body's fields for this candidate."
        ),
    ),
    CandidateInputs(
        model_id="openai/gpt-6-luna",
        dialect=DIALECT_STRICT,
        rationale=(
            "OpenAI's strict mode requires additionalProperties to be false on every "
            "object: measured 'Invalid schema for response_format: In context=("
            "('properties', 'cv'), 'additionalProperties' is required to be supplied and "
            "to be false'. It also cannot express a free-form map, so `skills` is asked "
            "for as an array of {category, items} rather than an object keyed by "
            "category. Verified live: all three families then accept the request."
        ),
    ),
    CandidateInputs(
        model_id="qwen/qwen3.8-flash",
        dialect=DIALECT_GEMINI,
    ),
    CandidateInputs(
        model_id="z-ai/glm-5.3-flash",
        dialect=DIALECT_GEMINI,
    ),
    CandidateInputs(
        model_id="mistralai/mistral-small-2603",
        dialect=DIALECT_GEMINI,
    ),
    CandidateInputs(
        model_id="google/gemini-3.8-flash",
        dialect=DIALECT_GEMINI,
    ),
    CandidateInputs(
        model_id="anthropic/claude-sonnet-5",
        dialect=DIALECT_ANTHROPIC_VERTEX,
        rationale=(
            "Same family and same Vertex routing as claude-haiku-5.5, so the same "
            "24-optional-parameter ceiling applies."
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


def count_optional_parameters(schema) -> int:
    """Optional parameters anywhere in a dumped JSON schema.

    Vertex's limit is on this number, and it is not obvious by inspection: the CV
    schema's 27 are spread across nested array items. Kept here so the constraint can be
    asserted rather than discovered through a paid 400.
    """

    def walk(node) -> int:
        total = 0
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                required = set(node.get("required") or [])
                total += sum(1 for name in properties if name not in required)
            for value in node.values():
                total += walk(value)
        elif isinstance(node, list):
            for value in node:
                total += walk(value)
        return total

    return walk(schema)


def to_dialect(schema, dialect: str):
    """``schema`` (a plain dict) rendered for ``dialect``.

    The three transformations are what the live errors demand, and they are applied
    structurally rather than by hand so a schema edit cannot quietly stop satisfying a
    provider:

    * :data:`DIALECT_GEMINI` -- returned unchanged, minus ``additionalProperties``,
      which Gemini rejects outright.
    * :data:`DIALECT_STRICT` -- every object's properties become ``required`` and
      ``additionalProperties: false`` is set, which is OpenAI's demand.
    * :data:`DIALECT_ANTHROPIC_VERTEX` -- the same tightening, because Vertex' limit is
      on *optional* parameters and requiring them reduces the count to zero. It is a
      separate constant because the reason differs and a future change may need to
      diverge.

    A free-form map is the one construct that cannot satisfy strict mode: an object with
    arbitrary keys is defined by *allowing* additional properties. ``skills`` is
    therefore reshaped by the caller rather than here, because only the caller knows
    which field is a map.
    """
    import copy

    result = copy.deepcopy(schema)

    def strip_additional(node) -> None:
        if isinstance(node, dict):
            node.pop("additionalProperties", None)
            node.pop("additional_properties", None)
            for value in node.values():
                strip_additional(value)
        elif isinstance(node, list):
            for value in node:
                strip_additional(value)

    def require_all(node) -> None:
        if isinstance(node, dict):
            # ``items`` inside an array, and nested objects, all need the treatment.
            if node.get("type") == "object" and isinstance(node.get("properties"), dict):
                node["required"] = sorted(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                require_all(value)
        elif isinstance(node, list):
            for value in node:
                require_all(value)

    if dialect == DIALECT_GEMINI:
        strip_additional(result)
    elif dialect in (DIALECT_STRICT, DIALECT_ANTHROPIC_VERTEX):
        require_all(result)
    else:
        raise ValueError(
            f"unknown schema dialect {dialect!r}; expected one of "
            f"{DIALECT_GEMINI!r}, {DIALECT_STRICT!r}, {DIALECT_ANTHROPIC_VERTEX!r}"
        )
    return result


#: The CV schema asks for ``skills`` as a free-form map (``{"type": "object"}``), which
#: is how the document is actually shaped: category name to list of skills. That
#: construct is **inexpressible** in a strict dialect, because
#: ``additionalProperties: false`` means precisely "no arbitrary keys" -- so a map and
#: strict mode are opposites, not a mismatch of degree.
#:
#: For a strict dialect the same information is asked for as an **array** of
#: ``{category, items}``, which is a different spelling of the same document and is
#: accepted. The parser accepts either, so the *document* is unchanged; only the way the
#: model is asked changes. Verified live against OpenAI, Vertex and Gemini: all three
#: return 200 with this shape, where the map shape failed on two of them.
SKILLS_AS_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "The skill category, e.g. 'Analytics' or 'Languages'.",
            },
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The skills in this category.",
            },
        },
        "required": ["category", "items"],
        "additionalProperties": False,
    },
    "description": (
        "Skill groups. Each entry names a category and lists its skills -- the same "
        "information as a category-to-skills map, as an array."
    ),
}


def reshape_free_form_maps(schema):
    """Replace ``skills``-style free-form maps with the array spelling.

    Only for a strict dialect: a map and ``additionalProperties: false`` contradict each
    other, so one of them has to give, and the document's meaning is preserved by
    changing the *request* rather than the acceptance rules.
    """
    import copy

    result = copy.deepcopy(schema)
    cv = ((result.get("properties") or {}).get("cv") or {}).get("properties") or {}
    skills = cv.get("skills")
    if isinstance(skills, dict) and skills.get("type") == "object" and "properties" not in skills:
        cv["skills"] = copy.deepcopy(SKILLS_AS_ARRAY)
    return result


def schema_for_candidate(model_id: str, base_schema):
    """``base_schema`` rendered the way ``model_id`` needs to be asked.

    The single entry point the evaluation uses, so a dialect cannot be applied to one
    call and forgotten on another.
    """
    candidate = inputs_for(model_id)
    if candidate.dialect == DIALECT_GEMINI:
        return to_dialect(base_schema, DIALECT_GEMINI)
    return to_dialect(reshape_free_form_maps(base_schema), candidate.dialect)
