# CV Tailor: capability inventory for the UI redesign

Source: code on branch `ui/redesign` (backend services, CLI, FastAPI, Streamlit UI, scripts, evaluation, skills) plus docs/ADRs. Judged from code, not from the current UI. No private store, profile, `.env`, `outputs/` or `local/` content was read. File:line cites refer to the repo at the time of writing.

Legend for "Exposed today": **GUI** = Streamlit page/widget; **CLI** = `cvtailor <cmd>`; **API** = FastAPI route in `backend/main.py`; **Skill** = only described in `skills/` or `.agents/skills/`; **None** = hand-edit a file or call Python only.
"Paid" = makes an LLM call that costs money. "Long" = takes more than a few seconds.

---

## 1. Capability table

### 1.1 Profiles and candidate rules

| Capability | Where it lives | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| List profiles with health (broken ones listed with reason) | `ui/services_bridge.py:list_profiles`; `cli/commands/profile.py:list_profiles` | GUI sidebar picker (`ui/app.py:112`), CLI `profile list` | in: config; out: `[ProfileOption(profile_id,name,roles,problem)]` | no | Broken profiles shown in an expander (`app.py:119-123`), not selectable. |
| Select active profile (remembered) | `services/gui_preferences.py:initial_profile/remember_profile`; `app.py:render_profile_picker` | GUI only | writes `<store>/preferences/gui.json` `{last_profile_id}` | no | ADR 0022: restore remembered if usable, else the only usable profile, else must choose. Cleared selection is not re-selected in-session. Switching clears draft/search/review state (`app.py:clear_candidate_state`). |
| Fail-closed profile resolution | `bridge.require_profile_id` (`services_bridge.py:92`); `services/profile_store.py:validate_profile_id`, `resolve_profile_id` | CLI/API/services enforce; the GUI does NOT call `require_profile_id` (grep: unused by `ui/*.py`) | id string -> validated id or raises `InvalidProfileIdError`/`UnknownProfileError` | no | The GUI relies on its picker state plus per-service validation. A new frontend must pass an explicit id on every call. |
| Create empty profile | `cli/commands/profile.py:new` -> `ProfileStore.create` | CLI only (`profile new <id> --name --email --force`) | creates a minimal valid profile ("New Candidate", `candidate@example.com`) | no | GUI says "Import a profile to get started; see Settings & help" (`app.py:115`) and prints CLI commands (`app.py:607-613`). No onboarding in GUI. |
| Import profile.yaml verbatim | `profile.py:import_profile` -> `ProfileStore.import_file` | CLI only (`profile import <path> --profile-id --force`) | validates then copies byte for byte | no | Skill `cv-tailor-setup` interviews or parses a CV/PDF then imports. |
| Export profile | `profile.py:export_profile` | CLI only (`profile export <dest> --force`) | copy of profile.yaml | no | Warns it contains personal data. |
| Show/inspect profile | `profile.py:show`; `bridge.load_profile` | CLI `profile show`; GUI read-only summary in Settings (`app.py:584-592`: name, role count, skill-group names only) | `Profile` model | no | GUI shows far less than the model holds (see richer sections below). |
| Edit profile (facts, skills, experience) | none | **None.** Edit `profile.yaml` by hand. Only programmatic write path is `claim_acceptance` (targeted insertion, `services/profile_text_edit.py`) | n/a | no | There is no profile editor, validator UI, or diff. `ProfileStore` has no update method. |
| Profile data model: identity, summary_base, experience (bullets, selected_projects, technologies, `optional`, `display_name`), education (with `highlights`, `ongoing`), certifications (string or `{name,issuer,year}`), skills (category -> list), languages (+proficiency), publications/activities (string or `{text,bullets}`), standalone_projects (+dates, technologies, context), `standalone_projects_policy: select\|all`, `cv_section_order`, `cv_hidden_sections` (also `summary`, `employer_projects`), `letter{salutation,sign_off}`, `job_search{keywords,country,city,remote_only}`, `rules{...}` | `models/profile.py` | Not exposed except job_search defaults (prefill Find jobs, `app.py:399-403`) and role count | | no | ADR 0027. New fields are omitted from serialisation at default so cache keys stay stable. |
| Section order and hidden sections | `Profile.cv_section_order/cv_hidden_sections`, `resolve_cv_section_order`; honoured by `renderers/latex_renderer.py` (`cv_section_order` template loop) and `application_review._expected_cv_text` | None (profile.yaml only) | | no | Skill setup interview asks about it. A UI control would need a profile write path. |
| Work authorization / country rules | `ProfileRules` (`models/profile.py`): `visa_label`, `home_countries`, `local_permit_countries`, `country_overrides{country -> work_authorization, requires_employer_support, authorization_basis, tailoring_guidance}`, `employers`, `banned_tools`, `summary_forbidden_verbs`; enforced in `services/pipeline.py:_apply_visa_label,_check_country_override_wording,_check_sponsorship_sentence` and `services/validation.py` | None for authoring. Consumed implicitly via the Country selector at generation (`app.py:226-241`). Also `home_countries` feeds job-search eligibility. | | no | Rules: CV never carries sponsorship text; cover letter carries it only where the override requires employer support. The UI does not show which override applies for the chosen country (help text only says "Check work-authorisation wording yourself"). |
| Private writing voice | `services/writing_voice.py:writing_voice_context`; file `<store>/profiles/<id>/writing_style.json` (`tone, preferences[], avoid[], sign_off`, version 1) | None (file only; documented in HOW_TO_GENERATE) | out: text appended to the cover-letter prompt and cache key | no | Malformed file fails generation before any paid call; absent is fine. GUI never tells the user whether a voice file exists or whether it is valid. |
| Candidate guidance | `services/candidate_guidance.py` ; file `candidate_guidance.json` (`cv, cover_letter, layout` lists up to 20 each, `acronyms`) | None. Scripts `scripts/capture_candidate_policy.py`, `scripts/migrate_candidate_guidance.py` are one-off migration tools | | no | Invalid file raises at generation and at render (`render`, `claim_cv_revision`). Acronyms also affect rendering of skill headings. |
| GUI preferences | `services/gui_preferences.py` | GUI | only `last_profile_id` | no | No other preference exists (no model default, layout default, country memory). |

