"""Skills and numbers in a tailored CV must come from the profile (WP10).

Each retry costs money, so half of these tests guard against false positives: harmless
rephrasing must pass, and only clear inventions are rejected. Fixtures are synthetic and
candidate-neutral; nothing here touches a network or the filesystem.
"""
from __future__ import annotations

import pytest

from models.profile import Profile
from models.tailored_output import TailoredCV, TailoredProject
from services import validation
from services.cv_delta import apply_cv_delta
from services.validation import ProfileRules


def make_profile(**overrides) -> Profile:
    data = {
        "version": "1.0",
        "identity": {"full_name": "Sam Example", "email": "sam@example.invalid",
                     "phone": "+49 555 1234567"},
        "summary_base": ["Researcher with experience across clinical data and reporting."],
        "experience": [
            {"company": "Acme Labs", "role": "Data Manager", "start_date": "2019-03",
             "end_date": "present",
             "bullets": ["Cleaned 12 study datasets and cut query turnaround by 35%.",
                         "Supported 3x faster database lock for 2 trials."],
             "selected_projects": [{"name": "Registry", "bullets": ["Loaded 1,200 records."],
                                    "technologies": ["REDCap"]}],
             "technologies": ["R", "SAS", "OMOP"]},
            {"company": "Beta Institute", "role": "Research Assistant", "start_date": "2017-01",
             "end_date": "2019-02", "bullets": ["Assisted with analyses."], "technologies": []},
        ],
        "education": [{"degree": "MSc Biostatistics", "institution": "Example University",
                       "start_year": 2015, "end_year": 2017}],
        "skills": {
            "data": ["SQL", "Python (pandas)", "Statistical Analysis", "C++", "Node.js"],
            "quality": ["GCP", "Documentation", "ISO 13485"],
        },
        "languages": [{"name": "English", "proficiency": "Fluent"},
                      {"name": "German", "proficiency": "A2"},
                      {"name": "Malayalam", "proficiency": "Native"}],
    }
    data.update(overrides)
    return Profile.model_validate(data)


def make_cv(profile: Profile, **changes) -> TailoredCV:
    cv = TailoredCV(
        summary=["Data manager with experience across clinical data."],
        skills={"Data": ["SQL", "Python"]},
        experience=[
            {"company": e.company, "role": e.role, "start_date": e.start_date,
             "end_date": e.end_date, "bullets": list(e.bullets)}
            for e in profile.experience
        ],
    )
    for key, value in changes.items():
        setattr(cv, key, value)
    return cv


def check(cv, profile):
    validation.validate_cv(cv, profile, ProfileRules())


@pytest.fixture
def profile():
    return make_profile()


def test_the_baseline_cv_passes(profile):
    check(make_cv(profile), profile)


# --- skills: accepted -------------------------------------------------------------------

@pytest.mark.parametrize("items", [
    ["SQL", "Python (pandas)", "Statistical Analysis"],                # verbatim
    ["sql", "PYTHON (PANDAS)"],                                          # case
    ["Python", "pandas"],                                                # parts of a profile item
    ["Python (pandas, SQL)"],                                            # harmless rephrasing
    ["Advanced SQL", "Basic Python", "Strong Statistical Analysis"],     # level words
    ["R", "SAS", "REDCap", "OMOP"],                                      # experience/project tech
    ["Statistical analyses", "statistical Analysis"],                     # plural/stem
    ["C++", "Node.js"],                                                  # symbols in names
    ["SQL, Python"],                                                     # bundled entry
    ["ISO 13485", "GCP", "Documentation"],
    ["Data analysis with R"],                                            # filler words
    ["Clinical data reporting"],                                         # all words in the profile
])
def test_profile_backed_skills_are_accepted(profile, items):
    check(make_cv(profile, skills={"Skills": items}), profile)


# --- skills: rejected -------------------------------------------------------------------

