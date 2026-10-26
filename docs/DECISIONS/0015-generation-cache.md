# 0015 — A validated-generation cache keyed by the bytes the model was shown

**Status:** Approved (2026-10-26) — implemented in Phase 3, item 5
**Related:** [0004](0004-storage.md) (the store layout this extends),
[0011](0011-private-store-location.md) (derived data stays out of the public
repository), [0012](0012-structured-output-scope.md) (the per-call schema that
becomes part of the key), [0013](0013-provider-interface-and-routing.md)
(per-task routing, which makes `model` two ingredients rather than one),
[0003](0003-profile-identity.md) (the candidate segment)

## Context

One profile against one posting re-drafted both documents from scratch every time.
Rendering was already free — `scripts/render_application.py` and the CLI's `render`
path contain no LLM call — so the item is about the **generation** path, not the
render path.

Four facts shaped the answer:

1. **Phase 3 item 4 made the profile bytes a single, stable, byte-identical block**
   per application. That is what makes the input keyable at all: before it, the
   profile was serialized per call and there was no one string to hash.
2. **A prompt change must not serve a stale document.** A key that omits the prompt,
   or that relies on someone remembering to bump a version constant, fails this
   silently — the user gets a document drafted under rules that no longer exist.
3. **Only a validated result may be stored.** The generation path has a retry loop
   (3 validation attempts × 4 layout attempts). An entry written before the gate
   would turn a failed loop's last failure into a permanent answer.
4. **Item 6 added model-per-task routing**, so two models can serve one posting. A
   key that knew only "the model" would serve one route's documents for another's.

Item 5's roadmap scope fixed the key's *content* but left its *implementation* open:
which store path, what the entry holds, and what happens on a corrupt or
no-longer-valid entry.

## Decision

**Store validated generations under `<store>/cache/<profile_id>/generations/<key>.json`,
keyed by a digest of the bytes the model was shown.**

| Element | Decision |
|---|---|
| Key | SHA-256 over a named-field JSON payload (below) |
| Named fields | Each ingredient is hashed with its name, so a value cannot be shifted between fields |
| `job_id` in the key | **No** — it embeds `time.time_ns()` milliseconds, so it would miss by construction |
| Timestamp in the key | **No**, for the same reason |
| When an entry is written | After the page-count gate passes, and nowhere else |
| What it holds | The accepted CV and letter, the explanation, the raw responses, the provider, the routed models, and the run's usage |
| On read | The stored documents are **re-validated through the same gate**, at no API cost |
| Location | `<store>/cache/<profile_id>/`, a sibling of `outputs/` (ADR 0011) — **always the store, never the repository**, including when the caller named a loose `--profile <path>` |
| Deletion | Always safe. Any read failure is a **miss**, never an error |
| Bypass | `use_cache=False` (CLI `--no-cache`, API `use_cache: false`) |

### The ingredients

`format_version`, the serialized profile, the job description, company name, role
title, work country, both prompt **files** byte-for-byte, the `PROMPT_VERSION`
digest, the response-schema digest, the provider, the CV model, the cover-letter
model, and the resolved validation rules.

The prompt *files* and `PROMPT_VERSION` are both included deliberately. The version
digest is read from disk per call rather than being a constant a prompt edit could
forget to bump — which is what makes "a prompt change must not serve a stale
document" true by construction rather than by discipline. The rules digest is present
because a `rules:` edit changes validation and the retry brief without changing the
profile block that was sent.

## Why each guard exists

- **The key and the prompt are derived from one string.** `serialize_profile_bytes`
  produces the bytes; the same string is both emitted into the prompt context and
  hashed. Two derivations could drift, and a drift would mean hashing something the
  model was never shown.
- **A hit is re-gated.** The cache is a plain JSON file a person can edit or
  truncate. "It was validated when it was stored" is a claim about the past, and
  `_build_model` costs nothing to run again. A stored document that no longer
  validates (because the profile changed, or the file was hand-edited) is treated as
  a miss and regenerated.
- **Nothing on the read path raises.** A missing, empty, malformed, truncated or
  wrong-format-version entry is a miss. A cache that can break a run that would
  otherwise have succeeded is worse than no cache. The read path also never *writes*:
  a bad entry is not deleted, it is simply not used, and the next generation
  overwrites it.
- **A hit reports zero usage, not the original run's tokens.** Replaying the original
  totals would put a cost on a run that made no call, on the one path where the
  saving is the entire point. The original cost is preserved in the same file as
  `original_usage`, so the information is not lost.