### 1.2 Job intake and discovery

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| Paste a posting | `services/posting.py:validate_posting` (>=50 chars; rejects a pasted `cvtailor ...` command) | GUI textarea (`app.py:207`), CLI `generate --job-file/--job/stdin` | text -> validated text | no | GUI shows word and character count only. |
| Posting from a URL | none | **Not implemented.** No generic URL fetcher or JSON-LD extractor exists (grep for fetch/JSON-LD finds only `PersonioSource.fetch_one`). The `.agents` skill tells an agent to do it manually. | | | PRODUCT_AUDIT proposes URL intake; a frontend that offers it needs a new backend service. |
| Job search across public sources | `services/job_search.py:search_jobs`; `services/job_connectors.py` (softgarden, Personio, Lever/Greenhouse/Ashby, Arbeitnow); `job_dedupe.py`, `job_match.py`, `job_normalize.py`, `models/job.py` | GUI Find jobs (`app.py:393-482`) via `bridge.search_from_fields`; CLI `jobs search`, `jobs sources` | in: `SearchQuery{keywords,country,city,remote,limit}`, `MatchPreferences`; out: `SearchOutcome{results[MatchResult], groups, expiry, failures, notes, jobs_read}` | Long (network, many HTTP requests, 0.5 s min interval, budget 60 requests in CLI); not paid | Free, no key. Keyword filter is local (sources cannot filter server side). |
| Match explanation and eligibility | `job_match.py`: rank = count of named evidence reasons; `Eligibility` eligible/uncertain/ineligible; `blockers`, `unknowns`, `unmatched_keywords` | GUI shows score metric, eligibility, `result.explanation()` lines (`app.py:456-471`) | | no | "Matching signals" is a count, not a probability. `include_ineligible` supported by service (`run_job_search`) but not by the GUI. |
| Per-profile / custom job sources | CLI `jobs search --ats platform:token[:Company] --softgarden-tenant --personio-tenant --only <source> --max-requests N` (`cli/commands/jobs.py:_apply_overrides`) | **CLI only.** GUI always uses `build_default_sources()` = the SAMPLE boards (ADR 0030: "sample boards appear as real results") | | | ADR 0030 says this is being redesigned; not yet designed. |
| Dedupe, expiry (sweep) tracking | `job_dedupe.py`, `job_search.load_sweep/save_sweep` -> `<store>/jobs/<id>/sweep.json`; `SearchOutcome.groups/expiry` | Computed on every search (the sweep file is updated on every search), but the GUI renders none of dedupe groups or "no longer appears" verdicts. CLI prints a summary line (`job_search.summarise`) | | no | Duplicate groups and "disappeared" counts are available in `outcome.as_dict()`. |
| Hand a result to New application | `bridge.posting_handoff` (description, company, role, verified country code, provenance url/source/posted_at/transferred_at) | GUI "Use this posting" (`app.py:475-478`) | | no | Provenance saved later as `source/posting_provenance.json` (`bridge.save_posting_provenance`). Jobs without a description just say "paste it" (`app.py:479-482`). |
| Source coverage / limitations | `bridge.source_coverage`; `SourceCapabilities.limitations_for` -> `outcome.notes` | GUI expander (`app.py:422-427`); CLI `jobs sources` prints the not-built list (StepStone, Indeed, LinkedIn, SmartRecruiters) | | no | Workday employers unsupported (ADR 0030). |

### 1.3 Tailoring and generation

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| Generate CV + cover letter | `services/tailor_service.py:tailor_documents`; `services/pipeline.py:DocumentGenerator` (draft CV, draft letter, up to 3 validation attempts per document, up to 4 layout attempts with shortening retries) | GUI "Generate CV and cover letter" (`app.py:290`) via `bridge.run_generation`; CLI `generate`; API `POST /api/tailor` | in: posting, profile, company, role, work_country, use_cache, balance_cv_pages, status_callback; out `TailorResponse` (job_id, paths, page counts, `token_usage`, `tailoring_explanation`, manifest metadata, `calls`, `cache_hit`, `cost_source`) | **Long and PAID** (several provider calls, then local LaTeX compiles) | Synchronous, blocking. Status messages are only: "Drafting CV...", "CV is N pages; shortening content...", "Reusing a stored generation for this exact posting." (`pipeline.py:358,388`, `tailor_service.py`). Rendering, letter drafting, Word/PDF conversion are silent. No cancel. |
| Failure persistence | `tailor_service.py` failure branches -> `ApplicationStore.save_drafts/save_failure` | GUI: error + "Review saved attempt" links (`app.py:369-381`); CLI | failed run keeps `drafts.json`, `content.json` (if any), `generation_result.json` with `status: failed` | | `drafts_saved` computed by checking for `source/drafts.json` in folders new since the run (`services_bridge.py:286-304`). |
| Provider and model choice | `config.py` (`CVTAILOR_PROVIDER` gemini\|openrouter; `CVTAILOR_MODEL`, `OPENROUTER_MODEL`, `GEMINI_MODEL`; `CVTAILOR_MODEL_<TASK>` for `cv, cover_letter, layout_retry, portal_answers`); `Config.model_for`; `bridge.model_options/generation_config`; `evaluation.curated_models.curated_models` | GUI: one selectbox for curated catalogue (OpenRouter only, currently ONE model; `app.py:248-259`). Provider, per-task routing, key: `.env` only | `with_overrides(model=..., task_models={})` | | `generation_config` wipes explicit per-task overrides when a catalogue model is picked (`services_bridge.py:467-472`). Default model `openai/gpt-6-luna` on openrouter (`config.py:DEFAULT_MODEL`). |
| Cost estimation / tracking | `services/pricing.py` (route- and tier-aware table, `estimate_cost`, `is_priced`, `describe_tier`, staleness helpers); `LLMService.calculate_token_usage` (prefers provider-reported spend); `bridge.format_cost_breakdown` | GUI shows cost AFTER a run only (via the success summary lines and Details). No before-run estimate. Claim drafting and portal-answers drafting show their own cost after the call. CLI prints tokens and `~$` after. | | no | `PRICE_SOURCES`/`staleness_message` exist but the GUI does not surface price staleness. A static "$0.003" label was removed earlier (GUI_REVIEW). There is no pre-run estimator function; the evaluation suite has `runner.plan`/`dry_run` for its own projections. |
| Cost cap | `CVTAILOR_MAX_COST_USD` -> `Config.max_cost_usd`, `budget_exceeded`; enforced in `LLMService._record_spend` (stops run) and in `portal_answers`/`claim_drafting` (refuse to start) | env only; not shown in the GUI | | | A UI should read `config.has_cost_cap/max_cost_usd` and show it near any paid button. |
| Generation cache / fingerprint | `services/cache_store.py` (`cache_key`, `GenerationCache` under `<store>/cache/<id>/`), `services/pipeline_fingerprint.py`, `tailor_service._cache_read/_cache_write` | Flag only: GUI checkbox "Force a fresh draft" (`app.py:261`), CLI `--no-cache`, API `use_cache`. No way to ask "would this be a cache hit?" before running | key covers profile bytes, posting, company/role/country, prompts, guidance, writing voice, schema, provider, models, rules, pipeline fingerprint | | Hit is re-validated against current rules; a stale entry silently becomes a miss (a paid call). A UI that promises "free repeat" cannot know in advance without a new `would_hit_cache` helper. Run details show `run_type` ("Fresh draft", "Cached result", "Reused draft + new calls") (`application_review.load_review`). |
| Country of employment | `work_country` arg; saved in `content.json` | GUI selectbox with 7 hardcoded names and free-entry (`app.py:226-241`); CLI `--country`; API field | | | Search results hand over ISO codes mapped through a second hardcoded dict (`app.py:191-198`). Not tied to the profile's `country_overrides` keys. |
| Company / role override | `company_name`, `role_title` | GUI text inputs, CLI, API | | | Otherwise inferred by the model (`cl.company_name`, `cl.role_title`). |
| Balanced page breaks (alternate CV layout search) | `tailor_documents(balance_cv_pages=True)` -> `LaTeXRenderer(explore_breaks)` | GUI selectbox "CV page layout" (`app.py:242-247`); NOT in CLI generate/API | | longer render | |
| Suggested claims produced in the CV call | `suggested_claims.store_from_response`, `claim_acceptance` | See 1.6 | | | Up to 8 per application. |
| Preflight (doctor-lite) | `bridge.preflight` | GUI expander "Ready to generate?" (`app.py:268-287`) | key configured, model per task, pdflatex found | no | Disables the Generate button when key or PDF engine is missing. |
| Remote-controllable generation | `backend/main.py` `POST /api/tailor` | API | `TailorRequest{job_description>=50 chars, company_name, role_title, work_country, profile_id, use_cache}`; no `balance_cv_pages` | Long, paid, synchronous | |

