# 0024 — Track rendered artifact freshness and keep document checks advisory

**Status:** Approved by the owner's instruction to implement the application-quality
audit, 2026-11-17. Existing factual, immigration and word-count policies remain.

## Decision

Use a single-column CV with 10.5pt body text, 9.5pt metadata and visible separators.
The professional headline and work-authorization line are separate; the existing
application-specific override/profile fallback is unchanged. The generic CV template
uses article directly; the old AltaCV class remains for historical reproduction.
Explicit interword spaces in pdfTeX output improve independent text extraction.
Keep the current business-letter design and four paragraphs/290–310 body words.

**Owner-requested design refinement, 2026-11-17:** retain these constraints while
restoring stronger company/role hierarchy, a 26pt charcoal name, navy accents,
aligned date/location text, subtle employer dividers and lighter project labels.
The visual treatment is reversible template styling; it does not justify a smaller
body font, columns, hidden separators or changes to approved application wording.

**Owner-requested compact top block, 2026-11-17:** the PDF may pair the name on the
left with right-aligned contact and work-authorization text on the right. This is
ordinary body content, not a page header/footer or text box; the main sections stay
single-column. Put the professional headline on its own full-width line below to
prevent contact lines interleaving with a wrapped title in coordinate extraction.
Keep the Word companion's stacked contact paragraphs. This limited top arrangement
supersedes the blanket no-columns wording above only for this requested design;
passing local extraction checks does not certify every ATS parser.

Saved manifests may contain `artifact_provenance` keyed by filename, with schema
version, UTC recording time and SHA-256 hashes of relevant content, render context,
actual profile snapshot, rendering dependencies and artifact bytes. Scoped renders
merge their records without marking untouched files current. Missing historical
records mean unknown, never inferred success. Downloads remain available.

PDF diagnostics use independent pypdf and pdfplumber defaults to compare normalized
source words, field phrases, paragraph order and unexpected glyphs. These are local
text checks, not ATS scores. Missing source/dependencies and parsing failures remain
explicitly unchecked. Personal extracted text is not included in diagnostic reports.

LibreOffice estimates DOCX pagination only on explicit request (GUI button or render
script flag). Convert a copied input in a disposable directory using an isolated
Office profile. Store the count and source artifact hash in `word_layout`; never
reuse the count after the file changes. Missing LibreOffice is unchecked. No extra
converted PDF is left among deliverables. Word desktop rendering may differ.

## Consequences

New metadata is optional and backwards compatible. No application schema migration,
database, paid review call, detector service or automatic application submission is
introduced. Existing manual prose and filenames remain authoritative. Refreshing
templates need not regenerate prose or change the source profile. Back up reviewed
deliverables before refreshing existing applications; keep backups privately.

Prompt improvements change future draft/cache inputs. No new live prose quality or
screening-outcome claim follows from passing deterministic software tests.
