# Application quality audit

Date: 2026-11-17. Scope: generated CVs and cover letters, their templates,
prompts, validation and generation instructions. This is a recommendation record;
it does not change generation policy, templates or existing applications.

**Implementation follow-up:** the owner approved implementation after this audit.
Readable layouts, explicit spaces, freshness records, extraction checks and Word
pagination are implemented in [ADR 0024](DECISIONS/0024-document-quality-and-artifact-freshness.md).
The observations below describe the pre-change artifacts. Current verification
and remaining limits are recorded at the top of [PROJECT_STATE.md](PROJECT_STATE.md).

## Conclusion

The current cover-letter design is a good base: single-column business-letter
structure, restrained navy accent, clear sender/recipient/subject and readable body.
The primary CV is visually coherent but compresses substantial content into 9pt body
text and small metadata. The Word autofill companion is easier to extract but is
not yet a polished two-page alternative. Improve these CVs before adding decoration.

No universal ATS compliance standard or acceptance guarantee was established.
Separate document parsing, qualification matching, application-question rules and
human editorial review. Each has its own failure modes.

Personal examples, filenames, extraction evidence and page images are retained in
the private store at `reviews/<profile_id>/full-audit-2026-11-17/REPORT.md`.
Do not copy this evidence or real candidate documents into this public repository.

## Verified scope and limits

- Inspected all 28 top-level PDFs across 13 application folders with pdfplumber;
  the inventory includes historical and alternate artifacts, not 28 current submissions.
- Visually inspected page images for five representative application folders,
  including older and current cover-letter layouts and an alternate CV.
- Converted three current cover-letter DOCX files and their three Word CV
  companions with LibreOffice, inspected all resulting pages. Letters: one page
  each. CV companions: three pages each. One splits an education entry.
- Compared pypdf and pdfplumber extraction for representative documents. The
  primary LaTeX CVs and current letters rely on positioned glyphs without explicit
  space characters. pypdf reconstructs readable prose; pdfplumber defaults merge
  many words, while `x_tolerance=1` recovers spacing. This is parser sensitivity,
  not proof that a named ATS rejects these documents.
- Read current prompts, renderers, validation, generation guide, application skill,
  private style preferences and prior voice audit. Two smaller-model reviewers
  independently reviewed instructions and sampled content versus postings.
- Full offline baseline: **1209 passed, 3 skipped**, one existing Google SDK
  deprecation warning, 148.17 seconds. No production code changed.
- No new paid generation, actual portal upload/submission, recruiter assessment,
  AI-authorship detector, Word desktop rendering or hiring-outcome experiment.

## Recommended order

| Priority | Change | Reason and acceptance evidence |
|---|---|---|
| P0 | Identify current reviewed deliverables and stale files | Template fixes do not update old artifacts. Several saved letters still use the old heading/footer. Record source revision, renderer/template version and artifact hashes; flag stale artifacts before download. Preserve manual aliases. |
| P0 | Add extraction diversity | Compare normalized words and required fields with source content using at least two extraction engines. Test contact details, complete titles/dates, education, skills and reading order. Report differences rather than an invented ATS score. |
| P0 | Make Word CV pagination explicit | It is currently an autofill aid, not a verified two-page CV. Add a rendered page-count result and warning. Design a two-page candidate using the same reviewed claims; avoid silently shortening it differently. |
| P1 | Increase primary CV readability | Trial 10.5–11pt dark body text, 9.5–10pt metadata, roughly 15–18mm margins. Reduce duplication and low-relevance material before reducing font size. Verify actual rendered sizes. |
| P1 | Simplify skill and role metadata layout | Use ordinary text skills with visible comma separators; remove dependence on 0.1pt white delimiters and badge text. Keep each role title, employer, dates and location in an unambiguous sequence. |
| P1 | Improve job-specific evidence selection | Rank requirements against profile-backed examples and explicit gaps. Prefer relevant completed outcomes over repeated generic duties or developing tooling. Never invent a missing qualification. |
| P1 | Make cover-letter prose less compressed | Keep the current four-paragraph/290–310-word policy unless the owner changes it. Allocate most space to one main and one complementary example; reduce closing repetition and tool inventories. |
| P2 | Reconcile instruction layers | Shared prompts, private voice, profile rules and the application skill should express one consistent policy. Move candidate-specific constraints out of generic prompts where feasible. |
| P2 | Add evidence provenance to achievements | Keep metric definition, period, baseline, contribution and status privately. Do not add numbers or causal certainty merely to strengthen prose. |

## Design direction

Keep a single content column, sans-serif type, navy headings and fine rules. Prefer
visible separators to invisible text repairs. Remove icons if their only role is
decoration. Add current city/country to the CV contact block rather than relying on
employment locations. Keep the professional headline focused on the role.