### 1.4 Outputs, rendering and layout

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| CV PDF (LaTeX, single column) | `renderers/latex_renderer.py:render_cv`; template `templates/cv/main.tex.jinja2`; `_render_cv` tries presets and break candidates, checks two PDF parsers for text retention, clipping, orphan headings | GUI downloads, preview (`st.pdf`), CLI `render` | out `<year>_CV_<name>_<role>.pdf` with embedded `/CVLayout` metadata | local, a few seconds to tens of seconds | `.tex` is NOT kept (intermediates deleted, `_cleanup_intermediates`). No LaTeX source export. |
| Adaptive typographic presets | `renderers/cv_layout.py:PRESETS` (comfortable 11pt, standard 10.5, compact 10.5/12.2), `rank_layout`, `measure_layout` | Auto only in GUI. CLI `render --layout-preset auto\|comfortable\|standard\|compact` and `scripts/render_application.py --layout-preset` | | | Hidden preset choice. ADR 0025. |
| Layout preview (alternative page breaks) | `services/application_layout_preview.py:preview_saved_cv_layout/save_cv_layout_preview`; `renderers/cv_layout.preview_breaks` | GUI: Documents tab expander "Compare CV page breaks" (`ui/layout_preview.py`); saves `cv_balanced_<hash>.pdf` | in saved content + snapshot; out `(pdf bytes, report{page_count, blank_tails_mm, baseline, source_revision,...})` | Long-ish (many LaTeX trials), local | Report has `baseline` so the UI compares to existing rules. Save is gated on checks passing and a matching `source_revision`. |
| Cover letter DOCX + PDF | `renderers/docx_renderer.py:render_cover_letter` (template `templates/cover_letter/cover_letter.docx`, PDF via LaTeX conversion) | GUI downloads; CLI `render --cover-letter-only` | | local | Date stamped at render time; salutation/sign-off from `profile.letter`. |
| Autofill CV (Word + text, "upload CV") | `renderers/upload_cv.py:render_upload_cv`; `services/upload_cv.py:export_saved_upload_cv`; `bridge.export_upload_cv` | GUI button "Create / refresh CV for autofill" (`review.py:176-192`, auto-built after generate `app.py:352-361`); CLI `render` also writes them | `<stem>_upload.docx` and `.txt` | local, offline | Plain, sequential layout for portal parsers; updates provenance. |
| Overflow handling | `tailor_service` layout loop (<= 4 attempts, `generator.shorten_cv` paid retries returning deltas via `services/cv_delta.py`), `layout_budget`; PDF warning for bullets spanning 3+ lines (`document_quality.inspect_cv_bullets`) | Automatic and invisible; failure raises "CV is still N pages after four layout attempts" | | **Paid retries** (layout_retry task) | `page_history` saved in manifest (`cv_page_history`); not shown in GUI. |
| Re-render edited text | `cli/commands/render.py` (reads `source/content.json`, preset, `--cv-only/--cover-letter-only`, `--mirror-configured`); `scripts/render_application.py` (adds `--check-word-layout`) | **CLI/script only.** GUI cannot edit CV/cover-letter text; no re-render button. | out refreshed artifacts, updates manifest and artifact provenance | local, free | GUI says only "Editable source is unavailable for this application" (`review.py:205`). Warns on 3rd page, cover letter != one page, != 4 paragraphs or 290-310 words. |
| Mirror to `OUTPUTS_DIR` | `ApplicationStore.mirror` (auto at generation when configured), `render --mirror-configured` | env + CLI | | | Not visible in GUI. |
| Word pagination check | `services/word_layout.py:inspect_word_layout`; `application_review.check_saved_word_layout`; `bridge.check_word_layout` | GUI button "Check Word pagination" (`review.py:208`) inside expander | LibreOffice headless; stores `word_layout` in manifest with artifact hash | Long (60 s timeout per file) | Advisory. The button renders only when the application already has Word files (`detail["word_layout"]` non-empty). |
| PDF quality checks | `services/document_quality.py:inspect_document`, `application_review.inspect_application_pdfs`; `load_review(include_quality=True)` | GUI button "Check PDFs" in expander (`review.py:252-272`) | per PDF: page_count, two parsers' word retention, missing fields, layout (preset, body size, used height per page), long-bullet list | local; moderate | Cached in session by fingerprint. Wording stresses "not an ATS score". |
| Artifact freshness | `services/artifact_provenance.py` (`record_artifact_provenance`, `artifact_freshness` -> current/stale/unknown) | GUI warning banner (`review.py:238-249`) | | no | Hashes content, render context, profile snapshot, renderer sources, artifact bytes. |
| Downloads / artifact listing | `bridge.list_artifacts` (pdf, docx, json, txt; hides `.sync-conflict-`), `read_artifact`; API download routes | GUI download buttons; API `/api/download/cv/{job_id}`, `/cover-letter/{job_id}` (DOCX), `/cover-letter-pdf/{job_id}` | | no | Labels via `document_label`, duplicated in `ui/review.py:_document_label`. |