@pytest.mark.parametrize("invented", [
    "Kubernetes", "Tableau", "Python (TensorFlow)", "Rust", "Terraform", "Power BI",
    "Machine Learning Engineering", "Salesforce Administration", "Java",
])
def test_invented_skills_are_rejected_by_name(profile, invented):
    cv = make_cv(profile, skills={"Data": ["SQL", invented]})
    with pytest.raises(ValueError, match="Unsupported skill") as error:
        check(cv, profile)
    assert repr(invented) in str(error.value)


def test_the_error_names_every_unsupported_skill_not_just_the_first(profile):
    cv = make_cv(profile, skills={"Data": ["Kubernetes", "SQL", "Tableau"]})
    with pytest.raises(ValueError) as error:
        check(cv, profile)
    assert "'Kubernetes'" in str(error.value) and "'Tableau'" in str(error.value)
    assert "'SQL'" not in str(error.value)


def test_a_substring_of_a_profile_word_is_not_support():
    """'Java' must not be supported by a profile that only says 'JavaScript'."""
    profile = make_profile(skills={"web": ["JavaScript"]})
    with pytest.raises(ValueError, match="'Java'"):
        check(make_cv(profile, skills={"Web": ["Java"]}), profile)


def test_a_banned_tool_in_rules_is_not_evidence():
    """The rules block must not count as the profile's evidence."""
    profile = make_profile(rules={"banned_tools": ["Tableau"]})
    with pytest.raises(ValueError, match="'Tableau'"):
        check(make_cv(profile, skills={"BI": ["Tableau"]}), profile)


def test_the_job_posting_cannot_justify_a_skill(profile):
    cv = make_cv(profile, skills={"Cloud": ["AWS"]})
    with pytest.raises(ValueError, match="'AWS'"):
        check(cv, profile)


# --- spoken languages -------------------------------------------------------------------

@pytest.mark.parametrize("items", [
    ["English (Fluent)", "German (A2)", "Malayalam (Native)"],     # the real failure
    ["English"],
    ["German - A2"],
    ["Malayalam: Native"],
    ["english (fluent)"],
    ["German, B1"],
])
def test_spoken_languages_are_rejected_when_the_profile_has_a_languages_section(profile, items):
    cv = make_cv(profile, skills={"Languages": ["SQL"] + items})
    with pytest.raises(ValueError, match="Languages section"):
        check(cv, profile)


def test_spoken_language_rejection_names_the_entries(profile):
    cv = make_cv(profile, skills={"Languages": ["English (Fluent)", "German (A2)"]})
    with pytest.raises(ValueError) as error:
        check(cv, profile)
    assert "'English (Fluent)'" in str(error.value)


def test_a_skill_that_merely_starts_with_a_language_name_is_fine():
    profile = make_profile(skills={"writing": ["English-language editing", "German market analysis"]})
    check(make_cv(profile, skills={"Writing": ["English-language editing",
                                                "German market analysis"]}), profile)


def test_spoken_languages_are_only_policed_when_a_languages_section_exists():
    profile = make_profile(languages=[], skills={"x": ["English (Fluent)"]})
    check(make_cv(profile, skills={"Communication": ["English (Fluent)"]}), profile)


def test_programming_languages_are_not_spoken_languages(profile):
    check(make_cv(profile, skills={"Programming languages": ["R", "SAS", "SQL"]}), profile)


# --- numbers: accepted ------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Cut query turnaround by 35% across 12 study datasets.",         # profile figures
    "Delivered database lock 3x faster for 2 trials.",
    "Loaded 1200 records into the registry.",                         # 1,200 spelled differently
    "Loaded 1.2k records into the registry.",                         # 1,200 scaled
    "Reduced turnaround by 35 %.",
    "Managed trials from 2019 onward.",                               # year in the profile's range
    "Worked in the field for over 5 years.",                          # duration within career span
    "Built a 24/7 on-call rota.",                                     # idiom
    "Delivered Phase 2 and Tier 1 reporting.",                        # labels
    "Migrated reports to GA4 and S3 storage.",                        # names containing digits
    "Ranked 1st among analysts.",                                     # ordinal
    "Maintained a 3D visualisation pipeline.",                        # name, not metric
    "Wrote tests for Python 3 scripts.",                              # version of a profile tool
    "Cleaned data for Q3 reporting.",
    "Developed reporting without a single number.",
])
def test_harmless_numbers_are_accepted(profile, text):
    check(make_cv(profile, summary=[text]), profile)
    cv = make_cv(profile)
    cv.experience[0].bullets[0] = text
    check(cv, profile)


