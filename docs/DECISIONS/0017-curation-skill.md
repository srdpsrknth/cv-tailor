# 0017 — The curation skill: detection reports, the proposal is inert, a human judges

**Status:** Approved (2026-10-30) — implemented in the curation-skill items
**Related:** [0005](0005-llm-provider-interface.md) (benchmark before switching; curation is a maintenance obligation),
[0014](0014-evaluation-suite-and-curation.md) (the suite and its limits),
[0016](0016-per-candidate-inputs-and-one-winner.md) (per-candidate inputs; one winner)

## Context

The 2026-10-26 curation took a full session of manual research: read OpenRouter's catalogue,
filter it down, pick eight candidates, run the study, read the documents, choose a winner,
edit four places by hand. The owner's requirement was recorded at the time — *"a skill that
re-runs this curation when new models arrive, so the set can be refreshed without repeating
this session's manual research"* — and ten clarifying questions were owed before any code.

Three facts shaped the answers.

1. **The machinery already existed and had never been exercised as a workflow.** `evaluation/`
   was offline by default, budget-capped and out of CI, with `live.py` the only place a paid
   call can originate. What did not exist was the *procedure*: which step comes first, what
   stops it, and who decides.
2. **The suite measures three things and the owner reserved three others.** It records
   acceptance, cost and correction calls. It measures **no prose, no rendering and no layout**
   — `cv_page_count` is the only thing it records about a rendered document, and there is no
   orphan-heading, clipping, whitespace or typography measurement anywhere in it.
3. **A curated set is a maintenance obligation**, not a one-off (ADR 0005). The catalogue
   moved between two reads *on the same day*; on 2026-10-30 it had fallen from 467 models to
   456, and four prices had moved within a single day of the original study.

## Decision

**Split the work: detection and screening are free and automated, the proposal is inert, and
the quality judgement is a human step the code enforces.**

### The ten answers

| # | Question | Decision |
|---|---|---|
| 1 | What triggers a re-curation? | **A manual command, plus an offline `--detect` that diffs a fresh listing against the committed record.** Detection *reports only* and cannot spend |
| 2 | Replace the set, or propose a diff? | **Propose a diff.** Applying it is a separate, deliberate commit |
| 3 | Full study per candidate, or screen first? | **Screen first**, only survivors measured, slate capped at 8 |
| 4 | Standing budget? | **Per-run**, default $5, re-checked before every call. No monthly ledger |
| 5 | Explicit yes each time, or autonomous? | **Explicit yes each time**, in the conversation, with the projection shown |
| 6 | Switch the default automatically? | **No. Report only.** The switch is the owner's call and its own commit |
| 7 | Who judges writing, PDF and layout? | **The owner**, and the workflow cannot complete without it |
| 8 | What makes a result a failure? | Acceptance below 2/3; accepted nothing; **no owner verdict**. Correction calls are recorded, not disqualifying |
| 9 | Skill file or CLI subcommand? | **Both, and not a `cvtailor` subcommand.** The skill is the procedure; the CLI is the tool |
| 10 | Reproducible from the repository alone? | **Yes:** commit the digest and the screened subset, never the raw payload |

### What was built

| Piece | What it does |
|---|---|
| `evaluation/listing.py` + `listing_2026-10-30.json` | A committable screened record: seven fields per model, the **full payload's** digest, the source count |
| `evaluation/screen.py` (`--screen`) | A listing record into a proposed slate, with every rejection reasoned and its failing value named |
| `evaluation/curation_diff.py` (`--detect`, `--report`) | A catalogue diff; and a curation proposal that describes and **writes nothing** |
| `evaluation/reading_packet.py` (`--packet`) | One folder per model per case with the rendered documents, plus a `VERDICTS.md` |
| `.agents/skills/cv-model-curation/SKILL.md` | The procedure, the prohibitions, and this project's operational traps |

### Why each fork went the way it did

**Detection reports rather than triggers.** It is the one part of this workflow that *could*
have been automatic, and that is exactly why it is not: OpenRouter's catalogue churns
constantly — the model count moved twice in four days and four prices moved within one day —
so an automatic trigger would let routine provider activity spend the owner's money without
anyone deciding to. The two are separate commands, so the separation is structural rather
than a convention someone has to remember.

**The proposal is inert because the measurements cannot support a switch on their own.** An
automated replacement would mean an automated step deleting the only model production uses,
chosen on evidence that measures **none** of the three qualities the owner reserved. The
first version of the reading of this was a mistake in the other direction too: a measured
acceptance rate is not a quality verdict, and the code now says so by refusing to make any
entry eligible without one.

**The verdict gate is enforced, not documented.** `apply_verdicts` is the only way an entry
becomes eligible; a blank or whitespace verdict counts as absent, so a placeholder in a
checklist cannot promote a candidate; and a test asserts `ProposalEntry` carries no field a
measurement could set to promote itself. There is deliberately **no code path** from a
measurement to a verdict, because the entire value of the human step is that it is not
automatable.

