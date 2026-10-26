"""One thin provider contract, with Gemini and OpenRouter implementations.

ADR 0005 deferred this interface: a single
``generate(prompt, *, schema, max_tokens, model)`` entry point, Gemini as the
default, OpenRouter as a second implementation. This module is that interface and
nothing more -- it does no prompt building, no parsing and no validation, so a
provider swap cannot reach any of those.

Three rules are load-bearing and are why this is not just an HTTP wrapper:

1. **``schema=None`` means "send no structured-output constraint".** Since Phase 3
   increment 3 the schema is a property of the *call*, not the service, and one
   call -- the layout retry -- must be able to opt out, because its response may be
   a delta of unit ids rather than a document (ADR 0012). A provider that always
   sent some schema would break that contract silently, so the absence of a schema
   is expressed here as an explicit, testable ``None``.
2. **No silent fallback.** A provider error raises :class:`ProviderError`. Nothing
   here retries against a different model or provider, because a fallback that
   changes the output contract would bypass ``validate_cv``.
3. **The response contract is preserved, not reinterpreted.** These providers
   return the raw text plus token counts. Parsing, the delta merge and
   ``validate_cv`` stay exactly where they were.

Provider facts verified from the providers' own documentation on 2026-10-26:

- OpenRouter takes ``response_format={"type": "json_schema", "json_schema":
  {"name", "strict", "schema"}}`` -- a *different* envelope from Gemini's native
  ``response_schema``, so :meth:`OpenRouterProvider._response_format` translates
  rather than passing the object through.
- OpenRouter documents that ``strict`` enforcement "varies by provider" and that
  exact compliance "is not guaranteed on every endpoint". A schema-constrained call
  therefore also sends ``provider.require_parameters: true``, so the request is not
  routed to an endpoint that would ignore the schema entirely.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

# The Google SDK is imported at module scope so a test can replace its client factory
# without reaching into a function body. Importing it has no side effects and reads no
# environment (ADR 0010); only ``genai.Client(...)`` touches credentials, and that
# happens in ``GeminiProvider.__init__``.
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

#: Attempts per request before a provider gives up. Matches the historical
#: ``_call_gemini`` retry budget so call counts are unchanged by this refactor.
MAX_REQUEST_ATTEMPTS = 3

#: OpenRouter's OpenAI-compatible endpoint.
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class ProviderError(Exception):
    """A provider call failed after its retries.

    Deliberately not a ``ValueError``: callers distinguish "the network/provider
    failed" from "the model returned something that did not validate", and only
    the latter may enter the correction loop.
    """


@dataclass(frozen=True)
class ProviderResponse:
    """One provider reply: the raw text and what it cost in tokens.

    ``text`` is returned unparsed on purpose. Every consumer downstream --
    ``parse_json_response``, ``apply_cv_delta``, ``validate_cv`` -- is provider
    independent, and keeping the text raw is what guarantees a second provider
    cannot quietly change the response contract.
    """

    text: str
    input_tokens: int
    output_tokens: int


class Provider:
    """The contract ADR 0005 specifies. Subclasses implement :meth:`generate`."""

    #: Stable identifier used in configuration and in error messages.
    name = "provider"

    def generate(
        self,
        prompt: str,
        *,
        schema: Optional[dict] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> ProviderResponse:
        """Send ``prompt`` and return the raw reply.

        Args:
            prompt: the complete prompt; this layer adds no context.
            schema: a JSON Schema to constrain the response, or ``None`` for an
                unconstrained call. ``None`` is meaningful and must stay meaning
                it: a call whose response is not a document sends no schema.
            max_tokens: output-token ceiling for this call.
            model: model id for this call, overriding the provider's default. This
                is the hook model-per-task routing uses.

        Raises:
            ProviderError: if the call fails after :data:`MAX_REQUEST_ATTEMPTS`.
        """
        raise NotImplementedError


class GeminiProvider(Provider):
    """Google Gemini, the default provider (decision 6).

    The request body is the one ``_call_gemini`` has always built; only its home
    moved. ``thinking_level="low"`` is kept for ``gemini-3.8-flash`` because it
    stops reasoning tokens from exhausting the document budget.
    """

    name = "gemini"

    #: Models given the low thinking level, to protect the document budget.
    LOW_THINKING_MODELS = ("gemini-3.8-flash",)

    def __init__(self, api_key: str, temperature: float = 0.3, max_output_tokens: int = 8000,
                 default_model: Optional[str] = None):
        self.client = genai.Client(api_key=api_key)
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.default_model = default_model

    def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
        resolved_model = model or self.default_model
        tokens_limit = max_tokens if max_tokens is not None else self.max_output_tokens
        last_error: Optional[Exception] = None

        for attempt in range(MAX_REQUEST_ATTEMPTS):
            try:
                config = types.GenerateContentConfig(
                    temperature=self.temperature,
                    max_output_tokens=tokens_limit,
                )
                # Keep reasoning from exhausting the document response budget.
                if resolved_model in self.LOW_THINKING_MODELS:
                    config.thinking_config = types.ThinkingConfig(thinking_level="low")

                # Mime type and schema travel together: JSON mode without a schema
                # still changes the envelope, so an unconstrained call keeps both
                # unset and the tolerant parser stays the path it always was.
                if schema is not None:
                    config.response_mime_type = "application/json"
                    config.response_schema = schema

                response = self.client.models.generate_content(
                    model=resolved_model, contents=prompt, config=config,
                )

                # A non-STOP finish reason is the truncation signal; log it rather
                # than infer anything, because the parser is what rejects a
                # truncated body.
                if response.candidates:
                    finish_reason = response.candidates[0].finish_reason
                    if finish_reason and finish_reason != 1:
                        logger.warning(
                            "Gemini finish_reason: %s (expected STOP=1)", finish_reason
                        )

                usage = response.usage_metadata
                return ProviderResponse(
                    text=response.text,
                    input_tokens=(usage.prompt_token_count if usage else 0) or 0,
                    output_tokens=(usage.candidates_token_count if usage else 0) or 0,
                )
            except Exception as error:  # noqa: BLE001 -- re-raised as ProviderError
                last_error = error
                if attempt < MAX_REQUEST_ATTEMPTS - 1:
                    wait_time = 2 ** attempt
                    print(f"Gemini API error (attempt {attempt + 1}/{MAX_REQUEST_ATTEMPTS}): {error}")
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

        raise ProviderError(
            f"Gemini API call failed after {MAX_REQUEST_ATTEMPTS} attempts: {last_error}"
        )


class OpenRouterProvider(Provider):
    """OpenRouter, the second implementation (ADR 0005).

    Reaches OpenRouter's OpenAI-compatible endpoint. The neutral JSON Schema is
    translated into OpenRouter's ``response_format`` envelope -- the shapes are not
    the same, so a passthrough would silently send no usable constraint.
    """

    name = "openrouter"

    def __init__(self, api_key: str, temperature: float = 0.3, max_output_tokens: int = 8000,
                 default_model: Optional[str] = None, timeout: int = 120):
        if not api_key:
            raise ProviderError(
                "An OpenRouter API key is required. Set OPENROUTER_API_KEY in .env "
                "or pass --api-key. Run `cvtailor doctor` to check your setup."
            )
        self.api_key = api_key
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.default_model = default_model
        self.timeout = timeout

    @staticmethod
    def _response_format(schema: dict, name: str = "document") -> dict:
        """Translate a neutral JSON Schema into OpenRouter's ``response_format``.

        ``strict`` is set because OpenRouter's own guidance is to set it, but it is
        explicitly **not** relied upon: their documentation states enforcement
        varies by provider and exact compliance is not guaranteed on every
        endpoint. Validation still happens where it always did.
        """
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        }

    def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
        import requests

        resolved_model = model or self.default_model
        if not resolved_model:
            raise ProviderError("No OpenRouter model configured for this call.")

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_output_tokens,
        }
        if schema is not None:
            payload["response_format"] = self._response_format(schema)
            # Their documented way to avoid an endpoint that would ignore the
            # schema. Sent only when a schema is requested, so an unconstrained
            # call keeps the widest set of endpoints available.
            payload["provider"] = {"require_parameters": True}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Optional[Exception] = None
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            try:
                response = requests.post(
                    OPENROUTER_CHAT_URL, headers=headers, json=payload, timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if "error" in data and "choices" not in data:
                    raise ProviderError(f"OpenRouter returned an error: {data['error']}")
                choices = data.get("choices") or []
                if not choices:
                    raise ProviderError("OpenRouter returned no choices.")
                text = (choices[0].get("message") or {}).get("content") or ""
                usage = data.get("usage") or {}
                return ProviderResponse(
                    text=text,
                    input_tokens=usage.get("prompt_tokens", 0) or 0,
                    output_tokens=usage.get("completion_tokens", 0) or 0,
                )
            except Exception as error:  # noqa: BLE001 -- re-raised as ProviderError
                last_error = error
                if attempt < MAX_REQUEST_ATTEMPTS - 1:
                    wait_time = 2 ** attempt
                    print(f"OpenRouter error (attempt {attempt + 1}/{MAX_REQUEST_ATTEMPTS}): {error}")
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

        raise ProviderError(
            f"OpenRouter call failed after {MAX_REQUEST_ATTEMPTS} attempts: {last_error}"
        )


def build_provider(config, api_key: Optional[str] = None) -> Provider:
    """Build the provider ``config`` names. Gemini is the default (decision 6).

    Reads only from the passed ``config``, so there is no import-time environment
    read (ADR 0010) and one test can override another's provider.

    Args:
        config: the resolved configuration naming the provider and its options.
        api_key: an explicit key, overriding the selected provider's configured one.
            It applies to the **selected** provider only, so passing one can never
            authenticate against a provider the caller did not choose.
    """
    provider_name = (getattr(config, "provider", None) or "gemini").strip().lower()
    if provider_name not in ("gemini", "openrouter"):
        raise ProviderError(
            f"Unknown provider {provider_name!r}. "
            "Configured providers: 'gemini', 'openrouter'."
        )

    key = api_key or _require_key(config, provider_name)
    options = {
        "api_key": key,
        "temperature": getattr(config, "temperature", 0.3),
        "max_output_tokens": getattr(config, "max_output_tokens", 8000),
        "default_model": getattr(config, "model", None),
    }
    return (GeminiProvider if provider_name == "gemini" else OpenRouterProvider)(**options)


def _require_key(config, provider_name: str) -> str:
    """The selected provider's key, or a fail-closed error naming the right variable."""
    field = "openrouter_api_key" if provider_name == "openrouter" else "api_key"
    key = getattr(config, field, None)
    if key:
        return key
    env_var = "OPENROUTER_API_KEY" if provider_name == "openrouter" else "GEMINI_API_KEY"
    raise ProviderError(
        f"{env_var} is not set for the {provider_name} provider. Add it to .env or "
        "pass --api-key. Run `cvtailor doctor` to check your setup."
    )


def schema_is_sent(schema: Optional[dict]) -> bool:
    """Whether a call carrying ``schema`` asks for structured output.

    Trivial, and deliberately so: it exists so a test can assert the *absent*
    schema case without duplicating the ``is not None`` rule in three places.
    """
    return schema is not None


def dumps_schema(schema: dict) -> str:
    """Serialise a schema for a log line or a test assertion, deterministically."""
    return json.dumps(schema, sort_keys=True)
