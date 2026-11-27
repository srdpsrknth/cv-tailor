# PR #1 release verification record

PR #1 merged into `refactor/architecture-v2` at `5af9bbe` on 2026-11-27. [ADRs 0026–0029](DECISIONS/README.md) are approved. This page records the release checks. For the current workflow, start with the [user guide](HOW_TO_GENERATE.md) and [testing commands](TESTING.md).

## Completed checks

- Pulled the integration branch by fast-forward. The earlier local work is preserved in a stash.
- Reviewed the active candidate profile and tested the Windows GUI launch, stop and saved-application review.
- Tested a live Windows generation and a free CV-only revision. Reviewed the two-page CV, one-page cover-letter PDF and saved wording. The application's offline validation passed.
- Confirmed that dismissing suggested claims leaves the profile unchanged. Profile acceptance and backup behavior have synthetic regression coverage.
- Re-rendered three saved applications in disposable folders on Windows. Each CV PDF retained two pages and each cover-letter PDF retained one. The CV checks found preserved text and no clipping or orphan headings. Each application had four matching technology lists across PDF, DOCX and text. The original files passed byte-for-byte verification. The earlier comparison also found differences in dates, section headings and punctuation.
- Ran the read-only saved-application check for one candidate. The failures were confined to the current cover-letter length and paragraph-count rules.
- Verified editable claim confirmation and a real CV revision in a disposable store from the owner's Windows terminal. MiKTeX produced a one-page PDF that passed both extraction checks. The edited wording appears in all three exports, and the original source and cover-letter text were preserved.
- The full Windows suite with MiKTeX passed 1,793 tests with three skipped after the layout-retry test was updated. See [Testing](TESTING.md).
- The owner opened a re-rendered DOCX CV in Microsoft Word and approved the layout.

## Open follow-up

- Decide whether to revise older cover letters flagged by the format checks. Review work-authorization wording separately against the actual country of employment.

The [project checkpoint](PROJECT_STATE.md) tracks this work alongside the other current tasks.