**The screen's shortlisting is not a rejection, and the first implementation conflated
them.** It labelled every model outside the cheapest eight as `over-slate-cap` — 258 of 266
against the real record — which reads as a finding about the model when it is a decision
about the slate. They now carry `not-shortlisted`, and the reason says in as many words that
the model remains viable.

**The slate is filled cheapest-first with one guard against blindness, and that took three
attempts.** Taking simply the cheapest eight produced a slate entirely inside the bottom 0.2%
of the price range and reported `cost spread NO` — correctly — since the 266 survivors span
$0.00049 to $0.70605 per run, a factor of about 1,450. A strict round-robin over the three
cost bands then fixed the spread and broke the slate, filling half of it with `*-pro` models
at $0.41–$0.71 per run, roughly 200x the selected model. The shipped rule is a cheapest-first
fill where, if the dearest band is unrepresented, its cheapest member replaces the slate's
dearest entry. Both wrong answers are recorded in the code with their measurements.

**Routing variants are dropped as routes, not models.** `:batch`, `:free`, `:extended` and
`~latest` aliases are ways to reach a model. The 2026-10-30 screen found 55 `:batch` entries
and 18 tilde aliases among its survivors, and a `:batch` route is often *cheaper* than the
model it shadows — so a cheapest-first slate filled up with routes this pipeline cannot call
and displaced the models that would have been proposed on merit.

**The listing record commits the digest and the subset, never the blob.** Two tests used to
**skip** because they compared curated prices against a gitignored 467-model payload that was
absent from every fresh working copy. A digest proves a document was read; it cannot prove
what it said. The record now carries the fields curation uses for models above the owner's
recency floor, plus the **full payload's** hash, so a future read can be tied to exactly what
was seen — and both tests now run and **fail** rather than skip when the evidence is missing.

**`cvtailor curate` was rejected.** `cvtailor` is the tool the owner runs to produce
applications; growing a model-research workflow inside it would put a spending path behind the
command used daily.

## Consequences

- **The repository can verify its own recorded prices** for the first time. `--detect` makes
  the maintenance obligation ADR 0005 names a command rather than an intention.
- **A re-curation is now a procedure with two human steps**, and the second of them is
  enforced in code: no verdict, no eligibility.
- **The suite's limits are stated where they are acted on**, not only in a document. The
  proposal prints what it does not measure beside the numbers that look like a verdict.
- **A monthly spending ledger does not exist.** Q4's answer is a per-run cap. A standing
  monthly budget needs a spend ledger that nothing here keeps, and it was deliberately left
  out rather than bolted on.
- **Nothing about the shipped model changed.** `openai/gpt-6-luna` remains `DEFAULT_MODEL`,
  the curated set remains one entry, and `verified="measured"` is still **not** set — the
  owner's writing/PDF/layout judgement is still outstanding, and a test fails on purpose if
  the marker is set without it.
- **`LISTING_VERIFIED_ON` still reads `2026-10-26`** in `curated_models.py`. That constant
  records the listing the set was *selected from*, which remains true and is a different fact
  from the 2026-10-30 verification read. Changing it is a curation decision.

## Alternatives considered

| Option | Why not |
|---|---|
| Make detection automatic and run the study when it finds something | A provider's routine catalogue churn would spend the owner's money without anyone deciding to. The catalogue moved twice in four days |
| Replace `CURATED_MODELS` automatically when a winner emerges | An automated step deleting the only model production uses, on evidence that measures none of prose, rendering or layout |
| Let a measured acceptance rate make an entry eligible | Presents a measurement as a quality verdict — the specific error ADR 0005 warns against, one level down |
| Skip the screen and measure the whole catalogue | The paid half costs money per candidate; the 2026-10-26 study put 8 forward from 467, and the screen is that reduction written down |
| Take the cheapest `cap` candidates | Produced a slate with no cost spread, invisible because every entry looked defensible on its own |
| Round-robin the cost bands | Fixed the spread and filled half the slate with `*-pro` models at roughly 200x the selected model |
| Keep a routing variant in the slate | Measures the route rather than the model, and `:batch` often shadows its model on price — so it wins a cheapest-first cut for the wrong reason |
| `cvtailor curate` as a subcommand | Puts a spending path behind the command the owner uses daily to produce applications |
| Commit the 467-model payload | ~750 KB of descriptions, modalities and link templates, none of which any decision rests on |
| Leave the two tests skipping | A guard that skips whenever its evidence is missing is not a guard, and no price in the repository could be re-checked |
| Fill in the verdicts from the run's table | Defeats the only step that can judge what the suite cannot; the skill explicitly forbids an agent doing it |
