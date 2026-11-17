---
name: cv-tailor-application
description: Generate and revise job-specific CV PDFs and cover letters with the local cv-tailor project, preserving editable content and verifying layouts. Use for applications or manual revisions using this project's profile and templates.
---

# CV Tailor Application

Use the existing cv-tailor project, at the Git repository root, its `.venv/Scripts/python.exe`, its profile store, and current templates. Read files before edits and preserve user changes. Do not change model settings or profile facts to match a job.

## Profile store (never in the public repository)

Profiles live **outside** this repository, in the private store named by `CVTAILOR_STORE` (default `./storage`; on this machine `D:\coding\cv-tailor-data`), as `<store>/profiles/<profile_id>/profile.yaml`. Never commit a real profile, application or generated document: this repository is public (ADR 0002, ADR 0011).

`profile_id` is **required and fails closed** — there is no default profile and nothing infers one (ADR 0003). Name it with `--profile-id <id>` or `CVTAILOR_PROFILE_ID`, and run `cvtailor profile list` to see what exists. If an id is missing or unknown, stop and ask rather than guessing.

## Application folder and editable content

Each application lives in `<store>/outputs/<profile_id>/{year}_{company_slug}_{role_slug}_{timestamp}/`, matching the backend job_id convention. The **candidate segment is part of the path**: it is what keeps two profiles applying to the same posting from overwriting each other, so always include it. Use the user's year/timezone and lowercase underscore-separated slugs. Revisions reuse the same folder; do not scatter drafts or duplicate finals at the outputs root.

Keep CV PDF, cover-letter DOCX, and cover-letter PDF at the application's top level. Use the renderer's filenames: `{year}_CV_{name_slug}_{role_slug}.pdf` and `{year}_cover_letter_{company_slug}_{role_slug}.{docx,pdf}`. Preserve user-renamed files; update an existing alias when it represents the same deliverable rather than leaving stale copies.

Keep `source/content.json`, `source/job_description.txt`, and `source/generation_result.json` for reproduction. `content.json` contains `company_name`, `role_title`, `cv`, and `cover_letter`; the latter two follow `backend/models/tailored_output.py`. Include the job URL and retrieval date in the job description. Optional metadata can record model and factual corrections. QA files belong outside outputs, for example `.runtime/qa/{job_id}/`.

## Read, draft, review

- Read the actual posting. Web fetch may return 403 although normal `requests.get` succeeds; extract public JobPosting JSON-LD when available. If retrieval fails, ask for posting text instead of guessing requirements.
- Load the latest validated profile. For AI drafts, use configured `LLMService` and the project's prompts. Save structured output before rendering. Inspect and correct it rather than accepting API success as proof of quality. Existing JSON cleanup helpers in `tailor_service.py` handle markdown wrappers. Persist reviewed JSON for deterministic edits.
- Tailor every new application to the supplied role and posting, including applications generated in chat. Identify priority requirements, business context, and recurring keywords; map them to actual profile evidence across all relevant employers. Rewrite headline, summary emphasis, role bullets, project selection, and cover-letter examples accordingly. Use the posting's terminology naturally where truthful, without keyword stuffing, fabricated tools, or unsupported industry claims. An existing application is a style reference, not fixed text for a different job.
- Rebuild the generated CV's skills section for each opening: prioritize relevant profile-backed tools and methods while retaining supported foundational skills expected for the role even if omitted from the posting. Adjust selection, ordering, and category names; remove less relevant skills to stay compact. The source profile remains the reusable full skills inventory and must not be pruned or overwritten for one application. Only update source facts when the user supplies or confirms new information.
- Review both documents for job alignment as well as factual accuracy. Record important requirement-to-experience mappings, skill priorities, and material unsupported requirements in the tailoring explanation; do not claim an ATS score or guaranteed screening result. Scoped manual revisions still preserve other user-approved text.
- Match experience without inventing tools, numbers, leadership scope, or completion status. Aklamio: contributor to an approximately 80-table DQ framework, owner of funnel/sales-channel checks, not lead of the entire framework. MCP/dashboard work remains under development unless the user updates its status. Prior roles establish dbt experience; Aklamio does not use dbt.
- Summary: concise, broad coverage of analytics engineering, BI, and growth analytics. Avoid third-person present-tense wording like "Combines" or "Builds"; prefer "experience across" and "background in". Use the approved Booking summary as a style reference rather than fixed text for every job.
- Prefer externally understandable project names, such as "Traffic Source & Customer Journey Attribution" instead of "Entrypoints v2". Explain internal vocabulary/acronyms where helpful.
- Aklamio: attribution is the main selected project, with three substantive bullets; fold DQ, MCP, and dashboarding into regular bullets. No dates or "in progress" labels in project headings; describe ongoing work accurately in bullets. Location: "Berlin, Germany".
- Keep chronological work history. Use the two-page space for relevant NeoTaste, ecoligo, and heycar details as well as the latest role. Do not invent bullets for older roles with empty profile entries.
- Cover letter: exactly four paragraphs and 290-310 body words, one page, grounded in profile and opening. These are fixed format requirements, not evidence of prose quality. Pick up the posting's language for the role's purpose; mention supported stack only when it adds meaning. Map priority requirements to at most two concrete explained examples, explicitly connecting the evidence to the need and omitting unsupported requirements. A short courteous close should not repeat the opening or summarize strengths already shown. Natural transitions are optional examples, not a required repeated pattern; short direct sentences are fine when they sound natural. Never leak visa/Blue Card/sponsorship wording into a domestic German letter. Distinguish developing work from shipped results. Preserve approved wording and manual edits; change only requested fields during revisions. Both DOCX (`Calibri`) and PDF (`Carlito` via LaTeX) render the same single-column business-letter structure (top sender contact block, render-time `date.today()`, recipient, bold subject line, `Dear <Company> Hiring Team,`, body, `closing_line`, signature name).
- Cover-letter voice: optional private `<store>/profiles/<profile_id>/writing_style.json` is loaded by the application for the letter only (ADR 0023). Use nominated historical letters as style references, never as evidence overriding current profile facts. Prefer one or two explained examples and their practical meaning to a tool/keyword inventory. Preserve warmth and the user's sign-off preference while trimming generic flattery and repetition. The effective voice changes the generation cache key; do not promise a cached/free run after changing it. Editorial quality requires the owner's reading, not an AI-detection score.

