"""One-off generator for tests/fixtures/llm_responses/*.

Not part of the test suite. Run from the repository root:

    .venv\\Scripts\\python.exe tools/build_fixtures.py

It writes synthetic, schema-valid recorded provider responses and refuses to write a
cover letter that would not pass the real validators (4 paragraphs, 290-310 words).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from models.tailored_output import TailoredCoverLetter, TailoredCV  # noqa: E402
from services.profile_loader import load_profile  # noqa: E402
from services.tailor_service import _validate_cover_letter, _validate_cv  # noqa: E402

SOURCE_FIXTURES = ROOT / "tests" / "fixtures"

# The DSH workspace sandbox can deny writes under tests/ to the project venv even when
# ACLs allow it. Pass a writable staging root as argv[1]; inputs are still read from the
# repository and the output is produced under the staging root, ready to be moved into
# place with tools/install_fixtures.py.
FIXTURES = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SOURCE_FIXTURES


def cv_payload(profile, title, summary, skills, authorization=None):
    experience = []
    for exp in profile.experience:
        experience.append({
            "company": exp.company,
            "role": exp.role,
            "start_date": exp.start_date,
            "end_date": exp.end_date,
            "bullets": list(exp.bullets),
            "projects": [{"name": p.name, "bullets": list(p.bullets)} for p in exp.selected_projects],
        })
    return {
        "title": title,
        "work_authorization": authorization,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "include_education": True,
        "include_certifications": True,
    }


def words(count, prefix):
    """Deterministic sentence of exactly `count` words, starting with `prefix`."""
    tokens = prefix.split()
    if len(tokens) > count:
        raise SystemExit(f"prefix is {len(tokens)} words but budget is {count}")
    i = 0
    while len(tokens) < count:
        tokens.append(f"filler{i}")
        i += 1
    return " ".join(tokens)


def letter(company, role, signature, paragraphs):
    text = " ".join(paragraphs)
    total = len(text.split())
    if len(paragraphs) != 4 or not 290 <= total <= 310:
        raise SystemExit(f"refusing to write letter: {len(paragraphs)} paragraphs, {total} words")
    return {
        "company_name": company,
        "role_title": role,
        "signature_name": signature,
        "closing_line": "Sincerely,",
        "paragraphs": paragraphs,
    }


def write_json(path: Path, payload):
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")

ANALYST_SKILLS = {
    "Core Analytics": ["Advanced SQL", "Python (Pandas, NumPy)", "Statistical Analysis",
                       "Cohort & Funnel Analysis", "Forecasting"],
    "Data Engineering": ["Snowflake", "dbt", "Apache Airflow", "Incremental ETL",
                         "Automated Data Quality"],
    "Collaboration": ["Stakeholder Management", "Data Storytelling", "Git"],
}

MARKETER_SKILLS = {
    "Marketing Analytics": ["Campaign Reporting", "Attribution Modeling", "LTV / CAC",
                            "Retention & Churn Analysis"],
    "Tooling": ["GA4", "Braze CRM", "SQL", "Power BI"],
}


def analyst_sessions():
    profile = load_profile(str(SOURCE_FIXTURES / "profiles/synthetic_analyst.yaml"))
    out = FIXTURES / "llm_responses/analyst_nordwind"

    draft = cv_payload(
        profile,
        "Analytical Engineer",
        ["Analytical engineer with experience across warehouse modelling, pipeline reliability "
         "and self-service reporting in synthetic fixture organisations."],
        ANALYST_SKILLS,
    )
    reviewed = json.loads(json.dumps(draft))
    reviewed["summary"] = [
        "Analytical engineer with experience across warehouse modelling, pipeline reliability "
        "and stakeholder-facing reporting in synthetic fixture organisations."
    ]
    explanation = {
        "summary_changes": "Aligned the approved summary with the posting's measurement focus.",
        "bullet_modifications": "Kept pipeline and data-quality bullets; shortened tooling detail.",
        "skill_reordering": "Led with SQL and warehouse modelling skills.",
        "project_selection": "Retained the attribution rebuild as the single attribution project.",
        "overall_strategy": "Emphasised the transformation layer the posting asks for.",
    }
    # `tailor_documents` reads `data.get("tailoring_explanation")` from the TOP level of
    # the parsed response, not from inside `cv`. Recorded the way production expects it.
    review_payload = {"cv": reviewed, "tailoring_explanation": explanation}
    shortened = json.loads(json.dumps(reviewed))
    shortened["summary"] = [
        "Analytical engineer with experience across warehouse modelling and pipeline reliability."
    ]
    shortened["experience"][0]["bullets"] = shortened["experience"][0]["bullets"][:2]

    letter_payload = letter(
        "Nordwind Analytics GmbH",
        "Analytical Engineer",
        profile.identity.full_name,
        [
            words(70, "I am applying for the Analytical Engineer role at Nordwind Analytics, "
                      "where the transformation layer between ingestion and reporting is the "
                      "centre of the position."),
            words(75, "In my current role I own batch pipelines end to end, from ingestion "
                      "through warehouse modelling to the datasets that reporting consumes."),
            words(80, "I am drawn to Nordwind because the posting treats data quality and change "
                      "control as first-class parts of the engineering job rather than as "
                      "afterthoughts, which matches how I prefer to work on shared models."),
            words(75, "I would welcome the opportunity to discuss how my experience with "
                      "orchestrated warehouse transformations and documented models could "
                      "support the measurement platform your customers depend on."),
        ],
    )

    # Validate against the real production validators before writing.
    for payload in (draft, reviewed, shortened):
        _validate_cv(TailoredCV.model_validate(payload), profile)
    _validate_cover_letter(TailoredCoverLetter.model_validate(letter_payload), profile)

    write_json(out / "01_cv_draft.json", {"cv": draft})
    write_json(out / "02_cv_editorial_review.json", review_payload)
    write_json(out / "03_cover_letter.json", {"cover_letter": letter_payload})
    # 04 is delivered inside a Markdown fence to exercise the tolerant parser.
    fenced = "```json\n" + json.dumps({"cv": shortened}, indent=2, ensure_ascii=False) + "\n```"
    write_text(out / "04_cv_layout_retry.json", fenced + "\n")

    write_json(out / "responses.json", {
        "session": "analyst_nordwind",
        "profile": "profiles/synthetic_analyst.yaml",
        "job_description": "job_descriptions/nordwind_analytics_engineer.txt",
        "steps": [
            {"attempt": "cv_draft", "file": "01_cv_draft.json", "format": "json"},
            {"attempt": "cv_editorial_review", "file": "02_cv_editorial_review.json", "format": "json"},
            {"attempt": "cover_letter", "file": "03_cover_letter.json", "format": "json"},
            {"attempt": "cv_layout_retry", "file": "04_cv_layout_retry.json", "format": "fenced"},
        ],
    })


def marketer_sessions():
    profile = load_profile(str(SOURCE_FIXTURES / "profiles/synthetic_marketer.yaml"))
    out = FIXTURES / "llm_responses/marketer_lumen"

    draft = cv_payload(
        profile,
        "Growth Analyst",
        ["Growth marketing analyst with experience across paid acquisition reporting, "
         "retention analysis and lifecycle experimentation in synthetic fixture organisations."],
        MARKETER_SKILLS,
    )
    reviewed = json.loads(json.dumps(draft))
    reviewed["summary"] = [
        "Growth marketing analyst with experience across paid acquisition reporting and "
        "lifecycle experimentation in synthetic fixture organisations."
    ]
    explanation = {
        "summary_changes": "Emphasised acquisition reporting and experimentation.",
        "bullet_modifications": "Kept campaign and lifecycle bullets, shortened tooling lists.",
        "skill_reordering": "Led with marketing analytics skills named in the posting.",
        "project_selection": "No selected projects in this profile; none were added.",
        "overall_strategy": "Matched the posting's acquisition and retention emphasis.",
    }
    review_payload = {"cv": reviewed, "tailoring_explanation": explanation}

    letter_payload = letter(
        "Lumen Consumer BV",
        "Growth Analyst",
        profile.identity.full_name,
        [
            words(72, "I am writing to apply for the Growth Analyst position at Lumen "
                      "Consumer, where the analytical partner role sits directly alongside "
                      "paid acquisition and lifecycle marketing."),
            words(78, "My current work centres on reporting paid acquisition performance and "
                      "maintaining retention cohorts, and on explaining movement between "
                      "periods rather than only describing it."),
            words(80, "The emphasis in your posting on turning analysis into a decision that "
                      "changes spend or messaging is the part of analytics I find most "
                      "valuable, and it is how I try to scope every recurring report I own."),
            words(72, "I would be glad to discuss how my experience with subscription "
                      "reporting, cohort analysis and test readouts could support the growth "
                      "team's acquisition and retention goals."),
        ],
    )

    for payload in (draft, reviewed):
        _validate_cv(TailoredCV.model_validate(payload), profile)
    _validate_cover_letter(TailoredCoverLetter.model_validate(letter_payload), profile)

    write_json(out / "01_cv_draft.json", {"cv": draft})
    write_json(out / "02_cv_editorial_review.json", review_payload)
    write_json(out / "03_cover_letter.json", {"cover_letter": letter_payload})
    write_json(out / "responses.json", {
        "session": "marketer_lumen",
        "profile": "profiles/synthetic_marketer.yaml",
        "job_description": "job_descriptions/lumen_growth_analyst.txt",
        "steps": [
            {"attempt": "cv_draft", "file": "01_cv_draft.json", "format": "json"},
            {"attempt": "cv_editorial_review", "file": "02_cv_editorial_review.json", "format": "json"},
            {"attempt": "cover_letter", "file": "03_cover_letter.json", "format": "json"},
        ],
    })


def content_documents():
    profile = load_profile(str(SOURCE_FIXTURES / "profiles/synthetic_analyst.yaml"))
    cv = cv_payload(
        profile,
        "Analytical Engineer",
        ["Analytical engineer with experience across warehouse modelling, pipeline reliability "
         "and self-service reporting in synthetic fixture organisations."],
        ANALYST_SKILLS,
    )
    letter_payload = json.loads(
        (FIXTURES / "llm_responses/analyst_nordwind/03_cover_letter.json").read_text(encoding="utf-8")
    )["cover_letter"]
    _validate_cv(TailoredCV.model_validate(cv), profile)
    _validate_cover_letter(TailoredCoverLetter.model_validate(letter_payload), profile)
    write_json(FIXTURES / "content/valid_content.json", {
        "company_name": "Nordwind Analytics GmbH",
        "role_title": "Analytical Engineer",
        "work_country": "Germany",
        "cv": cv,
        "cover_letter": letter_payload,
    })
    write_json(FIXTURES / "content/invalid_content.json", {
        "company_name": "Nordwind Analytics GmbH",
        "role_title": "Analytical Engineer",
        "cv": {"summary": "not-a-list"},
        "cover_letter": {"company_name": "Nordwind Analytics GmbH"},
    })


def main():
    analyst_sessions()
    marketer_sessions()
    content_documents()
    print("done")


if __name__ == "__main__":
    main()
