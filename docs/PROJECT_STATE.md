# Project state

**Last updated:** 2026-10-26
**Branch:** `refactor/architecture-v2`
**Worktree:** `D:\coding\cv-tailor-next`
**Latest commit:** `def7fe0` — *docs: define item 5 and retire the discharged item 6 briefing* (item 5's code follows in this increment)
**Stable branch:** `master` (`D:\coding\cv-tailor`) at `1416177` — **usable for real applications**

---

## Active task

**Phase 3 — LLM and document-generation improvements. Items 4, 2, 1, 3, 6's OFFLINE GROUNDWORK and now 5 are done.**

Phase 3's scope is deliberately split across several chats. The agreed order is
**4 → 2 → 1 → 3**, then **6**, and **5** only once 1–4 have settled. Do not
combine two of these items in one commit: each changes the LLM call-count baseline the
others are verified against, so mixing them makes an intended change indistinguishable
from a regression.

| Item | State |
|---|---|
| **4. Serialise the profile once per application** | **DONE** (`2943b45`) |
| **2. Remove or merge the editorial-review pass** | **DONE** (`7c0d58a`) |
| **1. Targeted layout retry instead of full regeneration** | **DONE** (`9a45811`) |
| **3. Enable structured output (`response_schema`)** | **DONE** (`2e528e1` → `85879b5`); see ADR 0012 |
| **6. Provider interface, model routing, budget caps, and the curated model set** | **OFFLINE GROUNDWORK DONE** (`372a7bf`, `3cc8da5`, `215ba08`) — **the budgeted live run has NOT been made**; see below |
| **5. Cache validated results** | **DONE** (2026-10-26); see [ADR 0015](DECISIONS/0015-generation-cache.md) |

**Phase 3 has one piece of work left, and it is not code: item 6's budgeted live evaluation
run.** Everything else in the agreed order is committed and green.

### Phase 3, item 5 — cache validated results (2026-10-26)

**What changed.** One profile against one posting re-drafted both documents from scratch and paid
for them again. It now stores a **validated** generation under
`<store>/cache/<profile_id>/generations/<key>.json` and serves an identical request from disk.

| Commit | What it did |
|---|---|
| *(this increment)* | `services/cache_store.py`: the key, the entry and the store; the pipeline reads before its first call and writes after the page-count gate; `--no-cache` and the API's `use_cache` bypass. [ADR 0015](DECISIONS/0015-generation-cache.md) |

**The key is the bytes the model was shown, and that is enforced structurally rather than by
convention.** `cache_store.serialize_profile_bytes(profile)` produces one string, and that same
string is both emitted into the prompt context *and* hashed into the key. Two derivations could
drift, and a drift would mean hashing something the model was never shown. The full ingredient
list is: `format_version`, the profile bytes, the job description, company/role/country, **both
prompt files byte-for-byte**, a `PROMPT_VERSION` digest of the CV prompt file, the
response-schema digest, the provider, the CV model, the cover-letter model, and a digest of the
resolved `rules`.

**The prompt files are read and hashed per call, not tracked by a version constant.** That is
deliberate and it is the whole risk the roadmap names: a hand-maintained constant is one more
thing a prompt edit can forget to bump, and the failure is silent — the user gets a document
drafted under rules that no longer exist. Reading the file makes "a prompt change must not serve
a stale document" true by construction. `model` is **two** ingredients (`model_cv`, `model_cl`)
rather than one, because item 6 added per-task routing and two models can serve one posting.

**`job_id` and timestamps are deliberately absent from the key.** `make_job_id` embeds
`time.time_ns() // 1_000_000`, so keying on it would miss every single time by construction —
the cache would be write-only. A test asserts this behaviourally: the same inputs, evaluated with
the clock advanced, produce the same key.

**Only a validated result may be cached, and the write happens in exactly one place.** The entry
is written after the page-count gate has passed, so a draft that failed the gate cannot become a
permanent answer. Asserted by counting entries **during** rendering — a renderer that inspects the
cache records zero entries — so a write moved earlier in the function would be caught rather than
merely absent.

**A stored document is re-validated on read, through the same gate.** The cache is a plain JSON
file a person can edit or truncate, so "it was validated when it was stored" is a claim about the
past, not about these bytes. `DocumentGenerator.restore` runs the stored documents through the
same `_build_model` a fresh draft goes through — at **no API cost** — and a stored document that
no longer validates (because the profile changed, or the file was hand-edited) is treated as a
miss and regenerated. The read path never writes: a bad entry is not deleted, it is simply not
used, and the next generation overwrites it.

**Every read failure is a miss, never an error.** Missing, empty, malformed, truncated,
wrong-format-version, no-longer-validating and wrong-shape entries all degrade to "generate it
again", because a cache that can break a run that would otherwise have succeeded is worse than no
cache. Deleting `<store>/cache/` costs a regeneration and nothing else — there is no document that
exists only in the cache, because every entry was written from an application that was already
persisted.

**A hit reports zero usage, and that is the honest number.** Replaying the original run's token
totals would put a cost on a run that made no call, on the one path where the saving is the entire
point. The original figures are not lost: they are preserved in the same file as `original_usage`.
A hit still writes a **complete job folder**, including the restored raw responses as
`drafts.json`, because the cache replaces the generation and not the persistence — the user asked
for an application and gets one, with the same audit trail.

**Call counts are UNCHANGED at 2/3/5 on a cold cache** (min/typical/max-successful), 12 worst.
This is stated explicitly because the item's scope required it: item 5 adds a lookup **before** the
first call and a write **after** the last one, and adds no request. On a **hit** the count is
**0**, which is the item's whole point. `tests/test_editorial_instructions.py` still pins 2/3/5 and
still passes unchanged.

**The cache is derived data in the private store** (ADR 0011), at `<store>/cache/<profile_id>/` —
a sibling of `outputs/`, never inside it, because anything listing a candidate's applications must
not start returning cache entries. `ProfileStore.cache_dir` mirrors `outputs_dir` and validates
the id, so two candidates cannot read each other's entries (ADR 0003).

**What is deliberately NOT built, and is a real open follow-up: there is no eviction policy.**
Nothing prunes entries, so the directory grows by one small JSON file per distinct generation. For
a single-user tool where the whole directory is documented as safe to delete, that is acceptable —
but it is a follow-up rather than a solved problem, and [ADR 0015](DECISIONS/0015-generation-cache.md)
records it as such.

**Half the saving only appears when the inputs are truly identical, and that is by design.** A
user who edits the profile, changes the country, switches model or edits a prompt gets a fresh
draft. That is the invalidation contract the item asked for, not a miss to be optimised away.

**Tests: 436 → 478 passed** (~116 s), fully offline, no paid calls. Fast lane 406 → **448 passed**
(~13 s). New file `tests/test_generation_cache.py` (42 tests). Verified against a throwaway
`git worktree` at `def7fe0` (not by stashing): the file's defensive import **fails** there
(`services.cache_store could not be imported`), which is the correct outcome for a brand-new
module; with that one guard neutralised and nothing else changed, **37 of the 42 fail**. The 5 that
pass there are named rather than glossed over — two assert *that a fresh call happens*, which is
also what code with no cache does, and three assert that a second ordinary run reproduces the
first's documents, which is trivially true when there is no cache to differ from.

**One existing test was modified, and the reason is worth recording.**
`test_layout_retry.py::test_a_delta_that_breaks_a_profile_rule_is_rejected` runs the same profile
against the same posting twice — once with an accepted delta and once with a forbidden one. Those
two runs share a cache key, so the second was being served from the first's entry and the rejection
it asserts never executed. It now passes `use_cache=False` on the second run. **No assertion
changed.** That is a genuine finding: it is the first case in the suite where two runs are
deliberately identical, and item 5 is precisely about identical runs no longer being independent.

**Do not re-open increments 4, 2, 1 or 3, and do not re-open item 6's groundwork.** None was touched.

### Phase 3, item 6 — what was built, and the one thing still owed (2026-10-26)

**Three increments, each verified on its own against the frozen 2/3/5 baseline.**

| Increment | Commit | What it did |
|---|---|---|
| **A — provider interface, routing, budget caps** | `372a7bf` | `services/provider.py`: `generate(prompt, *, schema, max_tokens, model)` with Gemini as default (decision 6) and OpenRouter as the second implementation. Model-per-task routing (`Config.model_for`) and an optional `CVTAILOR_MAX_COST_USD` that fails closed. [ADR 0013](DECISIONS/0013-provider-interface-and-routing.md) |
| **B — D-3 and D-4** | `3cc8da5` | `services/pricing.py` is the one pricing source of truth, keyed by `(provider, model)` and tier-aware. The UI stops duplicating the table |
| **C — evaluation suite and curated set** | `215ba08` | `evaluation/` implements ADR 0005's eight criteria, offline by default, budget-capped, out of CI. Five curated OpenRouter models, every one **UNMEASURED**. [ADR 0014](DECISIONS/0014-evaluation-suite-and-curation.md) |

**Decisions 5, 6 and 7 were re-confirmed at the start of the item.** Decision 5 (thin adapters)
and decision 7 (job sources) were untouched. **Decision 6 was honoured, not merely noted**: Gemini
stays the default provider and `gemini-3.8-flash` stays `DEFAULT_MODEL`; OpenRouter is opt-in; and
**no provider or model was switched**, because ADR 0005 requires benchmarking before switching and
the benchmark has not run.

**The per-call response contract survived the indirection — this was the main risk.** ADR 0012
scopes structured output *per call*, and one call (the layout retry) must send **no** schema
because its response may be a delta of unit ids with no document key. The provider layer receives
`schema=None` on that call and passes it through as "send no constraint" on **both** providers, so
a provider swap cannot quietly turn the retry into a constrained call. `response_schema_for`
remains the single decision point; `_call_gemini` is still the single call site.

**OpenRouter's schema envelope is not Gemini's, so it is translated rather than passed through.**
Their contract is `response_format={"type": "json_schema", "json_schema": {"name", "strict",
"schema"}}` (verified from openrouter.ai/docs/features/structured-outputs, 2026-10-26). Their docs
also state that `strict` enforcement "varies by provider" and exact compliance "is not guaranteed
on every endpoint", so a schema-constrained call additionally sends
`provider.require_parameters: true` — their documented way to avoid an endpoint that would ignore
the schema. `strict` is **not** relied upon: validation stays in `parse_json_response` and
`validate_cv`, exactly where it was.

**No silent fallback, and `ProviderError` is deliberately not a `ValueError`.** The pipeline's
3-attempt correction loop catches `ValueError`, so a provider outage misclassified as one would
burn three paid calls re-asking a question the provider never answered. An unknown provider name,
a missing key for the *selected* provider, and a provider failure all raise.

**D-3 and D-4 are fixed, and no published figure moved.** The long-context tier is now applied to
the tokens (for `gemini-2.5-pro` at 300k tokens the old flat estimate was **$0.375 against a real
$0.75 — half**), and price is keyed by route because a bare model name does not identify one:
OpenRouter lists `google/gemini-3.8-flash` at **$0.825/$4.125** per 1M while Google charges
**$0.75/$3.75** direct. The §5 rows in ASSESSMENT are **identical** under the new accounting
($0.01559 / $0.026482 / $0.048265), because `gemini-3.8-flash` has no long tier and its prompts are
~6.4k tokens — far below the 200k threshold.

**The model curation, and what it honestly claims.** Owner requirement, recorded 2026-10-26:
OpenRouter must not be exposed wholesale. Five models are offered, spanning
economy/balanced/frontier, each filtered on two **verified** properties rather than reputation:
`structured_outputs` is advertised for it in OpenRouter's own listing, and its endpoint can emit a
document. That filter is what excludes the Amazon Nova family — `nova-micro` at $0.035/$0.140 would
otherwise be the cheapest entry in the set.

**No quality ranking is claimed, because none was measured.** Every entry reads
`verified="price+capability"`, and a test asserts that none says `measured`. Ordering these by
reputation and presenting it as research would fabricate exactly the evidence ADR 0005 says must
precede a model switch. The set is a **shortlist awaiting measurement**, and that claim is a value
the code reports rather than a sentence in this document.

**The evaluation suite exists and has never run.** It is offline by default (`plan()` and
`dry_run()` make no network call; the CLI defaults to `--dry-run`), spending requires `--live`
**and** a cap the projection fits, an over-budget **projection** is refused before the provider is
built, a missing cap is a refusal rather than "unlimited", the cap is re-checked before every
call, and nothing under `evaluation/` is named `test_*` so pytest and CI cannot reach the paid
path. Cases read only `tests/fixtures/` and refuse a path that escapes it, so a live run cannot
send a real candidate's profile to a third party.

**The one thing item 6 still owes.** The projected cost of the whole curated run is **$1.68**
against the owner's agreed **$5** budget (upper-bounded at 12 calls per case). Running it needs
authorisation, not more code. It answers two open questions at once:

1. **Which model is genuinely best per *accepted* result** for this task — the curation's
   headline requirement.
2. **Whether structured output truncates on real documents** — the question increment 3 could not
   settle offline. Increment 3 proved a truncated constrained response is *rejected* rather than
   parsed short, and designed the schema to protect against it, but made no paid call, so provider
   behaviour is still **unverified**.

**Call counts are UNCHANGED at 2/3/5** (min/typical/max-successful), 12 worst. No increment added
a call: the interface adds routing, the pricing change adds no request, and the evaluation suite
is not part of the pipeline. `tests/test_editorial_instructions.py` still pins 2/3/5 and still
passes unchanged.

**Tests: 351 → 436 passed** (~115 s), fully offline, no paid calls. Fast lane 321 → **406 passed**
(~12 s). New files: `tests/test_provider_interface.py` (39), `tests/test_pricing.py` (17),
`tests/test_evaluation_suite.py` (29). Diagnosed against a throwaway `git worktree` at `23156b1`
(not by stashing): **39 of 39** provider tests and **17 of 17** pricing tests fail there. The
evaluation file's 29 tests **also pass there**, stated plainly rather than hidden — that suite and
the curated set are new code with no predecessor, so there is no old behaviour to fail against,
and the file guards the new code's properties instead.

**No existing test was modified in behaviour.** One seam moved:
`tests/test_structured_output.py` patched `gemini_service.genai.Client` and now patches
`provider.genai.Client`, which is where the request is built. **No assertion changed** — those
tests still inspect the real `GenerateContentConfig`, so they remain a check of what is *sent*.

**Do not re-open increments 4, 2, 1 or 3.** None was touched.

### Phase 3, item 6 — briefing retained for the follow-up chat

**Start state for the follow-up:** `refactor/architecture-v2` at `215ba08`. Working tree clean,
nothing half-done. **436 passed** (~115 s) offline; fast lane **406**. `master` untouched at
`1416177`.

**What to do next, in order:**

1. **Ask the owner to authorise the budgeted live run** and re-confirm the $5 cap. Method and
   budget must be agreed before any paid call (ADR 0005); the projection is **$1.68**.
   ```powershell
   .venv\Scripts\python.exe -m evaluation              # dry run, free, shows the plan
   .venv\Scripts\python.exe -m evaluation --live --cap-usd 5
   ```
2. **Then, and only then, fill in the curated set's ranking** in
   `evaluation/curated_models.py`: set `verified="measured"` and record `measured_notes` from the
   real results. `tests/test_evaluation_suite.py` deliberately fails until the marker is updated,
   so the claim cannot drift ahead of the evidence.
3. **Answer the truncation question** from the same run — whether a schema-constrained draft
   truncated on a real document. If it did not, ADR 0012 records that the body constraints *can*
   be tightened, as a measured decision rather than a guess.

**Blast radius for the follow-up:**

| Area | Why it matters |
|---|---|
| `services/provider.py` | The one place a request is built. `schema=None` must stay meaning "send no constraint" |
| `services/gemini_service.py` | `_call_gemini` is still the only pipeline call site; `PRICING` here is a **derived view**, not a table |
| `services/pricing.py` | The single pricing source (D-4). A new row needs a dated entry in `PRICE_SOURCES` |
| `evaluation/curated_models.py` | The curated set and the UNMEASURED markers |
| `evaluation/live.py` | The **only** place a paid call can originate; imported lazily, only after the cap check |
| `tests/test_editorial_instructions.py` | Pins 2/3/5 — must keep passing |
| `tests/test_provider_interface.py` | Pins the per-call schema contract across the indirection |
| `tests/test_pricing.py` | Pins D-3/D-4, including that no second pricing table exists |

**House rules that bit previous increments** (worth repeating): do not verify against old code by
stashing or `git checkout --` in the working tree — use a throwaway `git worktree`. Under this
session's sandbox a new worktree may not be writable; point `TEMP`/`TMP` at a directory inside the
main worktree and pass an absolute path to that worktree's pytest. A test file that imports a
brand-new module should import it defensively and **fail** (not skip) when absent, so a broken
import in the real tree cannot hide behind a skip.

**Also open, deliberately not in item 6's scope:** D-13, D-14, D-15, A-6 (date validation), A-7,
and blocker 8. ~~**Item 5 (caching) is next in the agreed order**~~ — **DONE 2026-10-26**; see the
item 5 section at the top of this file.

### Phase 3, increment 3 — enable structured output, scoped (2026-10-26)

**What changed.** `_call_gemini` now sends
`response_mime_type="application/json"` together with a `response_schema`, **but only on
the calls whose response is always one complete document**: the CV draft and the cover
letter. The layout retry is deliberately left unconstrained, because since item 1 its
response may be a **delta** — an object of unit ids such as
`{"experience[0].bullets[1]": "..."}` with no document key — which a schema requiring `cv`
cannot express. Recorded in [ADR 0012](DECISIONS/0012-structured-output-scope.md).

**Why scoping is the answer to the truncation question, not a dodge.** The comment at the
old `gemini_service.py:135-137` recorded that JSON mode *caused premature truncation of
long document responses*, and that comment is why the original `response_schema` code was
deleted as dead (D-1). The anti-truncation property is therefore **designed into the
schema** rather than hoped for:

- the schema requires the **envelope** key (`cv` / `cover_letter`) and *nothing else* —
  so the real gain is that `parse_json_response`'s brace-scan stops being the failure path;
- there is **no `required` inside the document body** and **no `additionalProperties:
  false` anywhere** — enumerating and requiring every field of a ~1,350-token document is
  what makes a constrained response long and cut-off-prone, and a cut-off response is
  invalid JSON. The body's properties are described so the contract is meaningful, and
  left optional so the response stays short enough to finish;
- `tailoring_explanation` is permitted at the top level **and** nested inside `cv`, and
  required in neither, so the schema does not silently decide which of the two shapes
  `extract_explanation` receives, nor turn a harmless omission into a failed run and a
  wasted paid call;
- a kind absent from `generation.RESPONSE_SCHEMAS` gets **no** schema, so a future document
  type cannot inherit the CV's constraints by accident.

**What this increment does NOT claim.** It does **not** claim truncation was *observed* not
to return on real documents. No paid call was made — the suite is offline by constraint,
and the worktree's `.env` still has no `GEMINI_API_KEY` (blocker 1). What is established
offline is that the schema is well-formed and serialized by the SDK, that a truncated
constrained response is **rejected** rather than parsed into a short document, and that the
scope excludes the one call whose response is not a document. Confirming the truncation
behaviour against the provider needs a budgeted live run, which belongs to **item 6**.

**No silent fallback, and `validate_cv` is not bypassed.** A schema-constrained response
goes through the same `parse_json_response` and the same gate as before. JSON mode is a
*request* to the provider, never a substitute for validation: two tests drive a
schema-violating draft and a malformed one through the real pipeline and assert the run
still fails after exactly three attempts.

**Both explanation shapes still work.** `extract_explanation` reads the top level then
`cv.`; both are exercised through the real pipeline and both reach `TailoringExplanation`.
A response that omits the explanation entirely still succeeds with
`tailoring_explanation == None`, which is why it is not required in the schema.

**Call counts are UNCHANGED at 2/3/5** (min/typical/max-successful), 12 worst — verified by
driving the real pipeline rather than derived on paper. `tests/test_editorial_instructions.py`
still pins them and `tests/test_structured_output.py` re-asserts the happy and typical ends
of the range. The schema is request metadata, not prompt content, so **no prompt byte
changed** and the token and cost figures in ASSESSMENT §5 are unchanged. A schema that
failed often enough to trigger the correction loop would show up as a *rise* on the happy
path, which is why that path is asserted rather than left unmeasured.

**Tests: 324 → 351 passed** (~108 s), fully offline, no paid calls. Fast lane 294 → **321
passed** (~6 s). New file `tests/test_structured_output.py` (27 tests); **13 of the 27 fail
against `85879b5`**, verified by running them in a throwaway `git worktree` of that commit
(not by stashing).

**No existing test was modified.** The one supporting change is that
`tests/support.py`'s `OfflineGemini` gained a `calls` list recording each call's keyword
arguments: the schema is chosen **per call**, so "was a schema sent here?" is a property of
the call and the existing `prompts` list cannot express it. That is an addition to the
double, not a change to an existing assertion.

**Fixtures were NOT regenerated.** The response *shape* the model returns is unchanged — the
schema constrains the envelope, and both recorded transcripts already carry the document
key the schema requires. `tools/build_fixtures.py` was not run, so its two transcripts
remain in step with each other as increment 2 left them.

**Do not re-open increments 4, 2 or 1.** None was touched by this increment.

### Phase 3, increment 3 — briefing for the next chat (DISCHARGED 2026-10-26)

The briefing that stood here was **fully discharged** by the increment 3 section above.
Every entry in its blast-radius list was addressed:

- **`parse_json_response`** — unchanged; its `accept_delta=False` default and the retry-only
  switch-on are untouched, and a schema that does not satisfy the parser still fails loudly;
- **`looks_like_cv_delta` / `apply_cv_delta`** — the whole-document/delta collision was
  checked deliberately and resolved by **not sending a schema on the call that may return a
  delta**, which is asserted by `test_a_layout_retry_sends_no_schema`;
- **`extract_explanation`** — both shapes still work; the schema permits the top-level and
  the nested explanation and requires neither, and both are exercised end to end;
- **`_call_gemini`** — config, `max_output_tokens` and the retry loop are otherwise
  unchanged, and **neither the provider nor the model was changed** (decision 7);
- **Both fixture transcripts** — deliberately *not* regenerated, because the response shape
  did not change; the two remain in step with each other;
- **`tests/test_editorial_instructions.py`** — still pins 2/3/5 and still passes unchanged.

### Phase 3, item 6 — briefing for the next chat (DISCHARGED 2026-10-26, live run still owed)

The briefing that stood here was **discharged** by the item 6 section at the top of this file.
Every entry in its blast-radius list was addressed:

- **`services/gemini_service.py`** — `_call_gemini` is still the only pipeline call site; the
  pricing table moved to `services/pricing.py` (D-3, D-4 resolved), and `PRICING` here is now a
  **derived view** of that one table, not a second copy;
- **`_call_gemini`'s `kind` / `allow_delta`** — unchanged; `response_schema_for` still selects the
  schema per call, and `schema=None` now reaches the provider as an explicit "send no constraint",
  asserted on **both** providers by `tests/test_provider_interface.py`;
- **`generation.RESPONSE_SCHEMAS`** — unchanged and still provider-specific in shape; the
  OpenRouter implementation **translates** it into its own `response_format` envelope rather than
  receiving a neutral object, so the constraint is not silently dropped;
- **`config.py`** — `provider`, `openrouter_api_key`, `task_models` and `max_cost_usd` added, all
  read once in `from_env()`, frozen, with `DEFAULT_MODEL` still in the pricing table and Gemini
  still the default provider (decision 6);
- **`ui/app.py`** — no longer duplicates the pricing table (D-4); it prices through
  `services.pricing`, and a test fails if a model-keyed table grows back;
- **`tests/test_tailoring_pipeline.py`** — still pins the pricing invariants and still passes
  **unchanged**;
- **`tests/test_structured_output.py`** — still pins the per-call schema scope on the real
  `GenerateContentConfig`. One monkeypatch seam moved (`gemini_service.genai` → `provider.genai`);
  **no assertion changed**;
- **`tests/test_editorial_instructions.py`** — still pins 2/3/5 and still passes unchanged.

**What the follow-up chat still owes is not code.** The budgeted live evaluation run is the one
outstanding step; see "The one thing item 6 still owes" above for the commands, the projection and
what it answers.

**Superseded start state, kept for the record.** The briefing was written against
`refactor/architecture-v2` at `67de8b1` with **351 passed** and fast lane **321**. The item
finished at `68b91a6` with **436 passed** and fast lane **406**. `master` was untouched at
`1416177` throughout, as it still is.

**Baseline to verify, not re-derive:** call counts **2 / 3 / 5** (min / typical /
max-successful) and 12 worst. Item 6 must not change them by accident; if it does, say so
explicitly and explain why, exactly as increments 1 and 3 do. **They were not changed.**

**What the item was.** [ADR 0005](DECISIONS/0005-llm-provider-interface.md) deferred a
**thin provider interface** — a single `generate(prompt, *, schema, max_tokens, model)`
contract — with Gemini as the default and OpenRouter as a second implementation;
model-per-task routing; and optional budget caps. Decisions 5, 6 and 7 were re-confirmed at
the start of the item.

**Owner requirement recorded 2026-10-26 — model curation, and it was the heart of the item.**
It is now recorded durably in [ADR 0005](DECISIONS/0005-llm-provider-interface.md)
§"Model curation" and [ADR 0014](DECISIONS/0014-evaluation-suite-and-curation.md), and the
requirement itself is stated in the item 6 section at the top of this file. In short: do not
expose the catalogue; research which model is genuinely best for CV and cover-letter generation
on **price against content quality**; offer a small set spanning cost levels so the user sees the
trade-off. A general leaderboard ranking is not evidence of fitness — the bar is a two-page CV
that passes the factual gate, keeps every employer and date, meets the 290–310-word letter
budget and returns schema-valid JSON. Cost is judged per **accepted** result.

**The three gating prerequisites — how each was met:**

1. **The evaluation suite did not exist.** It now does: `evaluation/`, over the synthetic
   profiles and anonymised postings in `tests/fixtures/`, **out of CI**, budget-capped and
   reproducible. It is offline by default and **has not been run**.
2. **Agree the method and a spending budget before any paid call.** Done: the owner approved the
   method and a **$5** cap. The suite has still never made a paid call, and refuses an
   over-budget plan before the first request.
3. **Verify OpenRouter prices from OpenRouter's own listing.** Done, from
   `https://openrouter.ai/api/v1/models` on 2026-10-26 (467 models, SHA-256 recorded). No figure
   was carried over from a secondary source or invented.

**Also in scope from the deferred list, both now resolved:** **D-3** (cost under-reported — the
total priced with one flat rate while `input_long`/`output_long` tiers existed) and **D-4**
(pricing duplicated in the UI). Both are fixed in `services/pricing.py`; see increment B above.

**The question increment 3 could not settle offline is still open.** Whether structured output
truncates on **real** documents remains **unverified**: increment 3 established offline that a
truncated constrained response is rejected rather than parsed short, and item 6 preserved that
contract, but no paid call was made. The suite built for it is the answer, and running it is the
one step item 6 still owes.

**Blast radius — what actually changed, for the record:**

| Area | Outcome |
|---|---|
| `services/gemini_service.py` | Still the only pipeline call site. Pricing moved out to `services/pricing.py`; `PRICING` here is a **derived view**, not a table |
| `_call_gemini`'s `kind` / `allow_delta` | Preserved. `schema=None` reaches the provider as "send no constraint" on **both** providers |
| `services/generation.py` `RESPONSE_SCHEMAS` | Unchanged shape; OpenRouter **translates** it into its own `response_format` rather than receiving a neutral object |
| `config.py` | `provider`, `openrouter_api_key`, `task_models`, `max_cost_usd` added — read once in `from_env()`, frozen, Gemini still the default, `DEFAULT_MODEL` still priced |
| `ui/app.py` | No longer duplicates the pricing table (D-4); a test fails if a model-keyed table grows back |
| `tests/test_tailoring_pipeline.py` | Pins the pricing invariants; passes **unchanged** |
| `tests/test_structured_output.py` | Pins the per-call schema scope. One monkeypatch seam moved; **no assertion changed** |
| `tests/test_editorial_instructions.py` | Pins 2/3/5; passes unchanged |

**House rules that bit previous increments** (still worth repeating): do not verify against old
code by stashing or `git checkout --` in the working tree — use a throwaway `git worktree` at the
previous commit. Under this session's sandbox a new worktree may not be writable; point
`TEMP`/`TMP` at a directory inside the main worktree and pass an absolute path to that worktree's
pytest. A test file importing a brand-new module should import it defensively and **fail** (not
skip) when it is absent, so a broken import in the real tree cannot hide behind a skip.

**Also open, deliberately not in item 6's scope:** D-13, D-14, D-15, A-6 (date validation),
A-7, and blocker 8. ~~**Item 5 (caching) is next**~~ — **DONE 2026-10-26**.

### Phase 3, increment 1 — targeted layout retry instead of full regeneration (2026-10-26)

**What changed.** `DocumentGenerator.shorten_cv` used to re-send the whole CV prompt —
prompt file, editorial requirements, job description and the entire serialized profile —
plus the complete previous CV, and asked for a complete shorter CV back. That was the
largest remaining source of repeated input (ASSESSMENT §5 estimated 25–45% of
typical-case input cost). The retry now sends a **targeted brief plus the current CV**,
and accepts **either** a complete CV (the old contract, still supported) **or a delta** of
replacement values that is merged onto the CV that was just rendered.

**Measured effect** (real pipeline, recorded transcript, `tiktoken` `cl100k_base` as a
local proxy for Gemini's tokenizer — absolute numbers are not billed counts, but every
old/new comparison is on the same basis):

| Retry input | Before | After |
|---|---|---|
| Retry prompt | 3,488 tokens (16,508 chars) | **740 tokens (3,301 chars)** |
| of which context (profile + JD) | 1,408 | **0** |
| Whole 3-call run | 8,365 | **5,617** (−33%) |
| Retry response, if a delta | ~386–481 tokens (full JSON copy) | **~91–267** |

The retry now sends **fewer input tokens than the draft call** (740 vs 2,886) instead of
more. Measured against the **baseline** retry the increment is **−79% input**; measured
against the whole typical run it is **−33%**. The old estimate of 25–45% is therefore met
on the per-retry basis and slightly under it on the per-run basis — the run also pays for
the draft and the letter, which this increment does not touch.

**Call counts are UNCHANGED at 2/3/5** (min/typical/max-successful), verified by driving
the real pipeline rather than derived on paper; `tests/test_editorial_instructions.py`
still pins them and `tests/test_layout_retry.py` re-asserts the counts it exercises. This
increment lowers tokens **per retry**, not the number of retries. Worst case stays 12.

**Why a delta cannot weaken the gate.** `validate_cv` is not bypassed — it is called on
the *merged* document, and a delta has no path around it:

- the delta is merged onto the previous CV, which **already passed** `validate_cv`;
- `generation.apply_cv_delta` accepts only unit ids for the **summary, bullets, project
  names/bullets and existing skills categories**. Employers, titles, dates, education,
  certifications and `work_authorization` are **not addressable**, so no delta can invent
  an employer, alter a date, or turn ongoing work (`end_date: present`) into completed
  work — structurally, not by convention;
- an unknown or malformed key raises `ValueError`; it is **never ignored**. A delta that
  cannot be applied goes through the unchanged 3-attempt correction loop and then raises
  the run. There is **no** path that silently keeps the unshortened CV and reports
  success;
- a complete-CV response still goes through `_build_model` exactly as before.

**`parse_json_response` gained `accept_delta=False`.** A delta has no document key, so the
parser would have rejected it. The flag is off by default and is switched on only when a
retry has a base CV, so a *draft* that returns a stray object still fails loudly. The
parser is otherwise unchanged, and this is not item 3's `response_mime_type` work.

**`tailoring_explanation` precedence survives.** `shorten_cv` still returns
`extract_explanation(data) or explanation`, so a retry that returns its own explanation
supersedes the draft's — including on the delta path, where the explanation is read from
the delta object. The existing precedence test still passes unchanged.

**Load-bearing prompt constraints kept.** The retry brief still states every rule the old
instruction carried (keep all employers and exact dates, education and core skills, do not
shrink the font, do not complete ongoing work, do not remove an achievement or metric), and
the profile-derived project clause is unchanged. The old "approximately 650/550 words"
budget is unchanged too, but the brief now **also** reports the document's real length —
the recorded fixtures are ~80–100 real body words, so the bare 650-word target described a
document 3–8× the size of the one being shortened.

**Tests: 309 → 324 passed** (~108 s), fully offline, no paid calls. Fast lane 279 → **294
passed** (~6 s). New file `tests/test_layout_retry.py` (15 tests); **13 of the 15 fail
against the pre-increment code**, verified by running them against a throwaway worktree of
`2a7632d` (not by stashing).

**Tests that legitimately changed this time** (each pinned the *old* retry contract, which
is exactly what this increment replaces — none was "fixed" to make a broken change pass):

| Test | Change | Why it is correct |
|---|---|---|
| `test_tailoring_pipeline.py::test_layout_retry_shortens_the_cv_until_it_fits` | asserted the retry was `offline.last_prompt`; now selects the retry by its marker | The letter is drafted last, so the old assertion was checking the *letter*; it passed only because the whole context was re-sent. It now pins the retry itself |
| `test_tailoring_pipeline.py::test_layout_retry_budget_shrinks_with_each_attempt` | selects retries by `LAYOUT RETRY` instead of `LAYOUT CORRECTION` | The 650/550 budget assertions are unchanged; only the marker moved |
| `test_editorial_instructions.py::test_a_layout_retry_also_carries_the_requirements` | inverted: the retry no longer re-sends them; the draft still carries them exactly once | The retry stopped re-sending the context. The requirement that matters — the checks reach the model, once — is asserted more precisely than before |
| `test_profile_serialization.py::test_a_layout_retry_reuses_the_serialized_profile` | inverted: the profile block is now on the draft and letter **only** | Increment 1's invariant was "the same bytes every time" because the retry re-sent the context. Item 1 goes further: re-sending it is now the regression |

`test_tailor_service.py:114` was **not** changed: it asserts
`shorter['summary'][0] in ... or 'CURRENT CV:' in ...`, and the second clause still holds.

**Next action: Phase 3, item 3 — enable structured output (`response_schema`)**, in a new
chat. `_call_gemini`'s config and `response_mime_type` and `parse_json_response` are item
3's to change; item 1 touched only the retry path and the parser's default-off flag.
**DISCHARGED 2026-10-26** — see the increment 3 section at the top of this file.

**Do not re-open increments 4 or 2.** Neither was touched by this increment.

### Phase 3, increment 3 — briefing for the next chat (DISCHARGED 2026-10-26)

The briefing that stood here has been **fully discharged** by the increment 3 section at
the top of this file. Its start state was `14e19e8` with 324 passed, and its central design
question — *show truncation does not come back, or scope structured output to the calls
where it is safe* — was answered by **scoping**, with the anti-truncation property designed
into the schema rather than assumed. See [ADR 0012](DECISIONS/0012-structured-output-scope.md).

### Phase 3, increment 2 — remove or merge the editorial-review pass (2026-10-26)

**What changed.** `DocumentGenerator.generate_pair` used to make a **second** CV call: it
re-sent the whole context *plus* the full draft CV with `EDITORIAL_REVIEW_INSTRUCTION`
appended, and expected a complete revised CV back. That call is gone.

**Decision: MERGE, then drop the call.** The instruction text was folded into the draft
prompt rather than deleted, because dropping the requirements outright would have removed
real editorial constraints (no invented outcomes, no claims that developing work is
complete, no repeated bullets, no sole-ownership claims) that nothing else in the prompt
states. The pass itself was removed because it was **redundant, not protective**:

- every clause in it was already covered by the draft prompt's `WRITING AND FACTUAL RULES`,
  so the second call mostly re-asked for what the first call had been told;
- the revision it returned was **re-validated from scratch** by `validate_cv`, exactly like
  the draft — so the pass bought a second draft, not a stronger gate;
- it cost one whole call and ~25% of total input tokens (ASSESSMENT §5), because the draft
  CV JSON (≈7,730 tokens) was sent on top of the ≈6,150-token context that was sent again.

**Where the merged text lives.** `generation.EDITORIAL_REQUIREMENTS` (replacing
`EDITORIAL_REVIEW_INSTRUCTION`), injected by the new `generation.build_cv_prompt()`, which
`tailor_service.tailor_documents` now calls. The requirements are placed **before** the job
description and profile, so the model drafts against them instead of being handed them after
writing. They are deliberately **not** in `tailor_cv_prompt.md` — that file is the
candidate-facing writing brief — and they are **not** added to `build_context`, so the
cover-letter prompt does not pay for CV rules it does not use. Both properties are tested.

**`tailoring_explanation` now comes from the draft.** It used to be read from the review
response, which was the last CV call. It is now read from the draft response via the
unchanged `extract_explanation`, which still prefers the top-level key and still accepts the
nested `cv.tailoring_explanation` shape. A layout retry's explanation still supersedes it.

**Validation did not weaken.** The draft was *already* the only document `validate_cv`
gated; the review's output was validated too, but by the same function against the same
rules. No silent fallback was introduced: an invalid draft is retried only through the
documented 3-attempt correction loop and then raises, and no cover letter is drafted from an
invalid CV. Two tests in `tests/test_editorial_instructions.py` assert exactly that.

**Verified new call counts** (driven through the real pipeline with recorded transcripts,
not derived on paper):

| Case | Was | Now |
|---|---|---|
| Happy path | 3 | **2** |
| Typical (1 layout retry) | 4 | **3** |
| Max successful (fits on 4th render) | 6 | **5** |
| Worst (validation retries exhausted) | 18 | **12** |

**Measured cost effect** (`gemini-3.8-flash`, $0.75/$3.75 per 1M): best $0.027 → **$0.016**,
typical $0.038 → **$0.026**, max-successful $0.060 → **$0.048**. The CV call grows from
≈6,150 to ≈6,438 tokens (the requirements are 616 chars ≈ 288 tokens); the ≈7,772-token
review call disappears. **Happy path: −41% input tokens and one fewer call.**

**A pre-existing error in the old §5 table was found and corrected.** The old
"Typical (4 calls)" row stated 34,601 input tokens — the arithmetic of *five* calls, not
four — and the old "Worst (6 calls)" row at 65,513 tokens actually described the
max-successful case. The new rows are derived consistently, so a count and its tokens now
describe the same run.

**Fixtures regenerated.** Both recorded transcripts lost their `02_cv_editorial_review.json`
step (`tools/build_fixtures.py`; the step files were renamed so the numbering has no gap),
and each `01_cv_draft.json` now **is** the previously-reviewed payload — same
`{"cv": …, "tailoring_explanation": …}` shape, same summary wording. They still describe a
realistic accepted document; they just get there in one call.

**Tests: 298 → 309 passed** (~107 s), fully offline, no paid calls. Fast lane 268 → **279
passed** (~6 s). New file `tests/test_editorial_instructions.py` (11 tests, **9 of which fail
against the pre-increment code**, verified by stashing the change).

**Tests that legitimately changed this time** (each pins behaviour this increment intends to
change — none was "fixed" to make a broken change pass):

| Test | Change | Why it is correct |
|---|---|---|
| `test_tailoring_pipeline.py:47` | `call_count` 3 → **2** | The review call is gone; the count is the increment's headline result |
| `test_tailoring_pipeline.py` saved-content | asserted the **reviewed** summary, now the **draft** one | The draft is the accepted CV; there is no reviewed revision any more |
| 4 explanation tests (`:145-225`) | read `cv_draft` instead of `cv_editorial_review`; injected transcripts reordered | The explanation's source moved with the removed call |
| `:597`, `:765` + tailor_service `:105` | `cv_attempts` 3 → **2**, token totals 3000/300 → 2000/200 | Same run, one fewer CV call |
| `test_short_letter…` (`:640`) | dropped the now-nonexistent review response from the fake transcript | The transcript must match the calls the pipeline actually makes |
| `test_profile_serialization.py:101`, `:121` | `call_count` 3 → 2, 4 → 3 | Same removal; the serialization invariant itself is untouched |

**Do not re-open increment 1.** It stayed a pure de-duplication and its byte-identical-prompt
guarantee still holds; this increment is what changed the prompt and the call count.

### Phase 3, increment 1 — serialise the profile once per application (2026-10-26)

**What changed.** `tailor_documents` serialized the profile once per call — once for the CV
prompt and once for the cover-letter prompt — and `_validate_no_banned_tools` rebuilt the
profile's facts block once per banned tool (7 tools with the original candidate's rules) on
every validated CV, i.e. on the draft, the editorial review and every layout retry.

