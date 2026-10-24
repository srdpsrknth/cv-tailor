import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter

from models.profile import Profile
from models.requests import TokenUsage
from models.tailored_output import TailoredCV, TailoredCoverLetter
from services import tailor_service as service


@pytest.fixture
def profile():
    return Profile(version='1.0', identity={'full_name': 'Candidate', 'email': 'name@example.com'},
                   experience=[{'company': 'Example', 'role': 'Analyst', 'start_date': '2020-01',
                                'end_date': 'present', 'bullets': ['Built reporting.']}])


@pytest.fixture(autouse=True)
def _this_files_own_candidate(tmp_path, monkeypatch, profile):
    """Store this file's throwaway "Candidate" profile under its own id.

    These tests build their own ``Profile`` rather than loading a fixture, and
    ``profile_id`` is now checked against the store (ADR 0003): a profile whose
    identity does not match the id it is filed under is exactly the cross-candidate
    error that check exists to catch. Registering the profile under a dedicated id
    keeps the check honest instead of disabling it for this file.
    """
    import yaml

    from services.profile_store import ProfileStore

    store_root = tmp_path
    store = ProfileStore.at(store_root)
    directory = store.profiles_dir / 'unit_candidate'
    directory.mkdir(parents=True)
    (directory / 'profile.yaml').write_text(
        yaml.safe_dump(profile.model_dump(), sort_keys=False), encoding='utf-8'
    )
    monkeypatch.setenv('CVTAILOR_STORE', str(store_root))
    monkeypatch.setenv('CVTAILOR_PROFILE_ID', 'unit_candidate')
    return 'unit_candidate'


def cv_data(profile):
    return {'summary': ['Analytics professional with a background in business intelligence.'],
            'skills': {'Data': ['SQL']},
            'experience': [{key: value for key, value in profile.experience[0].model_dump().items()
                            if key in ('company', 'role', 'start_date', 'end_date', 'bullets')}],
            'include_education': True, 'include_certifications': True}


def cl_data():
    return {'company_name': 'Test Company', 'role_title': 'Analyst', 'signature_name': 'Candidate',
            'paragraphs': [' '.join(['word'] * 75) for _ in range(4)]}


