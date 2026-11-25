"""Text preservation and isolation of the parser-oriented CV export."""

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfReader

from models.profile import Profile
from models.tailored_output import TailoredCoverLetter, TailoredCV
from support import latex_available, read_json


def test_upload_preserves_content_and_has_sequential_body_only(tmp_path, analyst_profile):
    from renderers.upload_cv import render_upload_cv

    cv = TailoredCV.model_validate(read_json('content', 'valid_content.json')['cv'])
    before = cv.model_dump()
    paths = render_upload_cv(cv, analyst_profile, tmp_path, 'Analytical Engineer')
    doc = Document(paths['cv_upload_docx_path'])
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert text == Path(paths['cv_upload_text_path']).read_text(encoding='utf-8').rstrip('\n')
    assert analyst_profile.identity.email in text
    assert analyst_profile.identity.linkedin in text
    for exp in cv.experience:
        assert text.index(exp.role) < text.index(exp.company)
        for bullet in exp.bullets:
            assert bullet in text
        for project in exp.projects:
            assert project.name in text
            assert all(b in text for b in project.bullets)
    assert cv.model_dump() == before
    assert not doc.tables
    with ZipFile(paths['cv_upload_docx_path']) as archive:
        xml = archive.read('word/document.xml').decode()
        assert 'w:tbl>' not in xml and 'w:txbxContent' not in xml
        assert not any(n.startswith(('word/header', 'word/footer')) for n in archive.namelist())


def test_upload_omissions_and_authorization_override(tmp_path, analyst_profile):
    from renderers.upload_cv import render_upload_cv

    cv = TailoredCV(include_education=False, include_certifications=False,
                    work_authorization='Application-specific label')
    paths = render_upload_cv(cv, analyst_profile, tmp_path)
    text = Path(paths['cv_upload_text_path']).read_text(encoding='utf-8')
    assert 'Education' not in text and 'Certifications' not in text
    assert 'Application-specific label' in text
    assert analyst_profile.identity.visa_status not in text