- `generation.build_context()` gained an optional `profile_json` parameter. It selects
  between two **identical** strings; its default reproduces the previous behaviour exactly.
- `tailor_service.tailor_documents()` now serializes **once** per application and passes
  those bytes in. The CV prompt, the letter prompt and every layout retry share that block.
- `generation.profile_facts_json()` memoizes the rules-excluded facts block on the profile
  object under a private attribute, so the seven-scan loop serializes once.

**This is a de-duplication of work, not a prompt change.** The bytes sent to the model are
unchanged, so the token and cost figures in ASSESSMENT.md §5 are unchanged too —
**do not record this increment as a cost saving.** The measured saving is CPU only
(≈0.044 ms per prompt serialization, ≈0.23 ms per facts rebuild on a 15k-character
profile — single-digit milliseconds per application).

**Two invariants were preserved deliberately, both with tests:**

1. **The rendered prompt is byte-identical.** `tests/test_profile_serialization.py` asserts
   the context with and without `profile_json` is the same string, for every branch of the
   country header.
2. **`rules` stays excluded from `_profile_facts_json`.** Declaring a tool banned must not
   silently un-ban it. The memo caches that same rules-excluded text, and a test asserts the
   banned-tool rejection still fires on the cached path.

**Cache placement (do not "simplify" this).** The memo is a **private attribute on the
profile object**, not a module-level map (no process-global state, no key to collide, entry
collected with its profile) and **not a `Profile` field**. Pydantic admits an undeclared
attribute only while its name is underscore-prefixed; a declared field would join
`model_dump()`, which is both sent to the model *and* the input to `_profile_facts_json` —
the block would contain itself. Setting it uses `object.__setattr__` with a recompute
fallback, so caching is never a requirement.