### 1.5 Review, provenance and application management

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| Application library | `bridge.application_library` -> `application_review.load_application_summary` | GUI Applications page: text search, status + model filters, paging of 20 as full-width buttons (`app.py:485-565`) | rows: `job_id,title,company,created_at,date_source,status{Generated,Failed,Answers only,Legacy / incomplete},manifest.models` | no | Sorted by folder mtime. No sort controls, no thumbnails, no per-row cost, no delete/archive/rename/duplicate. |
| Open application (workspace) | `bridge.load_application` -> `application_review.load_review` | GUI `render_application` (`ui/review.py:75`): sections Documents / Answers / Details, then the claims panel, then "Application folder" | returns manifest, content, snapshot, provenance, freshness, word_layout, explanation, run_type, `changes`, letter_words | no (reading never calls a model) | URL state: `?profile=&application=&tab=` (`app.py:36-50`). |
| "What changed" (profile snapshot -> tailored CV) | `application_review.compare_cv`; `ui/review.py:highlighted` | GUI: Details tab -> expander (`review.py:357-387`) | list of `{section, before, after, kind: Changed/Added/Omitted/Ambiguous alignment}` | no | Compares against the saved snapshot, not the live profile. Roles matched by company+role+dates, projects by name. |
| "Why these changes" | saved `tailoring_explanation` | GUI Details tab -> expander (`review.py:388`) | five text fields | no | Labelled generated rationale. |
| Run details / provider replies | manifest `models, token_usage, calls, cache_hit, original_usage, original_calls, cost_source, provider` | GUI Details -> "Run details" (`review.py:409-455`); raw `st.json(manifest)` | | no | Requested model vs provider-reported model distinguished. |
| Saved posting + posting provenance | `application_review.read_saved_posting`; `source/posting_provenance.json` | GUI Details -> Saved posting expander | | no | |
| Application status lifecycle (applied, interview, deadline, notes) | none | **Not implemented.** Status is only the generation outcome. ROADMAP defers "Application management" (lifecycle tracking, notes, deadlines, document versions). | | | Biggest greenfield area. |
| Versioning of documents | `claim_cv_revision` revisions under `source/cv_revisions/<id>/`; `cv_balanced_*.pdf` | partial | | | No general revision list for edited text (because there is no GUI text editing). |
| Failed / partial runs | `status: failed` manifest | Library shows "Failed"; review shows `manifest.error` and downloads whatever survived | | | |

### 1.6 Suggested claims (confirm-first) and CV revisions

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| Claim suggestions produced at generation | `services/suggested_claims.py` (max 8; targets must exist in profile; question-shaped/duplicate/over-long dropped; `reject_suggestion_leak` blocks rendering unconfirmed text) | Panel "Suggested claims (confirm only what is true)" (`ui/claims_panel.py`); CLI `claims list`; `generate` prints a hint | `suggested_claims.json` items `{requirement, proposed_text, attach_to{type,...}, rationale, status}`; `dropped[]` | no | `dropped` suggestions are never shown in GUI (CLI `claims list --json` includes them). |
| Plan acceptance (dry run) | `claim_acceptance.accept_suggestions(dry_run=True)` via `bridge.plan_claims` | GUI confirmation step (renders `plan.changes`, `plan.skipped`, `plan.warnings`) | `AcceptanceResult{changes[Change(number,attach_to,text,description)], skipped, approach, warnings}` | no | Plan is recomputed each rerun while confirming. |
| Edit statement before confirming | `edits={number: text}` (limits: skill 80, other 1600 chars; must not be a question) | GUI text areas; CLI cannot edit | | no | |
| Accept into profile (write) | `bridge.accept_claims` -> `claim_acceptance.accept_suggestions` | GUI "Yes, these are true: add them"; CLI `claims accept [--category] [--yes]` | writes `<store>/profiles/<id>/profile.yaml` after `profile.backup-<ts>.yaml`; validates; restores on failure; records status `accepted` with exact text | no | Targeted text insertion preserves comments; may fall back to full YAML dump (comments lost) and warns. CLI `--category` creates a new skills category; the GUI/bridge have no category parameter. |
| Reject / dismiss | `bridge.reject_claims` | GUI "Dismiss selected"; CLI `claims reject` | profile untouched | no | |
| AI-drafted wording from user notes | `services/claim_drafting.py:draft_claim_wording` via `bridge.draft_claim` | GUI "Send notes and draft with AI (paid)" (non-skill claims only); no CLI | in: confirmed notes (<=1600 chars), target facts, posting requirement; out `ClaimDraft{profile_entry, cv_bullet, cost_usd, cost_estimated}` | **PAID**, ~1 call | Result prefills the profile entry text area; the CV bullet is used later in the revision form. |
| Save a CV revision using an accepted claim | `services/claim_cv_revision.py` (`claim_cv_options`, `save_claim_cv_revision`, `list_claim_cv_revisions`, `read_claim_cv_artifact`) | GUI inside the claims panel: "Use a confirmed claim in this CV" -> add or replace entry -> "Approve wording and save CV revision" (`claims_panel.py:90-154`); no CLI | validates CV with `validate_cv`, leak guard, renders PDF/Word/Text, requires <=2 pages + text preserved + no clipping/orphans; writes `source/cv_revisions/<ns>-<hex>/{cv.pdf,cv.docx,cv.txt,revision.json,source/*}` | local, free | Optimistic concurrency via `source_id` (hash of content+snapshot). Each revision builds on the latest revision. CV only; the cover letter is never revised. Separate action from saving the claim to the profile (ADR 0028). |
| Regenerate with accepted claims | `generate --no-cache` | CLI only; the GUI offers no "regenerate" button anywhere | | **PAID** | CLI prints the exact `generate --job-file .../job_description.txt --no-cache` command after accept. |

### 1.7 Portal answers

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| Answers-only application (no documents) | `services/answers_only_application.py:create_answers_only_application` | GUI "Answers only" button on New application (`app.py:298-327`) | creates folder with snapshot, posting, `content.json` skeleton, manifest `status: answers_only`, id `..._answers_<hex8>` | no | Opens the Answers tab. Works without PDF engine or API key. |
| Question editor (batch paste, limits, notes, confirmed facts, manual-only) | `ui/answers.py`; models `AnswerQuestion` (id, text<=4000, `max_characters`<=8000, `max_words`<=1500, notes<=2000, `confirmed_facts` <=12, `manual_only`) | GUI Answers tab; no CLI | up to `MAX_QUESTIONS=12` | no | Paste splits on blank lines. |
| Public company sources | `PublicAnswerSource(url, snippet)`, up to 8 | GUI expander (manual URL + excerpt; nothing is fetched) | | no | No automated company research (PRODUCT_AUDIT idea only). |
| Draft answers | `services/portal_answers.py:draft_answers` | GUI "Draft selected answers" (`answers.py:327`) | one batch call; evidence = snapshot profile facts (flagged `used_in` cv/cover_letter), posting, public excerpts, per-question facts; out `AnswerBatch{drafts[status drafted\|needs_facts\|over_limit\|manual\|invalid\|unavailable, text, evidence_ids, missing_facts, characters, words, limits_met], evidence, warnings, usage}` | **PAID**, 1 call | Uses the saved profile snapshot; "use current profile" fallback checkbox only when the snapshot is unusable. Salary/availability/authorization must be marked manual. Drafts, evidence and missing facts live only in Streamlit session state, never persisted. |
| Edit, copy, save answers | `services/portal_answer_store.py:load_answer_sheet/save_answer_sheet`; JS copy component in `ui/answers.py:13-62` | GUI | append-only revisions in `source/portal_answers/<uuid>.json`; optimistic `expected_revision`; conflicts/diverged history raise `AnswerSheetConflict` and are shown as warnings that disable Save | no | Live char/word counter and "Over limit" in the JS component. Saved sheet holds questions, edits, public sources, but NOT drafts, evidence or missing facts. |

### 1.8 Checks, doctor, evaluation

