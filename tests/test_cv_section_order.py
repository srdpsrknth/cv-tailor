import json
from pathlib import Path

from docx import Document
from pypdf import PdfReader
import pytest
from pydantic import ValidationError

from models.profile import DEFAULT_CV_SECTION_ORDER, Profile, Project, resolve_cv_section_order
from models.tailored_output import TailoredCV, TailoredProject
from renderers.cv_layout import PRESETS
from renderers.latex_renderer import LaTeXRenderer
from renderers.upload_cv import render_upload_cv
from services.application_review import _expected_cv_text
from services.cache_store import serialize_profile_bytes
from support import latex_available, read_json


def _cv_and_snapshot(analyst_profile):
    original_prompt_profile = serialize_profile_bytes(analyst_profile)
    analyst_profile.cv_section_order = ["education", "projects", "skills"]
    assert serialize_profile_bytes(analyst_profile) == original_prompt_profile
    analyst_profile.standalone_projects = [Project(name="Transit Map", bullets=["Mapped transit stops."])]
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    cv.standalone_projects = ["Transit Map"]
    return cv, analyst_profile.model_dump()


@pytest.mark.parametrize("bad_order", [["education", "education"], ["unknown"]])
def test_section_order_rejects_invalid_preferences(analyst_profile, bad_order):
    with pytest.raises(ValidationError, match="cv_section_order"):
        Profile.model_validate({**analyst_profile.model_dump(), "cv_section_order": bad_order})


def test_legacy_and_partial_section_order(analyst_profile):
    legacy = analyst_profile.model_dump(exclude={"cv_section_order"})
    assert resolve_cv_section_order(Profile.model_validate(legacy).cv_section_order) == DEFAULT_CV_SECTION_ORDER
    assert resolve_cv_section_order(["languages", "education"]) == (
        "languages", "education", "experience", "projects", "certifications", "skills",
        "publications", "activities",
    )


def test_snapshot_controls_pdf_source_and_autofill_order(analyst_profile, tmp_path):
    cv, snapshot = _cv_and_snapshot(analyst_profile)
    profile = Profile.model_validate(snapshot)
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    source = renderer.jinja_env.get_template("main.tex.jinja2").render(
        **renderer._prepare_template_data(cv, profile), layout=PRESETS[0],
        break_before_employer_index=None, split_before=None,
    )
    headings = ["Education", "Projects", "Skills", "Professional Experience"]
    positions = [source.index(r"\cvsection{" + heading + "}") for heading in headings]
    assert positions == sorted(positions)

    paths = render_upload_cv(cv, profile, tmp_path)
    paragraphs = [row.text for row in Document(paths["cv_upload_docx_path"]).paragraphs]
    assert Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8").splitlines() == paragraphs
    positions = [paragraphs.index(heading) for heading in ["Education", "Projects", "Skills", "Professional Experience"]]
    assert positions == sorted(positions)

    expected_prose, _ = renderer._extraction_contract(cv, profile)
    reviewed_prose, _ = _expected_cv_text({"cv": cv.model_dump(), "_profile_snapshot": snapshot})
    assert reviewed_prose == expected_prose
    assert expected_prose.index("Mapped transit stops.") < expected_prose.index(cv.experience[0].bullets[0])
    rendered_prose, _ = _expected_cv_text(
        {"cv": cv.model_dump(), "_profile_snapshot": snapshot}, section_order=list(DEFAULT_CV_SECTION_ORDER),
    )
    assert rendered_prose.index(cv.experience[0].bullets[0]) < rendered_prose.index("Mapped transit stops.")


@pytest.mark.parametrize(("hidden", "dedicated_visible", "employer_visible"), [
    (["summary", "projects"], False, True),
    (["summary", "employer_projects"], True, False),
])
def test_project_display_choices_are_independent(analyst_profile, tmp_path, hidden, dedicated_visible, employer_visible):
    cv, snapshot = _cv_and_snapshot(analyst_profile)
    cv.experience[0].projects = [TailoredProject(name="Employer Project", bullets=["Built reporting."])]
    snapshot["cv_hidden_sections"] = hidden
    profile = Profile.model_validate(snapshot)
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    source = renderer.jinja_env.get_template("main.tex.jinja2").render(
        **renderer._prepare_template_data(cv, profile), layout=PRESETS[0],
        break_before_employer_index=None, split_before=None,
    )
    paths = render_upload_cv(cv, profile, tmp_path)
    expected_prose, _ = renderer._extraction_contract(cv, profile)
    reviewed_prose, _ = _expected_cv_text({"cv": cv.model_dump(), "_profile_snapshot": snapshot})
    assert reviewed_prose == expected_prose
    for text in (source, Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8"), "\n".join(expected_prose)):
        assert ("Transit Map" in text) == dedicated_visible
        assert ("Employer Project" in text) == employer_visible
        assert cv.summary[0] not in text


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
@pytest.mark.parametrize("hide_projects", [False, True])
def test_custom_section_order_in_rendered_pdf(analyst_profile, tmp_path, hide_projects):
    cv, snapshot = _cv_and_snapshot(analyst_profile)
    if hide_projects:
        snapshot["cv_hidden_sections"] = ["projects"]
    reader = PdfReader(LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, Profile.model_validate(snapshot)))
    pdf_text = " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
    headings = ["EDUCATION", "SKILLS", "PROFESSIONAL EXPERIENCE"]
    if not hide_projects:
        headings.insert(1, "PROJECTS")
    positions = [pdf_text.index(title) for title in headings]
    assert positions == sorted(positions)
    assert ("Transit Map" in pdf_text) == (not hide_projects)
    layout = json.loads(reader.metadata["/CVLayout"])
    assert ("projects" in layout["section_order"]) == (not hide_projects)
    assert layout["text_preserved"] and not layout["clipping"]
    assert len(reader.pages) <= 2