**Test count: 282 → 298 passed** (~112 s), fully offline. Fast lane 252 → **268 passed**
(~7 s). **No existing test was modified**, and the new file is `tests/test_profile_serialization.py`
(16 tests, 11 of which fail against the pre-increment code).

### Phase 3, increment 2 — briefing for the next chat (DISCHARGED 2026-10-26)

The briefing that stood here has been **fully discharged** by the increment 2 section above.
Every item in its blast-radius list was addressed:

- the happy-path `call_count` is now **2**, and `cv_attempts` **2** — asserted, not assumed;
- the saved CV is the **draft**, and the draft is what the letter is built from;
- the four explanation tests now read `cv_draft`; the nested and top-level precedence cases
  and the layout-retry precedence case all still hold;
- **both** transcripts dropped their `02_cv_editorial_review.json` step and were regenerated
  with `tools/build_fixtures.py` in step with each other;
- `EDITORIAL_REVIEW_INSTRUCTION` was replaced by `EDITORIAL_REQUIREMENTS`, as item 2 owned.

**Item 1's baseline is now frozen at 2/3/5.** Do not touch `shorten_cv` or
`layout_correction_instruction` outside item 1, and do not touch `_call_gemini`'s config,
`response_mime_type` or `parse_json_response` outside item 3.

