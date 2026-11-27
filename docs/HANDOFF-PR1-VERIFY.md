# Handoff: verify PR #1 after pulling (multi-candidate, cross-OS cleanup)

**Audience:** the coding agent (and the user) on a machine that already ran CV Tailor before this
PR, in particular the original Windows development machine with an existing private store.
**PR:** https://github.com/srdpsrknth/cv-tailor/pull/1 (`arundhathi/backlog` into
`refactor/architecture-v2`). Prepared on macOS on 2026-11-27.

Read this file, `AGENTS.md` and the **2026-11-27** section of `docs/PROJECT_STATE.md` first.
Do not change code while verifying. Report each check as PASS / FAIL with output. Ask the user
before any paid generation, and before editing the private profile.

---

## 1. What changed (summary)

The PR came from onboarding a second candidate (early-career, health/regulatory, macOS). It has
one commit per work package; `git log 42f75a4..HEAD` lists them. Design decisions:
[ADR 0026](DECISIONS/0026-profile-grounded-tailoring.md),
[0027](DECISIONS/0027-richer-profile-sections.md),
[0028](DECISIONS/0028-confirm-first-suggested-claims.md),
[0029](DECISIONS/0029-pipeline-fingerprint-cache-key.md) (all **Proposed**, so the owner
approves or amends them), and [0030](DECISIONS/0030-job-search-redesign.md) (job search
**deferred** to a redesign).

| Area | Change |
|---|---|
| Tests / CI | Green baseline; CI on Ubuntu, Windows, macOS plus a TeX Live job; `.gitattributes`; strict markers. Tests never read the real `.env` and need no key. |
| LaTeX | Single-pass `escape_latex` (no more double-escaped backslashes); Unicode sanitising (unsupported characters become `?` with a warning); safe contact links (`_`, `%`, `#` in email/URLs); utf-8 subprocess decoding; `amssymb` loaded (✓). |
| Tailoring rules | No gap statements, correct tense for ended roles; skills and numbers must be supported by the profile; spoken languages not listed as skills (ADR 0026). |
| Profile (all optional) | `standalone_projects_policy`, reworded standalone project bullets, project `dates`/`technologies`/`context`, publications/activities with bullets, `education[].highlights`, structured certifications, `experience[].optional`/`display_name`, `letter: {salutation, sign_off}`. Old profiles serialise unchanged (ADR 0027). |
| Layout / exports | No orphaned section headings; PDF/DOCX/TXT consistent ("Professional Experience", "Present", en dash, short months); nested sub-bullets in DOCX/TXT; locale-free month names; letter date and CV file-name year follow `CVTAILOR_TIMEZONE`. |
| Confirm-first | The CV call may return `suggested_claims` (never rendered). Review them with `cvtailor claims list/accept/reject` or the review page panel. Accepted text is written into the private profile, with a backup (ADR 0028). |
| Cache | The key now includes a pipeline fingerprint: prompt code, budgets, template, validator source (ADR 0029). **Existing cached drafts miss once.** |
| Setup / ops | OpenRouter is the provider default (Gemini opt-in; `google-genai` imported lazily). Python **3.12** floor shared by setup and doctor. `setup.py` checks an existing `.venv`'s Python version and CPU architecture. `start.py --status/--stop` on all OSes. TeX Live year-directory discovery. `doctor` fonts check. `load_profile()` needs an explicit path. |
| Docs | Generic, OS-neutral skills and docs; previous-owner data removed from live instructions (history marked historical). |
| New tool | `cvtailor --profile-id <id> applications check [--render]`: re-validates saved applications offline. |

## 2. Behaviour changes that can affect an existing user

Check each of these deliberately:

1. **Candidate rules must live in the profile.** Since upstream `b45bc0d`, a profile with no
   `rules:` block gets **neutral** rules: no employer rules, banned tools, visa label, or home
   or local-permit countries. The old built-in defaults are gone (`home_countries` and
   `local_permit_countries` now default to empty). If the original candidate relied on them
   (employer-specific project rules, banned tools, the Blue Card label, Germany as home, Ireland
   and Denmark as local-permit countries), they must be declared in **his** private
   `profile.yaml` `rules:`. Candidate-specific drafting text goes in `candidate_guidance.json`.
   The scripts `scripts/capture_candidate_policy.py` and `scripts/migrate_candidate_guidance.py`
   exist for this (`--check` previews). Verify with
   `python cvtailor.py --profile-id <id> profile show`: the output should say "Validation rules:
   declared in profile" and list the expected rules.
2. **Stricter validators** (ADR 0026) can reject drafts that used to pass. The offline check in
   step 3.6 shows which saved applications would now be retried.
3. **Upload CV text changes:** "Work Experience" becomes "Professional Experience", full months
   become short ("Apr 2023"), " - " becomes " – ", and "present" becomes "Present".
4. **Cache:** the first generation of an already-cached posting is a fresh paid run.
5. **Provider:** with only `GEMINI_API_KEY` set and no `CVTAILOR_PROVIDER=gemini`, generation now
   asks for `OPENROUTER_API_KEY`. Set `CVTAILOR_PROVIDER=gemini` to keep using Gemini.

## 3. Verification steps (Windows PowerShell; macOS equivalents in brackets)

Run from the checkout root. `$py` is the venv interpreter.

```powershell
git fetch origin
git switch refactor/architecture-v2
git pull --ff-only
$py = ".venv\Scripts\python.exe"          # [macOS: py=.venv/bin/python]
```

### 3.1 Environment
```powershell
python scripts\setup.py                    # uses the existing .venv; must not report a version/architecture mismatch
& $py cvtailor.py --profile-id <id> doctor --verify-key
```
PASS when everything is `ok`. The new `fonts` line should be ok or warn (Carlito). The
`pdflatex` line should show the MiKTeX or TeX Live path, and the api key line should be
verified with the selected provider.

