# CV Tailor architecture

This is the current architecture overview. See the [roadmap](ROADMAP.md) for planned work, the [project checkpoint](PROJECT_STATE.md) for verification status, and the [archive](ARCHIVE.md) for the Phase 0 assessment and later audits.

## Interfaces and services

| Responsibility | Entry point |
| --- | --- |
| Command-line setup, lookup, generation, rendering and review | [`cvtailor.py`](../cvtailor.py) and [CLI commands](../backend/cli/main.py) |
| Local UI, candidate choice, saved application review and job discovery | [Streamlit application](../ui/app.py) and [service bridge](../ui/services_bridge.py) |
| HTTP tailoring, health and candidate-scoped artifact access | [FastAPI application](../backend/main.py) |
| Configuration, selected provider, cost limits and model routing | [Configuration](../backend/config.py) and [provider adapters](../backend/services/provider.py) |
| Generation, profile-grounded validation, layout retries and caching | [Tailoring service](../backend/services/tailor_service.py), [pipeline](../backend/services/pipeline.py) and [validation](../backend/services/validation.py) |
| Saved applications, previews, provenance and offline checks | [Application storage](../backend/services/application_store.py) and [review](../backend/services/application_review.py) |
| Portal answers and candidate-confirmed facts | [Portal answers](../backend/services/portal_answers.py) and [claim acceptance](../backend/services/claim_acceptance.py) |

## Data and document flow

CLI, API and services require a resolved candidate ID for candidate-scoped work. The GUI can restore the last usable profile or select the sole usable profile, then passes its ID explicitly to services. See [ADR 0003](DECISIONS/0003-profile-identity.md) and [ADR 0022](DECISIONS/0022-gui-profile-memory.md).

The private store contains `profiles/<profile_id>/profile.yaml` and `outputs/<profile_id>/<job_id>/`. A run keeps editable content, posting text, profile snapshot and provenance in its `source/` directory. Older curated archives under `applications/` follow a separate restore workflow. Keep real candidate data in the private store and machine-specific credentials in local configuration. See [ADR 0011](DECISIONS/0011-private-store-location.md).

Generation sends the selected profile evidence and posting to the configured provider. The pipeline validates the output, tries local PDF layouts, and requests an editorial retry only if the layout overflows. Cache keys include profile and prompt inputs and a pipeline fingerprint. Re-rendering saved text, checking saved applications and reviewing claims locally require no model call. See [ADR 0025](DECISIONS/0025-adaptive-cv-layout.md), [ADR 0026](DECISIONS/0026-profile-grounded-tailoring.md), and [ADR 0029](DECISIONS/0029-pipeline-fingerprint-cache-key.md).

The standard CV PDF uses LaTeX. Autofill Word and text use their own sequential layout. PDF extraction checks are advisory, and Word pagination needs a separate check. Claim suggestions require human confirmation before they become profile facts. See [ADR 0024](DECISIONS/0024-document-quality-and-artifact-freshness.md) and [ADR 0028](DECISIONS/0028-confirm-first-suggested-claims.md).
