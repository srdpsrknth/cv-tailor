# Documentation archive

Use the [user guide](HOW_TO_GENERATE.md) for current workflows, the [architecture overview](ASSESSMENT.md) for the code structure, and the [roadmap](ROADMAP.md) for open work.

| Record | Why it is retained |
| --- | --- |
| [Phase 2 handoff](HANDOFF-PHASE-2.md) | Rationale and hazards from the move to a multi-candidate private store. |
| [PR #1 release verification](HANDOFF-PR1-VERIFY.md) | Evidence and follow-up checks for the multi-candidate cleanup. |
| [Product audit](PRODUCT_AUDIT.md) and [GUI review](GUI_REVIEW.md) | Original findings and acceptance criteria behind the application workspace. |
| [Application quality audit](APPLICATION_QUALITY_AUDIT.md) and [CV layout review](CV_LAYOUT_REVIEW.md) | Evidence and trade-offs behind the review, typography, and pagination decisions. |
| [Job-source findings](analysis/job-sources-research.md) and [LinkedIn MCP research](analysis/linkedin-mcp-research.md) | Dated source research. The current redesign requirements are in [ADR 0030](DECISIONS/0030-job-search-redesign.md). |

## Phase 0 assessment

The original assessment identified implicit candidate selection, data mixed with public code, configuration tied to the process environment, and generation logic coupled to one provider. The settled responses are in [ADR 0001](DECISIONS/0001-architecture-direction.md), [ADR 0002](DECISIONS/0002-privacy-model.md), [ADR 0003](DECISIONS/0003-profile-identity.md), [ADR 0010](DECISIONS/0010-config-object.md), and [ADR 0013](DECISIONS/0013-provider-interface-and-routing.md). The full assessment and completed roadmap phases remain in Git history.

The public [project checkpoint](PROJECT_STATE.md) uses portable examples and excludes candidate details. Keep machine- and candidate-specific history privately. Removing material from current files leaves earlier Git history intact.
