"""The curated OpenRouter model set.

**Why this module exists.** OpenRouter exposes 467 models (verified 2026-10-26). The
owner's instruction is explicit: do **not** expose the catalogue. A wall of models
hands the user a decision the tool should have made. This module is the tool having
made it.

**What is in it, and why.** A small set spanning different performance and cost
levels, so the trade-off is visible and the choice stays the user's. Every entry is
filtered on two things that are *verified* rather than assumed:

1. **`structured_outputs` is advertised for the model** in OpenRouter's own listing.
   A model without it cannot be relied on to return schema-valid JSON, which is the
   product requirement, so it is excluded regardless of quality or price. This is
   what removes the otherwise-attractive Amazon Nova family (`nova-micro` at
   $0.035/$0.140 would be the cheapest entry in this table).
2. **The endpoint's output ceiling can hold a document.** A CV draft is ≈1,350
   output tokens and a letter ≈620, and the pipeline sends `max_tokens`. An endpoint
   capped below a document is unusable for this task however cheap it is.

**What is NOT in it, and why that matters.** Quality is **not** measured here.
Selecting these models' *ranking* is what the evaluation suite
(:mod:`evaluation`) exists to do, and it has not run: choosing a winner from
leaderboard position or general reputation is exactly the mistake ADR 0005 warns
against, because the bar is task-specific — a two-page CV that passes the factual
gate, keeps every employer and date, meets the 290–310-word letter budget, and
returns schema-valid JSON. So each entry carries a :attr:`CuratedModel.verified`
field, and every entry currently reads ``price+capability``, never ``measured``.
The set is a **shortlist awaiting measurement**, and
:func:`curated_models` is what makes that claim machine-checkable rather than a
promise in a document.

**Maintenance.** ADR 0005 records that a curated set is a maintenance obligation,
because providers add, deprecate and reprice models constantly. The pinned rows were
read from one saved listing, hashed so a figure can be re-checked against exactly
what was read. Re-verify against the live listing before trusting a price, and see
``PRICE_SOURCES`` in :mod:`services.pricing` for the recorded provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: The OpenRouter listing the entries below were read from, and its SHA-256. A price
#: here is only meaningful alongside the exact listing it came from.
LISTING_URL = "https://openrouter.ai/api/v1/models"
LISTING_VERIFIED_ON = "2026-10-26"
LISTING_MODEL_COUNT = 467
LISTING_SHA256 = (
    "64B4A173A08F7027DD2F04778A85C5B5EFC4097331CF1529B502CBE249092BC7"
)

#: The two verification levels an entry may carry. ``measured`` is the only one that
#: licenses a quality claim, and nothing has it yet.
VERIFIED_PRICE_AND_CAPABILITY = "price+capability"
VERIFIED_MEASURED = "measured"


@dataclass(frozen=True)
class CuratedModel:
    """One offered option: an id, a plain-language label, and what is known about it.

    The label exists so the CLI and the UI can present the trade-off without the user
    needing to know what an OpenRouter slug means.
    """

    id: str
    #: Which cost tier this option sits in. Ordered by NATURAL_COST_ORDER below.
    tier: str
    label: str
    #: One line of user-facing guidance: what this option is *for*.
    guidance: str
    #: USD per 1M tokens, from the listing above. Recorded so the presentation can
    #: show the trade-off, and so a test can prove the tiers really are spread out.
    input_per_1m: float
    output_per_1m: float
    #: ``price+capability`` today, for every entry. See the module docstring.
    verified: str = VERIFIED_PRICE_AND_CAPABILITY
    #: Populated only by a completed evaluation run, never by hand.
    measured_notes: Optional[str] = None

    @property
    def is_measured(self) -> bool:
        """Whether this entry's *ranking* rests on measurement rather than inference."""
        return self.verified == VERIFIED_MEASURED

    def cost_for(self, input_tokens: int, output_tokens: int) -> float:
        """Cost of a run of this shape on this option, in USD."""
        return (input_tokens / 1_000_000) * self.input_per_1m + (
            output_tokens / 1_000_000
        ) * self.output_per_1m