### 3.2 Full test suite (needs pdflatex for the LaTeX tests)
```powershell
& $py -m pytest -q
```
Expected on macOS with MacTeX: **1786 passed, 3 skipped**. On Windows with MiKTeX the count
should match; LaTeX tests auto-skip only if pdflatex is missing. Report any failure in full.
Windows-specific risks: CRLF (fixed by `.gitattributes`), cp1252 decoding of pdflatex output
(fixed), and symlink tests (skip without Developer Mode).

### 3.3 Profile rules (behaviour change 1)
```powershell
& $py cvtailor.py --profile-id <id> profile show
```
Confirm the expected rules, visa label and home countries are declared. If not, ask the user,
then use the capture/migrate scripts or edit the private profile (back it up first).

### 3.4 GUI and launcher
- Start via the Windows shortcuts (`scripts\windows_gui.ps1`) and via
  `& $py scripts\start.py`. Open the printed URL.
- `& $py scripts\start.py --status` must list only services that `start.py` started.
  `--stop` must stop them and must never touch other listeners on the ports.
- In the GUI: select the profile, open a saved application, check the review page, and check that
  the "Suggested claims" panel appears only for applications that have suggestions.

### 3.5 Re-render saved applications (free, no AI)
Pick 2-3 recent saved applications. Copy each folder to a temporary location first, so the
originals stay untouched, then:
```powershell
& $py cvtailor.py --profile-id <id> render --content <copy>\source\content.json
```
Compare the new PDF, DOCX and TXT with the originals. **Expected differences only:**
- "Present" capitalised in the PDF date lines;
- in the DOCX/TXT, "Professional Experience", en dashes, short months and nested sub-bullets;
- a section heading that was previously stranded at a page bottom now moves to the next page.

Anything else (missing text, clipping, more pages) is a regression. Open the DOCX in **Word**:
headings should keep with the next paragraph, and fonts should be correct.

### 3.6 Saved applications against the new rules (free, offline, never writes to the store)
```powershell
& $py cvtailor.py --profile-id <id> applications check --render
```
For each FAIL, read the message:
- **Expected:** old drafts mentioning spoken languages in skills, or numbers or skills that the
  profile does not contain. The generator would now retry these.
- **Investigate as a possible false positive:** a skill or number that **is** in the profile but
  is reported as unsupported. Report the exact skill or number and the matching profile line.
  The rules live in `backend/services/fact_checks.py`.

### 3.7 One live generation per candidate (paid, about $0.004 each; ask the user first)
```powershell
& $py cvtailor.py --profile-id <id> generate --job-file <posting.txt> --company "<Co>" --role "<Role>" --country "<Country>"
```
Check:
- In `source\generation_result.json`, the number of calls and attempts, so new validators don't
  cause repeated retries.
- A **non-home** country with the Blue Card policy still gets the correct label and letter
  sentence. This exercises the declared rules from 3.3.
- Read the CV and letter: no gap statements; ended roles not called current; no invented
  numbers or skills.
- If the generation prints "N suggested claims to review", run
  `claims list --content ...`. Suggestions must be **statements**, attached to real profile
  entries.

### 3.8 Confirm-first round trip (use a throwaway copy of the profile, or accept only something true)
Accept one true suggestion in the GUI ("Add selected to my profile", then confirm), or with
`claims accept --content ... <n>`. Verify:
- `profile.backup-<timestamp>.yaml` exists;
- the profile diff is exactly the added line, with comments preserved;
- `profile show` still validates.
Also check that "Dismiss selected" marks suggestions as dismissed and leaves the profile unchanged.

### 3.9 Docs and ADRs
Skim `docs/HOW_TO_GENERATE.md`, `skills/cv-tailor-setup/`,
`.agents/skills/cv-tailor-application/SKILL.md` and `AGENTS.md`. They must be OS-neutral and
contain no single-candidate facts. The owner approves or amends ADRs 0026-0029; update
`docs/DECISIONS/README.md` to match.

## 4. Pass criteria

- [ ] 3.1 doctor all ok (fonts may warn)
- [ ] 3.2 full suite green
- [ ] 3.3 candidate rules declared and correct
- [ ] 3.4 GUI and start/stop work on Windows
- [ ] 3.5 re-renders show only the expected differences; DOCX looks right in Word
- [ ] 3.6 no false positives in `applications check` (expected FAILs are explained)
- [ ] 3.7 live generations fine; no excessive retries; work-authorization wording correct
- [ ] 3.8 confirm-first round trip preserves the profile
- [ ] 3.9 ADRs reviewed

## 5. If something fails

- Report the failing step, the command and the full output. Do not "fix" by loosening
  validators without the owner's decision: false positives should be fixed with a test that
  reproduces them (`tests/test_fact_checks.py`, `tests/test_gap_and_tense_validation.py`).
- Rendering regressions: compare `.tex` output and `cv_layout` diagnostics. See
  `tests/test_section_heading_orphans.py` and `tests/test_output_parity.py`.
- Windows-only issues: check encoding (`encoding="utf-8"`), path handling and TeX discovery
  (`backend/renderers/latex_renderer.py`, `LATEX_COMPILER`).

## 6. Not in this PR

- **Job search**: deliberately not changed; it will be redesigned (ADR 0030 lists the
  requirements). The current feature works as before.
- UI labels are centralised in `backend/renderers/cv_sections.py` but not translated.
- `applications check` runs the `validation.py` and fact checks, but not the generator's
  work-authorization and country-wording checks. Those run only during generation (3.7).
