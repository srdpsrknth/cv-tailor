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

from evaluation import cases

#: The OpenRouter listing the entries below were read from, and its SHA-256. A price
#: here is only meaningful alongside the exact listing it came from.
LISTING_URL = "https://openrouter.ai/api/v1/models"
LISTING_VERIFIED_ON = "2026-10-26"
LISTING_MODEL_COUNT = 467
LISTING_SHA256 = (
    "64B4A173A08F7027DD2F04778A85C5B5EFC4097331CF1529B502CBE249092BC7"
)

#: A **second** read of the same endpoint, later the same day, taken while the slate
#: below was selected. The catalogue is not static: between the two reads four pricing
#: entries moved (`deepseek/deepseek-v4-pro-0813` and `deepseek/deepseek-v4.1-flash-1017`
#: both halved, `moonshotai/kimi-k3` and `~moonshotai/kimi-latest` moved on input), the
#: model count did not change, and **no model in this slate changed price**. Recorded
#: because ADR 0005 calls a curated set a maintenance obligation, and this is the
#: measured evidence for why: a price is a fact with a timestamp, not a property.
LISTING_SHA256_LATER = (
    "6542C884A923D30F1A6AC3D8E97057C20C85795D4D02A2D7A49E4F784112524B"
)

#: The two verification levels an entry may carry. ``measured`` is the only one that
#: licenses a quality claim, and nothing has it yet.
VERIFIED_PRICE_AND_CAPABILITY = "price+capability"
VERIFIED_MEASURED = "measured"

#: Every entry must be at least this new. The owner's rule (2026-10-26): "i dont want
#: to use VERY old models either. i want models from oct 2025 onwards only." Enforced
#: by a test rather than by convention, because the cheapest tiers of a catalogue are
#: cheap *because* they are old -- an unpinned floor silently regrows a stale set.
MIN_CREATED = "2025-10-01"


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
    #: ``YYYY-MM-DD`` this model first appeared in the listing. Recorded so
    #: :data:`MIN_CREATED` can be enforced: the cheapest tiers of a catalogue are
    #: cheap *because* they are old, so without a pinned floor a "curated" set
    #: silently refills with stale models. A test asserts every entry is at or after
    #: the floor, and that every entry's id is priced on the OpenRouter route.
    created: str = ""
    #: ``price+capability`` today, for every entry. See the module docstring.
    verified: str = VERIFIED_PRICE_AND_CAPABILITY
    #: Populated only by a completed evaluation run, never by hand.
    measured_notes: Optional[str] = None
    #: The study's outcome for this candidate (ADR 0016), written from the run of
    #: 2026-10-26 and verifiable against the job folders that run left behind. An
    #: unmeasured candidate carries no values here and is not ranked at all -- nothing
    #: is inferred in their place.
    accepted: Optional[int] = None
    attempted: Optional[int] = None
    #: Cost per **accepted** result in USD -- the ranking metric. ``None`` for a
    #: candidate that accepted nothing: such a model has no meaningful cost per accepted
    #: result, and reporting ``0.0`` would make the worst performer look cheapest.
    cost_per_accepted: Optional[float] = None

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