#: Tier order, cheapest first. Used to present the set as a ladder rather than a list.
NATURAL_COST_ORDER = ("economy", "balanced", "frontier")


#: The curated set. Five options, chosen to span the cost range rather than to
#: exhaust it -- a user comparing five can hold the trade-off in their head; a user
#: comparing fifty cannot.
CURATED_MODELS: tuple[CuratedModel, ...] = (
    CuratedModel(
        id="google/gemini-2.5-flash-lite",
        tier="economy",
        label="Gemini 2.5 Flash Lite",
        guidance=(
            "Cheapest option that still supports structured output. Same family as "
            "the default, so its output style is closest to what you already get. "
            "Trial it on a role you do not care much about."
        ),
        input_per_1m=0.10,
        output_per_1m=0.40,
    ),
    CuratedModel(
        id="deepseek/deepseek-v4-flash",
        tier="economy",
        label="DeepSeek V4 Flash",
        guidance=(
            "Similarly cheap, from a different family, with a very large output "
            "ceiling. Useful as a second economy option when the Gemini family's "
            "wording does not suit a particular posting."
        ),
        input_per_1m=0.091,
        output_per_1m=0.182,
    ),
    CuratedModel(
        id="google/gemini-3-flash-preview",
        tier="balanced",
        label="Gemini 3 Flash (preview)",
        guidance=(
            "A newer generation than the default at roughly two-thirds the price. "
            "Preview, so it can change under you; worth knowing about, not worth "
            "depending on."
        ),
        input_per_1m=0.50,
        output_per_1m=3.00,
    ),
    CuratedModel(
        id="google/gemini-3.8-flash",
        tier="balanced",
        label="Gemini 3.8 Flash (the default)",
        guidance=(
            "The default, and the only option whose behaviour this project has used "
            "for real applications. Through OpenRouter it costs slightly more than "
            "going direct to Google."
        ),
        input_per_1m=0.825,
        output_per_1m=4.125,
    ),
    CuratedModel(
        id="anthropic/claude-sonnet-5",
        tier="frontier",
        label="Claude Sonnet 5",
        guidance=(
            "The expensive end, for a posting where the writing quality matters most. "
            "Roughly 30x the economy tiers per run, so use it deliberately."
        ),
        input_per_1m=2.00,
        output_per_1m=10.00,
    ),
)


def curated_models() -> tuple[CuratedModel, ...]:
    """The offered set, cheapest first.

    Returned as a tuple in :data:`NATURAL_COST_ORDER` so a caller presenting them
    shows a ladder rather than an arbitrary list.
    """
    return tuple(
        sorted(CURATED_MODELS, key=lambda m: NATURAL_COST_ORDER.index(m.tier))
    )


def find(model_id: str) -> Optional[CuratedModel]:
    """The curated entry for ``model_id``, or ``None`` if it is not offered.

    ``None`` is the meaningful answer: an id that is not curated is not something
    this tool will present, and the caller decides what to do about that rather than
    being handed a default.
    """
    for model in CURATED_MODELS:
        if model.id == model_id:
            return model
    return None


def unmeasured_entries() -> tuple[CuratedModel, ...]:
    """Every entry whose quality ranking is not yet measured.

    Exists so the honest claim -- "this is a shortlist, not a verdict" -- is a value
    the code can report and a test can assert, rather than a sentence in a document
    that could quietly stop being true.
    """
    return tuple(m for m in CURATED_MODELS if not m.is_measured)


def has_cost_spread() -> bool:
    """Whether the set spans genuinely different cost levels, as required.

    The owner's requirement is a set spanning performance *and* cost levels. A set
    that turned out to be five near-identical prices would satisfy "small" while
    failing the actual instruction, so this is checkable.
    """
    costs = [m.input_per_1m for m in CURATED_MODELS]
    return max(costs) >= 5 * min(costs)
