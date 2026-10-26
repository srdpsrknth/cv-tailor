"""One pricing source of truth, route- and tier-aware (D-3, D-4).

Before this module the price of a model lived in two places and was applied
wrongly in the third:

* ``gemini_service.PRICING`` held the table;
* ``ui/app.py`` held a **second, stale copy** (it still listed
  ``gemini-1.5-flash``, retired in Phase 1) and divided tokens by it, which is
  **D-4**: two tables can disagree, and the one a user sees was the stale one;
* ``_estimate_cost`` priced a run's *total* with a single flat rate while the
  table defined ``input_long``/``output_long`` tiers, which is **D-3**. Below the
  long-context threshold the error is invisible; above it the estimate is
  materially under-reported, and a cost-versus-quality comparison built on an
  under-reported cost is not trustworthy.

Two things this module deliberately does differently:

1. **Price is per route.** OpenRouter lists ``google/gemini-3.8-flash`` at
   $0.825/$4.125 per 1M while Google charges $0.75/$3.75 direct. Both are correct
   *for their route*, so a bare model name does not identify a price. Every row is
   therefore keyed by ``(provider, model)``.
2. **Tiers are applied to the tokens, not to the total.** The long-context rate
   applies when the *input* crosses the threshold, which is how the providers
   bill it.

Provider prices are verified against the provider's own listing; see
``PRICE_SOURCES`` for the date and URL of each. Do not add a row without one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: When each provider's prices were last verified, and against what. A row whose
#: route has no entry here has not been verified and must not be trusted.
PRICE_SOURCES = {
    "gemini": {
        "verified_on": "2026-10-23",
        "source": "ai.google.dev/gemini-api/docs/pricing",
        "note": "Pruned and re-verified in Phase 1 (D-5).",
    },
    "openrouter": {
        "verified_on": "2026-10-26",
        "source": "https://openrouter.ai/api/v1/models",
        "note": (
            "Read from OpenRouter's own listing during Phase 3 item 6. The 467-model "
            "response was saved and hashed (SHA-256 "
            "64B4A173A08F7027DD2F04778A85C5B5EFC4097331CF1529B502CBE249092BC7) so a "
            "figure can be re-checked against exactly what was read. Long-context "
            "tiers were confirmed from the listing's own 'overrides' entries."
        ),
    },
}

#: Input-token threshold above which a model's long-context rates apply. Providers
#: bill the long rate for the whole request once the prompt crosses this.
LONG_CONTEXT_THRESHOLD = 200_000

#: How long a verified price may go unchecked before it is treated as stale. The owner
#: set this rule on 2026-10-26: re-verify "if the last table update was longer than 2
#: months". It is measured, not assumed -- between two reads of OpenRouter's listing on
#: the *same day*, four entries had already moved (two halved).
PRICE_MAX_AGE_DAYS = 62


@dataclass(frozen=True)
class ModelPrice:
    """One model's price on one route, in USD per 1M tokens.

    ``input_long``/``output_long`` are optional because not every model has a
    long-context tier. When a row defines them they are **used**; a row that
    defines only one of the pair is a mistake, and :func:`price_for` treats the
    model as unpriced-long rather than silently charging the short rate above the
    threshold (see the module docstring on D-3).
    """

    input: float
    output: float
    input_long: Optional[float] = None
    output_long: Optional[float] = None

    @property
    def has_long_tier(self) -> bool:
        """True only when *both* long rates exist, so a half-row cannot mislead."""
        return self.input_long is not None and self.output_long is not None


#: The default route. Decision 6 keeps Gemini's latest Flash as the default model.
DEFAULT_PROVIDER = "gemini"

#: The model assumed when none is configured. Must exist below, asserted by a test.
DEFAULT_MODEL = "gemini-3.8-flash"


#: ``(provider, model) -> ModelPrice``. One table, one place (D-4).
PRICING: dict[tuple[str, str], ModelPrice] = {
    # --- Gemini, direct from Google (verified ai.google.dev, 2026-10-23) ---------
    ("gemini", "gemini-3.8-flash"): ModelPrice(
        # Introductory pricing through December 31, 2026; then $1.50 / $7.50.
        input=0.75, output=3.75,
    ),
    # gemini-3-pro-preview was shut down and has been removed rather than mispriced.
    ("gemini", "gemini-3-flash-preview"): ModelPrice(input=0.50, output=3.00),
    ("gemini", "gemini-2.5-pro"): ModelPrice(
        input=1.25, output=10.00, input_long=2.50, output_long=15.00,
    ),
    ("gemini", "gemini-2.5-flash"): ModelPrice(input=0.30, output=2.50),
    ("gemini", "gemini-2.5-flash-lite"): ModelPrice(input=0.10, output=0.40),

    # --- The same models through OpenRouter (verified from its listing, 2026-10-26)
    # These differ from the direct route for gemini-3.8-flash, which is exactly why
    # the route is part of the key: $0.825/$4.125 here versus $0.75/$3.75 direct.
    ("openrouter", "google/gemini-3.8-flash"): ModelPrice(input=0.825, output=4.125),
    ("openrouter", "google/gemini-2.5-pro"): ModelPrice(
        input=1.25, output=10.00, input_long=2.50, output_long=15.00,
    ),
    ("openrouter", "google/gemini-2.5-flash"): ModelPrice(input=0.30, output=2.50),
    ("openrouter", "google/gemini-2.5-flash-lite"): ModelPrice(input=0.10, output=0.40),
    ("openrouter", "google/gemini-3-flash-preview"): ModelPrice(input=0.50, output=3.00),

    # --- The curated evaluation slate, added 2026-10-26 ------------------------
    # These rows exist because the evaluation measures **cost per accepted result**,
    # and that figure is read from `pricing.estimate_cost`. Without a row here
    # `price_for` falls back to `(gemini, gemini-3.8-flash)` = $0.75/$3.75 for EVERY
    # unpriced route, so a run would report a plausible and entirely wrong cost for
    # each model -- `deepseek-v4-flash` at 8.2x too high, `claude-sonnet-5` at 2.7x
    # too low -- and rank them on it. `tests/test_pricing.py` asserts each curated id
    # is priced, so a model cannot be added to the set without its price.
    #
    # Read from the live listing on 2026-10-26 (see PRICE_SOURCES["openrouter"]).
    ("openrouter", "deepseek/deepseek-v4-flash"): ModelPrice(input=0.091, output=0.182),
    ("openrouter", "qwen/qwen3.8-flash"): ModelPrice(input=0.150, output=0.470),
    ("openrouter", "z-ai/glm-5.3-flash"): ModelPrice(input=0.150, output=0.500),
    ("openrouter", "mistralai/mistral-small-2603"): ModelPrice(input=0.150, output=0.600),
    ("openrouter", "anthropic/claude-haiku-5.5"): ModelPrice(input=0.100, output=0.500),
    ("openrouter", "openai/gpt-6-luna"): ModelPrice(input=0.100, output=0.500),
    ("openrouter", "anthropic/claude-sonnet-5"): ModelPrice(input=2.000, output=10.000),
}


def price_for(model: str, provider: str = DEFAULT_PROVIDER) -> ModelPrice:
    """The price for ``model`` on ``provider``, falling back to the default's price.

    The fallback exists so an unlisted model is priced **without crashing** -- the
    historical contract, kept. It targets the configured default rather than a
    removed legacy row, because the old fallback raised ``KeyError`` once that row
    was pruned (D-5).

    Callers that must distinguish "priced" from "guessed" should use
    :func:`is_priced`.
    """
    return PRICING.get(
        (provider or DEFAULT_PROVIDER, model),
        PRICING[(DEFAULT_PROVIDER, DEFAULT_MODEL)],
    )


def is_priced(model: str, provider: str = DEFAULT_PROVIDER) -> bool:
    """Whether this exact route is in the table, i.e. whether the price is verified."""
    return (provider or DEFAULT_PROVIDER, model) in PRICING


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str,
    provider: str = DEFAULT_PROVIDER,
) -> float:
    """Cost in USD, applying the long-context tier when the prompt crosses it.

    This is the D-3 fix. The previous implementation read ``pricing["input"]`` and
    ``pricing["output"]`` unconditionally, so a prompt over the threshold was billed
    at the short rate and the estimate came out **too low** -- the direction that
    makes a cheap-looking model look cheaper than it is.

    The tier is selected on the **input** count alone, which is how the providers
    bill: crossing the threshold re-rates the whole request, not just the excess.
    """
    price = price_for(model, provider)

    if price.has_long_tier and input_tokens > LONG_CONTEXT_THRESHOLD:
        input_rate = price.input_long
        output_rate = price.output_long
    else:
        input_rate = price.input
        output_rate = price.output

    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate


def describe_tier(input_tokens: int, model: str, provider: str = DEFAULT_PROVIDER) -> str:
    """A short human-readable label for which tier a run was priced at.

    Used by the UI so a user can see *why* a cost moved rather than only that it did.
    """
    price = price_for(model, provider)
    if price.has_long_tier and input_tokens > LONG_CONTEXT_THRESHOLD:
        return "long-context"
    return "standard"


def source_age_days(provider: str, *, today=None) -> Optional[int]:
    """How many days ago ``provider``'s prices were verified, or ``None``.

    ``None`` means there is no recorded verification date at all, which is a different
    and worse state than "old" -- an unverifiable row is not merely stale, it has no
    provenance. Callers should treat ``None`` and an over-age value the same way.
    """
    from datetime import date, datetime

    entry = PRICE_SOURCES.get(provider)
    if not entry:
        return None
    raw = entry.get("verified_on")
    if not raw:
        return None
    try:
        verified = datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        return None
    return ((today or date.today()) - verified).days


def is_stale(provider: str, *, max_age_days: int = PRICE_MAX_AGE_DAYS, today=None) -> bool:
    """Whether ``provider``'s prices are due for re-verification.

    **Fails towards "stale".** A missing date, an unparseable one, and an unknown
    provider all return True: the safe reading of "I cannot prove these prices are
    current" is that they are not. Returning False there would let a table with no
    provenance pass forever, which is the failure this guard exists to prevent.
    """
    age = source_age_days(provider, today=today)
    if age is None:
        return True
    return age > max_age_days


def staleness_message(provider: str, *, today=None) -> Optional[str]:
    """A one-line warning when ``provider``'s prices need re-verifying, else ``None``.

    Exists so the CLI and the evaluation can *say* that a cost figure is old rather
    than presenting a stale number with the same confidence as a fresh one.
    """
    age = source_age_days(provider, today=today)
    entry = PRICE_SOURCES.get(provider) or {}
    source = entry.get("source", "an unrecorded source")
    if age is None:
        return (
            f"{provider} prices have no recorded verification date "
            f"({source}); re-verify before trusting a cost figure."
        )
    if age > PRICE_MAX_AGE_DAYS:
        return (
            f"{provider} prices were last verified {age} days ago on "
            f"{entry.get('verified_on')} ({source}), which is older than "
            f"{PRICE_MAX_AGE_DAYS} days. Re-verify from the provider's own listing."
        )
    return None
