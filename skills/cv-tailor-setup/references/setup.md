# CV Tailor setup checklist

## Profile intake

Start with the candidate's name, contact details, target roles, and employment history. Verify date precision against the current schema. Use `present` for an ongoing employment entry. Verify that bullets describe the candidate's own contribution. Add only applicable education, certifications, skills, languages, and independent projects. For ongoing education use `ongoing: true` and set `end_year` only when an expected year is known. Check the current schema in `backend/models/profile.py` before writing a draft.

Confirm the CV layout separately from the facts. Offer the header and contact block, summary, experience, independent projects, education, certifications, skills, and languages. The header remains. Visible body sections can be reordered. `projects` hides the dedicated section. `employer_projects` hides only nested employer projects, and hiding Experience hides both roles and their nested projects. To show fewer nested projects, review the generated choices. Preserve original employer project evidence in the profile. Avoid duplicating the same project in both places. Publications and activities should only be configured when supported by the checkout.

```yaml
# Example for a candidate who has employer projects and wants Education near the top.
cv_section_order: [education, experience, skills]
cv_hidden_sections: [projects, certifications]
```

## Configuration inventory

| Scope | What to review |
| --- | --- |
| Machine and storage | Private `CVTAILOR_STORE`, optional `CVTAILOR_PROFILE_ID`, optional `OUTPUTS_DIR` mirror, `CVTAILOR_TIMEZONE`, PDF engine and `LATEX_COMPILER`, UI/API ports and settings used by the current launcher |
| Provider and costs | `CVTAILOR_PROVIDER`, its corresponding key, `CVTAILOR_MODEL`, `CVTAILOR_MODEL_CV`, `CVTAILOR_MODEL_COVER_LETTER`, `CVTAILOR_MODEL_LAYOUT_RETRY`, `CVTAILOR_MODEL_PORTAL_ANSWERS`, `CVTAILOR_MAX_COST_USD`, and documented model fallback, temperature and output token settings |
| Profile | Facts, project structure, `cv_section_order`, `cv_hidden_sections`, `job_search` defaults, and optional explicit country overrides and other factual rules. Use `writing_style.json` for cover-letter voice and `candidate_guidance.json` for scoped drafting or layout guidance if needed. Validate both against the checkout's documentation and loaders. |
| Application | Candidate ID, posting text, company, role, actual employment country, generation model and cache behavior, available page-layout choices, and outputs. Review project selection and optional section content. Explain that a new paid draft and a local re-render are separate actions. |

Read `.env.example`, `backend/config.py`, and the launcher for supported settings and precedence. Check which commands support CLI flags. Leave settings at their defaults unless the user has a reason to change them. Never copy someone else's keys, paths, or profile settings into a new installation.

## Verification on the target machine

From the checkout, use the platform venv Python (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS/Linux). Follow the setup guide if the environment is missing. In the examples below, replace `python` with that interpreter and pass `--store` before the command if overriding `.env`.

```text
python cvtailor.py profile list
python cvtailor.py profile import <reviewed-private-yaml> --profile-id <id>
python cvtailor.py --profile-id <id> profile show
python cvtailor.py --profile-id <id> doctor
python cvtailor.py --profile-id <id> generate --job-file <private-job-file> --company <company> --role <role> --country <country>
```

Use `profile new` only when creating an empty starting file is useful. Use plain `doctor` before optional `doctor --verify-key`, which contacts the configured provider. The GUI starts with the venv interpreter and `scripts/start.py` when supported. Pick the intended profile before generating. Use a local re-render for display changes where supported, then open the final PDF and check section order, project placement, dates, clipping, two-page CV fit, and a readable one-page cover letter. Use the recorded profile snapshot by default from the saved application workspace. For a deliberate profile change, use a render path that loads the updated profile.