**Phase 2 — multi-profile architecture. COMPLETE and CLOSED OUT (code + tests + migration +
docs + clean-up).**

`ProfileStore` is in place, `profile_id` is threaded end to end and fails closed, the real
profile has migrated into the private store, the real data is no longer tracked in the public
repository, and the API adapter now resolves through the store like everything else. `master`
is untouched.

**Next action (Phase 2):** discharged — Phase 2 owes nothing further. **The next action for
the project is Phase 3 increment 2: remove or merge the editorial-review pass.** It is a new
chat by design, because it changes the call count from 3/4/6 to 2/3/5 and therefore must be
verified against a baseline that increment 1 has now frozen. The close-out on 2026-10-26
closed the last functional gap (`backend/main.py`) and settled the remaining D-items:

1. **`backend/main.py` is multi-profile aware and tested** — closed in `a0b431c`; see
   "Close-out" below. This was the largest functional gap left and had no tests at all.
2. **D-9 re-verified as already resolved** — no `git rm --cached` was owed. The three untracked
   leftovers on disk were deleted after SHA-256 confirmation against the private store.
3. **D-10 decided by the owner — leave history as-is.** Recorded as an accepted limitation,
   consistent with [ADR 0011](DECISIONS/0011-private-store-location.md).
4. **D-11 deferred to Phase 5** by owner decision; [ADR 0009](DECISIONS/0009-interfaces-and-archive.md)
   carries the amendment.