| Capability | Where | Exposed today | Inputs / outputs | Long / paid | Notes |
|---|---|---|---|---|---|
| Local setup checks | `cli/commands/doctor.py` (python, venv, store, profile, timezone, templates, pdflatex, **fonts**, outputs, api key) ; `bridge.setup_checks` | GUI Settings "Run local setup checks" (`app.py:578`) lists `status · check · detail`, fix text; CLI `doctor` | `Check{name,status,detail,fix}` | quick | GUI omits `check_fonts` and the profile id argument; `check_api_key(verify=False)` hard-coded (`services_bridge.py:605`). |
| Verify API key with provider | `doctor.check_api_key(verify=True)`, `_check_openrouter_key` (GET `/api/v1/key`, returns remaining limit), Gemini model-metadata call | **CLI only** (`doctor --verify-key`) | contacts the provider but generates nothing | network, free | GUI wording: "Configured; not verified". A "Verify key" button is a safe addition (AGENTS.md: key verification is allowed, generation requires asking first). |
| Re-validate saved applications against current rules | `services/application_check.py:check_applications` (`validate_content`, optional `render_content` into temp dir) | **CLI/script only** (`applications check [--render]`, `scripts/check_saved_applications.py`) | per application PASS/FAIL + messages (+ page counts) | local, free, offline, read-only | Excludes country-specific work-authorization wording checks (ROADMAP deferred). |
| Evaluation suite | `evaluation/` (`__main__`, `runner.dry_run/plan/live_run`, `screen`, `curation_diff`, `listing`, `reading_packet`, `curated_models`); cases from synthetic fixtures | **CLI only** (`python -m evaluation --list-models --screen --detect --report --packet`; `--live --cap-usd` spends) | offline default; `--live` paid and refused over cap | Live: long, **PAID** | Developer/owner tool for choosing models; skill `.agents/skills/cv-model-curation`. Not a user-facing feature. |
| Start/stop services | `scripts/start.py [--status\|--stop]`, `scripts/mac_gui.sh`, `windows_gui.ps1`, shortcut installers | scripts | starts FastAPI + Streamlit, tracks PIDs in `.runtime/services.json` | | UI does not depend on the API (in-process services). |
| Setup/migration scripts | `scripts/setup.py`, `check_setup.py`, `capture_candidate_policy.py`, `migrate_candidate_guidance.py` | scripts | | | Not for a product UI. |

---

## 2. End-to-end journeys implied by the code

State key: **P** = active `profile_id`; **S** = store reachable; **K** = provider key; **T** = pdflatex; **J** = `job_id`.

### Journey A: first run / onboarding
1. Install and configure (`scripts/setup.py`, `.env` with `OPENROUTER_API_KEY`/`GEMINI_API_KEY`, `CVTAILOR_STORE`). Needs: nothing. Surface: not in GUI.
2. Diagnose (`doctor`; GUI Settings "Run local setup checks"). Decision: key present vs verified (`--verify-key`, CLI only). Needs S, T, K.
3. Create profile: `profile new` (blank) or `profile import <yaml>`; richer path via the setup skill interview from a CV/PDF. Decision: sections to show (order/hidden), employer projects vs standalone projects, publications/activities, `rules` + `country_overrides` for work authorization, optional `writing_style.json`, optional `candidate_guidance.json`. All hand-edited. State written: `profiles/<id>/profile.yaml`.
4. GUI picks it up (sole profile auto-selected, ADR 0022) -> user lands on New application.

### Journey B: find a job, tailor, review, export (main loop)
1. Select candidate (P). Needs a usable profile. Decision point: more than one profile and no remembered choice -> must pick.
2. Find jobs (optional): keywords/country/city/remote/limit (defaults from `profile.job_search`); sources are sample boards unless CLI overrides. Read results: score, eligibility (`CHECK` = uncertain), expiry/dups not shown. Decision: open posting / "Use this posting". Output: pending handoff (description, company, role, country, provenance).
3. New application: paste or review handed-over posting; set company, role, country of employment; pick CV page layout (Automatic / Balanced); pick model (curated) or routing; decide fresh vs cache. Needs P, K, T (Generate disabled otherwise). Decision: **Generate (paid)** vs **Answers only** (free to create).
4. Generation runs (blocking; progress messages sparse). Branches: cache hit (free; re-validated, may silently fall to miss/paid), success, validation failure (drafts saved), layout failure (saved attempt), cost cap hit.
5. On success the GUI also builds the autofill DOCX/TXT, saves posting provenance, then navigates to the application workspace (J).
6. Review in the workspace: header downloads (CV PDF, letter PDF), freshness banner; Documents (PDF preview, compare page breaks, other downloads, Word pagination, PDF checks), Details (what changed, why, run details, posting), Answers.
7. Decision: documents acceptable? Yes -> download and submit externally (not tracked). No -> branches:
   a. Hand-edit `source/content.json` + `render` (CLI only), or
   b. Review suggested claims (Journey C), or
   c. Try balanced layout preview and save `cv_balanced_*.pdf`, or
   d. Regenerate with fresh draft (paid; CLI `--no-cache` or GUI fresh-draft checkbox on a new application; there is no "regenerate this application" action).
8. Portal answers (Journey D) when the application form asks questions.
9. Track outcome: not supported (no applied/interview/notes state).

### Journey C: confirm suggested claims, revise the CV
1. Open an application with pending suggestions (panel auto-expands). Needs P (suggestions are validated against the profile at generation; accept re-checks target exists).
2. Tick claims; decision: **Add to profile** or **Dismiss** (dismiss = profile untouched, status `rejected`).
3. Confirmation step: edit statement text per claim (skill <=80 chars, others <=1600, not a question). Optional **AI draft** from notes (paid; non-skill only) fills profile entry text and a CV bullet. Dry-run plan displayed (exact YAML change, method targeted-insert vs full-dump warning).
4. "Yes, these are true: add them" -> backup `profile.backup-<ts>.yaml`, write, validate, record `accepted`. This is a profile change, not a CV change.
5. After at least one accepted claim: "Use a confirmed claim in this CV" -> choose claim, add vs replace entry, edit CV wording (<=320 chars) -> "Approve wording and save CV revision" (separate approval). Output: revision folder with PDF/Word/Text; list "Revised CVs" with downloads. Errors: stale source id, hidden section, >2 pages, layout checks failing, wording already present.
6. Optionally regenerate (paid, CLI `--no-cache`) so the model can use the confirmed facts in a full new draft.

### Journey D: portal answers
1. From an application's Answers tab, or "Answers only" intake (needs only P and a saved posting).
2. Add questions (batch paste or one at a time), optional limits, notes, confirmed facts, manual-only flag, public company excerpts. Decide per question whether to draft or enter manually (salary/availability/authorization -> manual).
3. "Draft selected answers" (paid, one batch call, max 12 questions, prompt <=120k chars). Shows cost, warnings, `needs_facts`/`over_limit` messages, evidence. Suggestions never overwrite typed text; "Use this draft" does.
4. Edit, copy, Save answers (append-only revision; conflict states block save).

### Journey E: maintenance and trust
- Re-check old applications against new rules: `applications check [--render]` (CLI) then decide edit+render vs regenerate.
- Run PDF checks / Word pagination / freshness review on an application.
- After a profile edit: stale artifacts flagged by `artifact_freshness`; "Create / refresh CV for autofill".
- Switch machines or sync: store layout `profiles/`, `outputs/`; GUI prefs and cache are local (docs/PRIVATE_STORE_SYNC.md).

