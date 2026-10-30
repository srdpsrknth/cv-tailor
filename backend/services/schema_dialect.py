"""The one schema-dialect conversion, shared by production and the study.

A response schema has to be rendered differently for each provider family, and the
renderings are not degrees of strictness -- they are contradictions, measured against
the live API:

| Family | Requirement | What a Gemini-shaped schema gets |
|---|---|---|
| OpenAI | ``additionalProperties: false`` **required** | `400 "required to be supplied and to be false"` |
| Anthropic via Vertex | **<= 24** optional parameters | `27 -> 400 "too many optional parameters (27)... limit: 24"` |
| Google Gemini | ``additionalProperties`` **forbidden** | `400 "not supported in the Gemini API"` |

Gemini rejects the keyword OpenAI requires. Serving all three from one implementation
is what stops the pipeline and the evaluation from drifting apart: they used to convert
separately, and only production's was exercised end to end, so a difference would have
shown up as the study scoring a schema the pipeline never sends.
"""
from __future__ import annotations


#: Which rendering a provider family needs. See :func:`to_dialect`.
DIALECT_GEMINI = "gemini"

DIALECT_STRICT = "strict"

DIALECT_ANTHROPIC_VERTEX = "anthropic-vertex"

#: Anthropic behind Vertex caps the number of *optional* parameters and rejects the
#: request above it rather than degrading: "Schemas contains too many optional parameters
#: (27)... (limit: 24)", measured against the live API. Recorded as a constant so the
#: constraint can be asserted rather than rediscovered through a paid 400.
VERTEX_OPTIONAL_PARAMETER_LIMIT = 24

#: Keywords the Gemini SDK emits that standard JSON Schema does not admit.
_GEMINI_ONLY_KEYWORDS = ("nullable", "property_ordering")

_TYPE_NAMES = {
    "STRING": "string", "NUMBER": "number", "INTEGER": "integer",
    "BOOLEAN": "boolean", "ARRAY": "array", "OBJECT": "object", "NULL": "null",
}

#: ``skills`` as a strict dialect must ask for it: an array of ``{category, items}``.
#: A category-to-skills *map* and ``additionalProperties: false`` are opposites, so the
#: request is respelled rather than the acceptance rules relaxed. Verified live against
#: OpenAI, Vertex and Gemini: all three accept this where the map shape failed on two.
#:
#: **The two former copies of this constant disagreed, and this is production's.** The
#: evaluation's copy carried ``description`` fields on ``category`` and ``items``; the
#: one production built inline did not. Collapsing the duplication had to pick one, and
#: it picks the bytes the pipeline actually sent, so this stays a pure refactor: the
#: response-schema digest is an ingredient of the generation cache key (ADR 0015), and
#: changing what the model is asked would silently invalidate every cached generation
#: and alter the request. Adding the descriptions back is a prompt change, and it belongs
#: with a prompt change rather than in a de-duplication commit.
SKILLS_AS_ARRAY = {
    "type": "array",
    "description": (
        "Skill groups. Each entry names a category and lists its skills -- the same "
        "information as a category-to-skills map, as an array."
    ),
    "items": {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["category", "items"],
        "additionalProperties": False,
    },
}

