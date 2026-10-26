# 0016 — The study selects one model, with inputs retooled per candidate

**Status:** Approved (2026-10-26) — supersedes part of [0012](0012-structured-output-scope.md)
and reframes [0014](0014-evaluation-suite-and-curation.md)
**Related:** [0005](0005-llm-provider-interface.md) (benchmark before switching; model
curation), [0012](0012-structured-output-scope.md) (the schema this changes),
[0014](0014-evaluation-suite-and-curation.md) (the suite and the curated set),
[0013](0013-provider-interface-and-routing.md) (routing)

## Context

The owner's requirement was always that the tool **makes** the model decision rather
than handing the user a catalogue, and that the decision rest on a measured comparison
on **cost per accepted result**. The suite built for that is
[ADR 0014](0014-evaluation-suite-and-curation.md)'s, and it was run for the first time
on 2026-10-26.

**The run failed to produce a usable ranking, and the reason is the finding.** Three
provider families demand **mutually incompatible** response schemas, measured against
the live API:

| Family | Requirement | This project's schema |
|---|---|---|
| OpenAI (`gpt-6-luna`) | `additionalProperties: false` is **required** | absent → `400 "additionalProperties is required to be supplied and to be false"` |
| Anthropic via Vertex (`claude-haiku-5.5`) | **at most 24** optional parameters | **27** → `400 "Schemas contains too many optional parameters (27)... limit: 24"` |
| Google Gemini (the default) | `additionalProperties` is **forbidden** | rejected outright → `400 "additionalProperties is not supported in the Gemini API"` |

These are not variations in strictness; two of them are **direct contradictions**. Gemini
rejects the keyword OpenAI requires. And the count of 27 optional parameters is a
*consequence of* [ADR 0012](0012-structured-output-scope.md)'s deliberate choice to leave
the document body optional — the anti-truncation design is what makes the schema
unacceptable to Vertex.

The first two rows are therefore not model defects. They are **schema defects**: each
model was failing a task it could have completed if the request had been shaped for it.
Ranking models on that basis would have measured the project's Gemini-shaped schema
rather than the models.

## Decision

**One schema and one prompt per candidate, tuned for that candidate, compared on cost
per accepted result; the study then recommends a single model and the product ships
that model rather than a menu.**

Four parts:

1. **The curated set becomes the study's candidate list**, not a user-facing ladder. Its
   job is to be the shortlist the study compares; presenting eight options to the user
   was never the requirement and is now explicitly not the deliverable.
2. **Inputs are retooled per candidate** — the response schema and the prompt. A model is
   judged on its best achievable configuration, so the comparison answers "how well can
   this model do this job?" rather than "how well does this model tolerate a schema
   written for a different provider?".
3. **The metric is unchanged: cost per accepted result**, from the provider's own
   reported charge.
4. **The output is one recommendation.** The product's curated set becomes that model,
   and the schema shipped is the one that model was measured with.

### Fairness is the load-bearing property

Per-candidate tuning makes the comparison *more* meaningful only if it stays honest. The
risk it introduces is that better prompt-tuning for one candidate is measured as a better
model. Three rules hold that line:

- **The acceptance bar is identical for every candidate.** The same profiles, postings,
  validation rules and word-count gate. Nothing about *what counts as success* varies.
- **The person tuning is not the person judging.** The owner reads the accepted documents
  and makes the writing and layout judgement; a tuning change can improve a model's
  pass rate without improving its prose, and only a human reading the output can tell
  those apart.
- **Every per-candidate adaptation is recorded**, so a result can be attributed to the
  model or to its inputs rather than being an unexplained aggregate. A tuned prompt is
  part of that candidate's result, and the shipped product must carry the winning
  candidate's prompt and schema together.

## Why this is better than one shared schema

- **It measures the right thing.** The requirement is "which model, at what cost, does
  this job best" — not "which model survives a schema authored for another vendor".
- **It removes a false negative.** `gpt-6-luna` and `claude-haiku-5.5` are not worse
  models for failing a Gemini-shaped schema; they were mis-asked. Under the old framing
  they would have been ranked last for a defect in this repository.
- **It matches how the product actually works.** One model, one prompt, one schema,
  measured together — which is exactly the configuration that ships.

## Consequences

- **ADR 0012's "leave the body optional" decision does not survive as a global rule.**
  It was a reasonable anti-truncation device for one provider; it is unacceptable to
  another. The scope of the schema becomes *per candidate*, and ADR 0012's reasoning is
  retained as the reason for one candidate's shape rather than for all of them.
  **Its truncation question is still open** and must be re-measured per candidate: a
  tightened body has more constrained output, which is the very risk 0012 was managing.
- **The truncation concern may return, and this time it is a measured question.** A
  body that requires every field is longer to emit. Whether that truncates is exactly
  what the run must observe, per candidate.
- **A prompt becomes part of a candidate's measured result**, so the product must ship
  the winning candidate's prompt and schema, not a generic one. A future model change
  re-opens the study, not just a config value.
- **The owner judges writing and layout themselves.** The suite measures acceptance, cost
  and correction calls; it does **not** measure prose or layout quality, and no ranking
  may claim them.
- **The suite still cannot spend by accident**: a cap is required, an over-budget
  projection is refused before the first call, the cap is re-checked before every call,
  and nothing under `evaluation/` is collected by pytest.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep one shared schema and accept that some models fail it | Ranks this repository's schema, not the models. `gpt-6-luna` and `claude-haiku-5.5` would be excluded for a defect that is ours |
| Ship a per-provider schema in the product | Makes the shipped behaviour depend on which provider is configured, and does not answer "which single model should we use" |
| Keep offering the user a model menu | Never the requirement, and the owner has now stated the opposite: the tool makes the decision |
| Tune prompts per candidate and rank on acceptance alone | Measures prompt engineering alongside model quality. Kept honest only by a fixed acceptance bar, a recorded adaptation, and the owner's own judgement of the output |
| Lower the word-count gate so more models pass | Moves the bar instead of measuring against it. The gate is the requirement |
