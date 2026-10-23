"""Characterization tests for CV tailoring, cover-letter generation and the retry loop.

Covers these ASSESSMENT.md §1 workflows:
  * CV tailoring
  * cover-letter generation
  * LLM response parsing
  * factual validation
  * retry handling
  * error handling

The pipeline is driven entirely from recorded fixtures through :class:`OfflineGemini`;
renderers are stubbed here because document output has its own suite
(`test_renderers_documents.py`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.tailored_output import TailoredCV, TailoredCoverLetter
from services import tailor_service as service
from support import read_json

JOB = 'A sufficiently detailed analytics engineering job description for fixture purposes.'


# --- happy path ----------------------------------------------------------------------

def test_pipeline_produces_a_two_page_cv_and_one_page_letter(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.status == 'success'
    assert result.cv_page_count == 2
    assert result.cover_letter_page_count == 1
    assert not offline.exhausted, 'pipeline asked for more responses than were recorded'
    # draft + editorial review + letter = 3 logical calls on the happy path.
    assert offline.call_count == 3


def test_saved_content_matches_the_accepted_documents(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))

    assert saved['company_name'] == 'Nordwind Analytics GmbH'
    assert saved['role_title'] == 'Analytical Engineer'
    # The letter passes through an editorial-reviewed CV, not the raw draft.
    assert saved['cv']['summary'] == analyst_session.step_payload('cv_editorial_review')['cv']['summary']
    assert saved['cover_letter']['paragraphs'] == \
        analyst_session.step_payload('cover_letter')['cover_letter']['paragraphs']


def test_artifacts_are_persisted_under_the_job_folder(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    job_folder = isolated_service / 'outputs' / result.job_id
    source = job_folder / 'source'

    assert Path(result.cv_path).exists()
    assert Path(result.cover_letter_path).exists()
    assert Path(result.cl_pdf_path).exists()
    for name in ('content.json', 'profile_snapshot.json', 'job_description.txt',
                 'drafts.json', 'generation_result.json'):
        assert (source / name).exists(), f'missing {name}'

    manifest = read_json(source / 'generation_result.json')
    assert manifest['status'] == 'success'
    assert manifest['cv_page_history'] == [2]


def test_job_id_encodes_year_company_role_and_a_timestamp(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    parts = result.job_id.split('_')
    assert parts[-1].isdigit()
    assert 'nordwind' in result.job_id and 'analytical' in result.job_id


def test_letter_company_and_role_are_forced_to_the_caller_values(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Explicit company/role must override whatever the model wrote."""
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Overridden Corp', role_title='Overridden Role',
    )
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))
    assert saved['cover_letter']['company_name'] == 'Overridden Corp'
    assert saved['cover_letter']['role_title'] == 'Overridden Role'
    assert saved['role_title'] == 'Overridden Role'


