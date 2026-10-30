"""The response contract sent to the provider, per document kind.

The schemas describe the envelope the model must return, and building them here rather
than per call keeps the cost off the generation path. They are plain data describing a
contract, not per-run state -- deliberately *not* an environment read (ADR 0010).

See [ADR 0012](../../../docs/DECISIONS/0012-structured-output-scope.md) for why the
constraint stops at the envelope, and
[ADR 0016](../../../docs/DECISIONS/0016-per-candidate-inputs-and-one-winner.md) for why
the shipped dialect is strict.
"""
from __future__ import annotations

from typing import Optional

from services.schema_dialect import reshape_free_form_maps, to_dialect, DIALECT_STRICT

# Where a schema is sent, and where it deliberately is not.
#
# Structured output constrains a response to a declared shape, so the brace-scan in
# :func:`parse_json_response` stops being the failure path. The first implementation was
# **deleted as dead code in Phase 1 (D-1)** because ``response_mime_type="application/json"``
# caused premature truncation of long document responses. That reason still holds, so the
# scope is per call rather than global (ADR 0012):
#
# * the **CV draft** and the **cover letter** always return one complete document, so they
#   get a schema;
# * the **layout retry** is the one call whose response may be a *delta* -- an object of
#   unit ids with no document key. A schema requiring ``cv`` cannot express that shape, so
#   sending one there would break :func:`apply_cv_delta` or make the provider substitute a
#   whole-document answer for the cheaper delta. That call sends **no** schema.
#
# The parse guarantee is designed into the schema rather than hoped for, and the
# truncation risk is handled where it belongs: the **output ceiling**. Measured, no
# constrained response truncated at its budget, while every token went to reasoning in the
# models that failed.
#
# **The body is now strict too, which reversed the original decision** (ADR 0016). The
# reasoning that left ``additionalProperties`` unset -- enumerating a ~1,350-token document
# makes a constrained response longer and so more cut-off-prone -- was sound for Gemini and
# is not permitted by the selected model: OpenAI's strict mode refuses a schema without
# ``additionalProperties: false`` outright. `schema_dialect.to_dialect` performs the
# conversion; ``tailoring_explanation`` stays nullable even there, so requiring it does not
# make it mandatory in meaning.


def _tailoring_explanation_schema():
    """The explanation object, accepted in either position by :func:`extract_explanation`."""
    from google.genai import types

    return types.Schema(
        type="OBJECT",
        description="How the document was tailored. Optional; omit it if there is nothing to say.",
        properties={
            key: types.Schema(type="STRING")
            for key in (
                "summary_changes",
                "bullet_modifications",
                "skill_reordering",
                "project_selection",
                "overall_strategy",
            )
        },
    )

def _cv_document_schema():
    """The CV body: properties described, nothing required.

    ``summary`` is an array of strings, ``skills`` a map of category to skills, and
    ``experience`` a list of roles with their own bullets and projects -- the shape
    ``TailoredCV`` validates. Listing them keeps the contract meaningful; *not*
    requiring them keeps the response short enough to finish.
    """
    from google.genai import types

    return types.Schema(
        type="OBJECT",
        description="The tailored CV. Keep every employer, title and date from the profile.",
        properties={
            "title": types.Schema(type="STRING"),
            "work_authorization": types.Schema(type="STRING", nullable=True),
            "summary": types.Schema(type="ARRAY", items=types.Schema(type="STRING")),
            "skills": types.Schema(
                type="OBJECT",
                # ``additional_properties`` is deliberately **not** set here, and this
                # is a fix rather than a simplification: the Gemini API rejects the
                # keyword outright -- "additionalProperties is not supported in the
                # Gemini API" -- so every schema-bearing draft call failed after three
                # attempts on the default provider. Verified against the live API on
                # 2026-10-26: an otherwise identical schema succeeds without it and
                # fails with it.
                #
                # Nothing is lost. The comment above already claimed this keyword was
                # unset; the code disagreed with its own comment. A map of category to
                # skills needs no declaration for the *response* to be valid -- it is
                # ``validate_cv`` that checks the contents, and it always was.
            ),
            "experience": types.Schema(
                type="ARRAY",
                items=types.Schema(
                    type="OBJECT",
                    properties={
                        "company": types.Schema(type="STRING"),
                        "role": types.Schema(type="STRING"),
                        "start_date": types.Schema(type="STRING"),
                        "end_date": types.Schema(type="STRING"),
                        "bullets": types.Schema(
                            type="ARRAY", items=types.Schema(type="STRING")
                        ),
                        "projects": types.Schema(
                            type="ARRAY",
                            items=types.Schema(
                                type="OBJECT",
                                properties={
                                    "name": types.Schema(type="STRING"),
                                    "bullets": types.Schema(
                                        type="ARRAY", items=types.Schema(type="STRING")
                                    ),
                                },
                            ),
                        ),
                    },
                ),
            ),
            "include_education": types.Schema(type="BOOLEAN"),
            "include_certifications": types.Schema(type="BOOLEAN"),
            # extract_explanation reads a nested explanation too, so it must stay legal
            # here. Forbidding it would decide, on the model's behalf, which of the two
            # shapes it may return -- the thing `extract_explanation` exists not to do.
            "tailoring_explanation": _tailoring_explanation_schema(),
        },
    )

