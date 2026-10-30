# Architecture decision records

Each decision is **Proposed**, **Approved**, **Deferred** or **Superseded**.
Only the owner can move a decision to **Approved**.

| # | Decision | Status |
|---|---|---|
| [0001](0001-architecture-direction.md) | Modular redesign, executed incrementally | **Approved** |
| [0002](0002-privacy-model.md) | Separate public code from private candidate data | **Approved** |
| [0003](0003-profile-identity.md) | Thread an explicit `profile_id`; never default | **Approved** |
| [0004](0004-storage.md) | Files keyed by `profile_id`; local first, no database server | **Approved** |
| [0005](0005-llm-provider-interface.md) | Thin provider interface; Gemini Flash default; benchmark first | **Approved** |
| [0006](0006-remote-profile-access.md) | Local-first store, remote profile access later | **Approved in principle** — deferred |
| [0007](0007-cli-framework.md) | CLI on `argparse` with a friendliness layer | **Approved** |
| [0008](0008-job-sources.md) | Job sources: ToS-compliant APIs first, scraping last | **Approved in principle** — Phase 4 |
| [0009](0009-interfaces-and-archive.md) | Keep FastAPI + Streamlit; `applications/` read-only until Phase 2 | **Approved** |
| [0010](0010-config-object.md) | One explicit `Config` object; no import-time environment reads | **Approved** — implemented |
| [0011](0011-private-store-location.md) | Private store is a sibling repo; untrack real data, do not rewrite history | **Approved** — Phase 2 |
| [0012](0012-structured-output-scope.md) | Structured output scoped per call; schema constrains the envelope, not the document body | **Approved** — Phase 3 increment 3 |
| [0013](0013-provider-interface-and-routing.md) | Thin provider interface; Gemini default, OpenRouter second; model-per-task routing; optional budget cap | **Approved** — Phase 3 item 6 |
| [0014](0014-evaluation-suite-and-curation.md) | The live evaluation suite stays opt-in and budget-capped; curation is a shortlist until measured | **Approved** — Phase 3 item 6 |
| [0015](0015-generation-cache.md) | Cache validated generations, keyed by the bytes the model was shown; only a validated result is stored, and the store is always safe to delete | **Approved** — Phase 3 item 5 |
| [0016](0016-per-candidate-inputs-and-one-winner.md) | One schema and prompt per candidate, judged on cost per accepted result; the study selects one model rather than shipping a menu | **Approved** — Phase 3 item 6, discharged 2026-10-27 |
| [0017](0017-curation-skill.md) | Curation is a procedure with two human steps: detection reports and cannot spend, the proposal is inert, and a candidate is ineligible without the owner's own writing/PDF/layout verdict | **Approved** — curation-skill items, 2026-10-30 |

**Decisions approved 2026-10-23.** Decisions marked "in principle" or "deferred" are to be
re-confirmed when their phase begins. [0010](0010-config-object.md) was recorded during Phase 1
implementation, because the shape of the config object is expensive to change once the CLI, the
API and the service layer all depend on it.

**Decisions approved 2026-10-24.** [0011](0011-private-store-location.md) was confirmed by the
owner at the start of Phase 2, before any code was written. It records three separate choices: the
private store's location, migrating the real profile/applications/outputs out of the public repo,
and the explicit decision **not** to rewrite history — so the data already published remains
published until a history rewrite is separately approved.

**Decision recorded 2026-10-26.** [0012](0012-structured-output-scope.md) was recorded during
Phase 3 increment 3, because it decides *where* structured output applies and *how strict* the
schema is. Both are expensive to change once a live evaluation depends on them, and the strictness
choice is the one that separates this increment from the change D-1 removed for causing
truncation.

**Decisions recorded 2026-10-26 (Phase 3 item 6).** [0013](0013-provider-interface-and-routing.md)
discharges the interface [0005](0005-llm-provider-interface.md) deferred, and records three choices
that are expensive to reverse: that `schema=None` means "send no constraint" and reaches the
provider as such; that there is **no** fallback between providers or models; and that a provider
failure is not a `ValueError`, because the correction loop catches `ValueError`.
[0014](0014-evaluation-suite-and-curation.md) records that the live evaluation stays opt-in,
budget-capped and out of CI, and — the part that matters most — that **the curated set's quality
ranking is unmeasured and is marked as such**, rather than inferred from price, reputation or a
general leaderboard. Both were written during implementation because the alternatives are either
unsafe (a silent provider fallback) or dishonest (a ranking presented as researched when it was
assumed).

**Decision recorded 2026-10-26 (Phase 3 item 5).** [0015](0015-generation-cache.md) records that
the generation cache is keyed by **the bytes the model was shown** — the serialized profile, the
posting plus company/role/country, both prompt files, the schema, the provider and both routed
models — and not by a `job_id` or a timestamp. Three parts are hard to reverse: that only a
**validated** result is ever stored (an entry written before the gate would make a retry loop's
failure into a permanent answer); that the key includes the **prompt files themselves**, read and
hashed per call, so a prompt edit cannot serve a stale document even if nobody bumps a constant;
and that the store is **derived data whose deletion is always safe**, so every read failure is a
miss rather than an error. `model` is two ingredients rather than one because item 6's
per-task routing lets two models serve one posting.

**Decisions recorded 2026-10-30 (the curation skill).** [0017](0017-curation-skill.md) answers
the ten clarifying questions owed before any curation-skill code, and records four choices that
are expensive to reverse: that **detection reports and cannot spend** (a provider's routine
catalogue churn must not be able to trigger a run — the catalogue moved twice in four days);
that the **proposal is inert**, because a measurement that covers none of prose, rendering or
layout must not be able to replace the model production uses; that **a candidate is ineligible
without the owner's own writing/PDF/layout verdict**, enforced in code rather than documented;
and that the **screened listing record is committed** while the raw payload is not, so a price
can be checked by anyone without a re-fetch. [0016](0016-per-candidate-inputs-and-one-winner.md)
is listed above for the first time — it was recorded on 2026-10-26 and omitted from this table.

## Owner's stated preferences (recorded verbatim in intent)
- Profiles should be reachable **from any machine** where cv-tailor can be installed, given
  internet — satisfied by [0006](0006-remote-profile-access.md), not by committing data.
- Storage: **start local**, add internet access later.
- CLI must be **user-friendly and easy to use**.
- Keep FastAPI + Streamlit; reassess at Phase 6.
- LLM: benchmark cost, performance and output quality before switching; **keep Gemini's
  latest Flash model as default**.
- Job sources: research ToS-compliant APIs first; scraping may be necessary for coverage;
  determine full scope at that phase.
- `applications/`: migrate in Phase 2; keep read-only until then.

Add a new record for every decision that is expensive to reverse. Keep each one short:
context, decision, consequences.
