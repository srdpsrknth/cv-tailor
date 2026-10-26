# 0014 — The evaluation suite stays opt-in, and curation is a shortlist until measured

**Status:** Approved (2026-10-26) — implemented in Phase 3, item 6
**Related:** [0005](0005-llm-provider-interface.md) (§"Model curation", and the
benchmark-before-switching rule), [0013](0013-provider-interface-and-routing.md)

## Context

ADR 0005 requires an evaluation suite over synthetic profiles and anonymised postings,
comparing accuracy, completeness, relevance, writing quality, structured-output
success, unnecessary claims, correction attempts and **total cost per accepted
result**. It calls that suite "the gating prerequisite for choosing the curated set".
It also requires that live evaluation stays out of CI, and that the method and a
spending budget are agreed with the owner **before any paid call**.

The owner recorded a curation requirement on 2026-10-26: OpenRouter exposes a very
large catalogue (467 models when verified) and it must **not** be exposed wholesale;
the tool should offer a small set spanning performance and cost levels, chosen by
research weighed on price against content quality — measured, not assumed.

Three facts constrain the answer:

1. **The suite had never made a paid call**, and must not start by accident.
2. **Quality cannot be inferred from price or from a general leaderboard.** The bar is
   task-specific (a two-page CV through the factual gate, every employer and date
   kept, a 290–310-word letter, schema-valid JSON), and a model that tops a general
   ranking is not thereby fit for it.
3. **The owner's budget for the curation run is under $5 total.**

## Decision

**Build the suite now; make it structurally incapable of spending by accident; and
mark the curated set as UNMEASURED, because it is.**

### The suite

| Property | How it is enforced |
|---|---|
| Offline by default | `plan()` and `dry_run()` make no network call; the CLI defaults to `--dry-run` |
| Spending needs two things | `--live` **and** a cap that the projection fits; `live_run` also requires `authorised=True`, which no default sets |
| Cap fails closed | An over-budget **projection** is refused before the provider is built; a missing cap is a refusal, not "unlimited"; the cap is re-checked before every call, not once at the start |
| Out of CI | Nothing under `evaluation/` is named `test_*`; a test asserts that, and asserts CI does not invoke it |
| Synthetic data only | Cases resolve exclusively inside `tests/fixtures/`; a path that escapes is refused |
| Reproducible | Fixed case set, recorded token shape, prices from one verified table |

### The curated set

Five models, spanning economy/balanced/frontier, each filtered on two **verified**
properties rather than reputation:

1. **`structured_outputs` is advertised for it** in OpenRouter's listing. This is the
   filter that excludes the Amazon Nova family — `nova-micro` at $0.035/$0.140 would
   otherwise be the cheapest entry in the table.
2. **The endpoint's output ceiling holds a document** (a CV draft is ≈1,350 tokens).

Every entry carries `verified="price+capability"`. No entry says `measured`, because
no quality run has happened, and a test asserts that none does. The claim "the quality
ranking is unmeasured" is therefore a value the code reports, not a sentence in a
document that could quietly stop being true.

## Why this is the honest answer rather than a dodge

The item's deliverable is a curated set, and this delivers one — with its prices and
capabilities **measured from the provider's own listing**, and its quality ranking
explicitly not claimed. The alternative, ordering the set by reputation and presenting
it as researched, would fabricate exactly the evidence ADR 0005 says must precede a
model switch. Recording the gap is what makes the next chat's paid run a measurement
rather than a confirmation of something already asserted.

**Cost per accepted result is the headline metric, not cost per call.** A model that is
cheap per token and fails the gate is retried, so it pays three times its per-call
price and produces nothing usable; dividing by *accepted* results makes that visible.
`ModelScore` keeps both figures side by side, because the gap between them is the
finding, and reports `None` — never `0.0` — when a model accepted nothing, so the worst
performer cannot look like the best value.

## Consequences

- **The suite is ready to run and has not been run.** The projected cost of the whole
  curated run is **$1.68** against the owner's **$5** budget, upper-bounded at 12
  calls per case. The next step is authorisation, not more code.
- **The curated set is a shortlist, not a verdict.** Presenting it as a finished
  curation would overstate what is known.
- **A quality ranking is a maintenance obligation** (ADR 0005): providers add,
  deprecate and reprice models constantly. The recorded listing is hashed so a figure
  can be re-checked against exactly what was read, and `PRICE_SOURCES` carries the
  date and document for every route.
- **Writing quality is not model-scored.** Adding a model as judge would add cost,
  variance and a second thing to distrust. The objective proxies (length budgets,
  bullet counts, schema validity, factual gate) are what can be asserted
  reproducibly; the final qualitative judgement in ADR 0005's list remains the
  owner's, made by reading accepted documents.
- **No provider or model was switched.** Decision 6 stands: Gemini's latest Flash
  remains the default.

## Alternatives considered

| Option | Why not |
|---|---|
| Expose the full catalogue with a price column | Directly contradicts the owner's requirement; a wall of models hands the user a decision the tool should make |
| Rank the curated set by reputation or leaderboard position now | Presents assumed quality as measured — the specific error ADR 0005 names |
| Ship no OpenRouter model list until a paid run completes | Leaves the interface unusable for its second provider, and the shortlist's *price* half is already verifiable and useful |
| Auto-run the evaluation on first use | Spends the owner's money without their agreement; ADR 0005 requires the method and budget be agreed first |
| Judge writing quality with an LLM | Adds cost and variance, and introduces a judge whose ranking would itself be unmeasured — the same problem one level up |
| Report cost per accepted result as `0.0` for a model that accepted nothing | Makes the worst performer look like the best value; `None` is the honest encoding |