def test_metrics_are_never_required(profile):
    cv = make_cv(profile, summary=["Data manager."])
    cv.experience[0].bullets = ["Cleaned study datasets."]
    check(cv, profile)


# --- numbers: rejected ------------------------------------------------------------------

@pytest.mark.parametrize("text,numbers", [
    ("Cut query turnaround by 40%.", "40"),
    ("Delivered 5x faster lock.", "5x"),
    ("Supported 50 trials.", "50"),
    ("Saved EUR 20k per year.", "20k"),
    ("Handled 1,500 records.", "1,500"),
    ("Reduced errors by 99.9%.", "99.9"),
    ("Managed a team of 8.", "8"),
    ("Led work since 2012.", "2012"),
    ("Worked in the field for over 25 years.", "25"),
])
def test_invented_numbers_in_a_bullet_are_rejected(profile, text, numbers):
    cv = make_cv(profile)
    cv.experience[0].bullets[0] = text
    with pytest.raises(ValueError, match="does not state") as error:
        check(cv, profile)
    assert numbers in str(error.value)
    assert "Acme Labs" in str(error.value)


def test_an_invented_number_in_the_summary_is_rejected(profile):
    cv = make_cv(profile, summary=["Data manager with 14 years of experience."])
    with pytest.raises(ValueError, match="the summary"):
        check(cv, profile)


def test_an_invented_number_in_a_project_bullet_is_rejected(profile):
    cv = make_cv(profile)
    cv.experience[0].projects = [TailoredProject(name="Registry", bullets=["Loaded 900 records."])]
    with pytest.raises(ValueError, match="900"):
        check(cv, profile)


def test_month_digits_of_a_date_do_not_excuse_a_small_metric(profile):
    cv = make_cv(profile)
    cv.experience[0].bullets[0] = "Supported 7 trials."
    with pytest.raises(ValueError, match="7"):
        check(cv, profile)


def test_the_phone_number_does_not_excuse_a_metric(profile):
    cv = make_cv(profile)
    cv.experience[0].bullets[0] = "Supported 555 trials."
    with pytest.raises(ValueError, match="555"):
        check(cv, profile)


# --- layout-retry deltas ----------------------------------------------------------------

def test_a_delta_may_reword_an_existing_skills_category(profile):
    merged = apply_cv_delta(make_cv(profile), {"skills.Data": ["SQL"]})
    assert merged.skills["Data"] == ["SQL"]


def test_a_delta_category_matches_case_insensitively_and_keeps_the_cv_spelling(profile):
    merged = apply_cv_delta(make_cv(profile), {"skills.data": ["SQL"]})
    assert list(merged.skills) == ["Data"]


def test_a_delta_cannot_create_a_new_skills_category(profile):
    with pytest.raises(ValueError, match="no such skills category"):
        apply_cv_delta(make_cv(profile), {"skills.Cloud": ["Kubernetes"]})


def test_a_failed_delta_leaves_the_original_cv_untouched(profile):
    cv = make_cv(profile)
    with pytest.raises(ValueError):
        apply_cv_delta(cv, {"skills.Data": ["SQL"], "skills.New": ["R"]})
    assert cv.skills == {"Data": ["SQL", "Python"]}


def test_new_items_in_a_delta_still_face_the_skills_check(profile):
    merged = apply_cv_delta(make_cv(profile), {"skills.Data": ["SQL", "Kubernetes"]})
    with pytest.raises(ValueError, match="'Kubernetes'"):
        check(merged, profile)


def test_a_delta_cannot_introduce_a_metric(profile):
    merged = apply_cv_delta(make_cv(profile), {"experience[0].bullets[0]": "Cut turnaround by 61%."})
    with pytest.raises(ValueError, match="61"):
        check(merged, profile)