- **A hit still writes a complete job folder**, including the restored raw responses
  as `drafts.json`. The cache replaces the generation, not the persistence: the user
  asked for an application and gets one, with the same audit trail.
- **Writes are atomic** (temporary file, then `replace`), so a crash mid-write cannot
  leave a half-written entry that a later run would read as valid.
- **The candidate segment is in the path** and `profile_id` is validated, so two
  candidates cannot read each other's entries (ADR 0003).
- **The cache is rooted in the store unconditionally — never beside the outputs.** The
  first implementation put it beside `outputs/`, which for a loose `--profile <path>`
  run means `<repo>/cache/`. That was wrong: an entry holds the accepted CV and letter,
  so it is real candidate data; and `<repo>/outputs/` is gitignored while a sibling
  `<repo>/cache/` is **not**, so such a run would have written real documents into the
  public repository's working tree. It was reachable — `evaluation/live.py` drives the
  pipeline with a loose `profile_path`, so the paid live run would have taken that
  branch. The store root is configuration (ADR 0004) and is available either way, so
  there is no case that needs the fallback. Two tests guard it, both verified to fail
  against the original code.

## Consequences

- **Call counts are unchanged at 2/3/5, worst 12, on a cold cache.** Item 5 adds a
  lookup before the first call and a write after the last one; it adds no request.
  Verified by driving the real pipeline, and asserted explicitly by a test that
  checks the cold path writes nothing before the gate.
- **No prompt byte changed**, so the token and cost figures in ASSESSMENT §5 are
  unaffected. A cache *hit* makes the same generation cost $0.
- **A repeat of an identical generation makes 0 LLM calls** and produces
  byte-identical accepted documents — the acceptance criterion.
- **The cache is derived data and deletion is a supported operation.** Removing
  `<store>/cache/` costs a regeneration and nothing else; there is no document that
  exists only in the cache, because every entry was written from an application that
  was already persisted.
- **The cache grows without bound.** Nothing evicts entries. At one small JSON file
  per distinct generation this is acceptable for a single-user tool, and deletion is
  always safe, but an eviction policy is a real follow-up rather than a solved
  problem.
- **Half the item's value is only realised when the profile and posting are truly
  identical.** A user who edits the profile, changes the country, or switches model
  gets a fresh draft by design — that is the invalidation contract, not a cache miss.
- **The evaluation suite and this cache do not interact.** `evaluation/` builds its
  own provider path and does not go through `tailor_documents`, so a live run cannot
  be served from the cache and cannot populate it.

## Alternatives considered

| Option | Why not |
|---|---|
| Key on `job_id` | It embeds a millisecond timestamp, so the same profile and posting produce a different id every run — the cache would never hit |
| Key on a timestamp or a run counter | Same failure, and it would make the cache write-only |
| Hash the `Profile` model instead of the serialized bytes | The bytes sent to the model and the bytes hashed would be two derivations that can drift; a drift means hashing something the model was never shown |
| A hand-maintained `PROMPT_VERSION` constant | The whole risk is a prompt edit that forgets to bump it. Read the prompt files and hash them instead |
| One key for the whole run, ignoring the model | Item 6's routing means one posting can be drafted by two models; the other route's documents would be served |
| Trust the stored documents without re-validating | The file is on disk and editable, and re-validation is free. Deleting the gate here would create the one path where an unvalidated document reaches the renderer |
| Raise when an entry is corrupt | A cache is an optimisation; breaking a run that would have succeeded is a worse outcome than regenerating |
| Delete a no-longer-valid entry on read | Makes a read mutate state, and a read-only store (a mounted or copied cache) would start failing. Overwriting on the next write is enough |
| Report the original run's token totals on a hit | Puts a cost on a run that made no call |
| Put the cache inside `<store>/outputs/` | Anything listing a candidate's applications would start returning cache entries |
| Put the cache beside the outputs when the caller named a loose `--profile <path>` | `<repo>/outputs/` is gitignored but a sibling `<repo>/cache/` is not, so this wrote real accepted documents into the public repository's working tree. `evaluation/live.py` takes exactly this branch, so it was reachable by the paid live run. The store root is available either way, so the fallback bought nothing |
| Evict by LRU or by age | Real complexity (a policy, a clock, a size budget) for a single-user tool where the whole directory is safe to delete. Deferred, and recorded as an open follow-up |
