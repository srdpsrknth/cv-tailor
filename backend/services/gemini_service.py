"""
Google Gemini API service for CV and cover letter tailoring.
Handles API calls, token tracking, cost estimation, and error handling.
"""
import os
from typing import Optional, Tuple

from config import DEFAULT_MODEL, Config
from models.requests import TokenUsage
from services.generation import response_schema_for
from services.provider import ProviderError, build_provider

# Re-exported for callers that only need the model name.
__all__ = ["GeminiService", "GeminiServiceError", "PRICING", "DEFAULT_MODEL", "ProviderError"]

# Pricing (per 1M tokens in USD), verified against ai.google.dev on 2026-10-23.
# Free tier: 15 requests/min, 1.5M tokens/day
PRICING = {
    # Introductory pricing through December 31, 2026; then $1.50 / $7.50.
    "gemini-3.8-flash": {
        "input": 0.75,
        "output": 3.75,
    },
    # --- GEMINI 3 SERIES ---
    # gemini-3-pro-preview was shut down and has been removed rather than mispriced.
    "gemini-3-flash-preview": {
        "input": 0.50,       # $0.50 / 1M
        "output": 3.00,      # $3.00 / 1M
    },

    # --- GEMINI 2.5 SERIES: Stable production models ---
    "gemini-2.5-pro": {
        "input": 1.25,       # $1.25 / 1M (<= 200k context)
        "input_long": 2.50,  # $2.50 / 1M (> 200k context)
        "output": 10.00,     # $10.00 / 1M
        "output_long": 15.00 # $15.00 / 1M
    },
    "gemini-2.5-flash": {
        "input": 0.30,       # $0.30 / 1M
        "output": 2.50,      # $2.50 / 1M
    },
    "gemini-2.5-flash-lite": {
        "input": 0.10,       # $0.10 / 1M
        "output": 0.40,      # $0.40 / 1M
    },
}


class GeminiServiceError(ProviderError):
    """Custom exception for provider service errors.

    Kept as a subclass of :class:`~services.provider.ProviderError` so existing
    ``except GeminiServiceError`` clauses keep catching what they always did, while
    new code can catch the provider-neutral type.
    """

    pass


