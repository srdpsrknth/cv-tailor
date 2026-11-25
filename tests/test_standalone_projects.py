import json
from pathlib import Path

from docx import Document
from pypdf import PdfReader
import pytest

from models.profile import Profile, Project
from models.tailored_output import TailoredCV
from renderers.cv_layout import PRESETS
from renderers.latex_renderer import LaTeXRenderer
from renderers.upload_cv import render_upload_cv
from services.application_review import _expected_cv_text
from services.pipeline import DocumentGenerator
from support import OfflineGemini, latex_available, read_json


@pytest.fixture
def project_cv(analyst_profile):
    analyst_profile.standalone_projects = [
        Project(name="Transit & Access", bullets=["Mapped public transport gaps."]),
        Project(name="Weather Archive", bullets=["Catalogued public weather records."]),
    ]
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    cv.standalone_projects = ["Transit & Access"]
    return analyst_profile, cv


def test_saved_project_selection_renders_from_snapshot(project_cv, tmp_path):
    profile, cv = project_cv
    snapshot = json.loads(profile.model_dump_json())
    profile = Profile.model_validate(snapshot)
    cv = TailoredCV.model_validate_json(cv.model_dump_json())
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    latex = renderer.jinja_env.get_template("main.tex.jinja2").render(
        **renderer._prepare_template_data(cv, profile), layout=PRESETS[0],
        break_before_employer_index=None, split_before=None,
    )
    assert r"\cvsection{Projects}" in latex
    assert r"Transit \& Access" in latex
    paths = render_upload_cv(cv, profile, tmp_path)
    passages = [Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8"),
                "\n".join(p.text for p in Document(paths["cv_upload_docx_path"]).paragraphs),
                "\n".join(renderer._extraction_contract(cv, profile)[0]),
                "\n".join(_expected_cv_text({"cv": cv.model_dump(), "_profile_snapshot": snapshot})[0])]
    for passage in passages:
        assert "Transit & Access\nMapped public transport gaps." in passage
        assert "Weather Archive" not in passage


@pytest.mark.parametrize("names", [["Made-up project"], ["Transit & Access", "Transit & Access"]])
def test_generation_rejects_unknown_or_duplicate_names(project_cv, names):
    profile, cv = project_cv
    cv.standalone_projects = names
    with pytest.raises(ValueError, match="distinct standalone project names"):
        DocumentGenerator(None, profile)._build_model({"cv": cv.model_dump()}, "cv", None, None, None)


def test_full_layout_retry_cannot_drop_selected_projects(project_cv):
    profile, cv = project_cv
    response = {"cv": cv.model_copy(update={"standalone_projects": []}).model_dump()}
    generator = DocumentGenerator(OfflineGemini([json.dumps(response)] * 3), profile)
    with pytest.raises(ValueError, match="Keep the selected standalone projects"):
        generator.generate("retry", "cv", base_cv=cv)


def test_delta_retry_preserves_selected_projects(project_cv):
    profile, cv = project_cv
    generator = DocumentGenerator(OfflineGemini(['{"summary": ["Analytics professional."]}']), profile)
    result, _ = generator.generate("retry", "cv", base_cv=cv)
    assert result.standalone_projects == ["Transit & Access"]


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_standalone_projects_in_rendered_pdf(project_cv, tmp_path):
    profile, cv = project_cv
    reader = PdfReader(LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, profile))
    text = " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
    assert "Transit & Access" in text
    assert "Mapped public transport gaps." in text
    assert "Weather Archive" not in text
    layout = json.loads(reader.metadata["/CVLayout"])
    assert layout["text_preserved"] and not layout["clipping"]