def test_message_reports_pages_and_letter_words(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    words = sum(len(p.split()) for p in
                analyst_session.step_payload('cover_letter')['cover_letter']['paragraphs'])
    assert '2 pages' in result.message
    assert f'{words} words' in result.message


def test_tailoring_explanation_is_carried_through(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The editorial-review response is the source of the explanation."""
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    assert result.tailoring_explanation is not None
    expected = analyst_session.step_payload('cv_editorial_review')['tailoring_explanation']
    assert result.tailoring_explanation['overall_strategy'] == expected['overall_strategy']


def test_nested_tailoring_explanation_is_read_from_inside_cv(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A response that nests the explanation under ``cv`` must not silently yield None.

    The documented shape puts it at the top level (covered above), but models often
    nest it inside ``cv``. Before the fix this produced
    ``tailoring_explanation is None`` with no error at all.
    """
    review = json.loads(analyst_session.step_text('cv_editorial_review'))
    nested = review.pop('tailoring_explanation')
    review['cv']['tailoring_explanation'] = nested
    offline_service([
        analyst_session.step_text('cv_draft'), json.dumps(review),
        analyst_session.step_text('cover_letter'),
    ])
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    assert result.tailoring_explanation is not None
    assert result.tailoring_explanation['overall_strategy'] == nested['overall_strategy']


def test_top_level_explanation_still_wins_over_a_nested_one(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Precedence is unchanged: the documented top-level key is authoritative."""
    review = json.loads(analyst_session.step_text('cv_editorial_review'))
    review['cv']['tailoring_explanation'] = {'overall_strategy': 'nested decoy'}
    offline_service([
        analyst_session.step_text('cv_draft'), json.dumps(review),
        analyst_session.step_text('cover_letter'),
    ])
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    assert result.tailoring_explanation['overall_strategy'] != 'nested decoy'
    assert result.tailoring_explanation['overall_strategy'] == \
        review['tailoring_explanation']['overall_strategy']


def test_layout_retry_explanation_takes_precedence_when_supplied(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A layout retry that returns its own explanation must supersede the review's one."""
    draft = analyst_session.step_text('cv_draft')
    review = analyst_session.step_text('cv_editorial_review')
    retry = service._parse_json_response(analyst_session.step_text('cv_layout_retry'))
    retry['tailoring_explanation'] = {'overall_strategy': 'from the layout retry'}
    offline_service([
        draft, review, analyst_session.step_text('cover_letter'), json.dumps(retry),
    ])
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    assert result.tailoring_explanation['overall_strategy'] == 'from the layout retry'


# --- a second, differently-shaped profile --------------------------------------------

def test_second_profile_generates_independently(
    isolated_service, offline_service, stub_renderers, marketer_profile, marketer_session,
):
    """ADR 0003 isolation: profile B's facts appear, profile A's do not."""
    offline = offline_service(marketer_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        marketer_session.job_description_text, marketer_profile,
        company_name='Lumen Consumer BV', role_title='Growth Analyst',
    )
    assert result.status == 'success'
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))

    prompt = '\n'.join(offline.prompts)
    assert 'Robin Example' in prompt and 'Initech Growth BV' in prompt
    for leak in ('Alex Sample', 'Northwind Analytics', 'Contoso', 'Fabrikam'):
        assert leak not in prompt, f'profile A leaked into profile B generation: {leak}'
    assert saved['cover_letter']['signature_name'] == 'Robin Example'


# --- LLM response parsing ------------------------------------------------------------

def test_parser_accepts_fenced_json(analyst_session):
    fenced = analyst_session.step_text('cv_layout_retry')
    assert fenced.lstrip().startswith('```')
    parsed = service._parse_json_response(fenced)
    assert parsed['cv']['title']


@pytest.mark.parametrize('wrapper', [
    'Here is the JSON you asked for: {"cv": {"title": "x"}} and some trailing prose.',
    '```json\n{"cv": {"title": "x"}}\n```',
    '{"cv": {"title": "x"}}',
])
def test_parser_tolerates_wrappers(wrapper):
    parsed = service._parse_json_response(wrapper)
    assert parsed['cv']['title'] == 'x'


@pytest.mark.parametrize('payload', ['{}', '', '   '])
def test_parser_rejects_payloads_without_a_document(payload):
    with pytest.raises(ValueError):
        service._parse_json_response(payload)


def test_parser_accepts_each_document_kind(analyst_session):
    assert 'cv' in service._parse_json_response(analyst_session.step_text('cv_draft'))
    assert 'cover_letter' in service._parse_json_response(analyst_session.step_text('cover_letter'))


@pytest.mark.parametrize('payload', [
    '{"cv": {"summary": ["incomplete',
    '{"cv": ',
    'not json at all',
    '[]',
    '{"unrelated": 1}',
])
def test_parser_rejects_unusable_payloads(payload):
    with pytest.raises(ValueError):
        service._parse_json_response(payload)


@pytest.mark.parametrize('payload', ['', '   ', None, 42])
def test_parser_rejects_empty_or_non_text(payload):
    with pytest.raises(ValueError, match='empty document'):
        service._parse_json_response(payload)


def test_truncated_json_is_never_repaired_into_a_document():
    """The documented guarantee: never repair truncated document data."""
    with pytest.raises(ValueError, match='complete document'):
        service._parse_json_response('{"cv":{"summary":["incomplete')


# --- factual validation --------------------------------------------------------------

def test_cv_validation_accepts_the_recorded_fixture(analyst_profile, analyst_session):
    cv = TailoredCV.model_validate(analyst_session.step_payload('cv_draft')['cv'])
    service._validate_cv(cv, analyst_profile)  # must not raise


def test_cv_validation_sorts_experience_into_profile_order(analyst_profile, analyst_session):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['experience'] = list(reversed(payload['experience']))
    cv = TailoredCV.model_validate(payload)

    service._validate_cv(cv, analyst_profile)

    expected = [exp.company for exp in analyst_profile.experience]
    assert [exp.company for exp in cv.experience] == expected


def test_missing_employer_is_rejected(analyst_profile, analyst_session):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['experience'] = payload['experience'][:-1]
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match='each profile employer exactly once'):
        service._validate_cv(cv, analyst_profile)


