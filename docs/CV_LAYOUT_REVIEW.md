# CV layout review — 2026-11-18

Status: investigation and private comparison renders only. No production template,
prompt, profile, application wording or saved deliverable changed. Independent
subagents reviewed pagination and researched layout guidance; Luna was unavailable
in the session's subagent model catalog.

## Findings

A newly generated two-page CV uses approximately 93% of the first page's printable
height and 70% of the second, with 95mm between the final glyph and paper edge on
page 2 (including the intended 15mm margin). Nothing in the inspected source
sections appears to be missing. The saved first-pass page history is `[2]`;
shortening retries did not cause the empty tail.

`templates/cv/main.tex.jinja2` protects role headers and regular bullets together,
then protects each selected project separately. A role can therefore end on page 1
and its project begin page 2. The remaining space after that role is insufficient
for the next protected project. This is a coherent project break, but weakens the
connection between the project and its parent employer.

`backend/services/tailor_service.py:538–545` accepts any render of at most two pages.
There is no occupied-height or page-balance check. The CV prompt intentionally has
no minimum length; its bullet/word ranges are guidance rather than quotas. Do not
replace this policy with padding or automatic expansion.

The compact contact header saves space, but is **not the cause of page-2 whitespace
in the frozen-content comparison**: reverting only to the preceding full-width
header leaves the second page's break and final glyph position unchanged. It
merely moves the first page's content down by 15.5pt.

## Frozen-content experiments

All six examples use identical structured CV content and the saved profile snapshot.
Body size/leading are points; percentages measure final glyph position within the
15mm top/bottom printable bounds, not ink coverage or ATS performance.

| Variant | Page 1 used height | Page 2 used height | Assessment |
|---|---:|---:|---|
| Current 10.5/12.2 | 93.2% | 70.0% | Dense first page; project opens second |
| Previous header | 95.2% | 70.0% | No page-2 improvement |
| 10.5/13.2 | 98.4% | 72.4% | Most added space consumed on first page |
| 11/13.2 | 86.5% | 88.3% | Best reviewed example; natural employer boundary |
| 19mm horizontal margins | 97.2% | 70.0% | Name wraps; reject this unchanged header trial |
| Explicit employer break, original type | 80.3% | 83.1% | Balanced but larger blank tails; application-specific |

Current and 11/13.2 pages were visually inspected. All six variants retained the
compared summary/responsibility/project prose and candidate name/email/headline in
both pypdf and default pdfplumber; checked prose order was correct. This is limited
local extraction evidence, not certification of every field or ATS.

Cross-checking 11/13.2 against all four available two-page examples with editable
source and profile snapshots kept two at two pages, but pushed two denser CVs to
three pages. Therefore do not apply 11pt globally based on the attractive example.
Two other historical three-page PDFs were inventoried, excluded from this
cross-check, and left unchanged.

Private reproduction script, metrics, source template copies and comparison PDFs:
`<store>/reviews/sreedeep/layout-review-2026-11-18/`.

## Recommended next implementation

1. Keep the present restrained hierarchy and single-column main body. Offer a
   standard 10.5/12.2 preset and a comfortable 11/13.2 preset. Consider the larger
   preset first when it fits two pages and improves page balance; retain standard
   for dense documents. Render unchanged content before choosing, with a stable
   deterministic selection rule and manual override. Record the actual preset in
   artifact provenance and describe actual sizes honestly in generation guidance.
2. Add advisory measurements: per-page last-glyph position, blank tail inside the
   margins, largest internal gap, and employer/project separation. Occupied height
   is not content density; report both page values. Approximately 75–95% can be a
   review preference for two-page output, not a hard minimum or ATS score. A
   one-page CV must remain valid when appropriate.
3. Preserve heading/first-content protection. Do not remove `samepage` globally or
   make every employer indivisible. A short continuation label may help when a
   project necessarily continues on page 2; verify extraction order if introduced.
4. Keep relevance ahead of fullness. Review omitted evidence only if it strengthens
   the application. Profile-wide technology lists currently bypass tailored skills
   selection; consider relevant technology selection separately, without changing
   source facts. Do not add generic bullets or vertically stretch sections to fill.
5. For any implementation, check short/dense/long-title examples, two-page cap,
   real font sizes, clipping/orphans, prose/field/order retention in two parsers,
   stable preset selection and provenance. Verify Word separately; these comparison
   renders cover the primary LaTeX PDF only.

No typography switch, automated selection or new gate is implemented by this review.

## Research and its practical limits

- [Bundesagentur für Arbeit](https://www.arbeitsagentur.de/vor-ort/zav/working-and-living-in-germany/newsletter-iss/01-2026/bewerbung)
  recommends at most two pages, recent experience first, clear sections, brief
  concrete bullets and quick readability. These support the existing direction.
- [Greenhouse parser documentation](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse)
  identifies columns, complex tables and header/footer/text-box contacts as parsing
  risks. Preserve plain-text body content and the sequential Word companion.
  The paired name/contact block remains an acknowledged local-parser tradeoff.
- [Penn career services](https://careerservices.upenn.edu/channels/resume/)
  recommends readable 10–12pt type and approximately .65–1in margins.
  Student-oriented guidance is not a rigid specification for experienced applicants.
- [University of Montana](https://careerhub.umt.edu/resources/resume-guide-samples/)
  suggests a second page at least half full, ideally three-quarters;
  [Colorado State](https://career.colostate.edu/resumes/) prefers full pages.
  This disagreement reinforces that no universal page-2 occupancy rule exists.
- [Harvard career services](https://careerservices.fas.harvard.edu/resources/create-a-strong-resume/)
  emphasizes importance-based section order and balanced whitespace.

The best fit here is a readable reverse-chronological two-page CV, clear role and
project grouping, and modest adaptive typography. A sidebar, skill charts or a
universal requirement to fill the bottom edge offers no demonstrated advantage.

## Verification

Offline baseline: **1267 passed, 3 skipped**, one existing Google SDK deprecation
warning, 42.85 seconds. No production code changes; no additional software tests
were needed. Six real-render comparisons and four cross-check renders completed.
No paid generation, portal upload, submission or Word desktop verification.
