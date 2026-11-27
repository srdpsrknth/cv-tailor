# Roadmap

Use [Project state](PROJECT_STATE.md) for the current checkpoint and [Testing](TESTING.md) for verification commands. [Architecture decision records](DECISIONS/README.md) record which decisions the owner has approved.

## Current milestone checklist

1. **Windows document verification complete.** The full offline suite, three saved-application re-renders and visual inspection in Microsoft Word passed. The owner decided to leave the pre-PR stash unapplied. See the [PR #1 verification record](HANDOFF-PR1-VERIFY.md).
2. **Review editable suggested claims before publishing.** Local confirmation and a same-application CV revision passed with a real PDF compile. Live drafting remains optional and requires approval before a paid provider call.
3. **Verify the Windows–Mac store pilot.** Use the [synthetic pilot](PRIVATE_STORE_SYNC.md) to test two-way rendering and transfer, partial arrivals, and conflict recovery. Review the evidence before proposing a real-store migration. Keep credentials and per-machine settings local.

PR #1 is merged and the decisions in ADRs 0026–0029 are approved. Older completion details are available in the [documentation archive](ARCHIVE.md).

## Deferred work

| Area | Next decision |
| --- | --- |
| Job search | Write a design ADR before implementation. [ADR 0030](DECISIONS/0030-job-search-redesign.md) holds the requirements for sources, eligibility, missing fields, ranking and filters. |
| Application management | Design lifecycle tracking, notes, deadlines and document versions. Include a migration plan for reviewed application archives under [ADR 0009](DECISIONS/0009-interfaces-and-archive.md). Review and rendering are available today. |
| Hosted use | Decide the deployment and authentication model and the long-term FastAPI role before exposing the local app. [ADR 0020](DECISIONS/0020-streamlit-refactor.md) records the UI decision. |
| Localisation | Design translated UI and document labels around the existing section labels. |
| Saved-application checks | Decide whether to add generation's country-specific work-authorization checks to `applications check`. |
