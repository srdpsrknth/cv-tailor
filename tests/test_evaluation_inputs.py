"""Per-candidate input profiles (ADR 0016).

The mechanism exists because three provider families demand mutually incompatible
response schemas, measured against the live API. These tests pin the properties that
make the comparison fair rather than the *contents* of any one schema:

* each candidate's schema satisfies its dialect's **hard constraint**, asserted
  structurally so a schema edit cannot quietly stop satisfying a provider;
* the constraints are the ones actually observed, not assumed -- Vertex's 24-optional
  limit and OpenAI's mandatory ``additionalProperties: false``;
* **the default is unchanged** for candidates that need nothing, so this mechanism
  cannot alter the behaviour the project already ships;
* an adaptation must **say why**, so a tuned candidate is never silently tuned.

Everything here is offline. No network call is made.
"""
from __future__ import annotations

import json

import pytest

# Imported defensively and failed, not skipped, when absent: a broken import in the real
# tree is the thing this file exists to catch.
try:
    from evaluation import candidate_inputs
    from evaluation.candidate_inputs import (
        CANDIDATE_INPUTS,
        DIALECT_ANTHROPIC_VERTEX,
        DIALECT_GEMINI,
        DIALECT_STRICT,
        CandidateInputs,
        adapted_candidates,
        count_optional_parameters,
        inputs_for,
        reshape_free_form_maps,
        schema_for_candidate,
        to_dialect,
    )
except ImportError as error:  # pragma: no cover - only on a broken tree
    pytest.fail(f"evaluation.candidate_inputs could not be imported: {error}", pytrace=False)


# --- the constraints are the measured ones -------------------------------------------------

def test_the_vertex_optional_parameter_limit_is_the_measured_one():
    """Vertex's ceiling is 24 and the *shipped* schema exceeds it by three.

    Measured against the live API: "Schemas contains too many optional parameters (27),
    which would make grammar compilation inefficient. Reduce the number of optional
    parameters in your tool schemas (limit: 24)". Asserted here so the number is a
    recorded fact rather than a comment, and so a schema change that raises the count
    is caught before it costs a paid 400.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))

    assert candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT == 24
    assert count_optional_parameters(base) == 27, (
        'the shipped schema no longer has 27 optional parameters; the recorded error '
        'and the reason for the Vertex adaptation need re-checking'
    )
    assert count_optional_parameters(base) > candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT


def test_every_strict_candidate_fits_the_vertex_limit():
    """The adaptation must actually clear the constraint it exists for.

    Scoped to the Vertex dialect on purpose: the limit is a property of *that* endpoint,
    not a universal rule. A Gemini-dialect candidate is free to exceed it, and asserting
    otherwise would push every candidate onto the tightened shape and delete the
    comparison this module exists to make.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    checked = 0
    for candidate in CANDIDATE_INPUTS:
        if candidate.dialect != DIALECT_ANTHROPIC_VERTEX:
            continue
        checked += 1
        schema = schema_for_candidate(candidate.model_id, base)
        assert count_optional_parameters(schema) <= candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT, (
            f'{candidate.model_id} still exceeds the Vertex optional-parameter limit'
        )
    assert checked, 'no Vertex-dialect candidate is being checked'