5. **Date validation (A-6)** — still unvalidated strings. The remaining genuine integrity risk,
   deliberately not bundled into a clean-up pass.

**Do not re-read [`HANDOFF-PHASE-2.md`](HANDOFF-PHASE-2.md) as a to-do list**: its entry
conditions and order of work are discharged. Its §4 privacy warning is resolved for *new* data
and explicitly **not** resolved for already-published history.

### Phase 2 close-out (2026-10-26)

| Item | Outcome |
|---|---|
| `backend/main.py` (blocker 7) | **Fixed** — `/api/tailor` and all three download routes take an explicit `profile_id`, resolve through the store and fail closed; `job_id` validated against `^[A-Za-z0-9_-]+$`; first 20 API tests added, 16 of which fail against the old code |
| D-8 | **Re-confirmed resolved** — `copilot-instructions.md` is a 37-line pointer to `AGENTS.md`; no second instruction file |
| D-9 | **Re-verified as already resolved** — `git ls-files outputs` → `outputs/.gitkeep` only; the untracked pre-Phase-2 PDFs/DOCX were deleted after SHA-256 confirmation against the store |
| D-10 | **Owner decision: leave history as-is** — untracked and gitignored; still in past commits, as ADR 0011 records |
| D-11 | **Owner decision: defer to Phase 5** — ADR 0009 amended |
| Dead code | **Removed** — `backend/validate_profile.py` (86 lines, unreferenced, hardcoded the dead single-profile path) and two self-referential `Config` aliases |
| Tests | **262 → 282 passed** (~114 s), offline; fast lane 232 → 252 (~7 s). **No existing test was modified** |

### What Phase 2 delivered