class GeminiService:
    """Drives a provider through the interface ADR 0005 specifies.

    The name is historical: this is now the pipeline's *client* of whatever
    provider ``config`` names, and ``_call_gemini`` is the one call site the
    generation pipeline uses. Renaming it is deliberately left to a later,
    separately verified increment so that this refactor changes no call count and
    no prompt byte.
    """

    def __init__(self, config: Optional[Config] = None, api_key: Optional[str] = None):
        """
        Initialize the service.

        Args:
            config: resolved configuration. Built from the environment only when
                omitted, so importing this module no longer fixes the model or key.
            api_key: explicit key, overriding the configured one.
        """
        self.config = config or Config.from_env()
        # The key is resolved by ``build_provider`` from the *selected* provider's
        # field, so a caller passing an explicit one does not need the configured key
        # to exist, and the Gemini key is never used for an OpenRouter call.
        self.api_key = api_key or self.config.require_provider_key()

        self.model = self.config.model
        self.temperature = self.config.temperature
        self.max_output_tokens = self.config.max_output_tokens

        #: Running spend for this service instance, used to enforce the optional cap.
        #: Starts at zero on every construction, so a cap bounds one run rather than
        #: accumulating across unrelated runs in a long-lived process.
        self.spent_usd = 0.0
        #: How many provider calls this instance has made, reported when a cap trips.
        self.calls_made = 0

        #: The provider this service speaks to. Built from the already-resolved
        #: config, so choosing a provider is a configuration decision and never an
        #: import-time one (ADR 0010). An explicit ``api_key`` overrides the key of
        #: whichever provider is selected -- never the other provider's.
        self.provider = build_provider(self.config, api_key=api_key)

    def _estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None,
    ) -> float:
        """
        Estimate cost for token usage in USD.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            model: the model these tokens were billed against. Defaults to
                ``self.model``. It is a parameter because model-per-task routing
                means one run can use several models, and pricing them all at the
                service default would misreport the cost.

        Returns:
            Cost in USD
        """
        # An unlisted model must still be priced without crashing. Fall back to the
        # configured default's rates rather than to a removed legacy model.
        pricing = PRICING.get(model or self.model, PRICING[DEFAULT_MODEL])

        # Calculate cost per million tokens
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_usd = input_cost + output_cost

        return total_usd

    def _call_gemini(
        self,
        prompt: str,
        max_retries: int = 3,
        max_output_tokens: Optional[int] = None,
        kind: Optional[str] = None,
        allow_delta: bool = False,
    ) -> Tuple[str, int, int]:
        """
        Call the configured provider, preserving the per-call response contract.

        Args:
            prompt: The prompt to send
            max_retries: Maximum number of retry attempts
            max_output_tokens: Override max_output_tokens for this call (uses self.max_output_tokens if None)
            kind: The document being asked for (``cv``, ``cover_letter``). Selects the
                structured-output schema; an unknown or missing kind gets no schema.
            allow_delta: True for a layout retry, whose response may be a *delta* of
                replacement values rather than a document. Such a call is deliberately
                left unconstrained -- see ``generation.RESPONSE_SCHEMAS``.

        Returns:
            Tuple of (response_text, input_tokens, output_tokens)

        Raises:
            GeminiServiceError: If the call fails after retries
        """
        # The schema is per *call*, not per service: the draft and the letter always
        # return one complete document, so they are constrained; a layout retry may
        # return a delta and is therefore not. See generation.RESPONSE_SCHEMAS for why
        # structured output is scoped rather than enabled everywhere -- an earlier
        # blanket application of response_mime_type caused premature truncation of long
        # document responses (D-1).
        #
        # ``None`` here is the whole point of the scope: it is passed through to the
        # provider as "send no constraint", so a provider swap cannot quietly turn the
        # retry into a constrained call. tests/test_provider_interface.py pins it.
        schema = response_schema_for(kind, allow_delta=allow_delta)

        # Model-per-task routing (ADR 0005). A layout retry is its own task, because
        # shortening an existing document is cheaper work than drafting one. A task
        # with no configured override keeps ``self.model``, so routing stays opt-in.
        #
        # ``getattr`` rather than a direct call: a config object that predates routing
        # (a caller's own, or a test double) means "no routing configured", which is
        # exactly ``self.model``. Requiring the method would make an unrelated config
        # unable to make a call at all.
        task = "layout_retry" if allow_delta else (kind or "")
        model_for = getattr(self.config, "model_for", None)
        routed_model = model_for(task) if (task and model_for) else self.model

        try:
            response = self.provider.generate(
                prompt,
                schema=schema,
                max_tokens=max_output_tokens if max_output_tokens is not None else self.max_output_tokens,
                model=routed_model,
            )
        except ProviderError as error:
            raise GeminiServiceError(str(error)) from error

        # The cap is checked against the running spend *before* the next call is made,
        # so a run stops at the budget instead of discovering the overrun afterwards.
        self._record_spend(response.input_tokens, response.output_tokens, routed_model)

        return response.text, response.input_tokens, response.output_tokens

    # --- cost accounting during a run --------------------------------------------------

    def _record_spend(self, input_tokens: int, output_tokens: int, model: Optional[str] = None) -> None:
        """Accumulate this call's estimated cost and enforce the budget cap.

        Raises:
            GeminiServiceError: when the configured cap has been reached. It is raised
                *after* accumulating, so the reported spend includes the call that hit
                the limit, and before the pipeline issues another paid request.
        """
        cost = self._estimate_cost(input_tokens, output_tokens, model=model)
        self.spent_usd += cost
        self.calls_made += 1
        # ``getattr`` for the same reason as routing: a config object without the cap
        # concept means "no cap configured", not "crash on every call".
        budget_exceeded = getattr(self.config, "budget_exceeded", None)
        if budget_exceeded is not None and budget_exceeded(self.spent_usd):
            raise GeminiServiceError(
                f"Cost cap reached: ${self.spent_usd:.6f} spent against "
                f"CVTAILOR_MAX_COST_USD=${self.config.max_cost_usd:.6f} after "
                f"{self.calls_made} call(s). No further requests were made."
            )

    def calculate_token_usage(
        self,
        cv_input_tokens: int,
        cv_output_tokens: int,
        cl_input_tokens: int,
        cl_output_tokens: int,
        cv_attempts: int = 1,
        cl_attempts: int = 1
    ) -> TokenUsage:
        """
        Calculate total token usage and costs.

        Args:
            cv_input_tokens: Total input tokens for CV tailoring (all attempts)
            cv_output_tokens: Total output tokens for CV tailoring (all attempts)
            cl_input_tokens: Total input tokens for cover letter (all attempts)
            cl_output_tokens: Total output tokens for cover letter (all attempts)
            cv_attempts: Number of attempts made for CV generation
            cl_attempts: Number of attempts made for cover letter generation

        Returns:
            TokenUsage object with costs in USD
        """
        total_input = cv_input_tokens + cl_input_tokens
        total_output = cv_output_tokens + cl_output_tokens
        total_tokens = total_input + total_output

        cost_usd = self._estimate_cost(total_input, total_output)

        return TokenUsage(
            cv_input_tokens=cv_input_tokens,
            cv_output_tokens=cv_output_tokens,
            cl_input_tokens=cl_input_tokens,
            cl_output_tokens=cl_output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost_usd, 6),
            cv_attempts=cv_attempts,
            cl_attempts=cl_attempts,
            model_name=self.model
        )
