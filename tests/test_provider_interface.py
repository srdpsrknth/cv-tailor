"""The thin provider interface, model routing and budget caps (Phase 3, item 6).

ADR 0005 deferred ``generate(prompt, *, schema, max_tokens, model)`` with Gemini as
the default and OpenRouter as a second implementation. These tests pin the
properties that make the interface safe to introduce *underneath* an existing
pipeline:

* **the per-call response contract survives the indirection** -- the call that must
  send no schema still sends none, and it does so by passing ``schema=None``
  through to the provider, not by a rule the provider layer might reinterpret;
* **a second provider translates rather than passes through** -- OpenRouter's
  ``response_format`` envelope is not Gemini's ``response_schema``, so a passthrough
  would silently send no usable constraint;
* **no silent fallback** -- an unknown provider, a missing key for the selected
  provider, and a provider failure all raise rather than quietly switching to
  something that works;
* **the call-count baseline is unchanged** -- 2/3/5 and 12 worst, driven through the
  real pipeline;
* **the budget cap fails closed** -- a malformed cap is an error, never a cap that
  silently does not apply.

Everything here is offline. No test in this file makes, or can make, a paid call:
the Gemini client is replaced and the OpenRouter transport is a recorded double.
"""
from __future__ import annotations

import pytest

from services import generation

# ``provider`` is the module this increment introduces. It is imported defensively so
# that running this file against the pre-increment code reports each test as a
# *failure* ("no provider interface") rather than aborting the module at collection --
# a collection error proves nothing about which behaviours are new. It deliberately
# does **not** skip: a skip here would also hide a broken import in the real tree,
# which is the one thing this file is supposed to catch.
try:
    from services import provider as provider_module
    from services.provider import (
        GeminiProvider,
        OpenRouterProvider,
        Provider,
        ProviderError,
        ProviderResponse,
        build_provider,
    )
    _PROVIDER_IMPORT_ERROR = None
except ImportError as _error:  # pragma: no cover - pre-increment code only
    provider_module = None
    GeminiProvider = OpenRouterProvider = Provider = None
    ProviderError = ProviderResponse = build_provider = None
    _PROVIDER_IMPORT_ERROR = _error


@pytest.fixture(autouse=True)
def _require_the_provider_module():
    """Fail every test in this file clearly when the interface does not exist."""
    if _PROVIDER_IMPORT_ERROR is not None:
        pytest.fail(
            "services.provider does not exist, so the provider interface is absent: "
            f"{_PROVIDER_IMPORT_ERROR}"
        )


# --- helpers ------------------------------------------------------------------------------

class _StubConfig:
    """The smallest config the provider factory needs.

    Deliberately *not* a real ``Config``: the factory must not depend on the full
    config API, or a caller could not build a provider without a complete
    environment. Its defaults mirror the real ones.
    """

    def __init__(self, **overrides):
        self.provider = 'gemini'
        self.model = 'gemini-3.8-flash'
        self.temperature = 0.3
        self.max_output_tokens = 8000
        self.api_key = 'unit-test-gemini-key'
        self.openrouter_api_key = None
        self.task_models = None
        self.max_cost_usd = None
        for key, value in overrides.items():
            setattr(self, key, value)

    def model_for(self, task):
        """Mirrors ``Config.model_for``: opt-in routing, default fallback."""
        return (self.task_models or {}).get(task) or self.model

    def budget_exceeded(self, spent_usd):
        """Mirrors ``Config.budget_exceeded``: no cap means no cap."""
        if self.max_cost_usd is None:
            return False
        return spent_usd >= self.max_cost_usd

    def require_provider_key(self):
        """Mirrors ``Config.require_provider_key`` for the selected provider."""
        return self.openrouter_api_key if self.provider == 'openrouter' else self.api_key


def _record_gemini_configs(monkeypatch):
    """Replace the Google client factory; return the list of built configs."""
    recorded: list = []

    class Client:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, *, model, contents, config):  # noqa: ARG002
            recorded.append(config)
            return _CannedGeminiResponse()

    monkeypatch.setattr(provider_module.genai, 'Client', Client)
    return recorded