### Journey F: model and cost governance (power user / owner)
Set provider and routing in `.env`; optional `CVTAILOR_MAX_COST_USD`; `doctor --verify-key`; `python -m evaluation --list-models` / `--screen` / `--live --cap-usd`; read per-application cost in Details.

---

## 3. Hidden or poorly surfaced capabilities (ranked by user value)

| # | Capability | Today | Why it matters |
|---|---|---|---|
| 1 | **Edit and re-render CV / cover letter text** | CLI `render` after hand-editing JSON. GUI only says "Editable source is unavailable" if missing (`ui/review.py:205-206`). No text editor, no re-render, no revision list for edited text. | The most common fix after reading a document. Free and deterministic; the backend renderer already validates page counts and word counts and records provenance. |
| 2 | **Profile creation and editing, section order, rules** | New profile = CLI (`profile new/import`); everything else hand-edited YAML. GUI profile view is read-only and minimal (`ui/app.py:584-592`), empty-state just points to the CLI (`app.py:115`, `app.py:607-613`). | Blocks any non-technical first run. Work-authorization rules (country_overrides), banned tools, voice and guidance files all invisible. |
| 3 | **Regenerate an existing application / re-run with confirmed claims** | CLI `generate --job-file <app>/source/job_description.txt --no-cache`. No GUI action; the claims panel says "You can now review a CV edit" but never offers regeneration (`claims_panel.py:56`). | Natural next step after claims and profile updates. Needs a paid-call confirmation. |
| 4 | **Pre-run cost estimate and cache preview** | Only post-run cost (`review.py:348-350`, `services_bridge.py:181`). `Force a fresh draft` checkbox hides whether the result would be free (`app.py:261-265`). Cost cap (`CVTAILOR_MAX_COST_USD`) never shown. Price staleness never shown. | Paid-call consent should state expected cost and whether the cache will serve it. Needs new `estimate`/`would_hit_cache` service functions. |
| 5 | **Job search configuration (sources, own employers, ineligible toggle, dedupe/expiry)** | CLI-only `--ats/--softgarden-tenant/--personio-tenant/--only/--max-requests`; GUI calls `build_default_sources()` so sample boards appear as real results (`services_bridge.py:337-349`, ADR 0030). Form only has keywords/country/city/remote/limit (`app.py:404-421`). Dedupe groups, expiry verdicts, `include_ineligible` and sweep history are computed but not rendered. | Biggest discovery-quality gap; ADR 0030 already commits to a redesign, so the UI should be built around per-profile saved sources rather than the sample list. |
| 6 | **Posting from a URL / email / portal** | Not implemented anywhere. Only paste (`app.py:207`) or the search handoff. | Common starting point; needs a fetch+extract service and provenance. Handoff provenance plumbing (`save_posting_provenance`) already exists. |
| 7 | **Application tracking (status, applied date, deadline, notes, outcome)** | None; status = generation result only (`application_review._application_summary`). Library is a column of full-width buttons (`app.py:556-565`) with no sort, no cost/page columns, no delete/archive. | ROADMAP defers it; the redesign should reserve space. Needs a new state file per application. |
| 8 | **`applications check` (re-validate against current rules)** | CLI/script only. | Valuable after upgrades or profile edits; free, offline, read-only; can run as a library health view. |
| 9 | **Verify API key** | CLI `doctor --verify-key`; GUI text "Configured; not verified" (`app.py:272-276`) with no way to verify; `setup_checks` hard-codes `verify=False` (`services_bridge.py:605`) and omits `check_fonts`. | Cheap, safe, removes a common failure before a paid run. |
| 10 | **CV layout preset choice (comfortable / standard / compact)** | CLI/script `--layout-preset`; GUI offers only Automatic vs Balanced (`app.py:242-247`). | Lets the user trade density for readability when auto is not what they want; also useful in a re-render action. |
| 11 | **Claim `--category` (new skills category) and "dropped" suggestions** | `claims accept --category` (CLI). Bridge `accept_claims` has no category parameter; skill claims can only go to the suggested category (`services_bridge.py:649-656`). `dropped[]` never shown. | Small, but a user cannot accept a skill into a new category from the GUI. |
| 12 | **Layout/quality tools buried** | PDF checks, Word pagination and Create-autofill live in the "More downloads and document checks" expander (`review.py:175-235`); layout preview is a second expander; "What changed" and "Why" are expanders inside the Details tab (`review.py:357-388`); claims panel is rendered below the tabs, independent of the tab radio (`review.py:144`). | The review workspace has four navigation layers (radio, expander, sub-expander, below-the-fold panel). |
| 13 | **Progress / cancel for generation** | One status line per phase; `st.status` blocks the page (`app.py:330-346`). Only three messages exist (`pipeline.py:358,388`, `tailor_service.py` cache hit). | A long, paid, non-cancellable action with almost no feedback. Needs richer progress events (see section 4). |
| 14 | **Run details: page history, drafts, validation retries, cost per call** | Raw `st.json(manifest)` and a dataframe (`review.py:433-456`); `cv_page_history` and `drafts.json` not surfaced. | Explains why a run cost more or shortened content. |
| 15 | **Mirror target, writing-voice and guidance status** | Env/files only. | Silent effects on output and on cache invalidation. At minimum a read-only "active voice / guidance / mirror" status. |
| 16 | **Hard-coded country list and duplicate mapping** | `app.py:226-237` (7 names) and `app.py:191-198` (6 ISO codes). Not derived from the profile's `country_overrides` or `home_countries`. | Country drives work-authorization wording, so the picker should show which rule applies. |
| 17 | **Evaluation / curation tooling** | CLI only (`python -m evaluation`), intentionally out of the GUI. | Keep out of the product UI; mention only as an admin path. |
| 18 | **FastAPI** | Only `POST /api/tailor` plus three download routes; no profile/application/claims/answers/search endpoints; ADR 0020 keeps it for programmatic use. | Relevant if the new frontend is not Streamlit (see section 4). |

Other UI awkwardness worth fixing during the redesign: `_document_label` duplicated in `ui/review.py:15-25` and `bridge.document_label` (`services_bridge.py:504`); profile id kept in `st.session_state` and query params both (`app.py:33,36-50`); answers editor state kept in Streamlit session state keys (`ui/answers.py:74-100`) so a stateless frontend must own that state; claims panel uses session-state "confirming" flow across reruns (`claims_panel.py:15-37`); search results and handoff held only in session state (`app.py:433,476`).

---

## 4. API surface a new frontend needs

### 4.1 Operations `ui/services_bridge.py` already provides

All take a loaded `config`. `profile_id` is passed explicitly everywhere (except `model_options`, `source_coverage`, `preflight`, `setup_checks`, `describe_configuration`, `format_cost_breakdown`, `posting_handoff`, `document_label`).

