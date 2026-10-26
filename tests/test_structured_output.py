"""Phase 3, item 3: structured output (`response_schema`) is on, and scoped safely.

`_call_gemini` deliberately did **not** set `response_mime_type="application/json"`.
The comment at `gemini_service.py:135-137` recorded why -- it caused premature
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


def test_the_cv_schema_requires_the_document_and_nothing_else():
    """The envelope is strict about *being* the envelope; the document stays flexible.

    The prompt asks for `{"cv": ..., "tailoring_explanation": ...}`, but the recorded
    fixtures show the explanation is genuinely optional in practice and
    ``extract_explanation`` reads it defensively. Requiring it would convert a
    missing-but-harmless key into a failed run, so only ``cv`` is required.
    """
    schema = generation.RESPONSE_SCHEMAS['cv'].model_dump(exclude_none=True)

    assert schema['type'] == 'OBJECT'
    assert schema['required'] == ['cv']
    assert set(schema['properties']) == {'cv', 'tailoring_explanation'}


def test_the_letter_schema_requires_the_cover_letter():
    schema = generation.RESPONSE_SCHEMAS['cover_letter'].model_dump(exclude_none=True)

    assert schema['type'] == 'OBJECT'
    assert schema['required'] == ['cover_letter']


def test_the_cv_schema_leaves_the_document_body_open():
    """No `required` inside `cv`, and no `additionalProperties: false` anywhere.

    This is the anti-truncation decision, and it is deliberately the *opposite* of
    what "strict structured output" usually means. A schema that enumerates and
    requires every field of a ~1,350-token document makes the provider allocate and
    emit far more constrained output, and a response cut off mid-document is exactly
    the failure the deleted code suffered. Constraining the *envelope* buys the parse
    guarantee this increment actually wants (the response is a JSON object with a
    `cv`/`cover_letter` key, so the brace-scan is no longer the failure path) while
    leaving the document's own length and shape to the model.
    """
    schema = generation.RESPONSE_SCHEMAS['cv'].model_dump(exclude_none=True)

    def walk(node, path='$'):
        if isinstance(node, dict):
            assert 'additionalProperties' not in node or node['additionalProperties'] is not False, (
                f'{path} forbids additional properties; a strict body is what truncated'
            )
            if path.endswith('.cv') or path == '$.cv':
                assert 'required' not in node, f'{path} requires fields inside the document body'
            for key, value in node.items():
                walk(value, f'{path}.{key}')
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f'{path}[{index}]')

    walk(schema)


def test_the_cv_schema_exposes_the_unit_ids_a_delta_would_need():
    """`cv` stays an object the *server* can validate, so the contract is not vacuous.

    A bare ``{"cv": {"type": "OBJECT"}}`` would satisfy "requires the document" while
    constraining nothing at all. The body is described -- properties listed, nothing
    required -- which is the middle ground the comment above argues for.
    """
    schema = generation.RESPONSE_SCHEMAS['cv'].model_dump(exclude_none=True)
    cv = schema['properties']['cv']

    assert cv['type'] == 'OBJECT'
    assert {'summary', 'skills', 'experience'} <= set(cv['properties'])
    experience_items = cv['properties']['experience']['items']
    assert {'company', 'role', 'start_date', 'end_date', 'bullets'} <= set(
        experience_items['properties']
    )
    assert 'required' not in experience_items


# --- what is sent on each call ------------------------------------------------------------

def test_a_draft_call_sends_the_schema_and_json_mime_type(monkeypatch):
    """The CV draft is the call the schema is for: its response is always a document."""
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_gemini('draft prompt', kind='cv')

    config = sent[-1]
    assert config.response_mime_type == 'application/json'
    assert config.response_schema == generation.RESPONSE_SCHEMAS['cv']


def test_a_letter_call_sends_its_own_schema(monkeypatch):
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_gemini('letter prompt', kind='cover_letter')

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

    _service_without_network()._call_gemini('retry brief', kind='cv', allow_delta=True)

    assert sent[-1].response_schema is None
    assert sent[-1].response_mime_type is None


def test_an_unknown_kind_is_not_given_a_schema(monkeypatch):
    """No schema is better than the wrong one: a kind with no contract stays free.

    `kind` is the only thing selecting the schema, so a new document type added later
    must not inherit the CV's constraints by accident and start producing truncated
    letters.
    """
    sent = _capture_configs(monkeypatch)

    _service_without_network()._call_gemini('prompt', kind='some_future_document')

    assert sent[-1].response_schema is None


def test_the_schema_choice_comes_from_the_caller_not_the_prompt(monkeypatch):
    """`kind` decides, so the schema cannot drift from what is being asked for."""
    sent = _capture_configs(monkeypatch)
    gemini = _service_without_network()

    gemini._call_gemini('same prompt text', kind='cv')
    gemini._call_gemini('same prompt text', kind='cover_letter')

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
    schema = generation.RESPONSE_SCHEMAS['cv'].model_dump(exclude_none=True)

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
    """A `GeminiService` whose client is the recording one, built without credentials.

    ``_capture_configs`` has already replaced ``genai.Client``, so the constructor
    picks up the recording client. The key is a literal placeholder: nothing reads the
    environment, and no request can leave the process.
    """
    from services.gemini_service import GeminiService

    class _Config:
        model = 'gemini-3.8-flash'
        temperature = 0.3
        max_output_tokens = 8000

    return GeminiService(config=_Config(), api_key=api_key)


class _CannedResponse:
    """Just enough of a provider response for `_call_gemini` to return cleanly."""

    candidates: list = []
    usage_metadata = None
    text = '{"cv": {"title": "Recorded"}}'
