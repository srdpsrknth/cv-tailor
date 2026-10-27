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


#: A Gemini-shaped schema with a free-form map, used to exercise the transformations.
#: The *shipped* schema is already strict and its `skills` is already an array, so
#: testing against production data would assert a no-op. A synthetic input tests the
#: transformation itself, which is what several of these tests are about.
_MAP_SCHEMA = {
    'type': 'object',
    'properties': {
        'cv': {
            'type': 'object',
            'properties': {'skills': {'type': 'object'}},
        }
    },
    'required': ['cv'],
}


# --- the constraints are the measured ones -------------------------------------------------

def test_the_vertex_optional_parameter_limit_is_the_measured_one():
    """Vertex's ceiling is 24, and the shipped schema is now comfortably inside it.

    Measured against the live API while the schema was Gemini-shaped: *"Schemas contains
    too many optional parameters (27)... (limit: 24)"*. Adopting the strict dialect in
    production (2026-10-27) reduced the count to 2 -- every declared property is required
    except ``tailoring_explanation``, which is optional by design -- so this constraint is
    now satisfied by construction rather than by a per-candidate adaptation.

    The limit is still asserted, because it remains a real property of that endpoint and
    a future schema change could exceed it again.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    optional = count_optional_parameters(base)

    assert candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT == 24
    assert optional <= candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT, (
        f'the shipped schema has {optional} optional parameters, over Vertex\'s limit of '
        f'{candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT}'
    )
    # Strict mode requires every declared property, so there are **no** optional
    # parameters at all. That is comfortably inside the limit, and worth asserting as an
    # exact figure: it is what "strict" means here, and 0 -> N is the change that would
    # breach the ceiling.
    assert optional == 0, (
        f'a strict schema requires every property it declares, so the optional count '
        f'should be 0; found {optional}'
    )


def test_the_vertex_dialect_clears_the_optional_parameter_limit():
    """The adaptation must actually clear the constraint it exists for.

    Exercised on the **transformation**, not on a shipped entry: the study's Vertex
    candidates were rejected and removed (2026-10-27), but the constraint is a property
    of that provider family and the dialect must still satisfy it if a future candidate
    needs it. Testing it against the shipped set would pass vacuously now that no entry
    uses that dialect.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    vertex_form = to_dialect(base, DIALECT_ANTHROPIC_VERTEX)

    assert count_optional_parameters(vertex_form) <= candidate_inputs.VERTEX_OPTIONAL_PARAMETER_LIMIT, (
        'the Vertex dialect still exceeds the optional-parameter limit'
    )
    # And the untransformed source must genuinely have been over it, or this proves
    # nothing: the shipped schema is strict already, so use a map-shaped schema.
    assert count_optional_parameters(_MAP_SCHEMA) > 0


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
    reshaped = reshape_free_form_maps(_MAP_SCHEMA)
    skills = reshaped['properties']['cv']['properties']['skills']

    assert skills['type'] == 'array'
    assert set(skills['items']['properties']) == {'category', 'items'}
    assert skills['items']['additionalProperties'] is False


def test_the_reshape_does_not_mutate_its_input():
    """It is applied to a copy, so one candidate's dialect cannot leak into another's."""
    before = json.dumps(_MAP_SCHEMA)
    reshape_free_form_maps(_MAP_SCHEMA)
    assert json.dumps(_MAP_SCHEMA) == before


def test_the_shipped_schema_already_uses_the_array_spelling():
    """The production schema needs no reshape, because it was converted at build time.

    This is the property that matters for the selected model: `skills` must already be an
    array in the schema the pipeline sends, or strict mode rejects the request.
    """
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    skills = base['properties']['cv']['properties']['skills']

    assert skills['type'] == 'array', 'the shipped schema must use the array spelling'
    # And reshaping it again changes nothing, so the two paths agree.
    assert json.dumps(reshape_free_form_maps(base)) == json.dumps(base)


def test_the_gemini_dialect_strips_the_keyword_gemini_rejects():
    """Gemini refuses `additionalProperties` outright, so it must be removed for it."""
    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    schema = schema_for_candidate('google/gemini-3.8-flash', base)

    assert 'additionalProperties' not in json.dumps(schema)


# --- the mechanism cannot change what already ships ------------------------------------------

def test_an_unlisted_candidate_gets_the_default_dialect():
    """The mapping lists *adaptations*; its absence means none was needed."""
    unknown = inputs_for('some/model-not-in-the-study')
    assert unknown.dialect == DIALECT_GEMINI
    assert unknown.prompt_overrides == {}


def test_the_gemini_dialect_only_removes_the_keyword_gemini_rejects():
    """The Gemini rendering must differ from the shipped schema in exactly one way.

    The shipped schema is now **strict** (the selected model requires it), while Gemini
    refuses ``additionalProperties`` outright. So the Gemini form is the shipped schema
    minus that keyword and nothing else -- the same fields, the same requirements, the
    same array-shaped ``skills``. If this ever diverged further, the two providers would
    be being asked for different documents.
    """

    def strip_additional(node):
        if isinstance(node, dict):
            return {
                key: strip_additional(value)
                for key, value in node.items()
                if key != 'additionalProperties'
            }
        if isinstance(node, list):
            return [strip_additional(item) for item in node]
        return node

    from services.generation import response_schema_for
    from services.provider import _plain_schema

    base = _plain_schema(response_schema_for('cv'))
    rendered = schema_for_candidate('google/gemini-3.8-flash', base)

    assert json.dumps(rendered) == json.dumps(strip_additional(base))
    assert 'additionalProperties' not in json.dumps(rendered)


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
    """The default 8,000-token ceiling left a reasoning model with an **empty** response.

    This is the defect that made the first study wrong about a candidate. Measured
    against the real CV prompt on 2026-10-27: `qwen3.8-flash` at an 8,000 ceiling
    returned `finish_reason: length` with 8,000 reasoning tokens and ``content_len: 0``
    -- and again at 16,000 -- while at 32,000 it produced a valid 4,974-character
    document. `z-ai/glm-5.3-flash` behaved the same way.

    Scoring the empty response as a model failure ranks *this project's ceiling* rather
    than the model, and `qwen3.8-flash` was recorded as 0/3 before this was understood.

    **Both of those models were rejected and removed on 2026-10-27**, and the selected
    model does not need a raised ceiling -- so this exercises the *mechanism* on a
    synthetic profile. The constraint it encodes is a property of reasoning models, not
    of one vendor, and the next curation will meet it again.
    """
    from evaluation.candidate_inputs import REASONING_MODEL_OUTPUT_TOKENS

    adapted = CandidateInputs(
        model_id='vendor/reasoning-model',
        max_output_tokens=REASONING_MODEL_OUTPUT_TOKENS,
        output_rationale='measured to empty its response at the default ceiling',
    )

    assert adapted.max_output_tokens > 16_000, (
        'a reasoning model was still empty at 16,000, so the budget must exceed it'
    )
    assert REASONING_MODEL_OUTPUT_TOKENS > 16_000

    # And the selected model keeps the default, which is the other half of the claim.
    assert inputs_for('openai/gpt-6-luna').max_output_tokens is None


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