| Function | Signature | Returns | Cost / effect |
|---|---|---|---|
| `list_profiles` | `(config)` | `list[ProfileOption{profile_id,name,roles,problem; is_usable; label()}]` | read |
| `require_profile_id` | `(config, explicit)` | `str` or raises `InvalidProfileIdError`/`UnknownProfileError` | read (unused by GUI) |
| `load_profile` | `(config, profile_id)` | `Profile` (pydantic) | read |
| `describe_configuration` | `(config)` | `dict{store, store_exists, profile_count, usable_profiles, configured_profile_id, model, provider}` | read |
| `initial_gui_profile` / `remember_gui_profile` | `(config, available_ids)` / `(config, profile_id)` | `str\|None` / `bool` | writes `preferences/gui.json` |
| `model_options` | `(config)` | `list[CuratedModel{id,tier,label,guidance,input_per_1m,...}]` (empty unless provider is openrouter) | read |
| `generation_config` | `(config, selected_model_id)` | `Config` variant; raises `ValueError` if not curated | read |
| `preflight` | `(config)` | `dict{key_configured: bool, models: {cv,cover_letter,layout_retry: str}, pdf_engine: bool}` | read |
| `setup_checks` | `(config)` | `list[dict{check,status,detail,fix}]` (status strings per `doctor.Check.as_dict`) | read; no network |
| `run_generation` | `(config, profile_id, job_description, *, company, role, work_country, use_cache=True, balance_cv_pages=False, status=callable)` | `GenerationOutcome{ok, job_id, job_folder, summary[str], error, drafts_saved, details{applications[]}}` | **Long, PAID**, blocking, no cancel |
| `format_cost_breakdown` | `(usage)` | `list[str]` | pure |
| `run_job_search` | `(config, profile_id, query, *, preferences, sources, include_ineligible)` | `SearchOutcome` | Long, free |
| `search_from_fields` | `(config, profile_id, keywords, country, city, remote, limit)` | `SearchOutcome{query, results[MatchResult{job, eligibility, evidence, blockers, unknowns, score, explanation()}], groups, expiry, failures{source:msg}, notes[], jobs_read}` | Long, free; writes `jobs/<id>/sweep.json` |
| `source_coverage` | `()` | `list[str]` | pure |
| `posting_handoff` | `(job)` | `dict{job_description, company, role, work_country, provenance{url,source,posted_at,transferred_at}}` | pure |
| `save_posting_provenance` | `(config, profile_id, job_id, provenance)` | None (writes `source/posting_provenance.json`) | write |
| `job_folder` | `(config, profile_id, job_id)` | `Path\|None` | pure |
| `list_artifacts` | `(folder)` | `list[dict{name,path,size_kb,mime,kind}]` | read |
| `list_applications` | `(config, profile_id, limit=20)` | `list[dict{job_id,path,artifacts,has_content}]` | read |
| `application_library` | `(config, profile_id)` | `list[dict{job_id,title,company,created_at,date_source,status,manifest{models}}]` | read |
| `load_application` | `(config, profile_id, job_id, *, include_quality=False)` | `dict` with summary fields plus `path, manifest, content, snapshot, posting_provenance, artifact_freshness{name:{status,...}}, word_layout{name:{status,report}}, document_quality{name:report}, quality_fingerprint, explanation, warnings, run_type, changes[{section,before,after,kind}], comparison_available, letter_words, artifacts[]` | read; quality pass is local CPU |
| `saved_posting` | `(config, profile_id, job_id)` | `str` | read |
| `read_artifact` | `(config, profile_id, job_id, name)` | `bytes` (only names in `list_artifacts`) | read |
| `export_upload_cv` | `(config, profile_id, job_id)` | `dict{cv_upload_docx_path, cv_upload_text_path}` | local render, writes |
| `check_word_layout` | `(config, profile_id, job_id)` | `dict{filename: report{page_count,engine,warnings,artifact_sha256,page_limit,exceeds_page_limit,status}}` | Long (LibreOffice), writes manifest |
| `claims_for` | `(config, profile_id, job_id)` | `list[dict{number, requirement, proposed_text, attach_to, rationale, status, accepted_text?, accepted_attach_to?}]` | read |
| `plan_claims` | `(config, profile_id, job_id, numbers, *, edits)` | `AcceptanceResult(dry_run)` | read; writes nothing |
| `accept_claims` | `(config, profile_id, job_id, numbers, *, edits)` | `AcceptanceResult{changes,skipped,approach,warnings,backup}` | **writes profile.yaml** (after backup) |
| `reject_claims` | `(config, profile_id, job_id, numbers)` | `list[int]` | writes `suggested_claims.json` |
| `draft_claim` | `(config, profile_id, job_id, number, notes)` | `ClaimDraft{profile_entry, cv_bullet, cost_usd, cost_estimated}` | **PAID** |

Backend functions the GUI calls directly, bypassing the bridge (should be wrapped for a new frontend): `services.claim_cv_revision.{list_claim_cv_revisions, read_claim_cv_artifact, claim_cv_options, save_claim_cv_revision}`, `services.application_layout_preview.{layout_source_revision, preview_saved_cv_layout, save_cv_layout_preview}`, `services.portal_answer_store.{load_answer_sheet, save_answer_sheet}`, `services.portal_answers.draft_answers` (+ `provider.build_provider`), `services.answers_only_application.create_answers_only_application`, `services.suggested_claims.describe_target/limits`, `services.claim_acceptance.MAX_CONFIRMED_TEXT`.

### 4.2 Existing FastAPI (`backend/main.py`)

`GET /health`; `POST /api/tailor` (sync, paid; body `TailorRequest`; no `balance_cv_pages`, no status stream); `GET /api/download/cv/{job_id}`, `/api/download/cover-letter/{job_id}` (DOCX), `/api/download/cover-letter-pdf/{job_id}` (all take `?profile_id=`, validate `job_id` against `^[A-Za-z0-9_-]+$`). Config is rebuilt per request.

### 4.3 Gaps: new endpoints a non-Streamlit frontend would need

Reads (cheap, JSON): profiles list/detail (full `Profile` incl. richer sections and rules); config + preflight + key presence + cost cap + price staleness; application list/detail (the `load_application` shape), per-artifact download by name, posting text; claims list; claim CV revisions list and artifact download; answer sheet load; job-source coverage; gui preference get/set.

Writes (local, free): profile create/import/export/validated edit (none exists; needs a backup + validate + atomic write like `claim_acceptance`), set rules/country overrides, writing_style/candidate_guidance read-write with validation (parsers `parse_candidate_guidance`, `writing_voice_context` exist); claim plan/accept/reject (wrap bridge); save CV revision; answer-sheet save with `expected_revision` and 409 on `AnswerSheetConflict`; create answers-only application; export upload CV; **edit content.json and re-render with preset choice** (`render` logic lives in the CLI module and would need extraction into a service); `applications check`; verify key (network, free); per-application tracking state (new).

