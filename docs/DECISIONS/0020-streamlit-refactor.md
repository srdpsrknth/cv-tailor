# 0020 — Refactor the Streamlit UI onto the services rather than replace it

**Status:** Approved (2026-11-15) — owner decision
**Related:** [0009](0009-interfaces-and-archive.md) (keeps FastAPI + Streamlit; this
confirms the "Streamlit" half and explains the FastAPI half),
[0003](0003-profile-identity.md) (the rule the old UI was bypassing),
[0018](0018-job-discovery.md) (the `job_search` service the new UI reuses)

## Context

Phase 6's first task was to *assess keeping vs replacing Streamlit*. Two options
were put to the owner: replace it with NiceGUI (event-driven, FastAPI-native,
MIT-licensed) or refactor it in place. **The owner chose replacement, and then
reversed that choice to refactoring** after NiceGUI could not be installed in this
environment — `pip` would not resolve its dependency graph here, and the attempt
consumed a substantial amount of time without a working install. The reversal is
recorded because the reasoning matters more than the outcome: the framework was
never rejected on its merits.

## What was actually wrong

`ui/app.py` was one 407-line Streamlit file last modified **2026-10-26**, i.e.
before Phase 2. Measured against every decision taken since:

| Settled decision | State of the old UI |
|---|---|
| ADR 0003 — `profile_id` required, fails closed | Sent **no `profile_id`**. It worked only because this machine's `.env` set one; a second candidate was unselectable and a machine without the variable failed. |
| Phase 3 — provider interface, routing, cost | Hardcoded `gemini-2.5-flash` and kept its **own copy** of the price table. |
| Phase 4 — job search | Nothing. |
| Roadmap acceptance — "reuses the same services as the CLI" | Not met: it was an HTTP client of the backend, with its own logic. |

So the UI was not merely stale — it was **bypassing the architecture's central safety
rule by accident**, and it could not run at all unless a second service happened to
be up.

## Decision

**Refactor Streamlit in place, and route everything through a framework-free service
layer.**

1. **`ui/services_bridge.py` owns every non-presentational decision.** It imports no
   UI framework (a test asserts this by reading the module source), so the logic is
   testable without a browser or a server. This is what makes the roadmap's
   acceptance criterion checkable rather than aspirational.
2. **The candidate is an explicit, fail-closed choice** (ADR 0003). The picker is
   populated from the store, and it says plainly that a choice is required **even
   when only one profile exists** — because the choice is what files the documents,
   and a silent default is exactly the failure that rule prevents.
3. **Generation runs in process**, calling `services.tailor_service` directly. The
   UI no longer depends on the API being up. The API itself stays, because ADR 0009
   keeps it and `/docs` is useful for inspecting a run.
4. **Cost is read from `services.pricing`.** The old UI's own copy had drifted and
   could show a figure the backend disagreed with.
5. **Streamlit is kept**, which confirms ADR 0009's "keep FastAPI + Streamlit" for
   the UI half. No new dependency is introduced.

## What the refactor preserved deliberately

The old UI's genuinely good parts, because they were good for reasons that survive
the rewrite: visible progress during a long generation, a cost breakdown, and
one-click downloads. What was removed was the duplicated logic, not the features.

## Consequences

* **A check that could not have caught this cannot guard it.** A headless screenshot
  of a Streamlit app shows the skeleton loader **even when the app works**, because
  the page is drawn over a websocket. This was confirmed against a control page
  rather than assumed. Verification therefore uses `streamlit.testing.v1.AppTest`,
  which genuinely executes the script — and it immediately found a fatal
  `st.navigation` bug that no screenshot could have revealed.
* **Two pre-existing guards were strengthened rather than deleted.** The
  "no second pricing table" guard now scans all of `ui/` (the code it guards moved,
  so the check followed it), and the work-country guard asserts against the call the
  UI actually makes instead of a removed HTTP body.
* **Test isolation needed the environment, not patching.** `get_config` is decorated
  with `@st.cache_resource`, which caches **per process**; patching the module
  attribute does not reach the copy the script builds, so the empty-store and
  corrupt-profile cases were silently re-rendering the first test's store. They now
  set `CVTAILOR_STORE` (the supported mechanism) and clear the cache.
* **The CLI remains the supported path for anything that breaks**, because it has no
  websocket, no session state and a clear exit code.
