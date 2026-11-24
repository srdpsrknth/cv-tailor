"""Ongoing education survives profile snapshots and all CV text paths."""
import json
from pathlib import Path

import pytest
from docx import Document
from pydantic import ValidationError
from pypdf import PdfReader

from models.profile import Education, Profile
from models.tailored_output import TailoredCV
from renderers.latex_renderer import LaTeXRenderer
from renderers.upload_cv import render_upload_cv
from support import latex_available, read_json


def test_education_validation_and_legacy_snapshot(analyst_profile):
    legacy = analyst_profile.model_dump()
    for education in legacy['education']:
        education.pop('ongoing')
    restored = Profile.model_validate(json.loads(json.dumps(legacy)))
    assert restored.education[0].date_range() == '2018 - 2020'
    with pytest.raises(ValidationError, match='requires an end_year'):
        Education(degree='MSc', institution='College', start_year=2025)


@pytest.mark.parametrize(('end_year', 'expected'), [
    (None, '2025 - Present'),
    (2028, '2025 - Present (expected 2028)'),
])
def test_ongoing_education_in_exports(tmp_path, analyst_profile, end_year, expected):
    education = Education(degree='MSc', institution='College', start_year=2025,
                          ongoing=True, end_year=end_year)
    analyst_profile.education = [education]
    snapshot = json.loads(analyst_profile.model_dump_json())
    profile = Profile.model_validate(snapshot)
    cv = TailoredCV()
    paths = render_upload_cv(cv, profile, tmp_path)
    assert expected in Path(paths['cv_upload_text_path']).read_text(encoding='utf-8')
    assert expected in '\n'.join(p.text for p in Document(paths['cv_upload_docx_path']).paragraphs)

    renderer = LaTeXRenderer(outputs_dir=str(tmp_path))
    data = renderer._prepare_template_data(cv, profile)
    latex_dates = expected.replace(' - ', ' -- ')
    assert data['education'][0]['dates'] == latex_dates
    assert data['education'][0]['end_year'] == latex_dates.split(' -- ', 1)[1]
    assert renderer._extraction_contract(cv, profile)[1]['Education dates 0'] == latex_dates
    from renderers.cv_layout import PRESETS
    source = renderer.jinja_env.get_template('main.tex.jinja2').render(
        **data, layout=PRESETS[0], break_before_employer_index=None, split_before=None
    )
    assert latex_dates in source


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_ongoing_education_in_rendered_pdf(tmp_path, analyst_profile):
    analyst_profile.education = [
        Education(
            degree="Synthetic MSc", institution="Example University",
            start_year=2025, end_year=2028, ongoing=True,
        ),
    ]
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    pdf = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, analyst_profile)
    reader = PdfReader(pdf)
    text = " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
    layout = json.loads(reader.metadata["/CVLayout"])
    assert "Present (expected 2028)" in text
    assert len(reader.pages) <= 2
    assert layout["text_preserved"]
    assert not layout["clipping"]