@pytest.mark.parametrize(('legacy', 'render_pdfs'), [
    pytest.param(False, False, id='current-snapshot'),
    pytest.param(True, False, id='legacy-snapshot'),
    pytest.param(False, True, id='current-full-exports', marks=pytest.mark.requires_latex),
    pytest.param(True, True, id='legacy-full-exports', marks=pytest.mark.requires_latex),
])
def test_saved_export_uses_snapshot_and_leaves_sources_unchanged(
    tmp_path, analyst_profile, legacy, render_pdfs, monkeypatch,
):
    if render_pdfs and not latex_available():
        pytest.skip('pdflatex unavailable')
    from services.upload_cv import export_saved_upload_cv
    from config import Config

    config = Config.from_env(
        load_env_file=False,
        overrides={"project_root": tmp_path, "profile_store_dir": tmp_path},
    )
    folder = config.store.outputs_dir('analyst_a') / 'upload_test'
    source = folder / 'source'
    source.mkdir(parents=True)
    snapshot = analyst_profile.model_dump()
    snapshot['identity']['full_name'] = 'Historical Candidate'
    content = read_json('content', 'valid_content.json')
    if legacy:
        for field in ('cv_section_order', 'cv_hidden_sections', 'standalone_projects',
                      'publications', 'activities', 'job_search'):
            snapshot.pop(field)
        for education in snapshot['education']:
            education.pop('ongoing')
        content['cv'].pop('standalone_projects', None)
    else:
        snapshot.update(
            standalone_projects=[{'name': 'Transit Map', 'bullets': ['Mapped bus stops.']}],
            publications=['A. Sample (2025). Transit Data.'],
            activities=['Volunteer Mentor, Example Club.'],
            cv_section_order=['education', 'projects', 'publications'],
            cv_hidden_sections=['activities'],
        )
        snapshot['education'][0].update(ongoing=True, end_year=2028)
        content['cv']['standalone_projects'] = ['Transit Map']
    for name, value in [('content', content), ('profile_snapshot', snapshot)]:
        (source / f'{name}.json').write_text(json.dumps(value), encoding='utf-8')
    (source / 'generation_result.json').write_text(
        json.dumps({'status': 'success', 'provider': 'historical',
                    'artifact_provenance': {'old.pdf': {'artifact_sha256': 'preserve'}}}),
        encoding='utf-8',
    )
    originals = {
        name: (source / f'{name}.json').read_bytes()
        for name in ('content', 'profile_snapshot')
    }
    paths = export_saved_upload_cv(config, 'analyst_a', folder.name)
    text = Path(paths['cv_upload_text_path']).read_text(encoding='utf-8')
    assert text.splitlines() == [row.text for row in Document(paths['cv_upload_docx_path']).paragraphs]
    assert 'Historical Candidate' in text
    assert 'Volunteer Mentor' not in text
    if legacy:
        assert all(heading not in text.splitlines() for heading in ['Projects', 'Publications', 'Activities'])
    else:
        assert text.index('Education\n') < text.index('Projects\n') < text.index('Publications\n')
        assert 'Present (expected 2028)' in text
        assert 'Mapped bus stops.' in text and 'A. Sample (2025). Transit Data.' in text
    if render_pdfs:
        import pdfplumber

        from renderers import LaTeXRendererError, create_docx_renderer
        from services import document_quality
        from services.application_layout_preview import preview_saved_cv_layout, save_cv_layout_preview

        inspect = document_quality.inspect_document
        trial_reports = []

        def record_trial(path, **expected):
            result = inspect(path, **expected)
            trial_reports.append({engine: {
                key: checks[key] for key in ('status', 'word_retention', 'reading_order',
                                             'missing_fields', 'suspicious_glyphs')
            } for engine, checks in result['engines'].items()})
            return result

        monkeypatch.setattr(document_quality, 'inspect_document', record_trial)
        try:
            pdf, report = preview_saved_cv_layout(config, 'analyst_a', folder.name)
        except LaTeXRendererError as error:
            if not trial_reports:
                raise
            pytest.fail(f'{error}\nPDF extraction trials: {json.dumps(trial_reports)}', pytrace=False)
        saved = save_cv_layout_preview(config, 'analyst_a', folder.name, pdf, report)
        assert saved.read_bytes() == pdf
        reader = PdfReader(BytesIO(pdf))
        pdf_text = ' '.join(' '.join(page.extract_text() or '' for page in reader.pages).split())
        assert 'historical candidate' in pdf_text.casefold()
        with pdfplumber.open(BytesIO(pdf)) as plumber_pdf:
            plumber_text = ' '.join((plumber_pdf.pages[0].extract_text() or '').split())
        assert 'historical candidate' in plumber_text.casefold()
        assert ('Present (expected 2028)' in pdf_text) == (not legacy)
        assert ('Mapped bus stops.' in pdf_text) == (not legacy)
        assert ('Transit Data.' in pdf_text) == (not legacy)
        assert 'Volunteer Mentor' not in pdf_text
        letter = TailoredCoverLetter.model_validate(content['cover_letter'])
        letter_docx, letter_pdf = create_docx_renderer(outputs_dir=folder).render_cover_letter(
            letter, Profile.model_validate(snapshot),
        )
        letter_word_text = ' '.join(' '.join(row.text for row in Document(letter_docx).paragraphs).split())
        letter_reader = PdfReader(letter_pdf)
        assert len(letter_reader.pages) == 1
        assert letter.paragraphs[0] in letter_word_text
        assert letter.paragraphs[0] in ' '.join(letter_reader.pages[0].extract_text().split())
    assert originals == {
        name: (source / f'{name}.json').read_bytes()
        for name in ('content', 'profile_snapshot')
    }
    manifest = json.loads((source / 'generation_result.json').read_text(encoding='utf-8'))
    assert manifest['provider'] == 'historical'
    assert manifest['artifact_provenance']['old.pdf']['artifact_sha256'] == 'preserve'
    assert set(Path(paths[key]).name for key in paths) <= set(manifest['artifact_provenance'])
    from services.application_review import load_review
    detail = load_review(config, 'analyst_a', folder.name)
    assert all(
        detail['artifact_freshness'][Path(path).name]['status'] == 'current'
        for path in paths.values()
    )
    with pytest.raises(ValueError):
        export_saved_upload_cv(config, 'marketer_b', folder.name)
    (source / 'profile_snapshot.json').unlink()
    with pytest.raises(ValueError, match='snapshot'):
        export_saved_upload_cv(config, 'analyst_a', folder.name)