| Increment | Commit | Outcome |
|---|---|---|
| `profile_id` | `f583349` | `ProfileStore`, fail-closed threading, `outputs/<profile_id>/<job_id>/`, A-9 fixed, `profile list/new/import/export` |
| Privacy split | `86b1a0d` | Real profiles/applications/outputs untracked; private store created and populated; boundary asserted by tests |
| Documents in the store | "fix: write generated documents into the private store" (latest) | Generated documents now land in `<store>/outputs/<profile_id>/<job_id>/`; `doctor` and `render` follow the store |

### Acceptance criteria — verified

| Criterion | Result |
|---|---|
| Two profiles generate independently, no cross-contamination | **Yes** — `tests/test_profile_isolation.py`, 13 tests |
| `profile_id` explicit and fail-closed; no code path defaults | **Yes** — `tests/test_profile_store.py`, 46 tests |
| Migration preserves facts, titles, dates and `rules:` block | **Yes** — copied byte-for-byte, SHA-256 verified, then loaded through the store |
| The real profile is not in the public repo | **Yes, for new commits** — untracked and gitignored, asserted by `tests/test_privacy_boundary.py`. **Not** removed from existing history |
| Generated documents land in the store, not the repo | **Yes** — `test_documents_are_written_into_the_store_not_the_repository` fails if `ApplicationStore` is rooted at `PROJECT_ROOT` again |
| 190 existing tests still pass | **Yes** — all 190 still pass. Four *path assertions* across three tests in `test_tailoring_pipeline.py` and `test_tailor_service.py` were updated, because the output layout itself changed (`outputs/<job_id>/` → `outputs/<profile_id>/<job_id>/`); their assertions about content and behaviour are unchanged |
| `pytest -q` green and offline | **282 passed** in ~114 s, no paid API calls (262 at the end of Phase 2 itself) |

### What Phase 1 delivered

| Increment | Commit | Outcome |
|---|---|---|
| Bug fix | `edb6efc` | `tailoring_explanation` is read from a nested `cv` as well as the top level |
| Dead code | `b568990` | D-1, D-2, D-5, D-6, D-7, D-12 removed; a latent `KeyError` in pricing fixed |
| Config | `ef500b6` | **No import-time env reads**; one `Config` object resolved at call time (A-5) |
| Service layer | `dfe03ec` | `tailor_documents` split into `generation` + `application_store` (A-3) |
| Profile rules | `e05562e` | Candidate rules are profile-scoped data, not hardcoded (A-1) |
| CLI | `179bd83` | `cvtailor` with `doctor`, `profile show`, `generate`, `render` (ADR 0007) |

### Acceptance criteria — verified

| Criterion | Result |
|---|---|
| All 141 baseline tests pass **unchanged** | **Yes** — no existing test was modified at any point |
| CLI reproduces a `content.json` render, same page count | **Yes** — asserted against `scripts/render_application.py`, byte-identical extracted text |
| No import-time environment reads | **Yes** — guarded by a test that fails if one is reintroduced |
| Behaviour preserved: same documents, page counts, costs | **Yes** — full suite green including real LaTeX/DOCX output |
| `pytest -q` green and fully offline | **190 passed** in ~110 s, no paid API calls |

### Approved decisions (summary)

1. **Privacy** — real profiles/applications/outputs move to a **private store**; commit only
   synthetic examples. Reachability from any machine is handled later by a remote store
   ([0006](DECISIONS/0006-remote-profile-access.md)). **Implemented in Phase 2** — the store
   is `D:\coding\cv-tailor-data`, its own private Git repository
   ([0011](DECISIONS/0011-private-store-location.md)).
2. **Architecture** — Option B, modular redesign, incrementally.
3. **Storage** — files keyed by `profile_id`, **local first**, no database server.
4. **CLI** — `argparse` plus a friendliness layer (guided default, prompts, `doctor`, `--json`).
5. **FastAPI + Streamlit** — keep both as thin adapters; reassess at Phase 6.
6. **LLM** — provider interface; benchmark cost/performance/quality before switching; keep
   Gemini's latest Flash as default.
7. **Job sources** — ToS-compliant APIs first; scraping only if permitted and necessary.
8. **`applications/`** — read-only reference until Phase 2, then migrate.

Re-confirm each decision when its phase begins.

---

## Current status

| Area | State |
|---|---|
| Stable app on `master` | Working, untouched, own `.venv` and `.env` (ports 8000/8501) |
| Dev branch | 34 commits ahead of `master` — Phases 1 and 2 complete, Phase 3 items 4, 2, 1, 3, 5 and item 6's offline groundwork done |
| Dev worktree runnable? | **Yes** — `.venv`, `.env` (ports 8001/8502) |
| Test baseline | **478 passed** (~116 s); fast lane `-m "not requires_latex"` → 448 passed (~13 s) |
| CLI | **Working** — `python cvtailor.py <command>`; `profile list/show/new/import/export`, `generate` (with `--no-cache`), `render`, `doctor` |
| Providers | **Gemini (default) and OpenRouter**, behind one `generate(...)` contract; model-per-task routing; optional `CVTAILOR_MAX_COST_USD` cap |
| Pricing | **One source of truth** — `services/pricing.py`, route- and tier-aware (D-3, D-4 resolved) |
| Generation cache | **Live** — a validated generation is stored under `<store>/cache/<profile_id>/`; an identical repeat costs **0** LLM calls. Derived data, safe to delete, **no eviction policy** |
| Evaluation suite | **Exists, offline by default, never in CI; has NOT been run.** Whole curated run projected at **$1.68** against a **$5** cap |
| Curated models | **5 offered** (economy/balanced/frontier), all **UNMEASURED** — quality ranking awaits the live run |
| HTTP API | **Multi-profile aware** — `/api/tailor` and the download routes resolve `profile_id` through the store and fail closed (`test_api.py`, 20 tests) |
| Fixtures | Synthetic only — `tests/fixtures/`; a test asserts no real identity appears in them |
| Private store | **`D:\coding\cv-tailor-data`** — its own Git repo (profile + 8 applications + outputs) |
| Generated documents | Written to `<store>/outputs/<profile_id>/<job_id>/`; the repo's own `outputs/` holds only `.gitkeep` |
| Real data in public repo | **Untracked since Phase 2**; still present in history (see blocker 2) |
| Assessment | Complete and committed — [`ASSESSMENT.md`](ASSESSMENT.md); D-3 and D-4 now resolved |
| Decisions | **14 approved**; **ADR 0013** (provider interface, routing, caps) and **ADR 0014** (evaluation suite, curation) are new |
| Roadmap | Phase 0, 1.1, **1 and 2 complete**, **Phase 3 items 4, 2, 1, 3, 5 and 6's offline groundwork done**. The **only** Phase 3 work left is item 6's budgeted live evaluation run, which needs owner authorisation rather than code |

### Verified baseline facts

- `.venv\Scripts\python.exe -m pytest -q` → **478 passed**, 1 warning (~116 s), offline.
- Fast lane `.venv\Scripts\python.exe -m pytest -q -m "not requires_latex"` → **448 passed**,
  30 deselected (~13 s).
- Fully offline: verified with `GEMINI_API_KEY` unset; no paid API calls in the suite. **No paid
  call has ever been made in this repository.**
- **No existing test was modified before Phase 2.** The suite grew 141 → 190 in Phase 1,
  190 → 262 in Phase 2, 262 → 282 in the 2026-10-26 close-out, 282 → 298 in Phase 3
  increment 1 (all new files), 298 → 309 in increment 2 (one new file, plus the legitimate
  edits listed in that increment's section — the first time edits to existing tests were
  intended rather than incidental), 309 → **324** in increment 1 of the agreed order
  (one new file, plus four existing tests that pinned the retry contract that increment
  deliberately replaced), 324 → **351** in increment 3 of the agreed order (one new
  file, **no existing test modified**), 351 → **390** in item 6 increment A (one new file,
  plus one monkeypatch-seam update in `test_structured_output.py` with no assertion changed),
  390 → **407** in increment B (one new file), and 407 → **436** in increment C (one new file),
  and 436 → **478** in Phase 3 item 5 (one new file, plus the one existing test recorded in
  that item's section — the first time an existing test was edited *because the cache made two
  identical runs non-independent*, not because behaviour was being pinned).
  In Phase 2,
  four *path assertions* across three pre-existing tests were updated because the output layout
  itself changed (`outputs/<job_id>/` → `outputs/<profile_id>/<job_id>/`); their assertions
  about content are unchanged.
- `tests/test_renderers_documents.py` renders **real** LaTeX and DOCX.
- `tests/test_cli.py` asserts the CLI's page count equals `render_application.py`'s.
- `tests/test_api.py` asserts the API resolves like the CLI: **16 of its 20 tests fail
  against the pre-close-out `main.py`**, verified by stashing the fix.
- `tests/test_profile_serialization.py` (Phase 3 increment 1) asserts the profile is
  serialized once per application and that the prompt bytes are unchanged: **11 of its 16
  tests fail against the pre-increment code**, verified by stashing the change.
- `tests/test_editorial_instructions.py` (Phase 3 increment 2) asserts the merged
  requirements reach the CV call only, that the gate is unchanged, and that the call counts
  are 2/3/5: **9 of its 11 tests fail against the pre-increment code**.
- `tests/test_layout_retry.py` (Phase 3 increment 1 of the agreed order): **13 of its 15 tests
  fail against `2a7632d`**, verified in a throwaway worktree of that commit (not by stashing).
- `tests/test_structured_output.py` (Phase 3 increment 3): **13 of its 27 tests fail against
  `85879b5`**, verified in a throwaway worktree.
- `tests/test_provider_interface.py` (item 6, increment A): **39 of 39 fail against `23156b1`** —
  the whole interface is new. Imports the new module defensively and **fails** rather than skips
  when it is absent, so a broken import in the real tree cannot hide behind a skip.
