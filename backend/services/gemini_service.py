"""Provider client for CV and cover letter tailoring.

Historically this module was the Gemini integration *and* the pricing table. Since
Phase 3 item 6 it is neither: the provider lives in :mod:`services.provider` and the
prices live in :mod:`services.pricing`, which is the one source of truth (D-4). What
remains here is the pipeline's client of whichever provider ``config`` selects, plus
the run-level token and cost roll-up.
"""
import os
from typing import Callable, Optional, Tuple

from config import DEFAULT_MODEL, Config
from models.requests import TokenUsage
from services import pricing
from services.generation import response_schema_for
from services.provider import ProviderError, build_provider

# Re-exported for callers that only need the model name or the table.
__all__ = ["GeminiService", "GeminiServiceError", "PRICING", "DEFAULT_MODEL", "ProviderError"]

#: Re-exported **view** of the single pricing table, for callers that still import it
#: from here. It is a derived mapping, not a second table: it exposes the Gemini-route
#: rows under their bare model names, which is the shape this module used to publish.
#: ``ui/app.py`` no longer reads it (that duplication was D-4); this exists so the
#: load-bearing invariants in ``tests/test_tailoring_pipeline.py`` -- that
#: ``DEFAULT_MODEL`` is priced, and that no retired row is -- keep being asserted
#: against something real.
PRICING = {
    model: {
        "input": price.input,
        "output": price.output,
        **({"input_long": price.input_long} if price.input_long is not None else {}),
        **({"output_long": price.output_long} if price.output_long is not None else {}),
    }
    for (provider, model), price in pricing.PRICING.items()
    if provider == pricing.DEFAULT_PROVIDER
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

    def __init__(self, config: Optional[Config] = None, api_key: Optional[str] = None,
                 render_schema: Optional[Callable] = None):
        """
        Initialize the service.

        Args:
            config: resolved configuration. Built from the environment only when
                omitted, so importing this module no longer fixes the model or key.
            api_key: explicit key, overriding the configured one.
            render_schema: optional callable applied to each document schema before it
                is sent, so a caller can ask a model in a dialect it accepts. Defaults
                to ``None``, which sends exactly what this project has always sent.
                Used by the evaluation (ADR 0016); production leaves it unset.
        """
        self.config = config or Config.from_env()
        #: Optional per-call schema adaptation. ``None`` means "send the schema as-is",
        #: which is the behaviour every existing caller already had.
        self.render_schema = render_schema
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
        #: How many of those calls were priced from the provider's **own** reported
        #: charge, and how many from the fallback table. Recorded so a run can state
        #: which figure it is relying on: a cost table presented as a measurement is
        #: the failure these two counters exist to make visible.
        self.reported_calls = 0
        self.estimated_calls = 0

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
        # Long-context tiers are applied to the tokens rather than to a flat total
        # (D-3), and the route is part of the price because the same model costs
        # different amounts direct and through OpenRouter. See services.pricing.
        #
        # ``getattr`` for the route: a service constructed without a config (the
        # "unlisted model must still be priced" invariant a test pins) has no route,
        # and the default route is the correct reading of "not specified".
        config = getattr(self, "config", None)
        provider = getattr(config, "provider", None) or pricing.DEFAULT_PROVIDER
        return pricing.estimate_cost(
            input_tokens, output_tokens, model or self.model, provider=provider,
        )

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

        # A caller may supply a **schema renderer**, and that exists purely so the
        # evaluation can ask each candidate model in a dialect it accepts. The three
        # provider families demand mutually incompatible schemas -- OpenAI requires
        # ``additionalProperties: false``, Vertex rejects a schema with more than 24
        # optional parameters, Gemini rejects the keyword outright -- so ranking models
        # against one shared schema measures the schema, not the models. See ADR 0016.
        #
        # It is a callable rather than a dialect name so this module stays ignorant of
        # provider families: the pipeline is handed "make this schema acceptable" and
        # nothing else. Absent, the schema is exactly what the project always sent.
        if schema is not None and self.render_schema is not None:
            schema = self.render_schema(schema)

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
        self._record_spend(
            response.input_tokens, response.output_tokens, routed_model,
            reported_cost_usd=response.reported_cost_usd,
        )

        return response.text, response.input_tokens, response.output_tokens

    # --- cost accounting during a run --------------------------------------------------

    def _record_spend(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None,
        reported_cost_usd: Optional[float] = None,
    ) -> None:
        """Accumulate this call's cost and enforce the budget cap.

        **The provider's own figure wins when it reports one.** OpenRouter returns
        ``usage.cost`` -- the amount actually charged -- and it is authoritative in a
        way no table can be, because pricing is per *request* and depends on which
        upstream provider served it. The estimate is the fallback, for providers that
        report only tokens (Gemini) and for anything that fails to report.

        Raises:
            GeminiServiceError: when the configured cap has been reached. It is raised
                *after* accumulating, so the reported spend includes the call that hit
                the limit, and before the pipeline issues another paid request.
        """
        if reported_cost_usd is None:
            cost = self._estimate_cost(input_tokens, output_tokens, model=model)
            #: Counted separately so a test can prove the table was actually consulted
            #: rather than merely present. An estimate presented as a measurement is
            #: the failure this distinction exists to catch.
            self.estimated_calls += 1
        else:
            cost = reported_cost_usd
            self.reported_calls += 1
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

        # **The accumulated spend wins when any call reported its own cost.**
        # Re-pricing the run's totals from the table here would silently discard what
        # the provider actually charged. That is not merely less accurate: the table
        # prices a *route*, while OpenRouter bills per *request* depending on which
        # upstream provider served it. So this prefers the figure the calls reported,
        # and falls back to the table only when none did -- which is the Gemini case,
        # where the API returns token counts and no cost at all.
        #
        # ``self.spent_usd`` accumulates across this service instance's calls, and a
        # service is constructed per generation, so it is this run's total.
        #
        # ``getattr`` because a service can legitimately be built without ``__init__``
        # -- tests construct one to exercise purely arithmetic paths -- and an object
        # with no spend counters has made no calls, so the table is the right answer.
        reported = getattr(self, "reported_calls", 0)
        spent = getattr(self, "spent_usd", 0.0)
        cost_usd = spent if reported else self._estimate_cost(total_input, total_output)

        return TokenUsage(
            cv_input_tokens=cv_input_tokens,
            cv_output_tokens=cv_output_tokens,
            cl_input_tokens=cl_input_tokens,
            cl_output_tokens=cl_output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost_usd, 6),
            cv_attempts=cv_attempts,
            cl_attempts=cl_attempts,
            model_name=self.model,
            provider=(
                getattr(getattr(self, "config", None), "provider", None)
                or pricing.DEFAULT_PROVIDER
            ),
        )