def test_every_strict_candidate_supplies_additional_properties_false():
    """OpenAI's demand: "required to be supplied and to be false".

    Asserted on every object in the schema, because one nested object missing it is
    enough for the request to be rejected with `invalid_json_schema`.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))

    def objects_without_it(node, path='$'):
        missing = []
        if isinstance(node, dict):
            if node.get('type') == 'object':
                if node.get('additionalProperties') is not False:
                    missing.append(path)
            for key, value in node.items():
                missing += objects_without_it(value, f'{path}.{key}')
        elif isinstance(node, list):
            for index, value in enumerate(node):
                missing += objects_without_it(value, f'{path}[{index}]')
        return missing

    for candidate in CANDIDATE_INPUTS:
        if candidate.dialect not in (DIALECT_STRICT, DIALECT_ANTHROPIC_VERTEX):
            continue
        schema = schema_for_candidate(candidate.model_id, base)
        assert objects_without_it(schema) == [], (
            f'{candidate.model_id}: objects lack additionalProperties: false'
        )


def test_no_gemini_candidate_sends_additional_properties():
    """Gemini rejects the keyword outright, so it must be absent, not false.

    ``additionalProperties: false`` and *no* ``additionalProperties`` are different
    requests: Gemini accepts the second and refuses the first.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    for candidate in CANDIDATE_INPUTS:
        if candidate.dialect != DIALECT_GEMINI:
            continue
        dumped = json.dumps(schema_for_candidate(candidate.model_id, base))
        assert 'additionalProperties' not in dumped, (
            f'{candidate.model_id} is on the Gemini dialect, which rejects '
            f'additionalProperties'
        )


# --- the free-form map is the construct strict mode cannot express ---------------------------

def test_a_free_form_map_is_reshaped_for_strict_dialects():
    """A map and `additionalProperties: false` are opposites, so one must change.

    ``skills`` is a category-to-skills map, which is *defined* by allowing arbitrary
    keys. Asking for it as an array of ``{category, items}`` carries the same document
    and is accepted -- verified live on all three families.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    assert (base['properties']['cv']['properties']['skills']).get('type') == 'object'

    reshaped = reshape_free_form_maps(base)
    skills = reshaped['properties']['cv']['properties']['skills']
    assert skills['type'] == 'array'
    assert set(skills['items']['properties']) == {'category', 'items'}


def test_the_reshape_does_not_mutate_its_input():
    """It is applied to a copy, so one candidate's dialect cannot leak into another's."""
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    before = json.dumps(base)
    reshape_free_form_maps(base)
    assert json.dumps(base) == before


def test_a_map_keeps_its_map_shape_on_the_gemini_dialect():
    """Gemini has no objection to a map, so its schema is left alone."""
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    schema = schema_for_candidate('google/gemini-3.8-flash', base)
    assert schema['properties']['cv']['properties']['skills'].get('type') == 'object'


# --- the mechanism cannot change what already ships ------------------------------------------

def test_an_unlisted_candidate_gets_the_default_dialect():
    """The mapping lists *adaptations*; its absence means none was needed."""
    unknown = inputs_for('some/model-not-in-the-study')
    assert unknown.dialect == DIALECT_GEMINI
    assert unknown.prompt_overrides == {}


def test_the_default_dialect_is_a_no_op_for_the_shipped_schema():
    """A Gemini candidate must be asked exactly what the project already sends.

    This is what stops the mechanism from altering production behaviour: for the
    default dialect the rendered schema differs from the base only by the keyword
    Gemini rejects, which the shipped path already omits.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    rendered = schema_for_candidate('google/gemini-3.8-flash', base)
    assert json.dumps(rendered) == json.dumps(base)


def test_an_adaptation_must_record_why():
    """A silhouette tuned without a reason is indistinguishable from a mistake."""
    with pytest.raises(ValueError, match='record why'):
        CandidateInputs(model_id='vendor/model', dialect=DIALECT_STRICT)

    # The default dialect needs no justification, or every entry would carry boilerplate.
    CandidateInputs(model_id='vendor/model', dialect=DIALECT_GEMINI)


def test_every_non_default_candidate_in_the_study_has_a_rationale():
    """Checked on the shipped list, not only on the constructor."""
    for candidate in adapted_candidates():
        assert candidate.rationale.strip(), (
            f'{candidate.model_id} is adapted but records no reason'
        )


def test_an_unknown_dialect_is_refused():
    """A typo must not silently render the default schema."""
    with pytest.raises(ValueError, match='unknown schema dialect'):
        to_dialect({'type': 'object'}, 'not-a-dialect')


# --- the output ceiling is a fairness parameter, and it must be justified --------------------

