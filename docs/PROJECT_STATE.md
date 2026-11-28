# Project state

- **Updated** 2026-11-28
- **Integration branch** `refactor/architecture-v2`
- **Stable branch** `master`

## Current work

- PR #1 is merged. ADRs 0026-0029 are approved. The release's Windows document verification is complete. See the [verification record](HANDOFF-PR1-VERIFY.md).
- The integration branch includes shorter-bullet guidance, an overflow retry budget based on visible editable prose, a PDF warning for bullets spanning three or more lines, and one combined Technologies list per role across PDF, Word and text.
- Editable suggested claims and same-application CV revisions are in the Windows working tree. Claim confirmation is local. Optional paid drafting previews wording for review. Saving a confirmed claim to the profile and approving a CV revision are separate actions.
- The owner reviewed the pre-PR #1 stash and decided to proceed without restoring it. The stash is still available locally.
- **UI redesign (branch `ui/redesign`, cut from `refactor/architecture-v2`).** Research and mock-ups are complete. The owner chose:
  - the "Bench" layout with the Proof Desk palette
  - Svelte 5 served by FastAPI, with a version 1 scope
  - the UI labels "Suggested additions", "Profile changes", "Cost and model" and "Tailoring"

  [ADR 0031](DECISIONS/0031-web-ui.md) and the [build plan](UI_REDESIGN_PLAN.md) are **Approved** (2026-11-28). The [design system](design/DESIGN_SYSTEM.md) is written. No code has changed yet, and Streamlit is unchanged. **Next:** wave 1 of the build plan, which waits on the owner's go-ahead. To resume on another device or with another model, read the [handoff](HANDOFF-UI-REDESIGN.md).

## Verification

- For the dated full-suite results, OS requirements and test commands, use [Testing](TESTING.md).
- The pre-push focused run for the readability and Technologies changes passed 189 tests. One was skipped and 17 LaTeX cases were excluded. The subsequent Windows re-render of three saved applications confirmed matching technology lists in PDF, DOCX and text.
- The suggested-claims enhancement passed 145 focused tests, with one case excluded. The disposable-store check passed with MiKTeX in the owner's Windows terminal. It verified the exact profile backup, original source preservation, and the revised PDF, Word and text exports. The one-page PDF passed both extraction checks. Any live drafting call requires approval.
- The full Windows rerun passed 1,793 tests with three skipped. All three copied CVs retained their two-page layout and all cover letters retained one page. The CV checks detected no clipping or orphan headings, and the original files remained byte-identical. The owner approved a re-rendered CV after inspecting it in Word.

## Where to look next

- [Roadmap](ROADMAP.md) for open priorities and deferred work.
- [Architecture](ASSESSMENT.md) and [decisions](DECISIONS/README.md) for the service boundaries and policy.
- [User guide](HOW_TO_GENERATE.md) and [development setup](DEVELOPMENT.md) for current commands.
- [Documentation archive](ARCHIVE.md) for historical evidence.
