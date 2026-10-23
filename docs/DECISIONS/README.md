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

**Decisions approved 2026-10-23.** Decisions marked "in principle" or "deferred" are to be
re-confirmed when their phase begins. [0010](0010-config-object.md) was recorded during Phase 1
implementation, because the shape of the config object is expensive to change once the CLI, the
API and the service layer all depend on it.

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
