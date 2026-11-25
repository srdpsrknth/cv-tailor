import json
from pathlib import Path

from docx import Document
from pydantic import ValidationError
from pypdf import PdfReader
import pytest

from models.profile import Profile
from models.tailored_output import TailoredCV
from renderers.cv_layout import PRESETS
from renderers.latex_renderer import LaTeXRenderer
from renderers.upload_cv import render_upload_cv
from services.application_review import _expected_cv_text
from support import latex_available, read_json


PUBLICATION = "A. Sample (2025). Transit & Access. Example Journal."
ACTIVITY = "Volunteer mentor, Community Data Club (2025–present)."


def profile_with_entries(profile, hidden=()):
    return Profile.model_validate({
        **profile.model_dump(),
        "cv_section_order": ["activities", "publications", "experience"],
        "cv_hidden_sections": list(hidden),
        "publications": [PUBLICATION],
        "activities": [ACTIVITY],
    })


@pytest.mark.parametrize(
    ("hidden", "visible"),
    [((), (ACTIVITY, PUBLICATION)), (("publications",), (ACTIVITY,)), (("activities",), (PUBLICATION,))],
)
def test_snapshot_controls_cv_export_and_review(analyst_profile, tmp_path, hidden, visible):
    profile = profile_with_entries(analyst_profile, hidden)
    snapshot = json.loads(profile.model_dump_json())
    profile = Profile.model_validate(snapshot)
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    source = renderer.jinja_env.get_template("main.tex.jinja2").render(
        **renderer._prepare_template_data(cv, profile), layout=PRESETS[0],
        break_before_employer_index=None, split_before=None,
    )
    paths = render_upload_cv(cv, profile, tmp_path)
    word = [paragraph.text for paragraph in Document(paths["cv_upload_docx_path"]).paragraphs]
    assert Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8").splitlines() == word
    _, render_fields = renderer._extraction_contract(cv, profile)
    _, review_fields = _expected_cv_text({"cv": cv.model_dump(), "_profile_snapshot": snapshot})
    assert tuple(entry for entry in word if entry in (ACTIVITY, PUBLICATION)) == visible
    for heading, entry in (("Activities", ACTIVITY), ("Publications", PUBLICATION)):
        assert (heading in word) == (entry in visible)
        assert (rf"\cvsection{{{heading}}}" in source) == (entry in visible)
        assert (entry in render_fields.values()) == (entry in visible)
        assert (entry in review_fields.values()) == (entry in visible)
    assert (r"Transit \& Access" in source) == (PUBLICATION in visible)
    assert snapshot["publications"] == [PUBLICATION] and snapshot["activities"] == [ACTIVITY]


def test_legacy_profile_has_no_entries_and_blank_entries_are_rejected(analyst_profile):
    legacy = analyst_profile.model_dump(exclude={"activities", "publications"})
    profile = Profile.model_validate(legacy)
    assert profile.activities == profile.publications == []
    with pytest.raises(ValidationError, match="publications"):
        Profile.model_validate({**legacy, "publications": [" "]})


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_rendered_pdf_honors_publication_and_activity_preferences(analyst_profile, tmp_path):
    profile = profile_with_entries(analyst_profile)
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    reader = PdfReader(LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, profile))
    text = " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
    assert text.index("ACTIVITIES") < text.index("PUBLICATIONS") < text.index("PROFESSIONAL EXPERIENCE")
    assert "Transit & Access" in text and "Volunteer mentor" in text
    layout = json.loads(reader.metadata["/CVLayout"])
    assert layout["text_preserved"] and not layout["clipping"]
    assert len(reader.pages) <= 2
