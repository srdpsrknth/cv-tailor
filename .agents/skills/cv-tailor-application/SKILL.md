---
name: cv-tailor-application
description: Generate and revise job-specific CV PDFs and cover letters with the local cv-tailor project, preserving editable content and verifying layouts. Use for applications or manual revisions using the selected candidate's profile and the project's templates.
---

# CV Tailor Application

Use the existing cv-tailor project at the Git repository root, its virtual environment, the selected candidate's profile in the private store, and the current templates. Read files before edits and preserve user changes. Do not change model settings or profile facts to match a job.

For first-time setup, profile intake and the user-facing workflow (finding jobs, generating, answering portal questions), use the companion skill [`skills/cv-tailor-setup/SKILL.md`](../../../skills/cv-tailor-setup/SKILL.md) and `docs/HOW_TO_GENERATE.md`. This skill covers only tailoring, reviewing and re-rendering an application; it does not repeat setup.

## Interpreter and commands

Pick the interpreter by OS and use it for every command below (or activate the venv and write `python`):

- macOS / Linux: `.venv/bin/python`
- Windows: `.venv\Scripts\python.exe`

Examples show `python`; substitute the interpreter above if the venv is not activated.

## Profile store (never in the public repository)

Profiles live **outside** this repository, in the private store named by `CVTAILOR_STORE` (default `./storage`), as `<store>/profiles/<profile_id>/profile.yaml`. Never commit a real profile, application or generated document: this repository is public (ADR 0002, ADR 0011).

`profile_id` is **required and fails closed** — there is no default profile and nothing infers one (ADR 0003). Name it with `--profile-id <id>` or `CVTAILOR_PROFILE_ID`, and run `python cvtailor.py profile list` to see what exists. If an id is missing or unknown, stop and ask rather than guessing.

**Candidate-specific constraints belong in the private store, not in this skill.** Employer-specific wording rules, ownership limits, immigration labels and per-country behaviour live in the selected profile (`rules`, `rules.country_overrides`) and in the optional `<store>/profiles/<profile_id>/candidate_guidance.json` (scoped drafting and layout guidance). Cover-letter voice lives in `writing_style.json` beside it. Read the selected candidate's files; never carry one candidate's rules over to another.

## Application folder and editable content

Each application lives in `<store>/outputs/<profile_id>/{year}_{company_slug}_{role_slug}_{timestamp}/`, matching the backend job_id convention. The **candidate segment is part of the path**: it is what keeps two profiles applying to the same posting from overwriting each other, so always include it. Use the user's year/timezone and lowercase underscore-separated slugs. Revisions reuse the same folder; do not scatter drafts or duplicate finals at the outputs root.

Keep CV PDF, cover-letter DOCX, and cover-letter PDF at the application's top level. Use the renderer's filenames: `{year}_CV_{name_slug}_{role_slug}.pdf` and `{year}_cover_letter_{company_slug}_{role_slug}.{docx,pdf}`. Preserve user-renamed files; update an existing alias when it represents the same deliverable rather than leaving stale copies.

Keep `source/content.json`, `source/job_description.txt`, and `source/generation_result.json` for reproduction. `content.json` contains `company_name`, `role_title`, `cv`, and `cover_letter`; the latter two follow `backend/models/tailored_output.py`. Include the job URL and retrieval date in the job description. Optional metadata can record model and factual corrections. QA files belong outside outputs, for example `.runtime/qa/{job_id}/`.

## Read, draft, review

