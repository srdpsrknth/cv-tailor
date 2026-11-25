# How to generate a CV and cover letter

A step-by-step guide for actually using CV Tailor. Written for the person doing the
job application, not for a developer reading the code.

**Two ways to use it, doing the same things:**

| | Command line | Web interface |
|---|---|---|
| Start | `cvtailor ...` (below) | `python scripts/start.py` then open the URL it prints |
| Best for | Anything that breaks; scripting; precision | Browsing applications, reading match explanations |
| Requires | nothing extra | nothing extra |

The web interface has four pages: **New application**, **Find jobs**, **Applications** and
**Settings & help**. It reads the same store, so an application generated in a terminal appears
in the browser and vice versa. **The command line is the supported path for anything
that goes wrong** — it has clearer errors and no browser in the way.

**Windows shortcut:** double-click **CV Tailor** on the desktop or find it in the
Start menu. It starts the GUI and opens your browser automatically. Choose your
profile in the sidebar, then use Generate or Find jobs. Closing the browser leaves
the app running; **Stop CV Tailor** shuts it down. To install these shortcuts, see
[DEVELOPMENT.md](DEVELOPMENT.md#windows-gui-shortcuts).

**This guide works on Windows, macOS and Linux.** Activate the project's virtual
environment once per terminal, then every command is written `python cvtailor.py ...`:

```bash
# macOS / Linux (bash, zsh)
source .venv/bin/activate
```
```powershell
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
```

Without activating, call the interpreter directly: `.venv/bin/python` on macOS/Linux,
`.venv\Scripts\python.exe` on Windows. Examples that span lines use the bash/zsh
backslash (`\`); in PowerShell use a backtick (`` ` ``) instead. Store paths are shown as
`<store>` (your `CVTAILOR_STORE`, for example `~/cv-tailor-data` or `..\cv-tailor-data`).

```bash
python cvtailor.py --profile-id <profile_id> generate --job-file job.txt
```

> **Setting up on a Mac for the first time?** Read
> [MAC_SETUP.md](MAC_SETUP.md) first — it covers MacTeX, the private store and
> credentials. This guide assumes the installation already works.

**What this does:** you give it a job posting, it writes a CV and cover letter
tailored to that posting using your saved profile, and produces a PDF (and Word
file) ready to send.

**What it costs:** roughly **$0.003 per application** on the default model
(`openai/gpt-6-luna`) — about a third of a cent. A full application is one CV call
plus one cover-letter call. Re-rendering an existing application is **free**, and so
is job search.

---

## Before the first run

You need three things. The `doctor` command checks all of them:

```bash
python cvtailor.py doctor
```

| Check | What "ok" means |
|---|---|
| `store` | Your private data folder exists, outside this repository |
| `profile` | Your CV profile is loaded and has roles in it |
| `pdflatex` | The PDF engine is installed (MacTeX on a Mac, MiKTeX on Windows) |
| `api key` | Your OpenRouter key is set and a model is chosen |

If any line says `FAIL`, fix that before continuing — the message tells you how.

> **On macOS, `pdflatex` is found even without PATH setup.** MacTeX installs to
> `/Library/TeX/texbin` and adds it to PATH only for login shells. CV Tailor searches
> that location explicitly, so a script or IDE terminal finds it anyway. If it still
> fails, set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` in `.env`.

> **Windows only: do not ignore `outputs ... Permission denied`.** On a Windows checkout where
> `.venv` inherited a Low integrity label, so its Python runs at Low integrity even
> from a normal terminal and cannot write to the private store. PowerShell being
> able to write there does not prove Python can. See the targeted repair in
> [DEVELOPMENT.md](DEVELOPMENT.md#windows-python-output-permission-error).

List available profiles and substitute your chosen ID for the synthetic example `sample-analyst`.

```bash
python cvtailor.py profile list
```

> **Where does `--profile-id` go?** It is a *global* option, so it goes **before**
> the command name, not after it:
>
> ```bash
> # right
> cvtailor.py --profile-id sample-analyst generate --job-file job.txt
> cvtailor.py --profile-id sample-analyst profile show
>
> # wrong -- "unrecognized arguments"
> cvtailor.py profile show --profile-id sample-analyst
> ```
>
> Pass the candidate ID explicitly, or set `CVTAILOR_PROFILE_ID` in your own `.env`.

---

## The normal workflow: a job posting you found

### 1. Save the posting to a text file

Copy the full job description — responsibilities, requirements, everything — into a
plain text file. For example `job.txt`.

Include the job URL and today's date at the top if you have them; it makes the saved
record easier to trace later.

Or save the clipboard **while it contains the posting**, then inspect the file:

```bash
# macOS
pbpaste > <store>/jobs/sample-analyst/job.txt
# Linux (X11: xclip; Wayland: wl-paste)
xclip -selection clipboard -o > <store>/jobs/sample-analyst/job.txt
wl-paste > <store>/jobs/sample-analyst/job.txt
head -5 <store>/jobs/sample-analyst/job.txt
```
```powershell
# Windows (PowerShell)
Get-Clipboard | Set-Content -Encoding utf8 <store>\jobs\sample-analyst\job.txt
Get-Content <store>\jobs\sample-analyst\job.txt -TotalCount 5
```

Use your actual private store and profile directory; create the directory first if
needed. Check that the first lines name the role and employer. Copying the generation
command replaces the clipboard, so passing the clipboard inline (for example
`--job "$(pbpaste)"`) can accidentally submit the
command itself. A saved file makes the input inspectable and repeatable. The CLI
rejects input starting with a CV Tailor invocation before any paid call and prints
the posting's length and first line before generation.

> **Tip:** if a website blocks copying, the posting is often also readable via the
> page's "JobPosting" data. Ask an agent to fetch it, or paste it from the email
> alert. Never guess at requirements you cannot read.

### 2. Generate

```bash
python cvtailor.py --profile-id sample-analyst generate --job-file job.txt
```

For a posting saved in the store, for example:

```bash
python cvtailor.py --profile-id sample-analyst generate \
  --job-file <store>/jobs/sample-analyst/job.txt \
  --company "Northwind Analytics" --role "Analytics Engineer" --country Germany
```

The company and role flags prevent generic inferred names if the posting is ambiguous.

**Country of employment** is the actual job location. Choose or enter the country
in the Generate page, or pass `--country` in the CLI. An explicit selection
overrides location inference from the posting.
It changes the work-authorization instructions and validation, is saved with the
application, and participates in the cache key. Changing country can therefore
require a new paid draft. It does not change the document language, source profile,
page/word limits, or the separate Find jobs country filter.

**Search defaults** are optional. For example, a synthetic profile can start
searches with the following private `profile.yaml` settings.

```yaml
job_search:
  keywords: data engineer
  country: CA
  city: Toronto
  remote_only: true
```

CLI flags override the selected profile's values. Omit a flag to use its profile
default, pass an empty string to clear a text filter, or use `--no-remote` to allow
any work mode. In Find jobs, edit or clear the prefilled fields. Existing profiles
without `job_search` start unfiltered. Source coverage still determines which
markets and filters can return results.

**Calendar timezone** comes from `CVTAILOR_TIMEZONE` in the local environment or
`.env` and defaults to UTC. To retain the former Berlin calendar for new application
IDs and upload CV filenames, set `CVTAILOR_TIMEZONE=Europe/Berlin`. Existing IDs
and files keep their names. Stored timestamps remain in UTC.
The cover-letter date and filename year follow the same setting; without it the
letter uses the machine's local date.

**Cover-letter wording** is optional. A private profile can set its salutation and
sign-off; `{company}` is the only placeholder. Omitted fields keep the defaults
(`Dear {company} Hiring Team,` and the letter's own closing, normally
`Warm regards,`). The DOCX and PDF letters always match, and the profile value wins
over wording the model wrote. The recipient line stays `Hiring Team`.

```yaml
letter:
  salutation: "Dear {company} recruiting team,"
  sign_off: "With best wishes,"
```

**Ongoing education** uses `ongoing: true` in a private profile's education
entry. Omit `end_year` if completion is unknown, or set it to the expected year
to show, for example, `Present (expected 2028)`. Completed degrees use the
existing `start_year` and `end_year` fields. An optional `highlights` list
(coursework, thesis title, focus) prints as one compact line under the degree,
joined with ` · `, in the PDF, Word and text exports:

```yaml
education:
  - degree: MSc Synthetic Analytics
    institution: Sampletown Institute of Technology
    start_year: 2018
    end_year: 2020
    highlights: ["Thesis: Synthetic Forecasting", "Focus: causal inference"]
```

**Certifications** may be plain strings or `{name, issuer, year}` objects (`issuer`
and `year` optional); the latter prints as `name (issuer, year)`.

**Standalone projects** go in the private profile's top-level
`standalone_projects` list. Each entry has a unique `name` and a `bullets` list.
For example:

```yaml
standalone_projects:
  - name: Transit Access Map
    bullets:
      - Mapped public transport gaps with open data.
```

A project may also carry `dates` (free text), `technologies` (a list, printed as a
`Technologies:` line like an employer role) and `context` (for example
`University team project`). They print as `Name — context | dates`. Employer
projects under `experience[].selected_projects` use the same fields and ignore them
unless set.

CV generation selects relevant projects by exact name and may also reword a
project's bullets toward the posting. Selecting a name renders the profile's
bullets verbatim; an object `{name, bullets}` renders the model's bullets, which
must use only facts already in that project's profile bullets (no new tools,
numbers, outcomes or responsibilities), number between one and one more than the
profile's, and pass the same banned-tool and gap checks as employer bullets. A
project with no profile bullets can only be selected by name. Metadata (`dates`,
`context`, `technologies`) always comes from the profile. Set
`standalone_projects_policy: all` (default `select`) to require every standalone
project, in profile order; layout retries may shorten reworded bullets but never
drop a project. The Projects section appears after work experience. Saved
application previews and autofill exports use the saved profile snapshot.
For a manual edit to `content.json`, set `cv.standalone_projects` to an ordered
list of names (or `{name, bullets}` objects) from the profile used for rendering. Omit the field or use an
empty list to leave the section out. Keep employer-specific projects under the
corresponding experience entry.

**Experience entries** accept two more optional fields. `optional: true` lets the
model leave that role out when it is irrelevant or to save space; every other
role is still required. `display_name` is a short company name used in compact
places (the project parenthetical and continuation headers) while the heading
keeps the full employer. A role with no regular `bullets` and exactly one project
prints the project name as an italic subheading, without the `Selected Projects:`
label or company parenthetical.

**CV section choices** are optional. Set `cv_section_order` in the private profile
to move sections to the front of the CV body, in the order listed:

```yaml
cv_section_order: [education, projects, experience]
```

Valid names are `experience`, `projects`, `education`, `certifications`, `skills`,
`languages`, `publications`, and `activities`. Any unlisted sections follow in that default order. Set
`cv_hidden_sections` to hide any of those, `summary`, or `employer_projects`.
For example, `cv_hidden_sections: [projects]` keeps employer projects nested under
Experience and hides the dedicated Projects section. A visible Projects section
needs at least one selected standalone project. Hiding a section preserves its
source data. The contact header stays at the top.

These preferences apply to the standard PDF and autofill DOCX and text. Saved
application exports from review use the saved profile snapshot. Older custom
LaTeX templates with a fixed layout continue to use their original layout.

For a one-off layout, copy the profile to a private YAML file, adjust the display
settings in that copy, then use `cvtailor --profile <private-copy.yaml> render
--content <application>/source/content.json --cv-only`. Render in a copy of the
application folder if you want to keep both versions.

**Publications and activities** are optional. Add one plain-text citation or
activity per line in the private profile, or an object `{text, bullets}` to list
supporting bullets under it. `text` (the citation) is always printed verbatim and
never sent for rewording. The standard PDF, Word, and text
exports use those entries directly. Empty lists produce no headings, and hidden
sections keep their source entries in the profile.

```yaml
publications:
  - "A. Sample (2025). Mapping Transit Access. Example Journal."
  - text: "A. Sample (2024). Second Paper. Example Press."
    bullets: ["Peer-reviewed by two referees."]
activities:
  - "Volunteer mentor, Community Data Club (2025–present)."
cv_section_order: [education, publications, experience]
cv_hidden_sections: [activities]
```

For an LLM-guided setup from scratch or from a résumé PDF or Word document, ask
your coding assistant to follow `skills/cv-tailor-setup/SKILL.md` in the checkout.
It guides private profile intake, section choices, configuration, and the first
CV and cover-letter generation.

For a profile holding a German EU Blue Card, the current rules behave as follows:

| Selection | Current document behaviour |
|---|---|
| Germany | Preserve the profile's status in the CV; do not require an overseas sponsorship sentence |
| Ireland | CV label: German EU Blue Card holder; final letter paragraph must mention the German card and employer support for a local employment permit, without claiming an Irish Blue Card |
| Netherlands | Same CV label; final letter paragraph must mention the German card and employer support for appropriate work authorization |
| India | Uses the selected profile's country override when configured; confirmed local work rights suppress immigration and sponsorship wording and allow country-specific tailoring emphasis |

These are the application's writing rules, not a determination of legal eligibility.
In particular, selecting India does not establish citizenship or existing Indian work
rights. Confirmed exceptions belong in that candidate's private profile under
`rules.country_overrides`, keyed by country name or ISO code. A rule declares
`work_authorization` (empty suppresses the CV immigration label),
`requires_employer_support`, optional `authorization_basis` recording the confirmed
reason, and optional `tailoring_guidance`. For a profile with
confirmed local work rights, the prompts and validation omit Blue Card, visa,
permit and sponsorship wording and can emphasize relevant experience abroad.
Other profiles retain their own rules; no citizenship is inferred from the country
selection. Updating these rules changes the generation cache key. Existing saved
applications are not rewritten automatically.

Useful variations:

```bash
# Give the company and role explicitly, instead of letting it infer them
python cvtailor.py --profile-id sample-analyst generate --job-file job.txt \
    --company "Northwind Analytics GmbH" --role "Analytical Engineer"

# Say which country the job is actually in (not the company headquarters)
python cvtailor.py --profile-id sample-analyst generate --job-file job.txt \
    --country Germany

# Paste the posting inline instead of using a file
python cvtailor.py --profile-id sample-analyst generate --job "We are looking for..."
```

**`--profile-id` is required and has no default.** That is deliberate: it makes it
impossible to generate documents for the wrong person. If you forget it, the tool
stops and tells you the available ids rather than guessing.

### 3. What happens while it runs

1. It drafts the CV, then the cover letter — one AI call each.
2. It renders the CV and **counts the pages**. If it is over two pages it trims and
   retries automatically (this is the "layout retry" — only the changed part is
   re-sent, so a retry is cheap).
3. It checks the cover letter is four paragraphs and 290–310 words.
4. Only when both pass does it report success.

Expect a minute or two. You will see progress in the terminal.

### 4. Collect the documents

Everything lands in your private store, **not** in this repository:

```
<store>/outputs/<profile_id>/<job_id>/

    2026_CV_<your_name>_<role>.pdf          <- formatted CV with searchable text; parser behavior varies
    2026_CV_<your_name>_<role>_upload.docx  <- plain single-column Word CV for portal autofill
    2026_CV_<your_name>_<role>_upload.txt   <- plain-text copy for manual portal paste
    2026_cover_letter_<company>_<role>.pdf  <- the cover letter
    2026_cover_letter_<company>_<role>.docx <- Word version, if a form wants it
    source/
        content.json          <- the editable text (see revisions below)
        job_description.txt   <- the posting it worked from
        generation_result.json<- what was produced and whether it passed
```

Not sure where your store is? `cvtailor doctor` prints it. Find the newest folder by
date:

```powershell
# Windows
Get-ChildItem <store>\outputs\<profile_id> |
    Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, LastWriteTime
```
```bash
# macOS / Linux
ls -lt <store>/outputs/"$CVTAILOR_PROFILE_ID" | head -4
```

### 5. Read them before you send them

**Always open both PDFs and check them.** The tool verifies page count and word
count, and the test suite checks for clipped text and orphan headings — but no
automated check reads your documents the way a recruiter will.

Look for: correct employer names and dates · no orphaned section headings · nothing
running off the page · the cover letter naming the right company and role · nothing
invented that you cannot back up in an interview.

The CV body uses one column, readable 10.5–11pt dark body text and visible skill separators.
The renderer compares comfortable, standard and compact typography plus eligible
employer-boundary breaks using identical wording. It selects a readable fit within
two pages, preferring balanced page endings. Genuine short CVs can remain one page.
Only when no readable preset fits does generation request content shortening.
The PDF and saved provenance record the selected preset and advisory page measurements.
For an explicit typography choice when re-rendering, use `--layout-preset comfortable`,
`standard` or `compact` with `cvtailor render` or `scripts/render_application.py`;
the default is `auto`. A fixed choice can still exceed two pages and requires review.
At the top, your name is on the left and contact/work-authorization details are
right-aligned beside it, in ordinary document-body text. The professional headline
starts on its own full-width line below this block so long titles do not interleave
with the contact details in text extraction. This compact top arrangement is a
design tradeoff, not a universal ATS guarantee. The Word autofill companion keeps
its simple stacked contact paragraphs for portals that need a more conservative format.
The refined PDF design uses a charcoal name, navy role headings, separate company
labels, aligned date/location text, subtle employer dividers and lighter project
labels. The main sections keep one sequential text column; no sidebar, skill graphics or hidden
text is needed for the visual hierarchy.
Do not shrink the font to force two pages; remove repeated or less relevant wording
while preserving your facts and approved project structure.

The Documents tab flags stale files when saved content, profile context, rendering
files or artifact bytes have changed. Older files without a render record show
unknown freshness. Existing downloads remain available. Open **PDF text extraction
checks · advisory** to compare two local parsers with the saved text. These are
extraction diagnostics, not ATS or AI-authorship scores. Newly rendered CVs also
show their selected typography and printable-height usage there. Page balance is
a visual preference, not a minimum word count or a screening score. The Word
companion uses its separate sequential layout; check its pagination independently.

Click **Check Word pagination** to estimate DOCX page counts with LibreOffice if
installed. This checks each Word file independently and records a hash so an old
count is not reused after edits. It makes no model call and keeps no extra PDF.
Missing LibreOffice means unchecked, not passed. Still inspect the actual file in
the application you will use to submit it.

For a scripted render, add `--check-word-layout` to `scripts/render_application.py`.
Use `--cv-only` or `--cover-letter-only` when changing just one document. Manual
wording and filenames remain authoritative; a template refresh does not rewrite prose.

For quantified achievements, keep optional supporting notes privately beside the
profile, for example `evidence_notes.json`. Record the profile claim it supports,
the measurement period, baseline/definition, your contribution, and a private
reference. Leave unknown details explicitly unverified; do not invent a baseline
or upgrade an approximate result. These notes are for your interview/review use;
the generator does not load them automatically or treat them as new profile facts.

---

## Revising a document (free, no AI call)

If you want to change wording yourself, edit the text and re-render. This costs
nothing and does not touch the AI.

1. Open `source/content.json` in the application folder.
2. Edit the text — `cv` and `cover_letter` sections.
3. Re-render:

```bash
python cvtailor.py --profile-id sample-analyst render \
    --content "<store>/outputs/sample-analyst/<job_id>/source/content.json"
```

Narrow it to one document if you only changed one:

```bash
# ...append --cv-only, or --cover-letter-only
```

**Re-render re-checks the page count**, so if your edit pushes the CV onto a third
page it will tell you. Re-rendering a cover letter stamps today's date (`date.today()`)
into both the DOCX and PDF headers so the document carries the current submission date.

---

## Re-running an application after a profile update

If you have updated your profile and want the documents regenerated from scratch:

```bash
python cvtailor.py --profile-id sample-analyst generate \
    --job-file "<store>/outputs/sample-analyst/<job_id>/source/job_description.txt" \
    --no-cache
```

`--no-cache` forces a fresh draft. Without it, an identical job and profile reuses
the stored result and costs nothing — useful to know if you re-run by accident.

---

## Finding jobs to apply to

The tool can search public job boards for you. This is **free** — no API key and no
AI call.

```bash
# See which sources are available and what each can do
python cvtailor.py jobs sources

# Search
python cvtailor.py --profile-id sample-analyst jobs search \
    --keywords "data engineer" --country DE --limit 10
```

Each result shows **why** it matched ("title matches data engineer", "description
names dbt") and flags anything needing a check before applying. Add `--json` for
machine-readable output.

Sources currently wired: softgarden, Personio, Lever/Greenhouse/Ashby boards, and
Arbeitnow. Some need configuration:

```bash
# Read a specific employer's board (repeatable)
python cvtailor.py --profile-id sample-analyst jobs search \
    --ats lever:somecompany:"Some Company" --only ats
```

---

## Using the web interface

```bash
python scripts/start.py
```

It prints two addresses; open the **UI** one. Keep the terminal open — Ctrl+C stops
the services. Logs go to `.runtime/logs/`.

> **The port is whatever `UI_PORT` in `.env` says** — 8501 for a fresh clone, but your `.env` may differ (for example 8502 and `BACKEND_PORT=8001`). Read the URL `start.py` prints rather
> than assuming; it is printed precisely because it varies.
>
> If a port is already in use, startup **refuses** rather than killing whatever is
> there. Stop the other service, or change `UI_PORT` / `BACKEND_PORT` in `.env`.

**First, check the active candidate** at the top. The GUI restores your last valid
choice or selects the only usable profile; use the sidebar to change it. With
multiple profiles and no remembered choice, select one before generating.

| Page | What it does |
|---|---|
| **New application** | Check the active candidate, paste a posting, check company/role/country and task models, then generate. Successful runs open the saved application workspace. |
| **Find jobs** | Free search with matching signals, eligibility and source notes. **Use this posting** transfers known text to New application without making a model call. |
| **Applications** | Click a recent application to open its workspace. Search by company or role and use **Filters** for status or requested model. CLI runs also appear here. |
| **Settings & help** | Private-store location, read-only profile summary and local setup checks. Key presence is distinct from provider verification. |

The workspace puts available CV and cover-letter PDF downloads under the application
title. Open the preview or run PDF checks when you need them. Other downloads include
Word and autofill files. To build missing autofill files for an older run, use
**Create / refresh CV for autofill**. It uses the saved editable text and profile
snapshot without a model call. For portals like Workday, try the plain `_upload.docx`
when accepted and verify the extracted form fields.

Open **Details** for the original posting, saved profile comparisons, the model's
explanation and run history. The run history distinguishes requested models from
provider-reported replies, and cached runs separate original usage from the current run.
Missing historical values are marked **Not recorded**. Opening a saved workspace or
checking its documents does not call the model. A failed run can expose a saved attempt
with whatever files survived.

Open **Application folder** to get the local path of the saved PDFs and source files.
For a saved CV with its profile snapshot, **Documents → Compare CV page breaks** shows
a rendered preview and the blank space at each page end. **Save preview to application
folder** saves a separate `cv_balanced_*.pdf` beside your original CV.

On **New application**, select **Balanced page breaks** under **CV page layout** to
include the alternative page breaks in the CV generated for that application.
**Automatic** uses the existing layout rules. Balanced page breaks can take longer.

Open **Answers** on a saved application, or choose **Answers only** when you already
have your documents. Paste questions separated by blank lines and check the resulting
rows. Add optional limits, notes, confirmed facts and public company excerpts. Drafting
selected questions uses your configured model and may cost money. You can edit or
write answers directly, copy each one, and select **Save answers** to keep a revision
with the application. A new suggested draft leaves existing text in the editor until
you choose to use it.

The GUI restores your last valid profile, or selects the only usable profile. The
active name/id is shown at the top of every page. Your choice survives browser and
server restarts in the private store's `preferences/gui.json`. With multiple profiles
and no remembered choice, choose one in the sidebar; switching clears the previous
candidate's draft/review state. The CLI and API still require an explicit profile id.

The curated-model selector affects only new applications. The current catalogue
contains one selected model; keeping configured routing also preserves any explicit
per-task overrides. Refreshing a saved workspace keeps it open when its application
belongs to the active profile.

If generation fails before documents exist, raw responses and a failed-run record
are saved when the store is writable. Review that attempt before paying for another
draft. Missing or damaged historical source files still allow existing downloads.

### Cover-letter voice

Letters should explain why the particular work is relevant and develop one or two
examples of what you did and why it mattered, rather than paraphrasing the CV or
listing the posting's keywords. The four-paragraph / 290–310 body-word / one-page
format is a fixed application requirement. A count passing is not proof that the prose
is good. The ATS-readable PDF has a searchable text layer, but parser behavior varies;
neither that nor the plain autofill companion guarantees a screening result.

Optional personal preferences live privately at
`<store>/profiles/<profile_id>/writing_style.json`:

```json
{
  "version": 1,
  "tone": "Warm, direct and professional",
  "preferences": ["Explain who used the work and what it helped them do."],
  "avoid": ["Repeated corporate flattery and long lists of tools."],
  "sign_off": "Warm regards,"
}
```

Only these distilled preferences are included in the letter brief; private reference
paths and old letter collections are not sent. Historical examples guide style, not
facts. The current profile remains authoritative. A changed effective voice brief
invalidates the paired generation cache automatically, so the next draft may make
fresh paid calls even if the posting is unchanged. Existing letters are not modified.
If a style file exists but is invalid, fix it before generation; it is not ignored.
Read every new letter yourself—naturalness and your voice are editorial judgments.

**Read both documents before sending them**, whichever way you produced them.

If the interface misbehaves, use the command line — it is the supported path and gives
clearer errors. `python cvtailor.py doctor` diagnoses most setup problems.

---

## If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `Which profile?` | You omitted `--profile-id`. Run `profile list` for the ids. |
| `unrecognized arguments: --profile-id` | You put it **after** the command. Move it before: `cvtailor.py --profile-id <id> <command>`. |
| `No profile 'x'` | Wrong id, or the profile is not in the store. Check `profile list`. |
| `No API key` | Add `OPENROUTER_API_KEY` to `.env`. Never commit that file. |
| `pdflatex not found` **(macOS)** | MacTeX is not installed, or is somewhere unusual. Install MacTeX, or set `LATEX_COMPILER=/Library/TeX/texbin/pdflatex` in `.env`. |
| `pdflatex not found` (Windows) | Install MiKTeX, or set `LATEX_COMPILER` to the full path of `pdflatex.exe`. |
| `pdflatex compilation failed` | Usually a **temp-directory** problem, not a broken document. See the note below. |
| Cover letter word count off | Re-render after editing `content.json`; the count is re-checked every time. |
| Word file looks different from the PDF | Minor spacing differences are expected between Word/LibreOffice (`Calibri`) and LaTeX (`Carlito`), though both follow the same single-column business-letter layout and stamp today's date (`date.today()`) at render time. Check both. |
| It generated for the wrong person | Should be impossible — `profile_id` fails closed. If you believe otherwise, stop and report it. |

> **About `pdflatex compilation failed`.** On Windows this is usually the temp
> directory, not the document: MiKTeX and the test suite need `TEMP`/`TMP` pointed at
> a writable folder, or concurrent LaTeX runs collide. Set them and retry:
>
> ```powershell
> # Windows
> $env:TEMP = (Join-Path $PWD ".tmp"); $env:TMP = $env:TEMP
> ```
>
> The same failure can leave a *usable PDF* behind — pdflatex occasionally crashes on
> exit after writing the file. Check whether the PDF exists and looks right before
> assuming the content is broken.

---

## The rules this tool will not break

* **It never picks a profile for you.** No default, no "the only one".
* **Your data never enters the repository.** Profiles, applications and generated
  documents live in your private store (`CVTAILOR_STORE`), outside this checkout. This repo is public.
* **It does not invent facts.** It tailors wording and emphasis from your real
  profile; it will not add a skill or employer you do not have.
* **Sponsorship and permit wording goes only in cover letters, never the CV.**
* **Default limits:** CV two pages, cover letter four paragraphs / 290–310 words. The
  cover-letter format and word range are fixed application requirements; they do not
  certify prose quality or ATS compatibility.

---

## Quick reference

With the venv activated (see the top of this guide) the commands are identical on every OS; without activating, replace `python` with `.venv/bin/python` (macOS/Linux) or `.venv\Scripts\python.exe` (Windows).

```bash
# Setup
python cvtailor.py doctor
python cvtailor.py profile list
python cvtailor.py --profile-id <profile_id> profile show

# Generate (costs ~$0.003)
python cvtailor.py --profile-id <profile_id> generate --job-file job.txt

# Find jobs (free)
python cvtailor.py --profile-id <profile_id> jobs search --keywords "data engineer"

# Revise (free)
python cvtailor.py --profile-id <profile_id> render --content <store>/outputs/<profile_id>/<job_id>/source/content.json

# Help
python cvtailor.py                  # guided menu
python cvtailor.py <command> --help
```