## Applications outside Germany

Streamlit has a Country of employment selector. Pass its explicit `work_country` to the backend; this overrides inference from the posting and is saved in source/content.json. In chat, pass the confirmed country when calling tailor_documents as well. For remote roles use the actual employment country. Keep this application context when revising saved content.

The candidate holds a valid German-issued EU Blue Card and has stated that overseas applications require employer permit support. Establish the actual country of work from the posting or user, not employer HQ; ask if ambiguous. Verify current destination requirements from official government sources before naming a permit route or eligibility. A German Blue Card is not unrestricted EU-wide work authorization. Ireland and Denmark do not participate in the scheme. Do not assume mobility eligibility, automatic transfer, timelines, or a sponsorship exemption.

For an overseas CV, set `cv.work_authorization` to a short application-specific label such as `German EU Blue Card holder`; the renderer uses it instead of the profile visa label. Mention sponsorship or permit support requirements only in the cover letter, never in the CV. Keep the source profile intact. For Germany, leave it null. Put one factual sentence in the cover letter's final paragraph, within the normal word budget: `I hold a valid EU Blue Card issued by Germany and would require employer support for the appropriate work authorization in [country].` For Ireland, use `I hold a valid German EU Blue Card and would require employer support for an Irish employment permit.` Name Critical Skills or another route only when verified for the opening; otherwise use generic local permit wording. Scoped edits to existing applications change only this label and sentence, then recheck layout. Consult the European Commission EU Blue Card portal and the destination government's permit guidance rather than relying on stored requirements.

## Render and verify

Render saved content without calling a model again:

```powershell
& .venv/Scripts/python.exe scripts/render_application.py --project . --profile-id <profile_id> --content <store>/outputs/<profile_id>/<job_id>/source/content.json --mirror-configured
```

`--profile-id` is required (or `CVTAILOR_PROFILE_ID` must be set): the render path no longer reads a hardcoded profile, so a missing id fails rather than rendering the wrong candidate.

Use `--cv-only` or `--cover-letter-only` for scoped edits. Resolve the skill path from its installation if different. `--mirror-configured` copies generated deliverables to the existing `.env` OUTPUTS_DIR under the same application folder name while retaining local files and editable source.

The helper validates models and uses the shared renderers. It keeps project headings with their content. Page/word warnings require review. If over two pages, reduce repetition and less relevant detail without changing facts. The Streamlit/backend flow validates factual constraints, parses complete JSON consistently across retries, and checks the rendered CV and cover-letter PDF page counts before reporting success. It persists editable content and layout history in the application source folder. Editorial quality still requires the owner's reading. Keep these shared prompts aligned with the preferences above; the backend does not load this skill automatically.

The CV body uses a single column with 10.5pt dark text and 9.5pt contact/metadata text. The compact PDF top block places the name on the left and right-aligned contact/work-authorization text beside it, all in the document body. Keep the professional headline on a separate full-width line below, so long titles are not interleaved with contacts during extraction. The Word autofill companion keeps stacked contact paragraphs. Skills and role metadata have visible separators. Preserve the existing immigration policy and application-specific label. Do not shrink fonts to meet the page cap or promise universal ATS compatibility for the paired top block.

Preserve the refined PDF hierarchy: 26pt charcoal name, navy role headline, distinct company and role lines, dates/location aligned on the role row, fine employer dividers and lighter project labels. Keep essential information as real text in normal reading order. The Word companion remains a sequential, readable autofill alternative; do not introduce sidebars, text boxes, skill charts or hidden separators to reproduce decoration.

Saved-document review distinguishes current, stale and unverified legacy files by content, profile, renderer and artifact hashes. Unknown freshness is not proof that a document is wrong; review it before sending. Open **PDF text extraction checks · advisory** for the two independent local parsers, and use **Check Word pagination** (or the render script's `--check-word-layout`) for a LibreOffice estimate when installed. The Word check creates no persistent extra PDF. Word and PDF counts are separate, and neither parser diagnostics nor page counts guarantee ATS acceptance. Preserve reviewed manual filenames and sources during scoped renders.

Use available PDF/document skills for visual QA. Inspect both CV pages and the cover-letter PDF; render DOCX separately with LibreOffice (`soffice --headless --convert-to pdf`) to confirm its pagination alongside the LaTeX cover-letter PDF. Check page breaks, orphan headings, clipping, spacing, unresolved fields, dates, numbers, and ongoing-work wording against the profile. If API downloads are delivered, compare their bytes with intended artifacts; the CV endpoint must not return a cover-letter PDF.

Finish with links to final documents, page count, and actual limitations. Keep editable sources, preserve user artifacts, and remove only identified temporary QA files. This skill does not submit applications or contact employers.

## Restoring saved applications

Versioned `<store>/applications/<job_id>/source/` folders preserve reviewed content and job context. Copy the application folder into `<store>/outputs/<profile_id>/<job_id>/` before rendering. Use its `source/render_application.py` when present to preserve application-specific technology lists and page breaks; otherwise use `scripts/render_application.py`. Keep the current `.env` and profile local configuration when restoring.