def _dumped_schema(schema) -> dict:
    """``schema`` as a plain dict in the standard dialect, whatever it arrived as.

    Accepting both spellings is what lets production (which builds SDK ``Schema``
    objects) and the evaluation suite (which hands over plain dicts) share one
    conversion. The SDK's dump is **not** standard JSON Schema -- its type names are
    uppercase and it emits keywords standard validators reject -- so two repairs happen
    here, and both were found by making a real call:

    * type names are lowercased, because the wire dialect is what an endpoint validates.
      Uppercase made DeepInfra answer *"Grammar error: Invalid type: OBJECT"* and
      Parasail *"Failed to compile json grammar"*;
    * ``nullable: true`` becomes ``type: [<t>, "null"]``, which is how standard JSON
      Schema expresses it. Dropping the keyword would silently turn an optional field
      into a required one -- a correctness change disguised as a compatibility fix.
    """
    if isinstance(schema, dict):
        dumped = schema
    else:
        model_dump = getattr(schema, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(exclude_none=True)
        else:
            to_json_dict = getattr(schema, "to_json_dict", None)
            dumped = to_json_dict() if callable(to_json_dict) else schema

    def to_standard(node):
        if isinstance(node, list):
            return [to_standard(item) for item in node]
        if not isinstance(node, dict) or "type" not in node and not any(
            key in node for key in _GEMINI_ONLY_KEYWORDS
        ):
            # Still recurse: a mapping without keywords at this level can hold objects
            # and arrays below it that do carry them.
            if isinstance(node, dict):
                return {key: to_standard(value) for key, value in node.items()}
            return node

        result = {}
        nullable = bool(node.get("nullable", False))
        for key, value in node.items():
            if key in _GEMINI_ONLY_KEYWORDS:
                continue
            if key == "type":
                if isinstance(value, list):
                    result[key] = [_TYPE_NAMES.get(str(v).upper(), v) for v in value]
                elif isinstance(value, str):
                    result[key] = _TYPE_NAMES.get(value.upper(), value)
                else:
                    result[key] = value
                continue
            result[key] = to_standard(value)

        if nullable and "type" in result:
            existing = result["type"]
            if isinstance(existing, list):
                if "null" not in existing:
                    result["type"] = existing + ["null"]
            elif existing != "null":
                result["type"] = [existing, "null"]
        return result

    return to_standard(dumped)

def _strip_additional_properties(node):
    """``node`` without any ``additionalProperties``, recursively.

    Gemini rejects the keyword outright -- "not supported in the Gemini API" -- so for
    that dialect it must be **absent**, not ``false``, which is a different request.
    """
    if isinstance(node, dict):
        return {
            key: _strip_additional_properties(value)
            for key, value in node.items()
            if key not in ("additionalProperties", "additional_properties")
        }
    if isinstance(node, list):
        return [_strip_additional_properties(item) for item in node]
    return node

#: Properties that are **required but nullable** in a strict dialect.
#:
#: Strict mode permits a required property whose type admits ``null``, so "no
#: explanation" is *expressed* rather than omitted. That matters because the explanation
#: is commentary: forcing a value would turn a harmless omission into a failed
#: validation and a wasted paid call, and ``extract_explanation`` already treats an
#: absent or null value as no explanation. Strict mode enforces the requirement
#: literally -- omitting the key yields "'required' is required to be supplied and to be
#: an array including every key in properties. Missing 'tailoring_explanation'." --
#: measured against the live API on 2026-10-27, where it broke the first real CLI run
#: after the model switch.
#:
#: The *modelling* is now right for every property at the source rather than forced here
#: after the fact: these are declared ``nullable=True`` where they are built. The rule is
#: kept because a schema handed in from elsewhere must not silently become stricter than
#: intended.
_REQUIRED_BUT_NULLABLE = ("tailoring_explanation",)

def _require_every_property(node):
    """Every object's declared properties become ``required``, and it is closed.

    Applied recursively because ``items`` inside an array and nested objects all need the
    treatment -- one nested object missing it is enough for the request to be rejected.
    Properties named in :data:`_REQUIRED_BUT_NULLABLE` additionally have ``"null"``
    admitted into their type, so requiring them does not make them mandatory in meaning.

    Children are visited **before** the node itself. It makes no difference to which
    objects get closed -- every object is reached either way -- but it keeps a node's own
    ``type`` from being rewritten to ``["object", "null"]`` before this function has
    decided whether the node is an object, which is the check the rule is written on.
    """
    if isinstance(node, dict):
        for value in node.values():
            _require_every_property(value)
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            properties = node["properties"]
            for name in _REQUIRED_BUT_NULLABLE:
                if name in properties:
                    declared = properties[name].get("type")
                    if isinstance(declared, str) and declared != "null":
                        properties[name]["type"] = [declared, "null"]
                    elif isinstance(declared, list) and "null" not in declared:
                        properties[name]["type"] = declared + ["null"]
            node["required"] = sorted(properties)
            node["additionalProperties"] = False
    elif isinstance(node, list):
        for value in node:
            _require_every_property(value)
    return node

def reshape_free_form_maps(schema):
    """Replace the CV's free-form ``skills`` map with the array spelling.

    Only meaningful for a strict dialect: a map and ``additionalProperties: false``
    contradict each other, so one has to give, and the document's meaning is preserved by
    changing the *request* rather than the acceptance rules. A no-op on a schema whose
    ``skills`` is already an array, which is why the shipped schema can be passed through
    it unconditionally.
    """
    import copy

    result = copy.deepcopy(_dumped_schema(schema))
    cv = ((result.get("properties") or {}).get("cv") or {}).get("properties") or {}
    skills = cv.get("skills")
    if isinstance(skills, dict) and skills.get("type") == "object" and "properties" not in skills:
        cv["skills"] = copy.deepcopy(SKILLS_AS_ARRAY)
    return result

def to_dialect(schema, dialect: str):
    """``schema`` rendered for ``dialect`` -- the one implementation of the conversion.

    **Why this is here and not duplicated.** Production and the evaluation suite both
    need to render a schema for a provider family, and they used to do it in two separate
    functions. Only production's was exercised end to end, so a drift between them would
    have shown up as the evaluation measuring something the pipeline never sends -- or,
    worse, as a schema the evaluation approves and a real call refuses. There is now one
    conversion, and the evaluation calls it.

    The transformations are what the live errors demand, applied structurally so a schema
    edit cannot quietly stop satisfying a provider:

    * :data:`DIALECT_GEMINI` -- ``additionalProperties`` stripped, because Gemini rejects
      that keyword with "not supported in the Gemini API". Note this is *absent*, not
      ``false``: the two are different requests and only one is accepted.
    * :data:`DIALECT_STRICT` -- every object's properties become ``required`` with
      ``additionalProperties: false``, which is OpenAI's documented demand.
    * :data:`DIALECT_ANTHROPIC_VERTEX` -- the same tightening, because Vertex's limit is
      on *optional* parameters and requiring them reduces the count to zero. Kept as a
      separate name because the reason differs and a future change may need to diverge.

    A free-form map cannot be expressed in a strict dialect, so :func:`reshape_free_form_maps`
    is applied by the caller that knows which field is a map.
    """
    import copy

    if dialect == DIALECT_GEMINI:
        return _strip_additional_properties(copy.deepcopy(_dumped_schema(schema)))
    if dialect in (DIALECT_STRICT, DIALECT_ANTHROPIC_VERTEX):
        return _require_every_property(copy.deepcopy(_dumped_schema(schema)))
    raise ValueError(
        f"unknown schema dialect {dialect!r}; expected one of "
        f"{DIALECT_GEMINI!r}, {DIALECT_STRICT!r}, {DIALECT_ANTHROPIC_VERTEX!r}"
    )

def count_optional_parameters(schema) -> int:
    """Optional parameters anywhere in a dumped JSON schema.

    Vertex's limit is on this number and it is not obvious by inspection: the CV
    schema's 27 were spread across nested array items. Kept so the constraint can be
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

    return walk(_dumped_schema(schema))
