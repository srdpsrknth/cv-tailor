"""Text preservation and isolation of the parser-oriented CV export."""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document

from models.tailored_output import TailoredCV
from support import read_json


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


def test_saved_export_uses_snapshot_and_leaves_sources_unchanged(tmp_path, analyst_profile, monkeypatch):
    from services.upload_cv import export_saved_upload_cv
    from config import Config

    config = Config.from_env(load_env_file=False)
    folder = config.store.outputs_dir('analyst_a') / 'upload_test'
    source = folder / 'source'
    source.mkdir(parents=True)
    snapshot = analyst_profile.model_dump()
    snapshot['identity']['full_name'] = 'Historical Candidate'
    content = read_json('content', 'valid_content.json')
    for name, value in [('content', content), ('profile_snapshot', snapshot)]:
        (source / f'{name}.json').write_text(json.dumps(value), encoding='utf-8')
    originals = {p.name: p.read_bytes() for p in source.iterdir()}
    paths = export_saved_upload_cv(config, 'analyst_a', folder.name)
    assert 'Historical Candidate' in Path(paths['cv_upload_text_path']).read_text(encoding='utf-8')
    assert originals == {p.name: p.read_bytes() for p in source.iterdir()}
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