def test_a_reasoning_model_gets_a_ceiling_it_can_finish_in():
    """The 8,000-token default left two models with an **empty** response.

    This is the defect that made the first study wrong about two candidates. Measured
    against the real CV prompt on 2026-10-27: `qwen3.8-flash` at an 8,000 ceiling
    returned `finish_reason: length` with 8,000 reasoning tokens and
    ``content_len: 0`` -- and again at 16,000 -- while at 32,000 it produced a valid
    4,974-character document. `z-ai/glm-5.3-flash` behaved the same way and succeeded
    from 16,000.

    Scoring the empty response as a model failure ranks *this project's ceiling* rather
    than the model, and both were recorded as 0/3 before this was understood.
    """
    from evaluation.candidate_inputs import REASONING_MODEL_OUTPUT_TOKENS

    for model_id in ('qwen/qwen3.8-flash', 'z-ai/glm-5.3-flash'):
        candidate = inputs_for(model_id)
        assert candidate.max_output_tokens is not None, (
            f'{model_id} emptied its response at the default ceiling and must be given '
            f'one it can finish in'
        )
        assert candidate.max_output_tokens >= REASONING_MODEL_OUTPUT_TOKENS
        # qwen was still empty at 16,000, so the budget must exceed that.
        assert candidate.max_output_tokens > 16_000


def test_an_unchanged_ceiling_stays_the_default():
    """Candidates that finish inside 8,000 must not be handed a larger budget.

    The adaptation is for a measured failure, not a general increase: giving every model
    more room would make the runs incomparable for no reason, and a budget that is never
    consumed costs nothing while a divergent one obscures the comparison.
    """
    for model_id in ('openai/gpt-6-luna', 'deepseek/deepseek-v4-flash',
                     'anthropic/claude-haiku-5.5', 'google/gemini-3.8-flash'):
        assert inputs_for(model_id).max_output_tokens is None, model_id


def test_a_raised_ceiling_must_record_why():
    """A bigger budget without a reason is indistinguishable from favouritism."""
    with pytest.raises(ValueError, match='output ceiling must record why'):
        CandidateInputs(model_id='vendor/model', max_output_tokens=64_000)

    # The default needs no justification, or every entry would carry boilerplate.
    CandidateInputs(model_id='vendor/model')

    # And every raised ceiling in the shipped study carries one.
    for candidate in CANDIDATE_INPUTS:
        if candidate.max_output_tokens is not None:
            assert candidate.output_rationale.strip(), candidate.model_id


# --- the study's candidates are the curated set ----------------------------------------------

def test_every_curated_model_has_an_input_profile():
    """The study compares the curated set, so each needs a defined way of being asked."""
    from evaluation.curated_models import CURATED_MODELS

    by_id = {c.model_id for c in CANDIDATE_INPUTS}
    missing = [m.id for m in CURATED_MODELS if m.id not in by_id]
    assert missing == [], (
        f'curated models with no input profile would be asked the default way by '
        f'accident: {missing}'
    )


def test_no_input_profile_names_an_uncurated_model():
    """A profile for a model outside the set is dead configuration."""
    from evaluation.curated_models import CURATED_MODELS

    curated = {m.id for m in CURATED_MODELS}
    extra = [c.model_id for c in CANDIDATE_INPUTS if c.model_id not in curated]
    assert extra == [], f'input profiles for uncurated models: {extra}'


def test_the_acceptance_bar_does_not_vary_by_candidate():
    """The property that makes per-candidate tuning fair rather than a thumb on a scale.

    Only the *asking* may differ. Everything about what counts as success -- the
    profiles, postings, validation rules and word-count gate -- is shared, and this
    asserts the module holds no per-candidate success rule.
    """
    source = (candidate_inputs.__file__)
    text = open(source, encoding='utf-8').read()

    for forbidden in ('word_count', 'validate_cv', 'is_valid', 'accepted ='):
        assert forbidden not in text, (
            f'{forbidden!r} appears in candidate inputs; the acceptance bar must not be '
            f'tunable per candidate or the ranking measures the tuning'
        )
