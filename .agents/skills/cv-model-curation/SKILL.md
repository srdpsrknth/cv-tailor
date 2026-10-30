---
name: cv-model-curation
description: Re-run the CV Tailor model study when new models arrive, so the curated model set can be refreshed without repeating manual research. Use when asked to re-curate, refresh or review the model choice, when a new model looks promising, or when a provider reprices or withdraws a model the tool uses.
---

# CV model curation

Refresh the model this tool uses, without repeating the manual research the first
curation took a full session. The procedure is here; the tooling is
`python -m evaluation`, which is offline by default and **cannot spend without an explicit
`--live` and a cap**.

**The owner's requirement has always been that the tool MAKES the model decision** rather
than offering a catalogue. So this is not a menu to widen: it is a measurement that ends in
one model.

## The order, and why it cannot be reordered

```
detect  →  screen  →  SHOW THE PLAN  →  ask  →  live run  →  packet  →  verdict  →  report  →  apply
   free      free         free        HUMAN    PAID      free       HUMAN      free      HUMAN
```

The two `HUMAN` steps are not advisory. `evaluation` measures **acceptance, cost and
correction calls** and nothing else — no prose, no rendering, no layout (ADR 0014). A
candidate with no verdict from the owner is reported as ineligible *for that reason*, and
that is enforced in `evaluation/curation_diff.py`, not by convention.

**Never run `--live` without asking the owner in the current conversation and showing them
the dry run's projection.** The cap protects against an overrun, not against a wrong plan.

## Step 0 — confirm the start state

Read `docs/PROJECT_STATE.md` first; it holds the verified baseline. Then:

```powershell
git rev-parse --abbrev-ref HEAD     # refactor/architecture-v2
git status --short                  # must be clean
.\.venv\Scripts\python.exe -m pytest -q
```

## Step 1 — detect whether anything changed (free, offline)

Fetch the listing yourself, then diff it against the committed record. Fetching is a
**keyless** network read; the detect command deliberately will not do it for you, so that
detection can never be the thing that touches the network on its own.

```powershell
# One keyless read. Never a paid API call.
$r = Invoke-WebRequest -Uri "https://openrouter.ai/api/v1/models" -UseBasicParsing -TimeoutSec 45
[System.IO.File]::WriteAllText("$PWD\.tmp\listing_new.json", $r.Content, [System.Text.UTF8Encoding]::new($false))

.\.venv\Scripts\python.exe -m evaluation --detect .tmp\listing_new.json
```

To refresh the **committed** record, rebuild it with `evaluation.listing.screen_payload`
and copy it in with `[System.IO.File]::WriteAllText($dst, $txt, [System.Text.UTF8Encoding]::new($false))`
— the Python subprocess cannot write most tracked paths in this worktree, and PowerShell's
`>` writes a BOM that makes a JSON file unparseable.

**No changes → stop here and say so.** A re-curation that finds nothing is a successful
re-curation. Do not run a study to confirm that nothing moved.

## Step 2 — screen the catalogue into a slate (free, offline)

```powershell
.\.venv\Scripts\python.exe -m evaluation --screen            # uses the committed record
```

Read the **rejections**, not only the slate. Every rejection carries the rule and the value
that failed, and the owner reviews *those*: "8 of 267, and here are the 259 I dropped". Note
`not-shortlisted` is a shortlisting decision and **not** a defect — it does not mean the
model is bad.

Then **stop and show the owner**: the proposed slate, the run's projected cost, and the
notable rejections. Ask for their go-ahead before anything else.

## Step 3 — add the slate to the study, then run it (PAID)

Adding candidates is a code change, and it is meant to be:

1. Add each candidate to `CURATED_MODELS` in `evaluation/curated_models.py`, with its price
   and `created` date from the record. Deciding which model to keep is what the run is for;
   the set is the study's candidate list (ADR 0016).
2. Add a price row for each id on the OpenRouter route in `backend/services/pricing.py`,
   with a dated `PRICE_SOURCES` entry. **Without it `price_for` borrows the fallback rate
   and every model reports the same invented cost** while looking entirely plausible.