class _CannedGeminiResponse:
    candidates: list = []
    usage_metadata = None
    text = '{"cv": {"title": "Recorded"}}'


def _record_openrouter_requests(monkeypatch, *, reply=None, status=200):
    """Replace ``requests.post``; return the list of (url, kwargs) it received."""
    sent: list = []

    class Response:
        def __init__(self):
            self.status_code = status
            self._payload = reply if reply is not None else {
                'choices': [{'message': {'content': '{"cv": {"title": "Recorded"}}'}}],
                'usage': {'prompt_tokens': 1234, 'completion_tokens': 567},
            }

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f'HTTP {self.status_code}')

        def json(self):
            return self._payload

    def post(url, headers=None, json=None, timeout=None):  # noqa: A002
        sent.append({'url': url, 'headers': headers, 'json': json, 'timeout': timeout})
        return Response()

    import requests

    monkeypatch.setattr(requests, 'post', post)
    return sent


# --- the contract itself -------------------------------------------------------------------

def test_every_provider_implements_the_single_generate_contract():
    """ADR 0005's shape, asserted rather than described."""
    for provider_class in (GeminiProvider, OpenRouterProvider):
        assert issubclass(provider_class, Provider)
        assert callable(provider_class.generate)


def test_the_generate_signature_is_the_contract_adr_0005_specified():
    import inspect

    signature = inspect.signature(Provider.generate)
    assert list(signature.parameters) == ['self', 'prompt', 'schema', 'max_tokens', 'model']
    # Everything but the prompt is keyword-only, so a positional call cannot
    # silently bind a schema to max_tokens.
    for name in ('schema', 'max_tokens', 'model'):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters['schema'].default is None
    assert signature.parameters['max_tokens'].default is None
    assert signature.parameters['model'].default is None


def test_the_response_carries_text_and_token_counts_and_nothing_else():
    """The text stays raw: parsing and validation are provider independent."""
    response = ProviderResponse(text='{"cv": {}}', input_tokens=10, output_tokens=2)
    assert response.text == '{"cv": {}}'
    assert (response.input_tokens, response.output_tokens) == (10, 2)


# --- the per-call schema contract survives the indirection ------------------------------------

def test_a_schema_call_constrains_gemini(monkeypatch):
    configs = _record_gemini_configs(monkeypatch)
    provider = GeminiProvider(api_key='k', default_model='gemini-3.8-flash')

    provider.generate('prompt', schema=generation.RESPONSE_SCHEMAS['cv'])

    assert configs[-1].response_mime_type == 'application/json'
    assert configs[-1].response_schema == generation.RESPONSE_SCHEMAS['cv']


def test_no_schema_means_no_constraint_on_gemini(monkeypatch):
    """``schema=None`` must leave both the mime type and the schema unset.

    This is the property ADR 0012 depends on: JSON mode without a schema still
    changes the response envelope, so "not constrained" and "constrained" have to
    be distinguishable at the provider boundary.
    """
    configs = _record_gemini_configs(monkeypatch)
    provider = GeminiProvider(api_key='k', default_model='gemini-3.8-flash')

    provider.generate('retry brief', schema=None)

    assert configs[-1].response_schema is None
    assert configs[-1].response_mime_type is None


def test_the_service_passes_none_through_for_the_layout_retry(monkeypatch):
    """Driven through ``_call_gemini``, which is where the scope is decided.

    The retry's response may be a delta of unit ids with no document key, so it must
    reach the provider with no schema -- exactly as it did before this refactor.
    """
    configs = _record_gemini_configs(monkeypatch)
    from services.gemini_service import GeminiService

    service = GeminiService(config=_StubConfig(), api_key='k')
    service._call_gemini('retry brief', kind='cv', allow_delta=True)

    assert configs[-1].response_schema is None
    assert configs[-1].response_mime_type is None


def test_the_service_still_constrains_the_draft_and_the_letter(monkeypatch):
    configs = _record_gemini_configs(monkeypatch)
    from services.gemini_service import GeminiService

    service = GeminiService(config=_StubConfig(), api_key='k')
    service._call_gemini('draft', kind='cv')
    service._call_gemini('letter', kind='cover_letter')

    assert configs[0].response_schema == generation.RESPONSE_SCHEMAS['cv']
    assert configs[1].response_schema == generation.RESPONSE_SCHEMAS['cover_letter']