def test_duplicated_employer_is_rejected(analyst_profile, analyst_session):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['experience'].append(dict(payload['experience'][0]))
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match='each profile employer exactly once'):
        service._validate_cv(cv, analyst_profile)


def test_altered_role_title_is_rejected(analyst_profile, analyst_session):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['experience'][0]['role'] = 'Head of Everything'
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match='exact profile title and dates'):
        service._validate_cv(cv, analyst_profile)


@pytest.mark.parametrize('field', ['start_date', 'end_date'])
def test_altered_dates_are_rejected(analyst_profile, analyst_session, field):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['experience'][0][field] = '1999-01'
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match='exact profile title and dates'):
        service._validate_cv(cv, analyst_profile)


def test_inventing_bullets_for_an_empty_employer_is_rejected(analyst_profile, analyst_session):
    """Fabrikam Internship has no profile bullets and must stay empty."""
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['experience'][-1]['bullets'] = ['Invented responsibility for a bulletless employer.']
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match='Do not invent responsibilities'):
        service._validate_cv(cv, analyst_profile)


@pytest.mark.parametrize('tool', ['Fivetran', 'Databricks', 'Tableau', 'ThoughtSpot',
                                  'DealCloud', 'Cortex', 'AWS'])
def test_unclaimed_tools_are_rejected(analyst_profile, analyst_session, tool):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['skills'] = {'Injected': [tool]}
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match=tool):
        service._validate_cv(cv, analyst_profile)


@pytest.mark.parametrize('phrase', ['combines', 'builds', 'aims', 'passionate', 'dedicated to'])
def test_aspirational_summary_language_is_rejected(analyst_profile, analyst_session, phrase):
    payload = analyst_session.step_payload('cv_draft')['cv']
    payload['summary'] = [f'An analyst who {phrase} deliver value.']
    cv = TailoredCV.model_validate(payload)

    with pytest.raises(ValueError, match='factual career summary'):
        service._validate_cv(cv, analyst_profile)


def test_cover_letter_validation_accepts_the_recorded_fixture(analyst_profile, analyst_session):
    letter = TailoredCoverLetter.model_validate(
        analyst_session.step_payload('cover_letter')['cover_letter'])
    service._validate_cover_letter(letter, analyst_profile)  # must not raise
    assert 290 <= sum(len(p.split()) for p in letter.paragraphs) <= 310


@pytest.mark.parametrize('count', [3, 5])
def test_wrong_paragraph_count_is_rejected(analyst_profile, analyst_session, count):
    payload = analyst_session.step_payload('cover_letter')['cover_letter']
    payload['paragraphs'] = (payload['paragraphs'] * 2)[:count]
    letter = TailoredCoverLetter.model_validate(payload)

    with pytest.raises(ValueError, match='exactly four body paragraphs'):
        service._validate_cover_letter(letter, analyst_profile)


def test_too_few_words_is_rejected(analyst_profile):
    letter = TailoredCoverLetter(
        company_name='X', role_title='Y', signature_name=analyst_profile.identity.full_name,
        paragraphs=['short paragraph'] * 4,
    )
    with pytest.raises(ValueError, match='290-310 words'):
        service._validate_cover_letter(letter, analyst_profile)


def test_too_many_words_is_rejected(analyst_profile):
    letter = TailoredCoverLetter(
        company_name='X', role_title='Y', signature_name=analyst_profile.identity.full_name,
        paragraphs=[' '.join(['word'] * 100)] * 4,
    )
    with pytest.raises(ValueError, match='290-310 words'):
        service._validate_cover_letter(letter, analyst_profile)


