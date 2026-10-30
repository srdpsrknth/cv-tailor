"""LLM orchestration and document validation -- the public surface of the pipeline.

This module is the **facade**. It holds no logic of its own: the pipeline was split
along the seams it already had, and every name that used to be defined here is
re-exported unchanged, so no caller or test had to move.

| Module | What it owns |
|---|---|
| `services.schema_dialect` | The one schema-dialect conversion, shared with the study |
| `services.response_schemas` | The response contract sent per document kind |
| `services.prompts` | Prompt construction: context, draft briefs, retry briefs |
| `services.cv_delta` | Response parsing, and the layout retry's delta |
| `services.validation` | Candidate-specific rules and the document gates |
| `services.pipeline` | `DocumentGenerator`, the call/validate/retry loop |

The split was mechanical and is proven so: every top-level statement was moved by AST
boundary and compared byte-for-byte against the original, with none edited, dropped or
duplicated.

The whole flow knows **nothing** about the filesystem. ``tailor_service`` owns
persistence and calls into here, which is what makes it testable in parts.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# --- parsing and the retry delta -------------------------------------------------------
from services.cv_delta import (  # noqa: F401
    apply_cv_delta,
    extract_explanation,
    looks_like_cv_delta,
    parse_json_response,
)

# --- the generation pipeline -----------------------------------------------------------
from services.pipeline import (  # noqa: F401
    MAX_LAYOUT_ATTEMPTS,
    MAX_VALIDATION_ATTEMPTS,
    DocumentGenerator,
    TokenCounts,
)

# --- prompt construction ---------------------------------------------------------------
from services.prompts import (  # noqa: F401
    EDITORIAL_REQUIREMENTS,
    LAYOUT_BUDGET_FLOOR,
    LAYOUT_BUDGET_START,
    LAYOUT_BUDGET_STEP,
    LAYOUT_RETRY_MARKER,
    PROMPT_CL_PATH,
    PROMPT_CV_PATH,
    build_context,
    build_cv_prompt,
    cv_body_words,
    layout_budget,
    layout_correction_instruction,
    layout_inventory,
    layout_retry_instruction,
    pinned_project_clause,
)

# --- the response contract -------------------------------------------------------------
from services.response_schemas import (  # noqa: F401
    RESPONSE_SCHEMAS,
    response_schema_for,
)

# --- schema dialect --------------------------------------------------------------------
from services.schema_dialect import (  # noqa: F401
    DIALECT_ANTHROPIC_VERTEX,
    DIALECT_GEMINI,
    DIALECT_STRICT,
    SKILLS_AS_ARRAY,
    VERTEX_OPTIONAL_PARAMETER_LIMIT,
    count_optional_parameters,
    reshape_free_form_maps,
    to_dialect,
)

# --- validation ------------------------------------------------------------------------
from services.validation import (  # noqa: F401
    _FACTS_CACHE_FIELD,
    _profile_facts_json,
    DEFAULT_PROFILE_RULES,
    ProfileRules,
    profile_facts_json,
    validate_cover_letter,
    validate_cv,
)

__all__ = [
    "DEFAULT_PROFILE_RULES",
    "DIALECT_ANTHROPIC_VERTEX",
    "DIALECT_GEMINI",
    "DIALECT_STRICT",
    "DocumentGenerator",
    "EDITORIAL_REQUIREMENTS",
    "LAYOUT_BUDGET_FLOOR",
    "LAYOUT_BUDGET_START",
    "LAYOUT_BUDGET_STEP",
    "LAYOUT_RETRY_MARKER",
    "MAX_LAYOUT_ATTEMPTS",
    "MAX_VALIDATION_ATTEMPTS",
    "PROMPT_CL_PATH",
    "PROMPT_CV_PATH",
    "ProfileRules",
    "RESPONSE_SCHEMAS",
    "SKILLS_AS_ARRAY",
    "TokenCounts",
    "VERTEX_OPTIONAL_PARAMETER_LIMIT",
    "apply_cv_delta",    "build_context",
    "build_cv_prompt",
    "count_optional_parameters",
    "cv_body_words",
    "extract_explanation",
    "layout_budget",
    "layout_correction_instruction",
    "layout_inventory",
    "layout_retry_instruction",
    "looks_like_cv_delta",
    "parse_json_response",
    "pinned_project_clause",
    "profile_facts_json",
    "reshape_free_form_maps",
    "response_schema_for",
    "to_dialect",
    "validate_cover_letter",
    "validate_cv",
]