#: The curated set. Eight options, chosen to span the cost range rather than to
#: exhaust it -- a user comparing eight can still hold the trade-off in their head; a
#: user comparing fifty cannot.
#:
#: **Re-selected 2026-10-26, on the owner's two rules.** The first draft of this set
#: was three Google models, one Anthropic and one DeepSeek, and the owner rejected it:
#: "which is fine but not much variety. i need to find the right balance of performance
#: of price for this task." The rules that replaced it:
#:
#: 1. **Seven distinct families.** A set of five models from four vendors is really two
#:    engineering choices dressed as five, and it cannot answer "does a non-Google model
#:    write these documents as well?".
#: 2. **Nothing older than 2025-10** (:data:`MIN_CREATED`). The cheapest models in a
#:    catalogue are the oldest, so an unpinned floor quietly regrows a stale set: the
#:    original draft's two cheapest entries were a 2024 Mistral and a 2025-08 OpenAI.
#: 3. **Every id priced on the OpenRouter route** (`services.pricing`), because
#:    `price_for` otherwise falls back to the default model's `$0.75/$3.75` and the
#:    run's headline metric -- cost per accepted result -- becomes fiction for every
#:    entry at once.
#: 4. **The default is kept as the control.** `google/gemini-3.8-flash` is the model
#:    this project actually ships, so every other entry has something real to be
#:    measured against rather than against a number on a leaderboard.
#:
#: **Two candidates were rejected on measured evidence, not on price.** Both would have
#: looked like good value on a capability ranking:
#:
#: * `minimax/minimax-m3.1-flash` scores 42.7 on the Artificial Analysis Intelligence
#:   Index -- on par with GLM-5.3 Flash -- but reports a **93% hallucination rate** on
#:   AA-Omniscience: when it does not know, it answers anyway rather than abstaining.
#:   This tool's hardest rule is "do not invent an achievement", so a model that never
#:   abstains is disqualified however cheap it is. Its predecessor `minimax-m3`
#:   measures 18.4%, which is why the family is not represented here at all: the
#:   calibration moved by 75 points in one release.
#: * `google/gemini-2.5-flash-lite` (2025-07) was in the rejected first draft. It is
#:   the cheapest thing that clears the capability screen and it is too old to keep.
#:
#: The evidence used to narrow the field, and its limits: OpenRouter's listing supplied
#: prices, ids, creation dates and the `structured_outputs` flag for all 467 models, of
#: which 189 met every structural requirement. Constraint-following evidence came from
#: IFBench (a model's ability to satisfy checkable instructions it has not seen -- the
#: closest public proxy for "keep every date, 290-310 words, schema-valid JSON"), and
#: non-fabrication evidence from AA-Omniscience's hallucination rate. **Neither is a
#: verdict on this task, no benchmark measures CV prose, and the leaderboards consulted
#: warn that their rank predicts deployment only weakly.** They exist here to choose
#: eight candidates worth paying to test, which is all they can support.
CURATED_MODELS: tuple[CuratedModel, ...] = (
    # --- economy -----------------------------------------------------------------
    CuratedModel(
        id="deepseek/deepseek-v4-flash",
        tier="economy",
        label="DeepSeek V4 Flash",
        guidance=(
            "The cheapest option per run, and the only surviving entry from the "
            "original shortlist. A very large output ceiling. Trial it on a role you "
            "do not care much about."
        ),
        input_per_1m=0.091,
        output_per_1m=0.182,
        created="2026-04-24",
        accepted=2,
        attempted=3,
        cost_per_accepted=0.00328,
        measured_notes=(
            'Second in both runs ($0.00328 and $0.00357). Cheapest per attempt, but 2/3 accepted '
            'with correction calls each time: one case failed the word-count gate. Cheapest per '
            'attempt and not per accepted result is exactly the gap this metric exists to expose.'
        ),
    ),
    CuratedModel(
        id="anthropic/claude-haiku-5.5",
        tier="economy",
        label="Claude Haiku 5.5",
        guidance=(
            "Anthropic's small model at an economy price -- a fifth of Claude Sonnet "
            "5 per run. The interesting question this entry answers is whether the "
            "expensive end is needed at all."
        ),
        input_per_1m=0.100,
        output_per_1m=0.500,
        created="2026-10-07",
        accepted=3,
        attempted=3,
        cost_per_accepted=0.00582,
        measured_notes=(
            'Third in both runs ($0.00582 and $0.00723). 3/3 accepted at about a fifth of Claude '
            'Sonnet 5 per accepted result, so the expensive end of its own family is not needed '
            'for this task. Asked in the anthropic-vertex dialect.'
        ),
    ),
    CuratedModel(
        id="openai/gpt-6-luna",
        tier="economy",
        label="GPT-6 Luna",
        guidance=(
            "OpenAI's newest small model, priced with the economy tier. Paired with "
            "Haiku 5.5 to test whether a current small model from a frontier lab "
            "matches a mid-price specialist on this task."
        ),
        input_per_1m=0.100,
        output_per_1m=0.500,
        created="2026-09-22",
        accepted=3,
        attempted=3,
        cost_per_accepted=0.00271,
        measured_notes=(
            'WINNER, and reproduced. Best cost per accepted result in both independent runs '
            '($0.00271 and $0.00353), 3/3 accepted with no correction calls in each, at roughly '
            '40x less than the incumbent default. Asked in the strict dialect.'
        ),
    ),
    # --- balanced ----------------------------------------------------------------
    CuratedModel(
        id="qwen/qwen3.8-flash",
        tier="balanced",
        label="Qwen3.8 Flash",
        guidance=(
            "Strong measured constraint-following (81.3% on IFBench) at a low price. "
            "A different family from everything else here."
        ),
        input_per_1m=0.150,
        output_per_1m=0.470,
        created="2026-08-26",
        accepted=0,
        attempted=3,
        cost_per_accepted=None,
        measured_notes=(
            '0/3 accepted in both runs. The failure is specific and reproducible: it leaked '
            'schema text into the output, returning a fragment such as a completionState object '
            'as the value of skills instead of a list of skills. Its 81.3% IFBench score did not '
            'predict this task.'
        ),
    ),
    CuratedModel(
        id="z-ai/glm-5.3-flash",
        tier="balanced",
        label="GLM-5.3 Flash",
        guidance=(
            "High measured intelligence at a flash price, with a low hallucination "
            "rate (27.6%) -- which matters here, because the failure this tool most "
            "needs to avoid is a confidently invented achievement."
        ),
        input_per_1m=0.150,
        output_per_1m=0.500,
        created="2026-08-26",
        accepted=0,
        attempted=3,
        cost_per_accepted=None,
        measured_notes=(
            '0/3 accepted in both runs. It omitted role, start_date and end_date from every work '
            'experience entry -- precisely the fields the factual gate exists to protect. Its low '
            'measured hallucination rate did not predict this either.'
        ),
    ),
    CuratedModel(
        id="mistralai/mistral-small-2603",
        tier="balanced",
        label="Mistral Small 4",
        guidance=(
            "The entry with the strongest *documented* schema guarantee: Mistral's own "
            "API reference specifies json_schema with strict enforcement, rather than "
            "leaving it to be inferred from a catalogue flag."
        ),
        input_per_1m=0.150,
        output_per_1m=0.600,
        created="2026-03-16",
        accepted=0,
        attempted=3,
        cost_per_accepted=None,
        measured_notes=(
            '0/3 accepted, and INCONCLUSIVE rather than failed: every call in both runs was '
            'rate-limited (HTTP 429) by its provider, so it never produced a document to judge. '
            'The one candidate that should be re-measured before it is judged.'
        ),
    ),
    # --- frontier ----------------------------------------------------------------
    CuratedModel(
        id="google/gemini-3.8-flash",
        tier="frontier",
        label="Gemini 3.8 Flash (the default)",
        guidance=(
            "The control. This is the model the project already uses for real "
            "applications, so every other entry is measured against something known "
            "rather than against a leaderboard. Through OpenRouter it costs slightly "
            "more than going direct to Google."
        ),
        input_per_1m=0.825,
        output_per_1m=4.125,
        created="2026-09-02",
        accepted=3,
        attempted=3,
        cost_per_accepted=0.11384,
        measured_notes=(
            'The incumbent default, kept as the control. 3/3 accepted in both runs but with 2 '
            "correction calls each time, at roughly 40x the winner's cost per accepted result. "
            'This is the number a switch would be justified against.'
        ),
    ),
    CuratedModel(
        id="anthropic/claude-sonnet-5",
        tier="frontier",
        label="Claude Sonnet 5",
        guidance=(
            "The expensive end, for a posting where the writing quality matters most. "
            "Roughly 20x the cheapest entry per run, so use it deliberately -- and "
            "note that Haiku 5.5 above exists to test whether it is worth it."
        ),
        input_per_1m=2.00,
        output_per_1m=10.00,
        created="2026-06-30",
        accepted=3,
        attempted=3,
        cost_per_accepted=0.15709,
        measured_notes=(
            'The most expensive candidate and the poorest value: 3/3 accepted at 1 correction '
            "call, for about 55x the winner's cost per accepted result. It works, and the "
            'measurement says it is not worth it here.'
        ),
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
    that turned out to be eight near-identical prices would satisfy "small" while
    failing the actual instruction, so this is checkable.

    **Measured on the run, not on the input rate.** Ranking by input price is actively
    misleading for this task: `z-ai/glm-5.2` is one of the cheapest entries in the
    catalogue per input token ($0.034/1M) and one of the most expensive per *run*,
    because this pipeline spends most of its budget on output. A spread test that
    compared input rates would pass a set that no user would call a spread.
    """
    costs = [typical_run_cost(m) for m in CURATED_MODELS]
    return max(costs) >= 5 * min(costs)


def typical_run_cost(model: "CuratedModel") -> float:
    """USD for one typical two-call application run on ``model``.

    The shape is the measured one from ASSESSMENT §5 -- a CV call (6,438 in / 1,350
    out) and a letter call (5,265 in / 622 out) -- and the token constants are
    **imported** from :mod:`evaluation.cases` rather than restated here. The two
    modules must agree on what a run costs, and a second copy of the numbers is
    exactly the kind of drift this project keeps having to remove.

    This is the figure a user actually pays, and the only basis on which two models'
    prices are comparable for this task: it is output-heavy, so an input-rate
    comparison misranks the set.
    """
    return model.cost_for(
        cases.CV_INPUT_TOKENS + cases.CL_INPUT_TOKENS,
        cases.CV_OUTPUT_TOKENS + cases.CL_OUTPUT_TOKENS,
    )


def unpriced_entries() -> tuple[CuratedModel, ...]:
    """Entries whose price is **not** on the OpenRouter route in ``services.pricing``.

    A curated entry with no price row does not raise -- ``price_for`` falls back to the
    default model's rate -- so it would be *silently* priced at $0.75/$3.75, and every
    entry in the set would report the same invented cost. Since the run's headline
    metric is cost per accepted result, that would make the whole measurement fiction
    while looking entirely plausible. A test asserts this tuple is **empty**.
    """
    from services.pricing import is_priced

    return tuple(m for m in CURATED_MODELS if not is_priced(m.id, "openrouter"))