The template declares 10pt but `\\small` makes most CV prose approximately 9pt;
contact text is approximately 8pt. Body colour is `#666666`. These are human
readability concerns, not demonstrated automatic rejection criteria. A trial with
darker text and larger type should retain the visual identity. Skills can be placed
earlier for technical roles when this improves scanning; it is not an ATS rule.

Keep a role heading with its first substantive bullet, but avoid treating a large
entire role as indivisible when this creates whitespace. Avoid beginning a page
with an unexplained project continuation. Word education blocks need keep-with-next
grouping. Final checks must inspect both pages, not merely count them.

The new letter format should remain. A compact two-line contact block is acceptable
when a long line becomes too small. A company/Hiring Team recipient is sufficient
when no verified contact is available. Do not fabricate an address or recipient.
The render-time date is an existing intentional decision, not a bug to reverse.

## Content and voice

CV bullets should explain action, scope and a supported result or practical use.
Do not force a numerical outcome into every bullet. Preserve exact historical
titles and dates while using a truthful target headline. Expand ambiguous acronyms
on first useful use; keep recognizable technical names. Avoid generic summaries
and repeating a tool list in the headline, summary, technologies and skills.

For letters, preserve warmth, first person, natural transitions, concrete users and
a courteous close. Do not use historical letters as evidence for current facts or
invent a personal passion for the employer. The desired structure is:

1. Why this particular work interests the candidate, with one credible connection.
2. The strongest relevant example: problem, contribution, use or supported outcome.
3. A complementary example proving a different important requirement.
4. A brief invitation and thanks, plus required overseas-support context.

The narrow word band is an owner-approved policy. A possible future option is a
wider configurable target, but this audit does not authorize changing it. Likewise,
punctuation preferences should be understood as personal style, not ATS rules.
The prompt prohibits em dashes but the validator only rejects colons/semicolons;
resolve that deliberately rather than presenting either as a screening requirement.
Transition examples should remain optional so every letter does not acquire the
same cadence. Configured sign-offs need checks against the actual effective voice.

The CV prompt contains both job-specific selection rules and fixed candidate/project
counts. Treat factual ownership/status as hard requirements and editorial allocation
as preferences where the owner permits. The approved three-bullet project structure
must not be silently removed during a layout refactor.

The domestic work-authorization fallback is a known renderer behaviour. The prompt
sets null to retain the profile status, and the renderer appends it to the headline.
If the owner wants it suppressed or separated, make that an explicit policy change;
continue keeping sponsorship/support wording only in overseas cover letters.

## ATS and AI screening evidence

[Greenhouse's parsing guidance](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse)
identifies complex columns, tables, headers/footers and unclear sections as possible
parsing problems. This supports a conservative design, not a guarantee that every
decorative element fails. Its documented parsing file limit is 2.5MB.
[Lever](https://help.lever.co/s/article/Understanding-Resume-Parsing) accepts Word
and PDF and recommends selectable text as an initial check. Neither source makes
DOCX universally superior to PDF.

[Greenhouse's matching documentation](https://support.greenhouse.io/hc/en-us/articles/41131616864283-Talent-Matching-Data-Processing-FAQ)
describes extracting skills, titles, employment dates, employers and experience,
with semantic matching. This supports explicit, truthful evidence and clear chronology.
Its matching feature does not itself auto-reject candidates; separate
[application rules](https://support.greenhouse.io/hc/en-us/articles/360000653472-Auto-reject)
can reject on answers. A better CV cannot overcome an unmet genuine eligibility rule.
Do not generalize this product's behaviour to all employer systems.

AI authorship detection is a different problem. A
[2023 study](https://arxiv.org/abs/2304.02819) found bias in tested English detectors;
a [2026 Czech-language study](https://arxiv.org/abs/2602.05769) found no systematic
non-native bias in its setting. Neither certifies a current hiring detector or
these letters. Do not optimize punctuation, add deliberate errors, use hidden
keywords or claim a detector-proof result. Optimize authenticity and factual clarity.

[Harvard's cover-letter guide](https://careerservices.fas.harvard.edu/resources/hes-create-impactful-resumes-and-cover-letters/)
supports concise, factual, one-page letters with specific examples tied to the role;
it does not establish the project's exact word band as an external requirement.

## Proposed release checks

- Current source and artifacts agree on wording, sign-off, country context and facts.
- Both intended CV upload formats are visually reviewed; document page counts are
  reported individually. Distinguish an autofill aid from a reviewed final CV.
- Extracted text retains required fields and body words in sensible order with no
  unexpected glyphs, merged tokens or detached metadata; record engine/settings.
- Facts, ownership, dates and developing-work status are checked against the profile.
- The top role requirements have evidence mappings; material gaps remain visible.
- The owner can read each document at normal zoom and recognize the letter's voice.
- On the next real application, inspect actual autofilled fields before submission.
  Record observed results without submitting test applications or promising acceptance.

Architecture and roadmap implementation status are unchanged. Suggested next work:
artifact freshness and extraction checks, followed by a two-page CV layout trial.