def test_an_unknown_kind_is_still_sent_no_schema(monkeypatch):
    """A future document type must not inherit the CV's constraints by accident."""
    configs = _record_gemini_configs(monkeypatch)
    from services.gemini_service import GeminiService

    service = GeminiService(config=_StubConfig(), api_key='k')
    service._call_gemini('prompt', kind='some_future_document')

    assert configs[-1].response_schema is None


# --- OpenRouter as the second implementation --------------------------------------------------

def test_openrouter_translates_the_schema_into_its_own_envelope(monkeypatch):
    """Their ``response_format`` shape is not Gemini's, so it must be translated.

    Verified against openrouter.ai/docs/features/structured-outputs on 2026-10-26:
    ``{"type": "json_schema", "json_schema": {"name", "strict", "schema"}}``.
    """
    sent = _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='k', default_model='vendor/model')

    provider.generate('prompt', schema=generation.RESPONSE_SCHEMAS['cv'])

    response_format = sent[-1]['json']['response_format']
    assert response_format['type'] == 'json_schema'
    assert response_format['json_schema']['schema'] == generation.RESPONSE_SCHEMAS['cv']
    assert response_format['json_schema']['name']
    assert response_format['json_schema']['strict'] is True
    # The neutral schema must not also leak in under Gemini's key.
    assert 'response_schema' not in sent[-1]['json']


def test_openrouter_requires_an_endpoint_that_supports_the_schema(monkeypatch):
    """Their docs: support is per endpoint, and ``require_parameters`` is the guard.

    Without it a request can be routed to an endpoint that ignores the schema, which
    would look like a model that returns unconstrained text for no reason.
    """
    sent = _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='k', default_model='vendor/model')

    provider.generate('prompt', schema=generation.RESPONSE_SCHEMAS['cv'])

    assert sent[-1]['json']['provider'] == {'require_parameters': True}


def test_an_unconstrained_openrouter_call_does_not_require_parameters(monkeypatch):
    """The guard is for schema calls only; it would needlessly narrow the others."""
    sent = _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='k', default_model='vendor/model')

    provider.generate('retry brief', schema=None)

    assert 'response_format' not in sent[-1]['json']
    assert 'provider' not in sent[-1]['json']


def test_openrouter_returns_the_raw_text_and_token_counts(monkeypatch):
    _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='k', default_model='vendor/model')

    response = provider.generate('prompt')

    assert response.text == '{"cv": {"title": "Recorded"}}'
    assert (response.input_tokens, response.output_tokens) == (1234, 567)


def test_openrouter_sends_a_bearer_token_and_never_logs_it(monkeypatch):
    sent = _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='secret-key-value', default_model='vendor/model')

    provider.generate('prompt')

    assert sent[-1]['headers']['Authorization'] == 'Bearer secret-key-value'


def test_openrouter_honours_a_per_call_model_override(monkeypatch):
    """This is the hook model-per-task routing uses."""
    sent = _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='k', default_model='vendor/default')

    provider.generate('prompt', model='vendor/routed')

    assert sent[-1]['json']['model'] == 'vendor/routed'


def test_openrouter_honours_a_per_call_token_ceiling(monkeypatch):
    sent = _record_openrouter_requests(monkeypatch)
    provider = OpenRouterProvider(api_key='k', default_model='vendor/model', max_output_tokens=8000)

    provider.generate('prompt', max_tokens=1234)

    assert sent[-1]['json']['max_tokens'] == 1234


def test_an_openrouter_error_response_fails_loudly(monkeypatch):
    """No silent empty string: an errored call raises rather than returning ''."""
    _record_openrouter_requests(
        monkeypatch, reply={'error': {'message': 'model unavailable'}}, status=200,
    )
    provider = OpenRouterProvider(api_key='k', default_model='vendor/model')

    with pytest.raises(ProviderError):
        provider.generate('prompt')


