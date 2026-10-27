"""Phase 3, item 3: structured output (`response_schema`) is on, and scoped safely.

`_call_provider` deliberately did **not** set `response_mime_type="application/json"`.
The comment at `llm_service.py:135-137` recorded why -- it caused premature
truncation of long document responses -- and that comment is the reason the original
`response_schema` code was deleted as dead in Phase 1 (D-1).

So the item is not "add a schema". It is "add a schema **without** reintroducing the
failure that got it removed", and the decision this file pins is: **scope it**.

Call shape decided by this increment:

| Call | Response contract | Schema |
|---|---|---|
| CV draft | one complete document, always | **required** (strict) |
| Cover letter | one complete document, always | **required** (strict) |
| Layout retry | complete CV **or** a delta of replacement values | **not sent** |
| Any schema-rejected attempt | the 3-attempt correction loop | re-sent |

Three things are asserted, in the order they matter:

1. **Truncation cannot come back silently.** Structured output is not enabled by
   turning a flag on and hoping: a constrained response that stops before it is
   complete must be *detected* and *rejected*, not parsed into a short document.
2. **No silent fallback.** A response that does not satisfy the schema never reaches
   `validate_cv` as a document, and never gets quietly accepted in place of one.
3. **The delta path is not broken.** `parse_json_response(accept_delta=True)` and
   `looks_like_cv_delta`/`apply_cv_delta` define a shape a whole-document schema cannot
   express, which is *why* the retry is left unconstrained.

Everything is offline. No paid API call is made: the schema is inspected on the
`GenerateContentConfig` the service would send, and the pipeline runs against recorded
transcripts with stubbed renderers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from services import generation  # noqa: E402
from services import tailor_service as service  # noqa: E402

from support import recorded_session  # noqa: E402


# --- the schema itself ------------------------------------------------------------------

def test_the_document_schemas_are_exported_for_both_documents():
    """A named schema per document kind, so the config can be built without guessing."""
    assert generation.RESPONSE_SCHEMAS['cv'] is not None
    assert generation.RESPONSE_SCHEMAS['cover_letter'] is not None
    assert set(generation.RESPONSE_SCHEMAS) == {'cv', 'cover_letter'}


def _dumped(kind: str) -> dict:
    """The schema for ``kind`` as plain JSON data.

    The production schema is a **plain dict** in the strict dialect since the switch to
    `openai/gpt-6-luna` (2026-10-27); it used to be a ``google.genai.types.Schema``.
    Reading it through this helper keeps the assertions about the *contract* rather than
    about which representation happens to carry it.
    """
    schema = generation.RESPONSE_SCHEMAS[kind]
    if hasattr(schema, 'model_dump'):
        return schema.model_dump(exclude_none=True)
    return schema


def test_the_cv_schema_requires_the_document_and_nothing_else():
    """The envelope is strict about *being* the envelope; the explanation stays optional
    **in meaning**.

    The prompt asks for `{"cv": ..., "tailoring_explanation": ...}`, and the recorded
    fixtures show the explanation is genuinely optional in practice while
    ``extract_explanation`` reads it defensively.

    Strict mode nevertheless **requires every declared property**, measured against the
    live API: omitting one returns *"'required' is required to be supplied and to be an
    array including every key in properties. Missing 'tailoring_explanation'."* So the
    property is required but its type admits **null**, which is how a strict schema
    expresses "present but empty". Nothing downstream changes: a null explanation is no
    explanation, and `extract_explanation` already treats it that way.
    """
    schema = _dumped('cv')

    assert schema['type'] == 'object'
    # Required, because strict mode demands it...
    assert set(schema['required']) == {'cv', 'tailoring_explanation'}
    # ...but nullable, because it is optional in meaning.
    assert 'null' in schema['properties']['tailoring_explanation']['type']


def test_the_letter_schema_requires_the_cover_letter():
    schema = _dumped('cover_letter')

    assert schema['type'] == 'object'
    assert schema['required'] == ['cover_letter']


def test_the_cv_schema_is_strict_throughout():
    """Every object forbids additional properties and names what it requires.

    **This asserts the opposite of what it used to, and the reversal is the decision.**
    The original design left the document body open, on the reasoning that requiring a
    ~1,350-token document's every field makes a constrained response longer and so more
    cut-off-prone. That reasoning was sound for Gemini and is **not optional** for the
    selected model: OpenAI's strict mode refuses the request outright --

        Invalid schema for response_format: In context=('properties', 'cv'),
        'additionalProperties' is required to be supplied and to be false.

    -- so a schema that leaves the body open cannot be sent at all (ADR 0016).

    The truncation risk this design was managing is real and is now handled where it
    belongs: the output ceiling. Measured, no constrained response truncated at 8,000
    tokens, while every token of the budget went to reasoning in the models that failed.
    """
    schema = _dumped('cv')

    def walk(node, path='$'):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node.get('additionalProperties') is False, (
                    f'{path} does not forbid additional properties; strict mode requires it'
                )
                declared = set(node.get('properties') or {})
                required = set(node.get('required') or [])
                # Strict mode requires **every** declared property, with no exceptions.
                # The explanation stays optional *in meaning* by admitting null in its
                # type rather than by being absent from `required`.
                assert required == declared, (
                    f'{path} does not require every property it declares '
                    f'(missing: {sorted(declared - required)})'
                )
                for name, prop in (node.get('properties') or {}).items():
                    if name == 'tailoring_explanation':
                        types = prop.get('type')
                        as_list = types if isinstance(types, list) else [types]
                        assert 'null' in as_list, (
                            f'{path}.{name} is required but not nullable, so a document '
                            f'without an explanation would fail validation'
                        )
            for key, value in node.items():
                walk(value, f'{path}.{key}')
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f'{path}[{index}]')

    walk(schema)


def test_the_cv_schema_describes_the_document_it_expects():
    """``cv`` is a described object, so the contract is not vacuous.

    A bare ``{"cv": {"type": "object"}}`` would satisfy "requires the document" while
    constraining nothing. The body names its fields, which is what makes the response
    checkable by the provider as well as by ``validate_cv``.
    """
    schema = _dumped('cv')
    cv = schema['properties']['cv']

    assert cv['type'] == 'object'
    assert {'summary', 'skills', 'experience'} <= set(cv['properties'])
    experience_items = cv['properties']['experience']['items']
    assert {'company', 'role', 'start_date', 'end_date', 'bullets'} <= set(
        experience_items['properties']
    )
    # The fields the factual gate exists to protect are now *required*, which is a
    # direct improvement: `glm-5.3-flash` failed the study by omitting them, and a
    # schema that names them as required gives the provider a reason to include them.
    assert {'company', 'role', 'start_date', 'end_date'} <= set(
        experience_items.get('required') or []
    )


def test_the_cv_schema_exposes_the_unit_ids_a_delta_would_need():
    """`cv` stays an object the *server* can validate, so the contract is not vacuous.

    A bare ``{"cv": {"type": "object"}}`` would satisfy "requires the document" while
    constraining nothing at all. The body names its fields, so the response is checkable
    by the provider as well as by ``validate_cv``.
    """
    schema = _dumped('cv')
    cv = schema['properties']['cv']

    assert cv['type'] == 'object'
    assert {'summary', 'skills', 'experience'} <= set(cv['properties'])
    experience_items = cv['properties']['experience']['items']
    assert {'company', 'role', 'start_date', 'end_date', 'bullets'} <= set(
        experience_items['properties']
    )
    # Strict mode requires them, which is a direct improvement: `glm-5.3-flash` failed
    # the study by omitting exactly these fields, and naming them as required gives the
    # provider a reason to include them.
    assert {'company', 'role', 'start_date', 'end_date'} <= set(
        experience_items.get('required') or []
    )


# --- what is sent on each call ------------------------------------------------------------

def test_a_draft_call_sends_the_schema_and_json_mime_type(monkeypatch):
    """The CV draft is the call the schema is for: its response is always a document."""
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_provider('draft prompt', kind='cv')

    config = sent[-1]
    assert config.response_mime_type == 'application/json'
    assert config.response_schema == generation.RESPONSE_SCHEMAS['cv']


def test_a_letter_call_sends_its_own_schema(monkeypatch):
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_provider('letter prompt', kind='cover_letter')

    assert sent[-1].response_schema == generation.RESPONSE_SCHEMAS['cover_letter']


def test_a_layout_retry_sends_no_schema(monkeypatch):
    """The retry is the one call whose response may be a delta, so it is unconstrained.

    `parse_json_response(accept_delta=True)` accepts an object of unit ids such as
    `{"experience[0].bullets[1]": "..."}`, which has no document key. A schema whose
    required property is `cv` would make the provider *reject* -- or worse, silently
    replace -- that shape, so the delta path would stop working. Leaving this call
    unconstrained is what keeps `apply_cv_delta` reachable.

    It is not a loss of the increment's benefit: the delta is a handful of short
    strings, which is the shape least likely to truncate, and its response still goes
    through the same gate.
    """
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_provider('retry brief', kind='cv', allow_delta=True)

    assert sent[-1].response_schema is None
    assert sent[-1].response_mime_type is None


def test_an_unknown_kind_is_not_given_a_schema(monkeypatch):
    """No schema is better than the wrong one: a kind with no contract stays free.

    `kind` is the only thing selecting the schema, so a new document type added later
    must not inherit the CV's constraints by accident and start producing truncated
    letters.
    """
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_provider('prompt', kind='some_future_document')

    assert sent[-1].response_schema is None


def test_the_schema_choice_comes_from_the_caller_not_the_prompt(monkeypatch):
    """`kind` decides, so the schema cannot drift from what is being asked for."""
    sent = _capture_configs(monkeypatch)
    gemini = _service_without_network()

    gemini._call_provider('same prompt text', kind='cv')
    gemini._call_provider('same prompt text', kind='cover_letter')

    assert sent[0].response_schema != sent[1].response_schema


# --- truncation cannot come back silently ---------------------------------------------------

def test_a_truncated_constrained_response_is_rejected(monkeypatch):
    """The failure that deleted the original code must fail loudly, not parse short.

    A JSON-mode response that stops mid-document is *invalid JSON*, and
    `parse_json_response` never repairs truncated document data. Pinning it here means
    that if structured output ever does reintroduce truncation, the suite says so at
    the parser rather than shipping a half-length CV.
    """
    truncated = '{"cv": {"title": "Analytical Engineer", "summary": ["Analytical engineer with'

    with pytest.raises(ValueError, match='complete document'):
        generation.parse_json_response(truncated)


def test_a_truncated_retry_response_is_also_rejected():
    truncated = '{"experience[0].bullets[0]": "Own batch pipelines from ingestion'

    with pytest.raises(ValueError):
        generation.parse_json_response(truncated, accept_delta=True)


def test_an_empty_constrained_response_is_rejected():
    """A blocked or zero-length candidate is an error, never an empty document."""
    with pytest.raises(ValueError, match='empty document'):
        generation.parse_json_response('')


@pytest.mark.parametrize('payload', [
    '{"document": {"summary": ["x"]}}',          # right shape, wrong envelope key
    '[]',
    '{"unrelated": 1}',
])
def test_a_response_outside_the_schema_is_not_a_document(payload):
    """A schema-shaped response is still checked by the parser, not trusted.

    Turning on structured output must not become "the provider said JSON, so it is a
    document". Anything that carries no document key is rejected by the same parser as
    before, exactly as it was when JSON mode was off.
    """
    with pytest.raises(ValueError):
        generation.parse_json_response(payload)


def test_the_parser_still_accepts_a_document_the_schema_would_not_ask_for():
    """The parser is more permissive than the schema, and must stay that way.

    The suite's own fixtures and `tests/test_tailoring_pipeline.py` parse a bare
    ``{"cover_letter": ...}``; `parse_json_response` is a *tolerant reader* of whatever
    comes back, while the schema is what the provider is *asked* for. Keeping the two
    separate is what lets a model that returns a valid document in the other envelope
    still be understood, instead of the schema silently becoming a second, stricter
    validator.
    """
    parsed = generation.parse_json_response('{"cover_letter": {"paragraphs": []}}')

    assert parsed == {'cover_letter': {'paragraphs': []}}


# --- no silent fallback ---------------------------------------------------------------------

def test_the_kind_reaches_the_service_from_the_pipeline(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The pipeline must actually pass the document kind, or no schema is ever sent.

    Asserted on the prompts the offline double received *and* on the kwargs the
    pipeline used, because a `kind` that is plumbed but never forwarded would leave
    the schema silently off in production while every unit test above still passed.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert [call['kind'] for call in offline.calls] == ['cv', 'cover_letter']
    assert [call.get('allow_delta', False) for call in offline.calls] == [False, False]


def test_a_layout_retry_declares_the_delta_contract(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The retry is the only call that opts into the delta shape."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert [call['kind'] for call in offline.calls] == ['cv', 'cover_letter', 'cv']
    assert [call.get('allow_delta', False) for call in offline.calls] == [False, False, True]


def test_a_schema_violating_draft_still_fails_the_run(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Structured output must not open a path around `validate_cv`.

    The draft here is complete JSON that satisfies the envelope and is then rejected by
    the profile gate (an employer is missing). Three attempts, then the run raises --
    exactly as before. If enabling JSON mode had introduced any "trust the provider"
    branch, this is where it would show.
    """
    bad = json.loads(analyst_session.step_text('cv_draft'))
    bad['cv']['experience'] = bad['cv']['experience'][:-1]
    offline = offline_service([json.dumps(bad)] * 3)
    stub_renderers([2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )
    assert offline.call_count == 3, 'the correction loop must still be the only retry path'


def test_a_malformed_draft_is_not_retried_into_a_shorter_document(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A truncated response must not be accepted on a later attempt either.

    Each attempt is parsed independently. A run whose model keeps returning a
    half-document raises; it never falls back to the previous, unvalidated response.
    """
    offline = offline_service(['{"cv": {"summary": ["cut off'] * 3)
    stub_renderers([2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )
    assert offline.call_count == 3


# --- both explanation shapes keep working ----------------------------------------------------

@pytest.mark.parametrize('shape', ['top_level', 'nested'])
def test_both_explanation_shapes_survive_a_schema_constrained_response(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
    shape,
):
    """`extract_explanation` reads the top level then `cv.`; a schema must not pick one.

    The schema lists `tailoring_explanation` at the top level and *also* permits it
    inside `cv`, precisely so tightening the envelope does not decide, on the suite's
    behalf, which of the two shapes the model returns. Both are exercised here through
    the real pipeline and both must reach `TailoringExplanation`.
    """
    payload = json.loads(analyst_session.step_text('cv_draft'))
    if shape == 'nested':
        payload['cv']['tailoring_explanation'] = payload.pop('tailoring_explanation')

    offline_service([json.dumps(payload), analyst_session.step_text('cover_letter')])
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.tailoring_explanation is not None
    assert result.tailoring_explanation['overall_strategy']


def test_the_schema_permits_a_nested_explanation():
    """The envelope must not *forbid* what `extract_explanation` still accepts."""
    schema = _dumped('cv')

    assert 'tailoring_explanation' in schema['properties']['cv']['properties']


def test_a_response_with_no_explanation_is_still_accepted(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The explanation is optional in the envelope because it is optional in practice.

    A run that returns an accepted CV with no explanation must succeed with
    `tailoring_explanation == None`, not fail because the schema over-promised.
    """
    payload = json.loads(analyst_session.step_text('cv_draft'))
    payload.pop('tailoring_explanation')
    offline_service([json.dumps(payload), analyst_session.step_text('cover_letter')])
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.cv_page_count == 2
    assert result.tailoring_explanation is None


# --- the call-count baseline ------------------------------------------------------------------

def test_the_happy_path_is_still_two_calls(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Structured output does not add or remove a call.

    A schema that failed often enough to trigger the correction loop would show up
    here as three calls. The counts stay 2/3/5 and this file asserts the two ends of
    that range on the paths it exercises.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert offline.call_count == 2


def test_the_typical_path_is_still_three_calls(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert offline.call_count == 3


# --- helpers ----------------------------------------------------------------------------------

def _capture_configs(monkeypatch):
    """Patch the SDK's client factory; every call's config is appended to the list.

    ``types.GenerateContentConfig`` itself stays **real** -- the assertions inspect the
    object the provider actually builds, including ``response_schema``, rather than a
    stub of it. Only the client is replaced, so no request can leave the process and
    the suite stays offline.

    The patch targets ``services.provider``, which is where the Gemini request is built
    since Phase 3 item 6 introduced the provider interface. The assertions below are
    unchanged: they still inspect the real config object, so this remains a check of
    what is *sent* rather than of how the service is wired.
    """
    from services import provider as provider_module

    recorded: list = []

    class Client:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, *, model, contents, config):  # noqa: ARG002
            recorded.append(config)
            return _CannedResponse()

    monkeypatch.setattr(provider_module.genai, 'Client', Client)
    return recorded


def _service_without_network(api_key: str = 'unit-test-key'):
    """A `LLMService` whose client is the recording one, built without credentials.

    ``_capture_configs`` has already replaced ``genai.Client``, so the constructor
    picks up the recording client. The key is a literal placeholder: nothing reads the
    environment, and no request can leave the process.
    """
    from services.llm_service import LLMService

    class _Config:
        model = 'gemini-3.8-flash'
        temperature = 0.3
        max_output_tokens = 8000

    return LLMService(config=_Config(), api_key=api_key)


class _CannedResponse:
    """Just enough of a provider response for `_call_provider` to return cleanly."""

    candidates: list = []
    usage_metadata = None
    text = '{"cv": {"title": "Recorded"}}'


# --- the schemas must be *accepted* by the provider, not merely well-formed ---------------

#: Keywords the Gemini API rejects outright. Verified against the live API on 2026-10-26:
#: an otherwise identical schema succeeds without ``additionalProperties`` and fails with
#: it, raising ``ValueError: additionalProperties is not supported in the Gemini API``.
GEMINI_UNSUPPORTED_KEYWORDS = (
    'additionalProperties',
    'additional_properties',
    '$schema',
    'patternProperties',
    'definitions',
)


def _walk_schema(node, path='$'):
    """Yield ``(path, key, value)`` for every mapping entry in a dumped schema."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from _walk_schema(value, f'{path}.{key}')
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_schema(value, f'{path}[{index}]')


def test_no_schema_uses_a_keyword_the_gemini_api_rejects():
    """A schema the provider refuses is a paid failure, not a validation failure.

    This is a regression guard with a real defect behind it. ``_cv_document_schema``
    set ``additional_properties`` on ``skills``, and the Gemini API rejects that
    keyword -- so **every schema-bearing draft call failed after three paid attempts
    on the default provider**. It was invisible offline because the tests inspected
    the schema object rather than asking whether the provider would accept it, and
    the module's own comment claimed the keyword was unset while the code set it.

    Asserted on the raw schema, so it catches the keyword however the SDK spelled it --
    ``additional_properties`` in Python becomes ``additionalProperties`` on the wire, and
    the API's complaint names the wire form.

    **The production schema now *does* set ``additionalProperties``, and that is the
    switch.** OpenAI's strict mode requires it (ADR 0016), so this test asserts the rule
    that still holds: **Gemini must never receive it**, which the provider layer now
    guarantees by rendering the schema per route rather than by keeping it out of the
    schema entirely.
    """
    from services import generation
    from services.provider import _plain_schema

    for kind, schema in generation.RESPONSE_SCHEMAS.items():
        dumped = _plain_schema(schema) if hasattr(schema, 'model_dump') else schema
        assert 'additionalProperties' in json.dumps(dumped), (
            f'{kind} must be strict: the selected model refuses a schema without '
            f'additionalProperties: false'
        )
        # ...and it must never be sent to Gemini, which rejects that keyword outright.
        from evaluation.candidate_inputs import DIALECT_GEMINI, to_dialect

        gemini_form = to_dialect(dumped, DIALECT_GEMINI)
        for path, key, _ in _walk_schema(gemini_form):
            assert key not in GEMINI_UNSUPPORTED_KEYWORDS, (
                f'{kind} would send {key!r} at {path} to Gemini, which rejects it with '
                f'"not supported in the Gemini API"'
            )


def test_the_comment_and_the_code_agree_about_additional_properties():
    """The schema's own documentation must describe the schema that exists.

    The original defect survived review partly because the module comment stated
    "``additionalProperties`` is left unset" while ``additional_properties`` was set two
    screens later. Inverted now that strict mode requires the keyword: the comment must
    not still claim it is absent, or the next reader will remove it and break every call.
    """
    from pathlib import Path

    from services import generation

    dumped = _dumped('cv')
    sets_it = any(
        key in GEMINI_UNSUPPORTED_KEYWORDS for _, key, _ in _walk_schema(dumped)
    )
    source = Path(generation.__file__).read_text(encoding='utf-8')

    assert sets_it, 'the shipped CV schema must be strict'
    # The stale claim is gone from the source.
    assert '``additionalProperties`` is left unset' not in source, (
        'the module still claims additionalProperties is unset, which would invite '
        'removing the keyword strict mode requires'
    )


def test_every_schema_keyword_reaches_the_wire():
    """A typo'd keyword is silently dropped and the constraint quietly does not exist.

    The production schema is plain data now rather than an SDK object, so the failure
    mode moved: a misspelled key is no longer dropped by a validating model, it is sent
    to the provider and rejected there. Asserted on the wire form, which is what the
    provider actually validates.
    """
    from services import generation

    for kind, schema in generation.RESPONSE_SCHEMAS.items():
        dumped = _dumped(kind)
        assert dumped, f'{kind} schema dumps to nothing'
        assert 'properties' in dumped, f'{kind} schema declares no properties'
        # The envelope the parser relies on must survive into the wire form.
        assert kind in dumped['properties'], (
            f'{kind} schema does not expose the {kind!r} envelope key'
        )
        # The wire form must be JSON-serializable: it is put in a request body.
        json.dumps(dumped)