def write_pdf(path, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open('wb') as stream:
        writer.write(stream)
    return str(path)


def configure(monkeypatch, tmp_path, profile, pages, responses):
    monkeypatch.setattr(service, 'PROJECT_ROOT', tmp_path)
    # The autouse fixture roots the store at tmp_path, so ``<store>/outputs`` is
    # ``<tmp_path>/outputs`` -- exactly what these tests assert against.
    monkeypatch.setenv('OUTPUTS_DIR', str(tmp_path / 'mirror'))
    fake = Mock()
    fake._call_gemini.side_effect = [(text, 100, 20) for text in responses]
    fake.calculate_token_usage.side_effect = lambda **kw: TokenUsage(**kw, model_name='test')
    monkeypatch.setattr(service, 'GeminiService', lambda: fake)
    page_counts = iter(pages)
    def latex_factory(outputs_dir):
        renderer = Mock()
        renderer.render_cv.side_effect = lambda *a, **kw: write_pdf(Path(outputs_dir) / 'CV.pdf', next(page_counts))
        return renderer
    def docx_factory(outputs_dir):
        def render(*a, **kw):
            docx = Path(outputs_dir) / 'cover_letter.docx'
            docx.write_bytes(b'docx')
            return str(docx), write_pdf(Path(outputs_dir) / 'cover_letter.pdf', 1)
        renderer = Mock()
        renderer.render_cover_letter.side_effect = render
        return renderer
    monkeypatch.setattr(service, 'create_latex_renderer', latex_factory)
    monkeypatch.setattr(service, 'create_docx_renderer', docx_factory)
    return fake


def test_length_retry_accepts_fenced_json_and_saves_final_content(monkeypatch, tmp_path, profile):
    cv = cv_data(profile)
    shorter = {**cv, 'summary': ['Analytics professional with broad reporting experience.']}
    fake = configure(monkeypatch, tmp_path, profile, [3, 2], [
        json.dumps({'cv': cv}), json.dumps({'cv': cv}), json.dumps({'cover_letter': cl_data()}),
        '```json\n' + json.dumps({'cv': shorter}) + '\n```',
    ])
    result = service.tailor_documents('A sufficiently detailed job description.', profile)
    assert result.status == 'success' and result.cv_page_count == 2
    assert result.token_usage.cv_attempts == 3 and result.token_usage.cl_attempts == 1
    assert result.token_usage.cv_input_tokens == 300 and result.token_usage.cl_input_tokens == 100
    saved = json.loads(Path(result.source_path).read_text())
    assert saved['cv']['summary'] == shorter['summary']
    assert Path(result.cv_path).read_bytes() == (Path(result.source_path).parent.parent / 'CV.pdf').read_bytes()
    history = json.loads(Path(result.source_path).with_name('generation_result.json').read_text())
    assert history['cv_page_history'] == [3, 2]
    assert shorter['summary'][0] in fake._call_gemini.call_args_list[-1].args[0] or 'CURRENT CV:' in fake._call_gemini.call_args_list[-1].args[0]


def test_three_page_cv_is_never_reported_as_success(monkeypatch, tmp_path, profile):
    cv = json.dumps({'cv': cv_data(profile)})
    configure(monkeypatch, tmp_path, profile, [3, 3, 3, 3],
              [cv, cv, json.dumps({'cover_letter': cl_data()}), cv, cv, cv])
    with pytest.raises(ValueError, match='not marked successful'):
        service.tailor_documents('A sufficiently detailed job description.', profile)
    # Phase 2 layout: outputs/<profile_id>/<job_id>/source/... (ADR 0003).
    manifest = next((tmp_path / 'outputs').glob('*/*/source/generation_result.json'))
    assert json.loads(manifest.read_text())['status'] == 'failed'
    assert not (tmp_path / 'mirror').exists()


def test_short_letter_is_corrected_instead_of_silently_accepted(monkeypatch, tmp_path, profile):
    cv = json.dumps({'cv': cv_data(profile)})
    short = {**cl_data(), 'paragraphs': ['short paragraph'] * 4}
    fake = configure(monkeypatch, tmp_path, profile, [2],
                     [cv, cv, json.dumps({'cover_letter': short}), json.dumps({'cover_letter': cl_data()})])
    result = service.tailor_documents('A sufficiently detailed job description.', profile)
    assert result.token_usage.cl_attempts == 2
    assert '8 words' in fake._call_gemini.call_args_list[-1].args[0]


def test_truncated_json_and_unreadable_pdf_fail():
    with pytest.raises(ValueError, match='complete document'):
        service._parse_json_response('{"cv":{"summary":["incomplete')
    with pytest.raises(Exception):
        service._count_pdf_pages(Path('missing.pdf'))


@pytest.mark.parametrize('country', ['Netherlands', 'Ireland'])
def test_selected_country_controls_prompt_header_and_saved_context(monkeypatch, tmp_path, profile, country):
    profile.identity.visa_status = 'Valid EU Blue Card Visa'
    cv = json.dumps({'cv': cv_data(profile)})
    letter = cl_data()
    closing = f'I hold a valid EU Blue Card issued by Germany and require employer support for an employment permit in {country}.'
    letter['paragraphs'][-1] = closing + ' ' + ' '.join(['word'] * (75 - len(closing.split())))
    fake = configure(monkeypatch, tmp_path, profile, [2], [cv, cv, json.dumps({'cover_letter': letter})])
    result = service.tailor_documents('Employer headquarters Germany; job description is ambiguous.', profile, work_country=country)
    saved = json.loads(Path(result.source_path).read_text())
    assert saved['work_country'] == country
    assert saved['cv']['work_authorization'] == 'German EU Blue Card holder'
    assert all(f'explicit user selection; overrides country inference): {country}' in call.args[0] for call in fake._call_gemini.call_args_list)


def test_streamlit_passes_selected_work_country(monkeypatch):
    from streamlit.testing.v1 import AppTest
    post = Mock(return_value=Mock(status_code=400, json=lambda: {'detail': 'Test response'}))
    monkeypatch.setattr('requests.post', post)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'ui/app.py')).run()
    app.text_area(key='job_desc').input('A detailed analytics engineering opening. ' * 3)
    app.selectbox(key='work_country_choice').select('Netherlands').run()
    app.button[0].click().run()
    assert not app.exception
    assert post.call_args.kwargs['json']['work_country'] == 'Netherlands'
    app.selectbox(key='work_country_choice').select('Other').run()
    assert app.button[0].disabled
    app.text_input(key='work_country_other').input('Sweden').run()
    assert not app.button[0].disabled


def test_invented_tools_and_altered_job_dates_are_rejected(profile):
    cv = TailoredCV.model_validate(cv_data(profile))
    cv.skills = {'Data': ['Fivetran']}
    with pytest.raises(ValueError, match='Fivetran'):
        service._validate_cv(cv, profile)
    cv.skills = {}
    cv.experience[0].start_date = '2018-01'
    with pytest.raises(ValueError, match='exact profile title and dates'):
        service._validate_cv(cv, profile)


def test_signoff_in_letter_body_is_rejected(profile):
    data = cl_data()
    data['paragraphs'][-1] = 'Sincerely, ' + data['paragraphs'][-1]
    with pytest.raises(ValueError, match='salutation or signature'):
        service._validate_cover_letter(TailoredCoverLetter(**data), profile)