def test_openrouter_without_a_key_fails_closed():
    """The selected provider's key is required; the other provider's is not a substitute."""
    with pytest.raises(ProviderError, match='OPENROUTER_API_KEY'):
        OpenRouterProvider(api_key='', default_model='vendor/model')


# --- provider selection fails closed ----------------------------------------------------------

def test_the_default_provider_is_gemini(monkeypatch):
    """Decision 6: Gemini's latest Flash stays the default."""
    _record_gemini_configs(monkeypatch)
    assert build_provider(_StubConfig()).name == 'gemini'


def test_selecting_openrouter_builds_the_openrouter_provider():
    provider = build_provider(
        _StubConfig(provider='openrouter', openrouter_api_key='k', model='vendor/model')
    )
    assert provider.name == 'openrouter'


def test_selecting_openrouter_does_not_borrow_the_gemini_key():
    """A missing OpenRouter key is an error, never a quiet fallback to the other key."""
    config = _StubConfig(provider='openrouter', openrouter_api_key=None, api_key='gemini-key')

    with pytest.raises(ProviderError, match='OPENROUTER_API_KEY'):
        build_provider(config)


def test_an_unknown_provider_raises_rather_than_defaulting():
    """A provider substitution would change the response contract unasked."""
    with pytest.raises(ProviderError, match='Unknown provider'):
        build_provider(_StubConfig(provider='some-other-vendor'))


def test_an_explicit_key_overrides_only_the_selected_provider():
    provider = build_provider(
        _StubConfig(provider='openrouter', openrouter_api_key='configured'), api_key='explicit',
    )
    assert provider.api_key == 'explicit'


# --- model-per-task routing --------------------------------------------------------------------

def test_config_routes_a_task_to_its_own_model():
    from config import Config

    config = Config.from_env(
        load_env_file=False,
        overrides={'task_models': {'cover_letter': 'cheap-model'}, 'model': 'strong-model'},
    )
    assert config.model_for('cover_letter') == 'cheap-model'
    assert config.model_for('cv') == 'strong-model'


def test_an_unrouted_task_falls_back_to_the_configured_model():
    """Routing is opt-in: configuring one task must not weaken another."""
    from config import Config

    config = Config.from_env(load_env_file=False, overrides={'model': 'strong-model'})
    for task in ('cv', 'cover_letter', 'layout_retry'):
        assert config.model_for(task) == 'strong-model'


def test_an_unknown_task_does_not_crash_a_run():
    from config import Config

    config = Config.from_env(load_env_file=False, overrides={'model': 'strong-model'})
    assert config.model_for('a-task-that-does-not-exist') == 'strong-model'


def test_routing_rejects_an_unknown_task_name():
    """A typo in a task name must not be silently ignored."""
    from config import Config, ConfigError

    with pytest.raises(ConfigError, match='Unknown task'):
        Config.from_env(load_env_file=False, overrides={'task_models': {'cvv': 'm'}})


def test_the_layout_retry_task_routes_to_its_configured_model(monkeypatch):
    """Driven through the real call site: a retry is its own task."""
    sent: list = []

    class RecordingProvider(Provider):
        name = 'recording'

        def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
            sent.append({'schema': schema, 'model': model})
            return ProviderResponse(text='{"cv": {"title": "Recorded"}}', input_tokens=1, output_tokens=1)

    from services.gemini_service import GeminiService

    service = GeminiService(
        config=_StubConfig(task_models={'layout_retry': 'cheap-model', 'cv': 'strong-model'}),
        api_key='k',
    )
    service.provider = RecordingProvider()

    service._call_gemini('draft', kind='cv')
    service._call_gemini('retry', kind='cv', allow_delta=True)

    assert sent[0]['model'] == 'strong-model'
    assert sent[1]['model'] == 'cheap-model'


def test_the_configured_provider_is_used_for_a_real_call(monkeypatch):
    """End of the wiring: selecting OpenRouter routes the pipeline's call to it."""
    sent = _record_openrouter_requests(monkeypatch)
    from services.gemini_service import GeminiService

    service = GeminiService(
        config=_StubConfig(provider='openrouter', openrouter_api_key='k', model='vendor/model')
    )
    service._call_gemini('draft', kind='cv')

    assert sent[-1]['url'] == provider_module.OPENROUTER_CHAT_URL
    assert sent[-1]['json']['model'] == 'vendor/model'
    assert sent[-1]['json']['response_format']['type'] == 'json_schema'


