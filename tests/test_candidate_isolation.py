"""Regression cases for moving candidate defaults into the private profile."""

import pytest

from models.profile import CountryApplicationRules, EmployerRules, Profile
from models.profile import ProfileRules as DeclaredRules
from services.pipeline import DocumentGenerator
from services.prompts import (
    PROMPT_CL_PATH,
    PROMPT_CV_PATH,
    build_context,
    build_cv_prompt,
    layout_correction_instruction,
)
from services.validation import ProfileRules
from support import read_json


@pytest.fixture
def health_profile():
    return Profile.model_validate({
        "version": "1.0",
        "identity": {
            "full_name": "Morgan Sample",
            "email": "morgan@example.invalid",
        },
        "summary_base": ["Health data graduate with experience in registry quality checks."],
        "experience": [{
            "company": "Example Clinical Registry",
            "role": "Research Assistant",
            "start_date": "2025-02",
            "end_date": "present",
            "bullets": ["Reviewed registry data quality checks."],
        }],
        "skills": {"Health Data": ["OMOP", "FHIR"]},
    })


@pytest.fixture
def health_cv(health_profile):
    return {
        "summary": health_profile.summary_base,
        "skills": health_profile.skills,
        "experience": [{
            "company": role.company,
            "role": role.role,
            "start_date": role.start_date,
            "end_date": role.end_date,
            "bullets": role.bullets,
        } for role in health_profile.experience],
    }


@pytest.fixture
def letter_payload(health_profile):
    # Use the existing four-paragraph synthetic letter to exercise the real length gate.
    payload = read_json("content", "valid_content.json")["cover_letter"]
    payload["signature_name"] = health_profile.identity.full_name
    return payload


@pytest.mark.parametrize("declare_empty_rules", [False, True], ids=["absent", "empty"])
def test_profile_defaults_are_candidate_neutral(health_profile, declare_empty_rules):
    if declare_empty_rules:
        health_profile.rules = DeclaredRules()

    rules = ProfileRules.from_profile(health_profile)

    assert not rules.special_employers
    assert not rules.banned_tools
    assert not rules.summary_forbidden_verbs
    assert rules.visa_label is None
    assert not rules.home_countries
    assert not rules.local_permit_countries
    assert not rules.country_overrides


def test_explicit_rules_are_scoped_to_the_candidate(analyst_profile, health_profile, health_cv):
    analyst_profile.rules = DeclaredRules(
        employers={"northwind": EmployerRules(project_count=1, bullets_per_project=3)},
        banned_tools=["FHIR"],
        home_countries=["Canada"],
        country_overrides={
            "Netherlands": CountryApplicationRules(
                work_authorization="Existing work rights in the Netherlands",
                requires_employer_support=False,
            ),
        },
    )
    analyst = DocumentGenerator(None, analyst_profile)
    health = DocumentGenerator(None, health_profile)
    posting = "Review clinical registry quality."
    analyst_context = build_context(posting, analyst_profile, work_country="Netherlands")
    health_context = build_context(posting, health_profile, work_country="Netherlands")

    assert "Existing work rights in the Netherlands" in analyst_context
    assert "northwind" in analyst_context.casefold()
    assert "Existing work rights in the Netherlands" not in health_context
    assert "northwind" not in health_context.casefold()
    assert analyst.rules.banned_tools == ("FHIR",)
    assert "northwind" in layout_correction_instruction(3, 650, analyst.rules).casefold()
    analyst_cv = read_json("content", "valid_content.json")["cv"]
    analyst_cv["skills"]["Health Data"] = ["FHIR"]
    with pytest.raises(ValueError, match="FHIR"):
        analyst._build_model({"cv": analyst_cv}, "cv", "Canada", None, None)
    cv = health._build_model({"cv": health_cv}, "cv", "Netherlands", None, None)
    assert cv.skills["Health Data"] == ["OMOP", "FHIR"]
    assert not cv.work_authorization


@pytest.mark.parametrize("kind", ["cv", "cover_letter"])
def test_new_candidate_prompt_omits_other_candidates_guidance(health_profile, kind):
    context = build_context("Review clinical registry quality.", health_profile, work_country="Ireland")
    if kind == "cv":
        prompt = build_cv_prompt(PROMPT_CV_PATH.read_text(encoding="utf-8"), context)
    else:
        prompt = PROMPT_CL_PATH.read_text(encoding="utf-8") + context
    prompt = prompt.casefold()

    assert "candidate holds a valid" not in prompt
    assert "german eu blue card holder" not in prompt
    assert "does not use dbt" not in prompt


def test_new_candidate_layout_retry_omits_employer_specific_project_constraints(health_profile):
    rules = ProfileRules.from_profile(health_profile)

    assert "attribution project" not in layout_correction_instruction(3, 650, rules)


@pytest.mark.parametrize("work_country", ["Ireland", None], ids=["explicit-country", "no-country"])
@pytest.mark.parametrize("field", ["work_authorization", "summary"])
def test_cv_rejects_invented_work_authorization(health_profile, health_cv, work_country, field):
    if field == "summary":
        health_cv[field] = ["Health data graduate holding a German EU Blue Card."]
    else:
        health_cv[field] = "German EU Blue Card holder"
    generator = DocumentGenerator(None, health_profile)

    with pytest.raises(ValueError, match=r"(?i)authori[sz]ation|blue card|immigration"):
        generator._build_model({"cv": health_cv}, "cv", work_country, None, None)


@pytest.mark.parametrize("work_country", ["Ireland", None], ids=["explicit-country", "no-country"])
@pytest.mark.parametrize("claim", [
    "I hold a valid German EU Blue Card.",
    "I require employer sponsorship for an employment permit.",
], ids=["status", "support-requirement"])
def test_letter_rejects_invented_work_authorization(
    health_profile, letter_payload, work_country, claim,
):
    generator = DocumentGenerator(None, health_profile)
    data = {"cover_letter": letter_payload}
    generator._build_model(data, "cover_letter", work_country, None, None)
    closing_words = letter_payload["paragraphs"][-1].split()
    letter_payload["paragraphs"][-1] = " ".join(
        closing_words[:-len(claim.split())] + [claim]
    )

    with pytest.raises(ValueError, match=r"(?i)authori[sz]ation|blue card|immigration|sponsorship"):
        generator._build_model(data, "cover_letter", work_country, None, None)
