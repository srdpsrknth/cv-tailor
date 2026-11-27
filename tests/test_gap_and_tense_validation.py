"""Documents must not state gaps or call an ended role current (WP3)."""

import pytest

from models.tailored_output import TailoredCV, TailoredCoverLetter
from services import validation
from services.validation import ProfileRules, find_gap_statement

GAPS = [
    "Experience relevant to clinical research, but no direct Clinical Research Coordinator or site-monitoring experience is listed.",
    "I have no prior experience with site monitoring.",
    "No formal hands-on experience in the field.",
    "I bring limited experience with German.",
    "Limited exposure to regulatory work.",
    "I lack experience in site monitoring.",
    "Lacking formal qualifications in the area.",
    "Site monitoring is not listed in my background.",
    "I do not have a certification in this area.",
    "The candidate does not have direct experience.",
    "Without direct clinical experience, I still learn fast.",
    "Although I have not worked in a hospital, I adapt quickly.",
    "While I haven't managed sites, I coordinated studies.",
    "I have not yet worked with that tool.",
    "Delivered results despite not having a mentor in the field.",
]
CLEAN = [
    "Reduced lack of data in the reporting layer by adding validation checks.",
    "Built dashboards that closed the lack of visibility into pipeline failures.",
    "The pipeline does not have duplicate rows after the dedup step.",
    "Coordinated experience reviews with 12 stakeholders.",
    "Gained exposure to clinical datasets and presented findings.",
    "Worked with limited budget and shipped on time.",
    "Presented findings while mentoring two analysts.",
    "No downtime during the migration of 40 tables.",
]


@pytest.mark.parametrize("text", GAPS)
def test_gap_statements_are_found(text):
    assert find_gap_statement(text)


@pytest.mark.parametrize("text", CLEAN)
def test_ordinary_sentences_are_not_gap_statements(text):
    assert find_gap_statement(text) is None


def _cv(analyst_session):
    return TailoredCV.model_validate(analyst_session.step_payload("cv_draft")["cv"])


def test_cv_summary_gap_is_rejected_with_actionable_message(analyst_profile, analyst_session):
    cv = _cv(analyst_session)
    cv.summary = ["Analyst with SQL depth, but no direct site-monitoring experience is listed."]
    with pytest.raises(ValueError, match="Remove the gap statement"):
        validation.validate_cv(cv, analyst_profile, ProfileRules())


def test_cv_bullet_gap_is_rejected(analyst_profile, analyst_session):
    cv = _cv(analyst_session)
    cv.experience[0].bullets[0] = "Supported analytics, with limited exposure to dbt."
    with pytest.raises(ValueError, match="Remove the gap statement"):
        validation.validate_cv(cv, analyst_profile, ProfileRules())


def test_ended_role_called_current_in_cv_is_rejected(analyst_profile, analyst_session):
    cv = _cv(analyst_session)
    ended = next(e for e in cv.experience if e.company == "Contoso Metrics Ltd")
    ended.bullets = ["Currently maintain the reporting models."]
    with pytest.raises(ValueError, match="past tense"):
        validation.validate_cv(cv, analyst_profile, ProfileRules())


def test_present_role_may_use_current_wording(analyst_profile, analyst_session):
    cv = _cv(analyst_session)
    cv.experience[0].bullets[0] = "Currently developing the data quality framework."
    validation.validate_cv(cv, analyst_profile, ProfileRules())


def _letter(analyst_session, paragraphs=None):
    cl = TailoredCoverLetter.model_validate(analyst_session.step_payload("cover_letter")["cover_letter"])
    if paragraphs:
        cl.paragraphs = paragraphs
    return cl


def test_recorded_letter_still_validates(analyst_profile, analyst_session):
    validation.validate_cover_letter(_letter(analyst_session), analyst_profile)


def _with_sentence(cl, sentence):
    """Swap the paragraph's trailing words for ``sentence``, keeping the word budget."""
    words = cl.paragraphs[1].split()
    cl.paragraphs = list(cl.paragraphs)
    cl.paragraphs[1] = " ".join(words[: -len(sentence.split())] + sentence.split())
    return cl


def test_letter_gap_apology_is_rejected(analyst_profile, analyst_session):
    cl = _with_sentence(_letter(analyst_session), "I have no prior experience with site monitoring.")
    with pytest.raises(ValueError, match="Remove the gap statement"):
        validation.validate_cover_letter(cl, analyst_profile)


def test_letter_calling_ended_role_current_is_rejected(analyst_profile, analyst_session):
    cl = _with_sentence(_letter(analyst_session), "In my current role at Contoso I built reports.")
    with pytest.raises(ValueError, match="past tense"):
        validation.validate_cover_letter(cl, analyst_profile)


def test_gap_check_runs_on_paragraphs_directly():
    with pytest.raises(ValueError, match="Remove the gap statement"):
        validation._validate_no_gap_statements(["I lack experience here."], "cover-letter paragraph")


def test_letter_calls_ended_role_current(analyst_profile):
    with pytest.raises(ValueError, match="past tense"):
        validation._validate_letter_tense(
            ["In my current role at Contoso, I built reports."], analyst_profile
        )
    with pytest.raises(ValueError, match="past tense"):
        validation._validate_letter_tense(
            ["Contoso is where I am currently building models."], analyst_profile
        )


def test_letter_current_wording_about_present_or_unrelated_is_allowed(analyst_profile):
    validation._validate_letter_tense(
        ["At Northwind I currently own the checks. At Contoso I built reports."], analyst_profile
    )
    validation._validate_letter_tense(
        ["Your current roadmap suits my work at Contoso."], analyst_profile
    )


def test_cache_readmission_goes_through_the_same_gate(analyst_profile, analyst_session):
    """Cache hits re-run validate_cv/validate_cover_letter, so a stale entry holding a
    gap statement raises (which the caller turns into a miss and regenerates)."""
    cv = _cv(analyst_session)
    cv.summary = ["Experience in data, but no direct experience in monitoring."]
    with pytest.raises(ValueError):
        validation.validate_cv(cv, analyst_profile, ProfileRules())