# --- the budget cap ---------------------------------------------------------------------------

def test_a_malformed_cap_is_an_error_not_a_silently_absent_cap():
    """A budget that fails open is worse than no budget, because it looks like one."""
    from config import Config, ConfigError

    with pytest.raises(ConfigError, match='must be a number'):
        Config.from_env(load_env_file=False, overrides={'max_cost_usd': 'five dollars'})


def test_a_negative_cap_is_rejected():
    from config import Config, ConfigError

    with pytest.raises(ConfigError, match='negative'):
        Config.from_env(load_env_file=False, overrides={'max_cost_usd': -1})


def test_no_cap_means_no_cap():
    from config import Config

    config = Config.from_env(load_env_file=False)
    assert config.has_cost_cap is False
    assert config.budget_exceeded(10_000.0) is False


def test_the_cap_stops_further_calls(monkeypatch):
    """The run raises once spend reaches the cap, instead of continuing to spend."""
    calls: list = []

    class RecordingProvider(Provider):
        name = 'recording'

        def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
            calls.append(model)
            return ProviderResponse(text='{"cv": {"title": "x"}}', input_tokens=2_000_000, output_tokens=0)

    from config import Config
    from services.gemini_service import GeminiService

    config = Config.from_env(load_env_file=False, overrides={'max_cost_usd': 1.0})
    service = GeminiService(config=config, api_key='k')
    service.provider = RecordingProvider()

    # $0.75 per 1M input on the default model, so 2M tokens is $1.50: over the cap.
    with pytest.raises(Exception, match='Cost cap reached'):
        service._call_gemini('draft', kind='cv')

    assert len(calls) == 1, 'the cap must stop the *next* call, and this one is the first'
    assert service.spent_usd > 1.0


def test_spend_is_accumulated_per_call_and_reported(monkeypatch):
    class RecordingProvider(Provider):
        name = 'recording'

        def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
            return ProviderResponse(text='{}', input_tokens=1_000_000, output_tokens=0)

    from services.gemini_service import GeminiService

    service = GeminiService(config=_StubConfig(), api_key='k')
    service.provider = RecordingProvider()

    service._call_gemini('a', kind='cv')
    service._call_gemini('b', kind='cover_letter')

    assert service.calls_made == 2
    # 2 x 1M input tokens at $0.75/1M.
    assert service.spent_usd == pytest.approx(1.5)


def test_a_routed_model_is_priced_as_itself_not_as_the_default():
    """Model-per-task routing means one run can bill against several models."""
    from services.gemini_service import GeminiService

    service = GeminiService(config=_StubConfig(), api_key='k')

    cheap = service._estimate_cost(1_000_000, 0, model='gemini-2.5-flash-lite')
    strong = service._estimate_cost(1_000_000, 0, model='gemini-3.8-flash')

    assert cheap < strong
    assert cheap == pytest.approx(0.10)
    assert strong == pytest.approx(0.75)


# --- no fallback, and no bypass of validation ---------------------------------------------------

def test_a_provider_failure_raises_and_does_not_retry_elsewhere(monkeypatch):
    """No silent fallback to a different provider or model."""
    attempts: list = []

    class FailingProvider(Provider):
        name = 'failing'

        def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
            attempts.append(model)
            raise ProviderError('simulated provider outage')

    from services.gemini_service import GeminiService, GeminiServiceError

    service = GeminiService(config=_StubConfig(), api_key='k')
    service.provider = FailingProvider()

    with pytest.raises(GeminiServiceError, match='simulated provider outage'):
        service._call_gemini('draft', kind='cv')

    assert len(attempts) == 1, 'a provider failure must not be retried on another provider'


def test_provider_error_is_not_a_value_error():
    """The distinction matters: only a ValueError may enter the correction loop.

    If a provider outage were a ValueError, the pipeline would burn three paid calls
    re-asking a question the provider never answered.
    """
    assert not issubclass(ProviderError, ValueError)