- `tests/test_pricing.py` (increment B): **17 of 17 fail against `23156b1`**. Same defensive
  import, same reasoning.
- `tests/test_evaluation_suite.py` (increment C): **29 tests, 0 skips in the real tree.** They
  also pass against `23156b1` with 2 skipped — stated plainly: the evaluation suite and the
  curated set are new code with no predecessor, so there is no old behaviour to fail against.
  The file guards the new code's *properties* (offline by default, cap fails closed, out of CI,
  unmeasured markers, rates match the listing) rather than diffing behaviour.
- `tests/test_generation_cache.py` (Phase 3 item 5): **37 of its 42 tests fail against `def7fe0`**
  once its own defensive import guard is neutralised, verified in a throwaway worktree. The file
  imports `services.cache_store` defensively and **fails** (not skips) when it is absent, so
  against `def7fe0` it errors at collection — the correct outcome for a new module, stated rather
  than hidden.
- `cvtailor render` needs no API key; `cvtailor doctor` checks the key for *presence* only
  unless `--verify-key` is passed.
- Backend `import main` ≈ **1.9 s**; `load_profile()` ≈ **169 ms**.
- LLM calls per application: **2 min / 3 typical / 5 max-successful / 12 worst** (was 3/4/6/18
  before increment 2). **Unchanged by increments 1 and 3 of the agreed order**, **unchanged
  by all three of item 6's increments**, and **unchanged by item 5 on a cold cache** — the
  provider interface adds routing, the pricing fix adds no request, the evaluation suite is not
  in the pipeline, and the cache adds a lookup and a write rather than a request.
- LLM calls on a **cache hit**: **0** (item 5). A hit also reports **zero** tokens and $0.00,
  rather than replaying the original run's totals; the originals are kept as `original_usage`.
- Estimated cost per application (`gemini-3.8-flash`): **$0.016 / $0.026 / $0.048**. Re-derived
  on 2026-10-26 under the new tiered, route-aware accounting: $0.01559 / $0.026482 / $0.048265 —
  **identical**, because `gemini-3.8-flash` has no long-context tier and its prompts are ~6.4k
  tokens, far below the 200k threshold. D-3 changes the models where it mattered.
- Pricing verified against ai.google.dev on 2026-10-23 and against **OpenRouter's own listing on
  2026-10-26** (467 models, SHA-256 `64B4A173A08F7027DD2F04778A85C5B5EFC4097331CF1529B502CBE249092BC7`).
  Each route's date and source are recorded in `pricing.PRICE_SOURCES` and asserted by a test.
  **Item 6 changed no provider and no default model** — decision 6 stands.

---

## Blockers and unresolved issues

1. **`GEMINI_API_KEY` is not set in this worktree's `.env`.** `cvtailor doctor` reports it as
   the only real blocker. The owner must enter it directly — never paste it into a chat. Live
   generation in this worktree is blocked until then; rendering, the CLI and all tests are not.
   **Item 6 adds a second, related gate:** the evaluation suite's paid path needs
   `OPENROUTER_API_KEY` (for an OpenRouter run) and explicit owner authorisation of the method
   and budget. It is refused before the first call without both.
2. **The already-published personal data is still public.** Untracking stopped *future*
   exposure; it did not un-publish anything. `storage/profile/profile.yaml` — name, email,
   mobile, city, immigration status, employment history — and the 64 application files remain
   in the public repository's **history**, retrievable by anyone who clones it. Removing them
   requires a history rewrite and a force-push, which
   [ADR 0011](DECISIONS/0011-private-store-location.md) records as **separate and not yet
   approved**. New data for any candidate is safe from here on.
3. **A-6: dates are still unvalidated strings.** Deferred out of the Phase 2 increment. Two
   existing tests deliberately pin the current wrong behaviour
   (`test_start_date_is_not_validated_yet`, `test_reversed_date_range_is_not_validated_yet`);
   they are tripwires to be inverted when the validation lands, not endorsements. **This is the
   most important item still outstanding after the close-out.**
4. **The private store is not backed up beyond its own Git history.** It is a local repository
   with no remote. Losing `D:\coding\cv-tailor-data` loses every profile.
5. **Sandbox caveat:** under the DSH `workspace-write` sandbox, pytest's `tmp_path` tests error
   on ACL operations, and this session additionally saw the venv Python denied **write** access
   to `outputs/` and `storage/profile/profile.yaml` while PowerShell could write both. That is
   an environment artifact, not a code fault — recorded in [`TESTING.md`](TESTING.md).
   `git commit` in this worktree needs unconfined access, because its git metadata lives in
   `D:\coding\cv-tailor\\.git`, outside the sandbox.
6. **`docx_renderer.py:304-307` mutates the caller's model** — verified real bug, still
   unfixed and **still untested** (deliberately: pinning it would bless it). Its practical
   impact is bounded by `test_docx_contains_every_body_paragraph`.
7. ~~**`backend/main.py` has no tests, and it bypasses the store.**~~ **RESOLVED 2026-10-26**
   (`a0b431c`). It called `load_profile()` with no argument, which reads the pre-Phase-2 default
   `storage/profile/profile.yaml`. On this machine that stale duplicate still existed and was
   byte-identical to the store's copy, so `/api/tailor` *appeared* to work while silently
   ignoring the store — the most dangerous shape of the bug. `/api/tailor` and the three
   download routes now take an explicit `profile_id`, resolve through the store, and fail
   closed; the download routes no longer use `config.outputs_dir` (that is the optional
   *mirror*, and it omitted the candidate segment, so they could not find a document the
   pipeline had just written). `tests/test_api.py` adds 20 tests. **Keep it this way**: the API
   must resolve identity exactly as the CLI does, and `ProfileStoreError` must stay mapped to a
   400 — it is deliberately not a `ValueError`, so an `except ValueError` clause will not catch it.
8. **`render_application.py` and the CLI's `render` now duplicate render logic.** The CLI's
   `render` does not yet add the `\needspace` project-heading pagination tweak that the script
   applies, so a CV that depends on that tweak could paginate differently. Tracked below.

### Resolved in Phase 2

- ~~Both candidates sharing one profile file~~ — `ProfileStore` keyed by `profile_id` (A-9's
  root cause), and `profile_id` fails closed.
- ~~Two candidates colliding on one `outputs/` folder~~ — the candidate segment is now part of
  the path, and of the mirror path.
- ~~A draft validated against whichever profile happened to be loaded~~ — the supplied profile
  is checked against the id's stored profile before anything is generated.
- ~~Real personal data committed to the public repository (ADR 0002)~~ — untracked, gitignored
  and migrated to the private store. **Caveat:** already-published history is unchanged; see
  blocker 2. D-9 is resolved by the same change.
- ~~A hardcoded `storage/profile/profile.yaml` in scripts and the CLI~~ — all call sites resolve
  through the store or an explicit `--profile`.
- ~~Generated documents written into the repository's `outputs/`~~ — found while auditing the
  docs: `ApplicationStore` was still rooted at `PROJECT_ROOT`, so a real CV landed in the
  public repository's gitignored `outputs/`, contradicting ADR 0011. Now rooted at the store's
  per-candidate outputs directory, with a regression test that fails if it moves back.

### Resolved in the Phase 2 close-out (2026-10-26)

- ~~The API resolves a profile by default and bypasses the store~~ — `/api/tailor` called
  `load_profile()` with no argument. Now takes an explicit `profile_id`, resolves through the
  store, fails closed, and is tested (blocker 7).
- ~~The download routes cannot find a generated document~~ — they used `config.outputs_dir`
  (the optional mirror) and omitted the candidate segment. Now
  `<store>/outputs/<profile_id>/<job_id>/`, with `job_id` validated against
  `^[A-Za-z0-9_-]+$`.
- ~~`backend/validate_profile.py`~~ — 86 lines, unreferenced, hardcoding the dead
  single-profile path. Removed.
- ~~`Config.LEGACY_PROFILE_PATH` / `DEFAULT_PROFILE_PATH`~~ — self-referential aliases nothing
  read. Removed.

### Resolved in Phase 1

- ~~Dead code: `validate_api_key`, `create_gemini_service`, `ErrorResponse`, `TailoredOutput`~~
  — removed (D-2, D-7). `response_schema` was removed here too, as dead code (D-1), and was
  **made live again** in Phase 3 increment 3, scoped per call — see
  [ADR 0012](DECISIONS/0012-structured-output-scope.md).
- ~~Import-time env reads~~ — `Config` object, guarded by a test (A-5).
- ~~296-line `tailor_documents`~~ — split into `generation` + `application_store` (A-3).
- ~~Candidate-specific rules hardcoded in the validator~~ — now profile-scoped (A-1).
- ~~No CLI~~ — `cvtailor` with four commands (ADR 0007).
- ~~Nested `tailoring_explanation` silently yields `None`~~ — fixed and tested.
- ~~Two `_escape_latex` and three `_slugify` copies~~ — consolidated into `utils/text.py` (D-12).
- ~~Stale pricing rows and unused dependencies~~ — pruned, with the model/prices verified (D-5, D-6).

---

## Known-important findings (do not lose)

- **The OpenRouter catalogue must not be exposed wholesale (owner requirement, 2026-10-26).**
  OpenRouter fronts a very large number of models (467 when verified on 2026-10-26); the tool
  carries a **small curated set spanning different performance and cost levels**. See
  [ADR 0005](DECISIONS/0005-llm-provider-interface.md) §"Model curation" and
  [ADR 0014](DECISIONS/0014-evaluation-suite-and-curation.md). **Implemented in item 6, with the
  quality ranking explicitly NOT claimed**: five models, each marked `verified="price+capability"`,
  none `measured`. A test fails if any entry claims a measured ranking, so the marker cannot drift
  ahead of the evidence.