- Read the actual posting. Web fetch may return 403 although normal `requests.get` succeeds; extract public JobPosting JSON-LD when available. If retrieval fails, ask for posting text instead of guessing requirements.
- Load the selected candidate's latest validated profile. For AI drafts, use configured `LLMService` and the project's prompts. Save structured output before rendering. Inspect and correct it rather than accepting API success as proof of quality. Existing JSON cleanup helpers in `tailor_service.py` handle markdown wrappers. Persist reviewed JSON for deterministic edits.
- Tailor every new application to the supplied role and posting, including applications generated in chat. Identify priority requirements, business context, and recurring keywords; map them to actual profile evidence across all relevant employers. Rewrite headline, summary emphasis, role bullets, project selection, and cover-letter examples accordingly. Use the posting's terminology naturally where truthful, without keyword stuffing, fabricated tools, or unsupported industry claims. An existing application is a style reference, not fixed text for a different job.
- Rebuild the generated CV's skills section for each opening: prioritize relevant profile-backed tools and methods while retaining supported foundational skills expected for the role even if omitted from the posting. Adjust selection, ordering, and category names; remove less relevant skills to stay compact. The source profile remains the reusable full skills inventory and must not be pruned or overwritten for one application. Only update source facts when the user supplies or confirms new information.
- Review both documents for job alignment as well as factual accuracy. Record important requirement-to-experience mappings, skill priorities, and material unsupported requirements in the tailoring explanation; do not claim an ATS score or guaranteed screening result. Scoped manual revisions still preserve other user-approved text.
- Match experience without inventing tools, numbers, leadership scope, or completion status. Respect the ownership, scope and status wording recorded in the profile (for example contributor versus lead, shipped versus under development). Do not credit a tool to an employer whose profile entry does not support it.
- Summary: concise and specific to the candidate's actual background and the role. Avoid third-person present-tense wording such as "Combines" or "Builds"; prefer "experience across" and "background in". Use an approved earlier summary as a style reference, not as fixed text for every job.
- Prefer externally understandable project names over internal code names, and explain internal vocabulary or acronyms where helpful. No dates or "in progress" labels in project headings; describe ongoing work accurately in bullets.
- Keep chronological work history. Use the two-page space for relevant older roles as well as the latest one. Do not invent bullets for roles with empty profile entries.
- Cover letter: exactly four paragraphs and 290-310 body words, one page, grounded in the profile and the opening. These are fixed format requirements, not evidence of prose quality. Pick up the posting's language for the role's purpose; mention supported stack only when it adds meaning. Map priority requirements to at most two concrete explained examples, explicitly connecting the evidence to the need and omitting unsupported requirements. A short courteous close should not repeat the opening or summarize strengths already shown. Natural transitions are optional examples, not a required repeated pattern; short direct sentences are fine when they sound natural. Distinguish developing work from shipped results. Preserve approved wording and manual edits; change only requested fields during revisions. Both DOCX (`Calibri`) and PDF (`Carlito` via LaTeX) render the same single-column business-letter structure (top sender contact block, render-time `date.today()`, recipient, bold subject line, `Dear <Company> Hiring Team,`, body, `closing_line`, signature name).
- Cover-letter voice: optional private `<store>/profiles/<profile_id>/writing_style.json` is loaded by the application for the letter only (ADR 0023). Use nominated historical letters as style references, never as evidence overriding current profile facts. Prefer one or two explained examples and their practical meaning to a tool/keyword inventory. Preserve warmth and the user's sign-off preference while trimming generic flattery and repetition. The effective voice changes the generation cache key; do not promise a cached/free run after changing it. Editorial quality requires the candidate's own reading, not an AI-detection score.

### Review checklist

Before delivering, confirm each item against the profile:

1. Every fact, title, date, tool, number and ownership claim is supported by the profile; nothing is fabricated.
2. **Never state gaps or missing qualifications in the documents** (no "I have not worked with X", "limited experience in Y", "although I lack..."). Omit unsupported requirements; record them only in the tailoring explanation.
3. **Never describe ended roles as current.** Use present tense and "present"/ongoing wording only for roles and projects the profile marks as ongoing; check end dates and status.
4. Ongoing, developing and shipped work are described accurately and consistently across CV and letter.
5. CV is at most two pages; cover letter is one page, four paragraphs, 290-310 body words.
6. Immigration/work-authorization wording appears only where the selected profile's rules and `country_overrides` establish it (see below).
7. Manual edits, titles, dates and approved wording are preserved; only requested fields changed.
8. Rendered pages inspected: no orphan headings, broken bullets, clipping or unresolved fields.

## Work country and work authorization

Establish the actual country of work from the posting or the user, not employer HQ; for remote roles use the actual employment country. Ask if it is ambiguous. In Streamlit, the Country of employment selector passes an explicit `work_country` to the backend; this overrides inference from the posting and is saved in `source/content.json`. In chat, pass the confirmed country when calling tailor_documents as well. Keep this application context when revising saved content.

Include immigration, permit or sponsorship wording **only** to the extent the selected profile's `rules` and `rules.country_overrides` establish it for that country:

- If the country's override sets `requires_employer_support: false`, omit visa, permit and sponsorship wording from both documents. An empty `work_authorization` explicitly suppresses the CV immigration label (null would restore the profile's default label).
- Where the profile requires employer support, set `cv.work_authorization` to the short application-specific label the rules allow (the renderer uses it instead of the profile's default label), and mention permit or sponsorship needs only in the cover letter, never in the CV, as one factual sentence in the final paragraph within the word budget.
- Follow the country's `tailoring_guidance` using profile-backed examples. Do not infer another candidate's rights, and do not invent international clients, leadership or relocation availability.
- Do not leak immigration wording into a letter for a country where the profile says no support is needed. Do not assume mobility eligibility, automatic transfer, timelines or a sponsorship exemption.
- Verify current destination requirements from official government sources before naming a permit route or eligibility; do not rely on stored requirements. Scoped edits to existing applications change only the label and that sentence, then recheck layout.

## Render and verify

Render saved content without calling a model again. Resolve `<store>`, `<profile_id>` and `<job_id>` from the current setup:

```bash
# macOS / Linux
.venv/bin/python scripts/render_application.py --project . --profile-id <profile_id> --content <store>/outputs/<profile_id>/<job_id>/source/content.json --mirror-configured
# or, equivalently, with the CLI:
.venv/bin/python cvtailor.py --profile-id <profile_id> render --content <store>/outputs/<profile_id>/<job_id>/source/content.json
```

```powershell
# Windows
.venv\Scripts\python.exe scripts/render_application.py --project . --profile-id <profile_id> --content <store>\outputs\<profile_id>\<job_id>\source\content.json --mirror-configured
.venv\Scripts\python.exe cvtailor.py --profile-id <profile_id> render --content <store>\outputs\<profile_id>\<job_id>\source\content.json
```

`--profile-id` is required (or `CVTAILOR_PROFILE_ID` must be set): the render path reads no hardcoded profile, so a missing id fails rather than rendering the wrong candidate. `.agents/skills/cv-tailor-application/scripts/render_application.py` is a thin wrapper that delegates to the root script with the same arguments.

Use `--cv-only` or `--cover-letter-only` for scoped edits. `--mirror-configured` copies generated deliverables to the existing `.env` OUTPUTS_DIR under the same application folder name while retaining local files and editable source.

The helper validates models and uses the shared renderers. It keeps project headings with their content. Page/word warnings require review. If over two pages, reduce repetition and less relevant detail without changing facts. The Streamlit/backend flow validates factual constraints, parses complete JSON consistently across retries, and checks the rendered CV and cover-letter PDF page counts before reporting success. It persists editable content and layout history in the application source folder. Editorial quality still requires the candidate's reading. Keep these shared prompts aligned with the preferences above; the backend does not load this skill automatically.

The CV body uses a single column with automatically selected 10.5–11pt dark text and 9.5pt contact/metadata text. The shared renderer compares comfortable (11/13.2pt), standard (10.5/12.6pt) and compact (10.5/12.2pt) presets with unchanged content, and eligible employer-boundary breaks, before generation requests shortening. It checks both parsers for source retention and measures page balance. Do not force two pages for genuinely short content or add filler. The selected preset/measurements are embedded in the PDF and recorded in provenance. Optional `--layout-preset` on the render CLI/script fixes typography; default `auto` compares layouts. Fixed typography does not bypass content/geometry checks or the need to review overflow. The compact PDF top block places the name on the left and right-aligned contact/work-authorization text beside it, all in the document body. Keep the professional headline on a separate full-width line below, so long titles are not interleaved with contacts during extraction. The Word autofill companion keeps stacked contact paragraphs. Skills and role metadata have visible separators. Preserve the profile's immigration policy and application-specific label. Do not shrink fonts to meet the page cap or promise universal ATS compatibility for the paired top block.

Preserve the refined PDF hierarchy: 26pt charcoal name, navy role headline, distinct company and role lines, dates/location aligned on the role row, fine employer dividers and lighter project labels. Keep essential information as real text in normal reading order. The Word companion remains a sequential, readable autofill alternative; do not introduce sidebars, text boxes, skill charts or hidden separators to reproduce decoration.

Saved-document review distinguishes current, stale and unverified legacy files by content, profile, renderer and artifact hashes. Unknown freshness is not proof that a document is wrong; review it before sending. Open **PDF text extraction checks · advisory** for the two independent local parsers, and use **Check Word pagination** (or the render script's `--check-word-layout`) for a LibreOffice estimate when installed. The Word check creates no persistent extra PDF. Word and PDF counts are separate, and neither parser diagnostics nor page counts guarantee ATS acceptance. Preserve reviewed manual filenames and sources during scoped renders.

Use available PDF/document skills for visual QA. Inspect both CV pages and the cover-letter PDF; render DOCX separately with LibreOffice (`soffice --headless --convert-to pdf`) to confirm its pagination alongside the LaTeX cover-letter PDF. Check page breaks, orphan headings, clipping, spacing, unresolved fields, dates, numbers, and ongoing-work wording against the profile. If API downloads are delivered, compare their bytes with intended artifacts; the CV endpoint must not return a cover-letter PDF.

Finish with links to final documents, page count, and actual limitations. Keep editable sources, preserve user artifacts, and remove only identified temporary QA files. This skill does not submit applications or contact employers.

## Restoring saved applications

Versioned `<store>/applications/<job_id>/source/` folders preserve reviewed content and job context. Copy the application folder into `<store>/outputs/<profile_id>/<job_id>/` before rendering. Use its `source/render_application.py` when present to preserve application-specific technology lists and page breaks; otherwise use `scripts/render_application.py`. Keep the current `.env` and profile local configuration when restoring.