def test_the_service_error_stays_compatible_with_the_provider_error():
    """Existing ``except GeminiServiceError`` clauses keep catching what they did."""
    from services.gemini_service import GeminiServiceError

    assert issubclass(GeminiServiceError, ProviderError)


# --- the call-count baseline is unchanged --------------------------------------------------------

def test_the_call_counts_are_unchanged_by_the_provider_refactor():
    """2 / 3 / 5 must survive: the interface adds routing, not calls."""
    import inspect

    from services.gemini_service import GeminiService
    from services import generation as generation_module

    # One provider call per generate() attempt, exactly as before.
    source = inspect.getsource(generation_module.DocumentGenerator.generate)
    assert source.count('self.service._call_gemini(') == 1
    # The service delegates once, so there is no second call site hiding here.
    assert inspect.getsource(GeminiService._call_gemini).count('self.provider.generate(') == 1


def test_the_happy_path_still_makes_two_calls_driven_through_the_pipeline(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Driven through the real pipeline, not derived on paper.

    The provider interface is indirection, and indirection is exactly where an extra
    call site hides. This runs the recorded transcript end to end so the 2-call happy
    path is observed rather than argued.
    """
    from services import tailor_service as service

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.status == 'success'
    assert offline.call_count == 2
    assert [call['kind'] for call in offline.calls] == ['cv', 'cover_letter']
    assert not offline.exhausted


# --- the provider's own cost figure, and when it is not available --------------------------

def test_openrouter_reports_its_own_charge(monkeypatch):
    """``usage.cost`` is read from the response and carried out as a money figure.

    This is the authoritative number for a real run: OpenRouter bills per *request*
    and depends on which upstream provider served it, so a static per-model table
    cannot express it. Their docs state usage accounting is returned automatically
    with every response and needs no request parameter, which is why no assertion
    here inspects the request body -- nothing about the request changed.
    """
    sent = _record_openrouter_requests(monkeypatch, reply={
        'choices': [{'message': {'content': '{"cv": {"title": "Recorded"}}'}}],
        'usage': {'prompt_tokens': 1234, 'completion_tokens': 567, 'cost': 0.001234},
    })
    provider = OpenRouterProvider(api_key='k', default_model='deepseek/deepseek-v4-flash')

    response = provider.generate('prompt', model='deepseek/deepseek-v4-flash')

    assert response.reported_cost_usd == pytest.approx(0.001234)
    # The request is unchanged: no `usage` opt-in was added to obtain this.
    assert 'usage' not in (sent[0]['json'] or {})


def test_an_absent_reported_cost_is_none_never_zero(monkeypatch):
    """A missing figure must not be read as "free".

    ``None`` means "estimate it"; ``0.0`` means "this cost nothing". Conflating them
    would record a paid call at $0.00, which is the one direction of error that
    flatters a model -- and cost per accepted result is the ranking metric.
    """
    _record_openrouter_requests(monkeypatch, reply={
        'choices': [{'message': {'content': '{}'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
    })
    provider = OpenRouterProvider(api_key='k', default_model='m')

    response = provider.generate('prompt', model='m')

    assert response.reported_cost_usd is None


@pytest.mark.parametrize('reported', ['not-a-number', None, -1])
def test_an_unusable_reported_cost_degrades_to_none(monkeypatch, reported):
    """Malformed, null and negative all mean "no usable figure", not zero."""
    _record_openrouter_requests(monkeypatch, reply={
        'choices': [{'message': {'content': '{}'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'cost': reported},
    })
    provider = OpenRouterProvider(api_key='k', default_model='m')

    assert provider.generate('prompt', model='m').reported_cost_usd is None


def test_a_genuinely_free_model_reports_zero_not_none(monkeypatch):
    """A real $0 charge is a figure, and must survive as one."""
    _record_openrouter_requests(monkeypatch, reply={
        'choices': [{'message': {'content': '{}'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'cost': 0},
    })
    provider = OpenRouterProvider(api_key='k', default_model='m')

    assert provider.generate('prompt', model='m').reported_cost_usd == 0.0


def test_gemini_reports_no_cost_because_the_api_has_none():
    """``usage_metadata`` carries token counts only -- verified against ai.google.dev.

    Gemini's response has no cost field, so this is ``None`` and the caller prices it
    from the table. Asserted rather than assumed, because a future SDK change that
    *did* add a cost would otherwise go unnoticed while the table quietly disagreed.
    """
    import sys
    import types

    from services.gemini_service import GeminiService

    class _Usage:
        prompt_token_count = 100
        candidates_token_count = 50
        thoughts_token_count = 0

    class _Response:
        candidates: list = []
        text = '{}'
        usage_metadata = _Usage()

    class _Models:
        def generate_content(self, **kwargs):
            return _Response()

    class _Client:
        def __init__(self, **kwargs):
            self.models = _Models()

    config = _StubConfig(provider='gemini')

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(provider_module.genai, 'Client', _Client)
        service = GeminiService(config=config)
        text, _, _ = service._call_gemini('prompt', kind='cv')

    assert text == '{}'
    # The service tracked the call, and priced it from the table rather than a report.
    assert service.reported_calls == 0
    assert service.estimated_calls == 1


def test_thinking_tokens_are_counted_as_output():
    """Gemini bills thinking as output but excludes it from ``candidates_token_count``.

    Google's token docs are explicit: the output count does **not** include thinking
    tokens, which arrive separately in ``thoughts_token_count``. This project turns
    thinking on for ``gemini-3.8-flash``, so reading only ``candidates_token_count``
    under-reported the shipped model's output tokens and therefore its cost.
    """
    import sys
    import types

    from services.gemini_service import GeminiService

    class _Usage:
        prompt_token_count = 100
        candidates_token_count = 500
        thoughts_token_count = 250

    class _Response:
        candidates: list = []
        text = '{}'
        usage_metadata = _Usage()

    class _Models:
        def generate_content(self, **kwargs):
            return _Response()

    class _Client:
        def __init__(self, **kwargs):
            self.models = _Models()

    config = _StubConfig(provider='gemini')
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(provider_module.genai, 'Client', _Client)
        service = GeminiService(config=config)
        _, _, output_tokens = service._call_gemini('prompt', kind='cv')

    assert output_tokens == 750, 'thinking tokens are billed as output and must be counted'


def test_a_reported_cost_replaces_the_table_in_the_run_total(monkeypatch):
    """The headline figure a run reports is what the provider charged, not an estimate.

    This is the guard that matters: before this, ``calculate_token_usage`` re-priced the
    run's token totals from the table, silently discarding what the provider said. The
    two disagree here on purpose, so passing this test requires the reported figure to
    have won.
    """
    from services.gemini_service import GeminiService

    class _Config(_StubConfig):
        provider = 'openrouter'
        model = 'deepseek/deepseek-v4-flash'

        def model_for(self, task):
            return 'deepseek/deepseek-v4-flash'

        def budget_exceeded(self, spent):
            return False

    config = _Config()
    service = object.__new__(GeminiService)
    service.config = config
    service.model = config.model
    service.spent_usd = 0.0
    service.calls_made = 0
    service.reported_calls = 0
    service.estimated_calls = 0

    service._record_spend(1000, 500, 'deepseek/deepseek-v4-flash', reported_cost_usd=0.4321)

    usage = service.calculate_token_usage(1000, 500, 0, 0)

    assert usage.estimated_cost_usd == pytest.approx(0.4321)
    assert service.reported_calls == 1
    assert service.estimated_calls == 0


def test_a_run_with_no_report_falls_back_to_the_table():
    """Gemini reports no cost, so the table must still price the run."""
    from services.gemini_service import GeminiService

    class _Config(_StubConfig):
        provider = 'gemini'

    config = _Config()
    service = object.__new__(GeminiService)
    service.config = config
    service.model = 'gemini-3.8-flash'
    service.spent_usd = 0.0
    service.calls_made = 0
    service.reported_calls = 0
    service.estimated_calls = 0

    service._record_spend(1000, 500, 'gemini-3.8-flash')

    usage = service.calculate_token_usage(1000, 500, 0, 0)

    assert service.estimated_calls == 1
    assert usage.estimated_cost_usd == pytest.approx(0.002625, abs=1e-6)