- **The curated set's ranking is unmeasured, on purpose, and this is the honest state.** A model
  that tops a general leaderboard is not thereby fit for this task — the bar is a two-page CV that
  passes the factual gate, keeps every employer and date, meets the 290–310-word letter budget and
  returns schema-valid JSON. Cost must be judged per **accepted** result, because a cheap model
  that fails validation and burns three correction calls is not cheap. The suite that measures
  this exists and is offline by default; running it needs authorisation, not code.

- **Structured output's behaviour on real documents is still unverified.** Increment 3 proved
  offline that a truncated constrained response is *rejected* rather than parsed short, and
  designed the schema to protect against truncation — but made no paid call. **Item 6 did not
  change that**: it preserved the contract (including `schema=None` reaching both providers) and
  built the suite that would answer it. The budgeted live run is the remaining step.

- **A price without a named route is ambiguous.** OpenRouter lists `google/gemini-3.8-flash` at
  **$0.825/$4.125** per 1M while Google charges **$0.75/$3.75** direct (both verified from the
  providers' own listings). The pricing table is therefore keyed by `(provider, model)`, and each
  route records the date and document its prices came from. Do not add a row without one — a test
  requires it.

- **`schema=None` must keep meaning "send no constraint".** The layout retry's response may be a
  delta of unit ids with no document key, which a schema requiring `cv` cannot express. The
  provider layer receives `None` and passes it through on both providers; a provider that decided
  for itself would be a second, weaker gate on the same question.

- **`ProviderError` must not become a `ValueError`.** The pipeline's correction loop catches
  `ValueError`; a provider outage classified as one would burn three paid calls re-asking a
  question the provider never answered.

- **The budget cap fails closed, and a missing cap is a refusal — not "unlimited".** A malformed
  `CVTAILOR_MAX_COST_USD` is a `ConfigError`. An evaluation plan whose *projection* exceeds the cap
  is refused **before** the provider is built, and the cap is re-checked before every call rather
  than once at the start.

- **Nothing under `evaluation/` may be named `test_*`.** That is what keeps the paid path out of
  CI; a test asserts it and asserts that the CI workflow does not invoke the suite.

- **Structured output is scoped per call, and the scope is load-bearing — do not "simplify"
  it into a global JSON mode.** The CV draft and the cover letter send
  `response_mime_type="application/json"` plus a `response_schema`; the layout retry and any
  unknown document kind send **neither**. The retry is excluded because its response may be a
  **delta** of unit ids, which a schema requiring `cv` cannot express. The schema requires the
  **envelope** key and leaves the document body open (no `required` inside it, no
  `additionalProperties: false` anywhere) because a strict body is what truncated long
  responses and got the first implementation deleted (D-1). See
  [ADR 0012](DECISIONS/0012-structured-output-scope.md) and `tests/test_structured_output.py`.

- ~~`.github/copilot-instructions.md` describes a **different system** (Tectonic,
  `gemini-1.5-flash`, a non-existent `/api/preview` endpoint)~~ — resolved in `c3839da`: it is
  now a short pointer to `AGENTS.md` (D-8). **Keep it that way**: one set of project
  instructions, tool-independent. Do not let a second instruction file grow back. Re-confirmed
  unchanged on 2026-10-26.
- ~~Generated PDFs/DOCX are **tracked** in `outputs/` despite `.gitignore` (D-9)~~ — resolved in
  Phase 2 by untracking `outputs/` (ADR 0011). The three PDFs/DOCX and the `.gitkeep` are gone
  from the index. Generated documents are written into the private store's
  `outputs/<profile_id>/<job_id>/`; the repository's own `outputs/` now holds only `.gitkeep`.
  **Re-verified 2026-10-26:** `git ls-files outputs` → `outputs/.gitkeep` only, so no further
  untracking was owed. Three untracked pre-Phase-2 PDFs/DOCX were still sitting on disk in
  `outputs/`; they were deleted after each was confirmed byte-identical (SHA-256) to its copy
  in the private store.
- `initial_generation_result.json:4-6` leaks absolute local paths incl. a third-party name
  (D-10). **Untracked** with the rest of `applications/`, so it cannot be re-committed, but
  still present in public history. **Owner decision 2026-10-26: leave history as-is.** This is
  the accepted limitation ADR 0011 records; no rewrite or force-push is approved.
- **D-11 (inconsistent saved-application schemas) moved from Phase 2 to Phase 5** by owner
  decision on 2026-10-26; [ADR 0009](DECISIONS/0009-interfaces-and-archive.md) carries the
  amendment. The archive is private data now, and Phase 5 owns application schemas.
- **`profile_id` is resolved before any paid work, on purpose.** A missing or unknown id must
  cost nothing and leave no folder behind. If you reorder `tailor_documents`, keep the
  resolution first — a test asserts no API call happens when it fails.
- **`ApplicationStore` appends the candidate segment itself.** Pass it the *parent* of
  `ProfileStore.outputs_dir(profile_id)` — that method already ends in the id, so passing it
  directly nested the id twice (`<store>/outputs/<id>/<id>/<job_id>`) and broke the documented
  layout silently. A regression test pins the exact relative path.
- **`Config.profile_path` and `Config.profile_id` are different things and only one may be
  set.** `profile_path` means "the caller named a file" and deliberately bypasses the store
  lookup; `profile_id` means "look it up". Code that sets both is a bug.
- **`conftest` supplies `CVTAILOR_PROFILE_ID` and a synthetic store suite-wide.** That is why
  32 pre-existing tests did not need editing. `tests/test_profile_store.py` removes both
  again in its own autouse fixture, because it asserts the *absence* of an id.
- **Removing a stale pricing row is only safe while the fallback target still exists.** The old
  fallback was `PRICING["gemini-1.5-flash"]`, so deleting that row would have raised `KeyError`
  for any unlisted model. The fallback is now `PRICING[DEFAULT_MODEL]`, and a test asserts
  `DEFAULT_MODEL in PRICING`. Keep that invariant when editing the table.
- **A tool named in `rules.banned_tools` must not count as evidence the candidate used it.**
  The check serializes the profile with the `rules` block excluded; without that, declaring a
  tool banned would silently un-ban it.
- **The generation cache's key is the bytes the model was shown, and it is derived from one
  string.** `cache_store.serialize_profile_bytes(profile)` produces the profile bytes; that same
  string is emitted into the prompt context **and** hashed into the key. Do not "simplify" this
  into two derivations — if the hashed bytes and the sent bytes can differ, a prompt change can be
  served from cache and nobody would see it. `job_id` and timestamps must stay out of the key:
  `make_job_id` embeds a millisecond timestamp, so keying on it would miss every time.
- **The prompt files are hashed per call on purpose.** `prompt_version=_source_digest(PROMPT_CV_PATH)`
  reads and hashes the file rather than trusting a `PROMPT_VERSION` constant, because the failure a
  constant produces is silent: the user is served a document drafted under rules that no longer
  exist. Do not replace it with a hand-bumped constant.
- **Only a validated result may be cached, and the write site is load-bearing.** The entry is
  written after the page-count gate and nowhere else. Moving that write earlier would turn a failed
  layout loop into a permanent answer; a test counts entries *during* rendering so the move cannot
  happen unnoticed.
- **A cache read never raises and never writes.** Missing, malformed, truncated,
  wrong-format-version, no-longer-validating and wrong-shape entries are all **misses**. A stored
  document is re-validated through `DocumentGenerator.restore` — the same `_build_model` a fresh
  draft uses — because the cache is an editable file on disk, not a guarantee. Do not add an
  `except`-free path here or a delete-on-read.
- **A cache hit reports zero usage, not the original run's totals.** Pricing a run that made no
  call is the dishonesty this item exists to remove; the originals live in `original_usage`.
- **`model` is two key ingredients, not one** (`model_cv`, `model_cl`), because item 6's per-task
  routing lets two models serve one posting.

- **The generation cache has no eviction policy — this is a real open follow-up, not an oversight.**
  Nothing prunes `<store>/cache/`; it grows by one small JSON file per distinct generation. Deleting
  the directory is documented as always safe (it is derived data and every entry came from an
  application that was already persisted), and clearing it by hand is the documented mechanism. An
  eviction or size policy is unbuilt; see [ADR 0015](DECISIONS/0015-generation-cache.md).

- **A stored-application folder has no `source/content.json` in one case.**
  `outputs/2026_adjoe_senior_data_analyst_1769343142/` is the D-14 partial-folder case. Do not
  assume `outputs/*/source/` exists.
- `docx_renderer.py:264` writes a `latex_work/` scratch dir inside the deliverable folder (D-13).

---

## Session-start checklist

1. `git rev-parse --abbrev-ref HEAD` → confirm `refactor/architecture-v2`.
2. `git status` → confirm clean; never discard uncommitted work.
3. Read `AGENTS.md`, then this file.
4. Read the relevant section of [`ASSESSMENT.md`](ASSESSMENT.md) and [`ROADMAP.md`](ROADMAP.md).
5. Read `docs/DECISIONS/` for settled choices.
6. `python -m pytest -q` (unconfined) to confirm the baseline still holds.
7. Confirm acceptance criteria for the assigned task; continue from here.

Do **not** re-run the whole assessment unless the architecture materially changed.