Paid/long operations that need job semantics (start -> poll or stream -> result), with explicit confirmation tokens: 
- generation (`tailor_documents`): needs events for "drafting CV", "validating", "drafting cover letter", "rendering layout attempt n", "shortening (page count)", "rendering letter/Word/PDF", "cache reused", spend so far, and a cancel flag checked between provider calls. Today only `status_callback(str)` with 3 messages exists.
- claim drafting (`draft_claim_wording`), portal-answers drafting (`draft_answers`): one provider call each; short but paid; return cost.
- job search: network-long, free; per-source progress (`collect_jobs` iterates sources sequentially, could emit `source started/finished/failed`).
- layout preview, PDF quality, Word layout check, `applications check --render`: local long-running; return progress or a result handle.
- regenerate-from-application (new): reads `source/job_description.txt` and `content.json` fields (company, role, country) and calls `tailor_documents`.
- pre-run estimate (new): `pricing.estimate_cost` plus prompt-size accounting; `would_hit_cache` using `cache_key`.

Also needed: stable, serialisable error classes (`InvalidProfileIdError`, `UnknownProfileError`, `ProfileMismatchError`, `ClaimError`, `AnswerSheetConflict`, `LaTeXRendererError`, `ProviderError`, `ConfigError`, budget exceeded) mapped to statuses; a pydantic response model for `load_application`; and an auth model if ever hosted (ROADMAP: deferred).

---

## 5. Invariants a UI must respect

1. **`profile_id` is explicit and fail-closed on every operation** (ADR 0003). CLI/API/services never infer it; the UI passes it on each call, rejects blank/malformed/unknown ids (`validate_profile_id`: lowercase letters, digits, `-`, `_`), and never reads or writes across candidates. `tailor_documents` also refuses an id/profile name mismatch (`ProfileMismatchError`).
2. **GUI profile memory (ADR 0022):** restore the remembered id only if it is currently usable; otherwise auto-select only when exactly one usable profile exists; otherwise require a choice (no first-item default, no name inference). A user clear is not auto-reselected in the same session. Remember the id only (`<store>/preferences/gui.json`, atomic write, warn if it fails). Show the active full name and id on every screen. Switching profile clears draft, search, claim-editor, answer-editor and review state. Corrupt/stale memory is ignored.
3. **Paid calls need explicit confirmation** (AGENTS.md: ask before paid AI generation): generation, layout-retry (implicit in generation), claim AI drafting, portal-answers drafting, evaluation `--live`. Free/local: search, review, PDF/Word checks, layout preview, re-render, `applications check`, claim accept/reject, autofill export, key verification (contacts provider, no generation). Show model, provider, what data is sent (profile + posting), cap (`CVTAILOR_MAX_COST_USD`), and whether the cache may serve the request. A fresh draft always costs money.
4. **No fabrication.** Suggested claims are questions, never in a document until the candidate marks them true; accepting writes to the private profile only after confirmation and backup; the `reject_suggestion_leak` guard rejects CVs containing unconfirmed text. Do not pre-tick claim checkboxes, never auto-accept, never edit profile facts to fit a job. AI-drafted claim wording is a preview only and needs separate confirmation.
5. **Two separate approvals:** (a) "Save confirmed fact to profile" (`accept_claims`, writes profile.yaml, backup) and (b) "Approve wording and save CV revision" (`save_claim_cv_revision`, writes a new revision folder, never overwrites originals). The UI must not merge them or imply (a) changes existing documents.
6. **Limits and checks:** CV <= 2 pages; cover letter exactly 1 page, 4 paragraphs, 290-310 body words, no colons/semicolons or salutation/signature in paragraphs; CV bullets <=320 chars for claims (`MAX_BULLET_CHARS`), skill names <=80, confirmed claim text <=1600; portal answers <=12 questions, <=8 public sources, question text <=4000, answer <=8000, per-question character/word limits; posting >=50 characters and not a pasted `cvtailor` command. Layout/extraction checks are advisory and must not be presented as an ATS score or hiring guarantee. Show the exact limit near any editor.
7. **Work authorization:** pass the actual country of employment (not HQ). Immigration/permit/sponsorship wording is governed by the profile's `rules` + `country_overrides`; CV never carries sponsorship text; employer-support wording only in the cover letter and only where the override requires it; an empty `work_authorization` suppresses the label. The UI must not generate or suggest authorization wording itself.
8. **Gap and tense rules are enforced server-side:** documents never state missing qualifications; ended roles are not "current". A UI that lets users edit text must run the same validators (`services.application_check.validate_content`) and show failures.
9. **Privacy:** profiles, outputs, cache, sweeps, answers, preferences and revisions stay in the private store; never place real data in the repository, URLs or logs; never print API keys (show present/missing and, after verification, remaining limit only). Do not send candidate data to anything but the configured provider; public company excerpts are user-pasted, not fetched.
10. **Read paths never call a model.** Opening/comparing/checking an application, viewing its rationale, rendering previews and re-rendering existing text are free. Keep reads separate from paid actions in the UI.
11. **Never silently overwrite:** layout preview is saved to a new `cv_balanced_<hash>.pdf` and only if checks pass and `source_revision` matches; claim revisions are new folders; answer sheets are append-only revisions with `expected_revision` and conflict states (diverged history, sync-conflict files, incomplete history disable Save); profile writes keep a timestamped backup and roll back on failure; saved manifests are merged, not replaced.
12. **Honest provenance and freshness:** requested model vs provider-reported model; cached runs separate original usage from this run; missing historical values read "Not recorded"; freshness status current/stale/unknown (unknown is not proof of error); estimated vs reported cost labelled.
13. **Results are partial-data tolerant:** legacy or failed applications may lack content, snapshot, manifest fields or PDFs. Hide or explain actions that need them (compare, layout preview, autofill export, claims-to-CV).
14. **Path safety:** job ids match `[\w.-]+` / `^[A-Za-z0-9_-]+$` (API); artifacts are only served from the application folder and must not be a symlink or `.sync-conflict-*` copy; revisions match `\d{19}-[0-9a-f]{10}`.
15. **Platform notes:** PDF output needs pdflatex; Word pagination needs LibreOffice (optional); on Windows use `.venv/Scripts/python.exe`, on macOS/Linux `.venv/bin/python`.
16. **Streamlit-only behaviours to re-implement deliberately:** URL-addressable workspace (`profile`, `application`, `tab` query params), preserving form inputs across navigation (`retain_inputs`), copy-to-clipboard with live counters, PDF inline preview.

---

## 6. Facts a designer might otherwise miss

- The GUI has exactly four pages (New application, Find jobs, Applications, Settings & help); the application workspace is a sub-view of Applications, entered after generation via `st.switch_page`.
- Default provider is OpenRouter with a single curated model today; the GUI selector is effectively a one-option dropdown and empty for Gemini.
- Status values in the library: `Generated`, `Failed`, `Answers only`, `Legacy / incomplete` (computed, not user-set).
- Search "Matching signals" is a count of named reasons; eligibility has three values (eligible / uncertain / ineligible); a keyword missing from the posting hides the job.
- `docs/ROADMAP.md` defers: job-search redesign (ADR 0030), application management, hosted use/auth, localisation, work-authorization checks inside `applications check`.
- `docs/design/gui-proposal.html` and `docs/GUI_REVIEW.md`, `docs/PRODUCT_AUDIT.md` contain earlier UI proposals (historical).
