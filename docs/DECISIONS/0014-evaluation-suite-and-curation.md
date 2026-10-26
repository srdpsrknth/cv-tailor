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

**Re-selected 2026-10-26, after the owner rejected the first draft.** Five models
(three Google, one Anthropic, one DeepSeek) spanning economy/balanced/frontier was
the original set; the owner's objection was variety, and the rules that replaced it
are enforced by tests rather than recorded as intentions:

| Rule | Why, and how it is enforced |
|---|---|
| **≥ 5 distinct families** | Five entries from three vendors is two engineering choices wearing five labels, and cannot answer whether a non-Google model writes these documents as well. `test_the_set_spans_several_families` |
| **Nothing older than 2025-10** | The owner's instruction. The cheapest tiers of any catalogue are cheap *because* they are old — the first draft's two cheapest entries were a 2024 Mistral and a 2025-08 OpenAI model. `test_every_entry_is_recent_enough` |
| **A price row on the OpenRouter route** | `price_for` silently falls back to the default route's $0.75/$3.75 for any unknown model, so an unpriced entry reports the *same* invented cost as every other one. `test_every_curated_model_is_priced_on_the_route_the_run_uses` |
| **≤ 8 entries, < 10% of the listing** | The original requirement: do not expose the catalogue. 8 of 467 is under 2% |

Every entry still carries `verified="price+capability"`. No entry says `measured`,
because no quality run has happened, and a test asserts that none does.

**Two candidates were rejected on measured evidence, not on price.** Both would have
looked like good value on a capability ranking:

- **`minimax/minimax-m3.1-flash`** scores 42.7 on the Artificial Analysis Intelligence
  Index — on par with GLM-5.3 Flash — but reports a **93% hallucination rate** on
  AA-Omniscience: when it does not know, it answers anyway rather than abstaining. This
  tool's hardest rule is "do not invent an achievement", so a model that never abstains
  is disqualified however cheap it is. Its predecessor `minimax-m3` measures 18.4%,
  which is why the family is absent entirely: its calibration moved 75 points in one
  release.
- **`google/gemini-2.5-flash-lite`** (2025-07) was in the rejected draft. It is the
  cheapest thing that clears the capability screen and it is too old to keep.

### The limits of the evidence used to choose the set

Written down because the set is *presented* as curated, and the strength of that claim
should be visible rather than implied.

- **No benchmark measures this task's prose quality.** OpenRouter's own benchmarks cover
  agents, media and reasoning; there is no writing, summarisation or CV evaluation, and
  no "writing" task type in their benchmarks API.
- **IFBench is the closest proxy and is still a proxy.** It measures whether a model
  satisfies checkable instructions it has not seen — which maps onto "keep every date,
  290–310 words, return schema-valid JSON" — but it is not this task, and the
  leaderboards consulted warn that rank predicts deployment only weakly.
- **The `structured_outputs` flag is weaker than it looks, and this was verified.**
  OpenRouter's own docs state support "is determined per endpoint, not just per model",
  and that on `strict: true` some providers "treat it as a strong hint, so exact
  compliance is not guaranteed on every endpoint". The `/api/v1/models` payload carries
  **no per-endpoint field at all** — `supported_parameters` is one model-level array —
  so the flag cannot distinguish "natively enforces the schema" from "accepts the
  parameter and translates it". DeepSeek's own docs document only `json_object`, and
  Z.AI's reference lists only `text`/`json_object`, while both families carry the flag.
  *(The provider-doc claims are reported by a research pass and were not independently
  confirmed by the agent that wrote this record; the structural half — that the listing
  has no per-endpoint field — was verified directly. Treated as unresolved.)*
- **Therefore the flag is a filter, not a guarantee.** `require_parameters: true` is
  sent on schema-bearing calls, and validation stays in `parse_json_response` and
  `validate_cv` exactly where it was. Whether a given endpoint actually enforces the
  schema is what the live run measures, which is part of why it is worth paying for.

### Cost is the provider's own figure, and the table is only for projection

`ProviderResponse` carries `reported_cost_usd`, read from OpenRouter's `usage.cost`,
which their docs state is returned automatically with every response and needs no
request parameter (the old `usage.include` opt-in is deprecated and "has no effect").
It is authoritative in a way a table cannot be: pricing is per *request* and depends on
which upstream provider served it. `_record_spend` prefers it; `calculate_token_usage`
no longer re-prices the run's totals from the table.