def _cover_letter_document_schema():
    from google.genai import types

    return types.Schema(
        type="OBJECT",
        description="The tailored cover letter: four paragraphs, 290-310 body words.",
        properties={
            "role_title": types.Schema(type="STRING"),
            "company_name": types.Schema(type="STRING"),
            "paragraphs": types.Schema(type="ARRAY", items=types.Schema(type="STRING")),
            "closing_line": types.Schema(type="STRING"),
            "signature_name": types.Schema(type="STRING"),
        },
    )

def _document_response_schema(envelope_key: str, document):
    """Wrap one document in its envelope, requiring exactly that envelope key.

    ``cv``/``cover_letter`` is the only required property. The prompt asks for
    ``tailoring_explanation`` beside it, but the recorded fixtures show it is genuinely
    optional in practice and :func:`extract_explanation` reads it defensively -- so
    requiring it would turn a harmless omission into a failed run and a wasted call.
    """
    from google.genai import types

    properties = {envelope_key: document}
    if envelope_key == "cv":
        properties["tailoring_explanation"] = _tailoring_explanation_schema()
    return types.Schema(
        type="OBJECT",
        description=(
            "A JSON object carrying the tailored document under "
            f"{envelope_key!r}. No markdown, commentary or LaTeX."
        ),
        properties=properties,
        required=[envelope_key],
    )

def _to_strict_dialect(schema):
    """``schema`` in the strict dialect, with the CV's free-form map respelled.

    The conversion itself, and why the shipped contract is strict at all, live in
    :func:`services.schema_dialect.to_dialect` and the module comment above. What is
    specific to this call site is the **order**: the map is reshaped *before* the
    conversion, because a strict dialect is what makes the map inexpressible in the
    first place.
    """
    return to_dialect(reshape_free_form_maps(schema), DIALECT_STRICT)

def _build_response_schemas() -> dict:
    """Build the per-document schemas once, at import.

    Building them here rather than per call keeps the cost off the generation path.
    They are plain data describing a contract, not per-run state, so a module-level
    mapping is correct -- this is deliberately *not* an environment read (ADR 0010).

    Every schema is rendered into the **strict** dialect (see :func:`_to_strict_dialect`),
    because the selected model requires it and a schema is sent to the provider as-is.
    """
    return {
        "cv": _to_strict_dialect(_document_response_schema("cv", _cv_document_schema())),
        "cover_letter": _to_strict_dialect(
            _document_response_schema("cover_letter", _cover_letter_document_schema())
        ),
    }

#: Response contract per document kind. A kind absent from this mapping is sent **no**
#: schema: an unknown document type must not inherit the CV's constraints by accident.
RESPONSE_SCHEMAS = _build_response_schemas()

def response_schema_for(kind: Optional[str], allow_delta: bool = False):
    """The schema for one call, or ``None`` to leave the response unconstrained.

    ``allow_delta`` marks the layout retry, whose response may be a delta rather than a
    document. That path is deliberately schema-free: see the module comment above
    :data:`RESPONSE_SCHEMAS`.

    Returning ``None`` means "no schema", and the caller must then also leave
    ``response_mime_type`` unset -- JSON mode without a schema still changes the
    response envelope, and this function's contract is about the whole config.
    """
    if allow_delta:
        return None
    return RESPONSE_SCHEMAS.get(kind or "")
