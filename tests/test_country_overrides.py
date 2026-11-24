"""Confirmed work rights are per candidate; overseas experience is not a permit."""
import pytest

from models.profile import CountryApplicationRules, ProfileRules as DeclaredRules
from models.tailored_output import TailoredCV, TailoredCoverLetter
from renderers.latex_renderer import LaTeXRenderer
from services.cache_store import rules_fingerprint
from services.pipeline import DocumentGenerator
from services.prompts import build_context
from services.validation import ProfileRules
from support import read_json


@pytest.fixture
def local_rights_profile(analyst_profile):
    profile = analyst_profile.model_copy(deep=True)
    profile.identity.visa_status = 'Valid German EU Blue Card'
    profile.rules = DeclaredRules(visa_label='German EU Blue Card holder', home_countries=['Germany'])
    profile.rules.country_overrides['India'] = CountryApplicationRules(
        work_authorization='', requires_employer_support=False,
        tailoring_guidance=(
            'Highlight profile-backed European work experience where relevant to '
            'the Indian role. Do not invent international clients or leadership.'
        ),
    )
    return profile


@pytest.mark.parametrize('country', ['India', 'IN', 'ind', ' india '])
def test_local_rights_override_suppresses_cv_immigration_label(
    local_rights_profile, country, tmp_path,
):
    generator = DocumentGenerator(None, local_rights_profile)
    cv = TailoredCV.model_validate(read_json('content', 'valid_content.json')['cv'])
    generator._apply_visa_label(cv, country)
    assert cv.work_authorization == ''
    # None would fall back to the German status at render time; empty must not.
    rendered = LaTeXRenderer(outputs_dir=str(tmp_path))._prepare_template_data(
        cv, local_rights_profile,
    )
    assert 'Blue Card' not in rendered['tagline']


def test_letter_without_permit_sentence_is_accepted_for_local_rights(local_rights_profile):
    letter = TailoredCoverLetter.model_validate(
        read_json('content', 'valid_content.json')['cover_letter']
    )
    DocumentGenerator(None, local_rights_profile)._check_sponsorship_sentence(letter, 'India')


def test_full_model_validation_applies_the_override(local_rights_profile):
    generator = DocumentGenerator(None, local_rights_profile)
    content = read_json('content', 'valid_content.json')
    cv = generator._build_model({'cv': content['cv']}, 'cv', 'India', None, None)
    assert cv.work_authorization == ''
    letter = generator._build_model(
        {'cover_letter': content['cover_letter']}, 'cover_letter', 'India', None, None,
    )
    assert len(letter.paragraphs) == 4
    content['cv']['summary'] = ['Analyst holding a German EU Blue Card.']
    with pytest.raises(ValueError, match='existing work rights'):
        generator._build_model({'cv': content['cv']}, 'cv', 'India', None, None)


@pytest.mark.parametrize('wording', [
    'I hold a German EU Blue Card.',
    'I require employer support for an employment permit.',
    'No sponsorship is needed.',
])
def test_inapplicable_immigration_wording_triggers_correction(local_rights_profile, wording):
    generator = DocumentGenerator(None, local_rights_profile)
    letter = TailoredCoverLetter(role_title='Analyst', company_name='Example',
                                paragraphs=['First', 'Second', 'Third', wording])
    with pytest.raises(ValueError, match='existing work rights'):
        generator._check_sponsorship_sentence(letter, 'India')
    with pytest.raises(ValueError, match='existing work rights'):
        generator._check_country_override_wording(wording, 'India')


@pytest.mark.parametrize('country', ['Ireland', 'Netherlands'])
def test_other_destinations_still_require_their_support_sentence(local_rights_profile, country):
    generator = DocumentGenerator(None, local_rights_profile)
    letter = TailoredCoverLetter(role_title='Analyst', company_name='Example',
                                paragraphs=['First', 'Second', 'Third', 'Thank you.'])
    with pytest.raises(ValueError, match='employer permit support'):
        generator._check_sponsorship_sentence(letter, country)
    cv = TailoredCV()
    generator._apply_visa_label(cv, country)
    assert cv.work_authorization == 'German EU Blue Card holder'


def test_override_does_not_give_other_candidates_local_work_rights(
    analyst_profile, local_rights_profile,
):
    assert ProfileRules.from_profile(analyst_profile).country_override('India') is None
    assert ProfileRules.from_profile(local_rights_profile).country_override('India') is not None
    other_candidate = analyst_profile.model_copy(deep=True)
    other_candidate.identity.visa_status = 'Valid German EU Blue Card'
    letter = TailoredCoverLetter(role_title='Analyst', company_name='Example',
                                paragraphs=['First', 'Second', 'Third', 'Thank you.'])
    DocumentGenerator(None, other_candidate)._check_sponsorship_sentence(letter, 'India')


def test_germany_preserves_existing_status(local_rights_profile):
    cv = TailoredCV(work_authorization='model-generated label')
    DocumentGenerator(None, local_rights_profile)._apply_visa_label(cv, 'Germany')
    assert cv.work_authorization is None


def test_payment_brand_is_not_mistaken_for_a_visa_requirement(local_rights_profile):
    DocumentGenerator(None, local_rights_profile)._check_country_override_wording(
        'Experience reporting on Visa card payments.', 'India',
    )


@pytest.mark.parametrize('claim', [
    'I hold a valid EU Blue Card issued by France and require employer support.',
    'I hold a valid German EU Blue Card and a Green Card and require employer support.',
    'I hold a valid German EU Blue Card and require no employer sponsorship.',
])
def test_overseas_support_policy_does_not_allow_other_claims(local_rights_profile, claim):
    letter = TailoredCoverLetter(role_title='Analyst', company_name='Example',
                                paragraphs=['First', 'Second', 'Third', claim])
    with pytest.raises(ValueError, match='issuer|status|support'):
        DocumentGenerator(None, local_rights_profile)._check_sponsorship_sentence(letter, 'Ireland')


def test_explicit_support_override_can_apply_without_a_visa_status(analyst_profile):
    analyst_profile.identity.visa_status = None
    analyst_profile.rules = DeclaredRules(country_overrides={
        'Canada': CountryApplicationRules(requires_employer_support=True),
    })
    letter = TailoredCoverLetter(role_title='Analyst', company_name='Example',
                                paragraphs=['First', 'Second', 'Third',
                                            'I would require employer support for a work permit.'])
    DocumentGenerator(None, analyst_profile)._check_sponsorship_sentence(letter, 'Canada')


@pytest.mark.parametrize('country', ['India', None])
def test_context_explains_precedence_and_evidence_based_european_experience(
    local_rights_profile, country,
):
    context = build_context('An analytics role.', local_rights_profile, work_country=country)
    assert 'take precedence over generic visa instructions' in context
    assert 'European work experience' in context
    assert '"requires_employer_support": false' in context
    assert 'Apply only the actual employment country' in context
    assert 'do not invent international clients' in context.lower()


def test_changed_local_rights_invalidate_the_rules_digest(analyst_profile, local_rights_profile):
    before = rules_fingerprint(ProfileRules.from_profile(analyst_profile))
    after = rules_fingerprint(ProfileRules.from_profile(local_rights_profile))
    assert before != after
    local_rights_profile.rules.country_overrides['India'].tailoring_guidance = 'Updated emphasis.'
    assert after != rules_fingerprint(ProfileRules.from_profile(local_rights_profile))