The static table is retained for exactly two jobs, and for no third: pricing the
**projection** (ADR 0014 requires an over-budget plan be refused *before* any call,
when nothing has been reported yet), and pricing providers that report no cost at all —
which is Gemini, whose `usage_metadata` carries token counts only.

**A price is a fact with a timestamp.** `PRICE_MAX_AGE_DAYS` (62) encodes the owner's
"re-verify if older than 2 months" rule, the dry run — the screen a spend is approved
from — warns when the table is stale, and the guard fails towards stale: a missing or
unparseable verification date counts as stale, because "cannot prove it is current" is
not "is current".

**The rule is not ceremony, and here is the measured evidence.** Two reads of
OpenRouter's listing on the same day found four entries already moved — two of them
halved — while the model count was unchanged and no entry in this slate had moved.

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
  curated run is **$1.6467** for eight models against the owner's **$5** budget,
  upper-bounded at 12 calls per case. The next step is authorisation, not more code.
- **The curated set is a shortlist, not a verdict.** Presenting it as a finished
  curation would overstate what is known.
- **A quality ranking is a maintenance obligation** (ADR 0005): providers add,
  deprecate and reprice models constantly. The recorded listing is hashed so a figure
  can be re-checked against exactly what was read, and `PRICE_SOURCES` carries the
  date and document for every route. The staleness guard and the same-day price
  movement recorded above are what that obligation looks like in practice.
- **Writing quality is not model-scored.** Adding a model as judge would add cost,
  variance and a second thing to distrust. The objective proxies (length budgets,
  bullet counts, schema validity, factual gate) are what can be asserted
  reproducibly; the final qualitative judgement in ADR 0005's list remains the
  owner's, made by reading accepted documents. **The owner has confirmed they want to
  make that judgement themselves before any ranking is marked final**, so the run must
  leave them readable artefacts rather than only a table.
- **Layout and PDF quality are not measured by this suite at all.** The pipeline does
  render real LaTeX, so a PDF exists per case and the page-count gate really runs, but
  `evaluation/` records only `cv_page_count`: there is no orphan-heading, clipping,
  whitespace or typography measurement anywhere in it. A layout verdict from this run
  would be unwarranted, and the owner's reading of the artefacts is the only evidence
  there is for it.
- **No provider or model was switched.** Decision 6 stands: Gemini's latest Flash
  remains the default, and it is kept in the set as the control precisely so a future
  switch rests on a comparison against the model actually in use.

## Alternatives considered

| Option | Why not |
|---|---|
| Expose the full catalogue with a price column | Directly contradicts the owner's requirement; a wall of models hands the user a decision the tool should make |
| Rank the curated set by reputation or leaderboard position now | Presents assumed quality as measured — the specific error ADR 0005 names |
| Ship no OpenRouter model list until a paid run completes | Leaves the interface unusable for its second provider, and the shortlist's *price* half is already verifiable and useful |
| Auto-run the evaluation on first use | Spends the owner's money without their agreement; ADR 0005 requires the method and budget be agreed first |
| Judge writing quality with an LLM | Adds cost and variance, and introduces a judge whose ranking would itself be unmeasured — the same problem one level up |
| Report cost per accepted result as `0.0` for a model that accepted nothing | Makes the worst performer look like the best value; `None` is the honest encoding |
| Rank the set by input price per 1M tokens | Actively misleads for this task. This pipeline is output-heavy, so a model can be among the cheapest on input and among the most expensive per *run*: `z-ai/glm-5.2` is 8th-cheapest by input and worse per run than the default. The spread test measures a run, not a rate |
| Keep the static price table as the authority for a run's cost | OpenRouter reports the actual charge per request, and the same model routed to a different upstream provider costs a different amount — which no per-model row can express. The table is kept for the projection and for Gemini, which reports no cost |
| Trust the `structured_outputs` flag as proof of strict enforcement | The listing has no per-endpoint field, so the flag cannot distinguish native enforcement from translation, and OpenRouter's own docs say compliance "is not guaranteed on every endpoint". It is a filter; validation stays in the parser |
| Drop `minimax-m3.1-flash` silently on the hallucination figure | The rejection and its reason are recorded here, because a curation that removes candidates without saying why is indistinguishable from one that never considered them |
| Judge layout quality from the evaluation's page counts | The suite records `cv_page_count` and nothing else about rendering. Reporting a layout verdict from it would be inventing a measurement |