3. Add a `CandidateInputs` entry in `evaluation/candidate_inputs.py` if the candidate needs
   a non-default schema dialect or output ceiling. **The rationale must record the
   *measured* error that forced it** — the constructor refuses one without. A dialect hint
   from `--screen` is `assumed=True` and is **not** a measurement; do not paste one in.
   Known families: OpenAI needs `additionalProperties: false`; Anthropic behind Vertex
   rejects more than 24 optional parameters; Gemini rejects that keyword outright. A
   reasoning model may need a raised ceiling or it returns an **empty** body.

Three tests assert these three things, so the run cannot start with a broken candidate.

```powershell
# Clear the sandbox first, or an earlier run's artefacts are reused and a reading packet
# will contain documents from a previous slate.
Remove-Item -Recurse -Force .tmp\evaluation-store

.\.venv\Scripts\python.exe -m evaluation              # dry run: the projection to approve
.\.venv\Scripts\python.exe -m evaluation --live --cap-usd 5
```

The cap is **per run**, defaults to $5, and is re-checked before every call. Do not raise it
on your own initiative; a raise is the owner's decision. An over-budget projection is
refused before the first call.

## Step 4 — the reading packet (free)

```powershell
# ranking: best first, by cost per accepted result, from the run's own summary.
# Write {"ranking": [...], "notes": [...]} to .tmp\ranking.json first.
.\.venv\Scripts\python.exe -m evaluation --packet .tmp\ranking.json
```

Hand the owner the packet path and `VERDICTS.md`. **Do not fill the verdicts in yourself
and do not ask leading questions about them.** The four questions are already in the file,
and free-form prose is the expected answer.

## Step 5 — the proposal (free, and it writes nothing)

After the owner has written their verdicts, merge them into the run's scores and report:

```powershell
.\.venv\Scripts\python.exe -m evaluation --report .tmp\scores_with_verdicts.json
```

The disqualifiers are the owner's settled three: **acceptance below 2/3**, **accepted
nothing**, and **no owner verdict**. Correction calls are recorded and are *not*
disqualifying — a model that needs them is neither cheap nor out, merely more expensive.

**"Keep the current model" is a real and common outcome.** Report it as such.

## Step 6 — applying it is a separate, deliberate commit

`--report` emits the diff as **text** and never applies it. Applying it means:

1. Replacing `CURATED_MODELS` with the winner, `accepted`/`attempted`/`cost_per_accepted`
   from the run.
2. Updating the price row and `PRICE_SOURCES` if the winner's route differs.
3. Setting `cost_per_accepted` and `measured_notes` from the run.
4. **`verified="measured"` only once the owner's verdict exists** — the marker licenses a
   quality claim, and the suite measures none. A test fails on purpose if it is set
   without that judgement.
5. Updating `DEFAULT_MODEL` in `backend/config.py` **and** `backend/services/pricing.py`,
   and the hard-coded id in `tests/test_evaluation_suite.py`.
6. One commit, with the measurement recorded. `e53ef8a` is the precedent.

**Never switch the default autonomously.** It changes what every future application is
generated with, and it is the owner's call.

## Hard rules

- **`--live` needs the owner's explicit yes in the current conversation**, with the
  projection shown first. No exceptions, including "the cap is small".
- **The acceptance bar is identical for every candidate.** Only the *asking* may vary
  (ADR 0016). Editing a profile, a posting, the validation rules or the word-count gate to
  make a candidate pass moves the bar instead of measuring against it.
- **No quality claim from a leaderboard.** No benchmark measures CV prose. IFBench and the
  hallucination figures exist to narrow the field to candidates worth paying to test, which
  is all they can support.
- **Cost is per *accepted* result, never per call.** A cheap model that fails the gate pays
  for its retries and produces nothing; `None`, never `0.0`, for a model that accepted
  nothing.
- **Every per-candidate adaptation is recorded**, so a result is attributable to the model
  or to the inputs it was given.
- **The suite reads only `tests/fixtures/`.** A live run must never send a real candidate's
  profile to a third party. Never point it at the private store.
- **ADRs are history.** Five name `GeminiService` deliberately; do not "fix" them.
  `PROJECT_STATE.md` describes the present and is where current names belong.
- **The test baseline must not regress.** Run `python -m pytest -q` after any code change
  and report what passed, what failed, and what you did not run.