def test_wrong_signature_name_is_rejected(analyst_profile, analyst_session):
    payload = analyst_session.step_payload('cover_letter')['cover_letter']
    payload['signature_name'] = 'Someone Else'
    letter = TailoredCoverLetter.model_validate(payload)

    with pytest.raises(ValueError, match='exact candidate name'):
        service._validate_cover_letter(letter, analyst_profile)


@pytest.mark.parametrize('opening', ['Dear Hiring Manager,', 'Sincerely,', 'Best regards,',
                                     'Kind regards,'])
def test_salutation_or_signoff_inside_the_body_is_rejected(analyst_profile, analyst_session, opening):
    payload = analyst_session.step_payload('cover_letter')['cover_letter']
    payload['paragraphs'][0] = opening + ' ' + payload['paragraphs'][0]
    letter = TailoredCoverLetter.model_validate(payload)

    with pytest.raises(ValueError, match='salutation or signature'):
        service._validate_cover_letter(letter, analyst_profile)


# --- retry handling ------------------------------------------------------------------

def test_layout_retry_shortens_the_cv_until_it_fits(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.cv_page_count == 2
    # draft + editorial review + one layout revision
    assert result.token_usage.cv_attempts == 3
    manifest = read_json(Path(result.source_path).with_name('generation_result.json'))
    assert manifest['cv_page_history'] == [3, 2]
    # The retry must be sent the current candidate, not the original prompt alone.
    assert 'CURRENT CV:' in offline.last_prompt
    assert 'LAYOUT CORRECTION' in offline.last_prompt
    assert '2 words' not in offline.last_prompt


def test_layout_retry_budget_shrinks_with_each_attempt(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline = offline_service(analyst_session.texts())
    stub_renderers([4, 3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    budgets = [p for p in offline.prompts if 'LAYOUT CORRECTION' in p]
    assert len(budgets) == 2
    assert 'approximately 650 words' in budgets[0]
    assert 'approximately 550 words' in budgets[1]


def test_three_page_cv_is_never_reported_as_success(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([3, 3, 3, 3])

    with pytest.raises(ValueError, match='not marked successful'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )


def test_short_letter_is_corrected_rather_than_silently_accepted(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    draft = analyst_session.step_payload('cv_draft')
    review = analyst_session.step_payload('cv_editorial_review')
    good_letter = analyst_session.step_text('cover_letter')

    bad = json.loads(good_letter)
    bad['cover_letter']['paragraphs'] = ['short paragraph'] * 4
    offline = offline_service([
        json.dumps(draft), json.dumps(review), json.dumps(bad), good_letter,
    ])
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.token_usage.cl_attempts == 2
    assert 'CORRECTION REQUIRED' in offline.last_prompt
    assert '290-310 words' in offline.last_prompt


def test_validation_retries_are_capped_at_three_attempts(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    bad = json.loads(analyst_session.step_text('cv_draft'))
    bad['cv']['experience'] = bad['cv']['experience'][:-1]  # always missing an employer
    offline_service([json.dumps(bad)] * 3)
    stub_renderers([2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )


def test_fenced_json_is_accepted_on_a_retry(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The recorded layout-retry step is fenced; the parser must accept it."""
    offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))
    assert saved['cv']['summary'] == [
        'Analytical engineer with experience across warehouse modelling and pipeline reliability.'
    ]


# --- error handling ------------------------------------------------------------------

@pytest.mark.parametrize('job_description', ['', '   ', '\n\t '])
def test_empty_job_description_is_rejected(tmp_path, analyst_profile, job_description, isolated_service):
    with pytest.raises(ValueError, match='Job description is empty'):
        service.tailor_documents(job_description, analyst_profile)


def test_missing_pdf_fails_instead_of_counting_zero_pages(tmp_path):
    with pytest.raises(Exception):
        service._count_pdf_pages(tmp_path / 'missing.pdf')


def test_failed_generation_records_a_manifest_and_skips_mirroring(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session, monkeypatch,
):
    offline_service(analyst_session.texts())
    stub_renderers([3, 3, 3, 3])
    monkeypatch.setenv('OUTPUTS_DIR', str(isolated_service / 'mirror'))

    with pytest.raises(ValueError):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )

    manifests = list((isolated_service / 'outputs').glob('*/source/generation_result.json'))
    assert len(manifests) == 1
    manifest = read_json(manifests[0])
    assert manifest['status'] == 'failed'
    assert manifest['error']
    assert manifest['cv_page_history'] == [3, 3, 3, 3]
    # A failed run must not publish anything downstream.
    assert not (isolated_service / 'mirror').exists()


def test_failure_still_preserves_the_editable_draft(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([3, 3, 3, 3])

    with pytest.raises(ValueError) as error:
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )

    source = next((isolated_service / 'outputs').glob('*/source'))
    assert (source / 'content.json').exists()
    assert (source / 'drafts.json').exists()
    assert str(source) in str(error.value)


# --- cost accounting -----------------------------------------------------------------

def test_token_usage_is_attributed_per_component(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts(), inputs_per_call=1000, outputs_per_call=100)
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    usage = result.token_usage

    # 3 CV calls (draft, review, one layout retry), 1 letter call.
    assert usage.cv_attempts == 3 and usage.cl_attempts == 1
    assert usage.cv_input_tokens == 3000 and usage.cl_input_tokens == 1000
    assert usage.cv_output_tokens == 300 and usage.cl_output_tokens == 100
    assert usage.total_tokens == 4400


# --- shared text helpers (D-12) ------------------------------------------------------

def test_shared_slugify_matches_the_previous_renderer_behaviour():
    """D-12 replaced three _slugify copies with one; the observable results must not drift."""
    from utils.text import slugify

    assert slugify('Nordwind Analytics GmbH') == 'nordwind_analytics_gmbh'
    assert slugify('  Senior Data Analyst  ') == 'senior_data_analyst'
    # Runs of punctuation collapse to a single underscore, and edges are trimmed.
    assert slugify('Data / Engineering -- Lead') == 'data_engineering_lead'
    assert slugify('C++ & Python') == 'c_python'
    # The documented empty-input fallback.
    assert slugify('') == 'role'
    assert slugify('!!!') == 'role'


def test_both_renderers_escape_latex_identically():
    """The two renderers must agree, including the backslash-first ordering."""
    from renderers.docx_renderer import DocxRenderer
    from renderers.latex_renderer import LaTeXRenderer

    sample = r'100% & 5_000 #1 $x {y} ~n ^c \d'
    assert LaTeXRenderer._escape_latex(sample) == DocxRenderer._escape_latex(sample)
    # Backslash is replaced first, so the braces in its own replacement text are then
    # escaped too. That is the long-standing behaviour of both original copies and is
    # pinned here so consolidating them (D-12) cannot silently change it.
    assert LaTeXRenderer._escape_latex('\\') == r'\textbackslash\{\}'
    assert LaTeXRenderer._escape_latex('a&b') == r'a\&b'
    assert LaTeXRenderer._escape_latex('100%') == r'100\%'


def test_escaping_is_idempotent_for_text_without_specials():
    from utils.text import escape_latex

    assert escape_latex('plain text 123') == 'plain text 123'
    assert escape_latex('') == ''
    # Non-string values pass through, as the renderers rely on for optional fields.
    assert escape_latex(None) is None
    assert escape_latex(42) == 42


# --- pricing table -------------------------------------------------------------------

def test_an_unknown_model_is_priced_without_crashing():
    """A model missing from PRICING must fall back, never raise KeyError.

    The fallback used to point at a legacy pricing row. Removing stale rows is only
    safe while the fallback target is itself always present -- this test pins that.
    """
    from services.gemini_service import DEFAULT_MODEL, PRICING, GeminiService

    assert DEFAULT_MODEL in PRICING, 'the fallback target must always be priced'

    service_double = object.__new__(GeminiService)
    service_double.model = 'a-model-that-does-not-exist'
    cost = service_double._estimate_cost(1_000_000, 1_000_000)

    assert cost == PRICING[DEFAULT_MODEL]['input'] + PRICING[DEFAULT_MODEL]['output']


def test_no_retired_model_rows_remain_in_pricing():
    """Legacy rows mispriced nothing but actively misled; they are gone (D-5)."""
    from services.gemini_service import PRICING

    for retired in ('gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-3-pro-preview'):
        assert retired not in PRICING, f'{retired} is retired and must not be priced'