def test_upload_download_labels():
    from ui.services_bridge import document_label

    assert document_label('2026_CV_ada_upload.docx') == 'CV for autofill · DOCX'
    assert document_label('2026_CV_ada_upload.txt') == 'CV for autofill · TXT'


def test_upload_preserves_acronyms_core_properties_and_unicode_bullets(tmp_path, analyst_profile):
    from renderers.upload_cv import render_upload_cv

    cv = TailoredCV.model_validate(read_json('content', 'valid_content.json')['cv'])
    cv.skills = {
        'BI_and_AI_tools': ['Looker', 'Claude'],
        'sql_data_engineering': ['Snowflake', 'dbt'],
    }
    paths = render_upload_cv(cv, analyst_profile, tmp_path, 'Analytical Engineer')
    doc = Document(paths['cv_upload_docx_path'])
    assert doc.core_properties.author == analyst_profile.identity.full_name
    assert analyst_profile.identity.full_name in doc.core_properties.title
    assert 'Analytical Engineer' in doc.core_properties.title

    text = Path(paths['cv_upload_text_path']).read_text(encoding='utf-8')
    assert 'BI And AI Tools: Looker, Claude' in text
    assert 'SQL Data Engineering: Snowflake, dbt' in text

    with ZipFile(paths['cv_upload_docx_path']) as archive:
        numbering_xml = archive.read('word/numbering.xml').decode('utf-8')
        assert '\uf0b7' not in numbering_xml
        assert '\u2022' in numbering_xml


def test_review_autofill_button_survives_stale_bridge_module(tmp_path, analyst_profile, monkeypatch):
    import shutil
    from streamlit.testing.v1 import AppTest
    from ui import services_bridge as bridge

    profile_dir = tmp_path / 'profiles' / 'analyst_a'
    profile_dir.mkdir(parents=True)
    shutil.copy2(
        Path(__file__).parent / 'fixtures' / 'profiles' / 'synthetic_analyst.yaml',
        profile_dir / 'profile.yaml',
    )
    folder = tmp_path / 'outputs' / 'analyst_a' / 'stale_bridge_job'
    source = folder / 'source'
    source.mkdir(parents=True)
    (source / 'content.json').write_text(
        json.dumps(read_json('content', 'valid_content.json')), encoding='utf-8'
    )
    (source / 'profile_snapshot.json').write_text(
        json.dumps(analyst_profile.model_dump()), encoding='utf-8'
    )
    (source / 'generation_result.json').write_text(
        json.dumps({'status': 'success'}), encoding='utf-8'
    )

    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path))
    monkeypatch.setenv('CVTAILOR_PROFILE_ID', 'analyst_a')
    monkeypatch.delattr(bridge, 'export_upload_cv', raising=False)
    monkeypatch.setattr(bridge, 'document_label', lambda name: name)

    def render_review():
        from config import Config
        from ui.review import render_application

        render_application(
            Config.from_env(load_env_file=False), 'analyst_a', 'stale_bridge_job'
        )

    at = AppTest.from_function(render_review).run(timeout=30)
    assert not at.exception
    next(b for b in at.button if b.label == 'Create / refresh CV for autofill').click().run(timeout=30)
    assert not at.exception
    assert any('Autofill DOCX and text created' in s.value for s in at.success)
    assert list(folder.glob('*_upload.docx'))
    assert list(folder.glob('*_upload.txt'))
    labels = [b.label for b in at.get('download_button')]
    assert 'CV for autofill · DOCX' in labels
    assert 'CV for autofill · TXT' in labels
