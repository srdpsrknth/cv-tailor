"""A section heading must never be left alone at the bottom of a page (synthetic data).

``\\cvsection`` reserves room for the heading plus the first entry. The sweep below
pushes every section heading through the page break, one filler line at a time, and
checks the last real line of each page with an extractor independent of the renderer's
own orphan detector.
"""
import pdfplumber
import pytest

from models.profile import Profile, Project
from models.tailored_output import TailoredCV
from renderers import cv_layout
from renderers.cv_layout import _SECTIONS, _last_content_line, _normalized
from renderers.cv_sections import SECTION_TITLES
from renderers.latex_renderer import LaTeXRenderer
from support import latex_available, read_json

ORDER = ["skills", "projects", "education", "certifications", "languages",
         "publications", "activities", "experience"]


def _profile(analyst_profile):
    return Profile.model_validate({
        **analyst_profile.model_dump(),
        "standalone_projects": [
            Project(name="Transit Access Study", bullets=["Mapped public transport gaps."]).model_dump()],
        "publications": ["A. Sample (2025). Open Mobility Data. Example Journal."],
        "activities": ["Volunteer mentor, Community Data Club (2025)."],
        "cv_section_order": ORDER,
    })


def _cv(filler_lines):
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    cv.standalone_projects = ["Transit Access Study"]
    cv.skills = {f"Filler {index:02d}": ["synthetic"] for index in range(filler_lines)}
    return cv


def _page_endings(path):
    """For every page: (normalised last content line, lines below the last heading)."""
    result = []
    with pdfplumber.open(path) as document:
        for page in document.pages:
            lines = [_normalized(line["text"]) for line in page.extract_text_lines()]
            lines = [line for line in lines if line]
            headings = [i for i, line in enumerate(lines) if line in _SECTIONS]
            below = len(lines) - 1 - headings[-1] if headings else None
            result.append((_last_content_line(lines), below))
    return result


def test_detector_knows_every_printed_section_heading():
    assert {_normalized(title) for key, title in SECTION_TITLES.items() if key != "summary"} <= _SECTIONS
    assert {"projects", "publications", "activities"} <= _SECTIONS


def test_orphan_detector_is_robust_to_blank_and_footer_lines():
    assert _last_content_line([]) == ""
    assert _last_content_line(["projects", "", "page 1 of 2"]) == "projects"
    assert _last_content_line(["projects", "a bullet"]) == "a bullet"


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_no_section_heading_ends_a_page(analyst_profile, tmp_path):
    profile = _profile(analyst_profile)
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    near_bottom = 0
    for filler in range(26, 50):
        cv = _cv(filler)
        pdf = renderer.render_cv(cv, profile, job_position=f"sweep {filler}", layout_preset="compact")
        for number, (last, below) in enumerate(_page_endings(pdf), start=1):
            assert last not in _SECTIONS, (
                f"heading {last!r} ends page {number} with {filler} filler lines")
            if number == 1 and below is not None and below <= 3:
                near_bottom += 1
        assert not cv_layout.measure_layout(pdf)["orphan_headings"]
    # The sweep is only a regression test if headings really reach the page bottom.
    assert near_bottom >= 3
