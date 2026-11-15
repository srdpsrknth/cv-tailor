# How to generate a CV and cover letter

A step-by-step guide for actually using CV Tailor. Written for the person doing the
job application, not for a developer reading the code.

**What this does:** you give it a job posting, it writes a CV and cover letter
tailored to that posting using your saved profile, and produces a PDF (and Word
file) ready to send.

**What it costs:** roughly **$0.003 per application** on the default model
(`openai/gpt-6-luna`) — about a third of a cent. A full application is one CV call
plus one cover-letter call. Re-rendering an existing application is **free**.

---

## Before the first run

You need three things. The `doctor` command checks all of them:

```powershell
.\.venv\Scripts\python.exe cvtailor.py doctor
```

| Check | What "ok" means |
|---|---|
| `store` | Your private data folder exists, outside this repository |
| `profile` | Your CV profile is loaded and has roles in it |
| `pdflatex` | The PDF engine is installed |
| `api key` | Your OpenRouter key is set and a model is chosen |

If any line says `FAIL`, fix that before continuing — the message tells you how.

> **One `FAIL` is expected and harmless in this setup.** `doctor` reports
> `outputs ... Permission denied` when it is run from inside the sandboxed agent
> environment. PowerShell and the tool itself can write there; only the sandboxed
> Python subprocess cannot. Real runs are unaffected.

To see which profiles exist (`sreedeep` is this machine's):

```powershell
.\.venv\Scripts\python.exe cvtailor.py profile list
```

> **Where does `--profile-id` go?** It is a *global* option, so it goes **before**
> the command name, not after it:
>
> ```powershell
> # right
> cvtailor.py --profile-id sreedeep generate --job-file job.txt
> cvtailor.py --profile-id sreedeep profile show
>
> # wrong -- "unrecognized arguments"
> cvtailor.py profile show --profile-id sreedeep
> ```
>
> This machine's `.env` already sets `CVTAILOR_PROFILE_ID=sreedeep`, so commands work
> without the flag here. Pass it explicitly anyway: it is what makes the command
> unambiguous, and it is required on any machine whose `.env` does not set it.

---

## The normal workflow: a job posting you found

### 1. Save the posting to a text file

Copy the full job description — responsibilities, requirements, everything — into a
plain text file. For example `job.txt`.

Include the job URL and today's date at the top if you have them; it makes the saved
record easier to trace later.

> **Tip:** if a website blocks copying, the posting is often also readable via the
> page's "JobPosting" data. Ask an agent to fetch it, or paste it from the email
> alert. Never guess at requirements you cannot read.

### 2. Generate

```powershell
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep generate --job-file job.txt
```

Useful variations:

```powershell
# Give the company and role explicitly, instead of letting it infer them
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep generate --job-file job.txt `
    --company "Northwind Analytics GmbH" --role "Analytical Engineer"

# Say which country the job is actually in (not the company headquarters)
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep generate --job-file job.txt `
    --country Germany

# Paste the posting inline instead of using a file
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep generate --job "We are looking for..."
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
D:\coding\cv-tailor-data\outputs\sreedeep\<job_id>\
    2026_CV_<your_name>_<role>.pdf          <- the CV
    2026_cover_letter_<company>_<role>.pdf  <- the cover letter
    2026_cover_letter_<company>_<role>.docx <- Word version, if a form wants it
    source\
        content.json          <- the editable text (see revisions below)
        job_description.txt   <- the posting it worked from
        generation_result.json<- what was produced and whether it passed
```

Find the newest folder by date:

```powershell
Get-ChildItem D:\coding\cv-tailor-data\outputs\sreedeep |
    Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, LastWriteTime
```

### 5. Read them before you send them

**Always open both PDFs and check them.** The tool verifies page count and word
count, and the test suite checks for clipped text and orphan headings — but no
automated check reads your documents the way a recruiter will.

Look for: correct employer names and dates · no orphaned section headings · nothing
running off the page · the cover letter naming the right company and role · nothing
invented that you cannot back up in an interview.

---

## Revising a document (free, no AI call)

If you want to change wording yourself, edit the text and re-render. This costs
nothing and does not touch the AI.

1. Open `source\content.json` in the application folder.
2. Edit the text — `cv` and `cover_letter` sections.
3. Re-render:

```powershell
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep render `
    --content "D:\coding\cv-tailor-data\outputs\sreedeep\<job_id>\source\content.json"
```

Narrow it to one document if you only changed one:

```powershell
# ...append --cv-only, or --cover-letter-only
```

**Re-render re-checks the page count**, so if your edit pushes the CV onto a third
page it will tell you.

---

## Re-running an application after a profile update

If you have updated your profile and want the documents regenerated from scratch:

```powershell
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep generate `
    --job-file "D:\coding\cv-tailor-data\outputs\sreedeep\<job_id>\source\job_description.txt" `
    --no-cache
```

`--no-cache` forces a fresh draft. Without it, an identical job and profile reuses
the stored result and costs nothing — useful to know if you re-run by accident.

---

## Finding jobs to apply to

The tool can search public job boards for you. This is **free** — no API key and no
AI call.

```powershell
# See which sources are available and what each can do
.\.venv\Scripts\python.exe cvtailor.py jobs sources

# Search
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep jobs search `
    --keywords "data engineer" --country DE --limit 10
```

Each result shows **why** it matched ("title matches data engineer", "description
names dbt") and flags anything needing a check before applying. Add `--json` for
machine-readable output.

Sources currently wired: softgarden, Personio, Lever/Greenhouse/Ashby boards, and
Arbeitnow. Some need configuration:

```powershell
# Read a specific employer's board (repeatable)
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep jobs search `
    --ats lever:somecompany:"Some Company" --only ats
```

---

## If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `Which profile?` | You omitted `--profile-id`. Run `profile list` for the ids. |
| `unrecognized arguments: --profile-id` | You put it **after** the command. Move it before: `cvtailor.py --profile-id <id> <command>`. |
| `No profile 'x'` | Wrong id, or the profile is not in the store. Check `profile list`. |
| `No API key` | Add your OpenRouter key to `.env`. Never commit that file. |
| `pdflatex compilation failed` | Usually a **temp-directory** problem, not a broken document. Set `$env:TEMP` and `$env:TMP` to a folder inside the project, then retry. |
| Cover letter word count off | Re-render after editing `content.json`; the count is re-checked every time. |
| It generated for the wrong person | Should be impossible — `profile_id` fails closed. If you believe otherwise, stop and report it. |

---

## The rules this tool will not break

* **It never picks a profile for you.** No default, no "the only one".
* **Your data never enters the repository.** Profiles, applications and generated
  documents live in `D:\coding\cv-tailor-data`. This repo is public.
* **It does not invent facts.** It tailors wording and emphasis from your real
  profile; it will not add a skill or employer you do not have.
* **Sponsorship and permit wording goes only in cover letters, never the CV.**
* **Default limits:** CV two pages, cover letter four paragraphs / 290–310 words.

---

## Quick reference

```powershell
# Setup
.\.venv\Scripts\python.exe cvtailor.py doctor
.\.venv\Scripts\python.exe cvtailor.py profile list
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep profile show

# Generate (costs ~$0.003)
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep generate --job-file job.txt

# Find jobs (free)
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep jobs search --keywords "data engineer"

# Revise (free)
.\.venv\Scripts\python.exe cvtailor.py --profile-id sreedeep render --content <job_id>\source\content.json

# Help
.\.venv\Scripts\python.exe cvtailor.py                  # guided menu
.\.venv\Scripts\python.exe cvtailor.py <command> --help
```
