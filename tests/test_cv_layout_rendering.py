"""Real PDF checks for automatic layout selection, using synthetic content only."""

import json
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
import pytest

from models.tailored_output import TailoredCV
from renderers.latex_renderer import LaTeXRenderer
from support import latex_available, read_json


def _cv():
    return TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])


def _metadata(path):
    reader = PdfReader(path)
    return reader, json.loads(reader.metadata["/CVLayout"])


def _texts(path):
    with pdfplumber.open(path) as document:
        plumber = " ".join(page.extract_text() or "" for page in document.pages)
    pypdf = " ".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return [" ".join(text.split()) for text in (plumber, pypdf)]


def _assert_prose_retained(path, cv):
    paragraphs = list(cv.summary)
    for experience in cv.experience:
        paragraphs.extend(experience.bullets)
        for project in experience.projects:
            paragraphs.extend(project.bullets)
    for text in _texts(path):
        cursor = 0
        for paragraph in paragraphs:
            phrase = " ".join(paragraph.split())
            position = text.find(phrase, cursor)
            assert position >= 0, f"Missing or reordered source prose: {phrase}"
            cursor = position + len(phrase)


def _expanded_cv(profile, *, employers=6, bullets=4):
    """Independent short semantic blocks, rather than one impossible giant role."""
    cv = _cv()
    role = cv.experience[0]
    profile_role = profile.experience[0]
    experiences = []
    profile_experiences = []
    for index in range(employers):
        company = f"Synthetic Warehouse {index} GmbH"
        prose = [
            f"Validated warehouse dataset {index} version {bullet} using documented "
            "quality checks and reproducible transformation models, supporting "
            "reliable reporting for operational decision making."
            for bullet in range(bullets)
        ]
        experiences.append(
            role.model_copy(update={"company": company, "bullets": prose, "projects": []})
        )
        profile_experiences.append(
            profile_role.model_copy(
                update={"company": company, "bullets": prose, "selected_projects": []}
            )
        )
    return (
        cv.model_copy(update={"experience": experiences}),
        profile.model_copy(update={"experience": profile_experiences}),
    )


@pytest.mark.parametrize("preset,body_size,leading", [
    ("comfortable", 11, 13.2),
    ("standard", 10.5, 12.6),
    ("compact", 10.5, 12.2),
])
@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_explicit_preset_is_recorded_and_uses_real_readable_type(
    tmp_path, analyst_profile, preset, body_size, leading
):
    cv = _cv()
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    path = renderer.render_cv(cv, analyst_profile, layout_preset=preset)
    reader, layout = _metadata(path)
    assert layout["preset"] == preset
    assert layout["body_size"] == body_size
    assert layout["leading"] == leading
    assert layout["schema_version"] == 1
    assert renderer.last_layout == layout
    assert layout["page_count"] == len(reader.pages)
    assert reader.metadata.author == analyst_profile.identity.full_name
    with pdfplumber.open(path) as document:
        phrase = document.pages[0].search("Own end-to-end", return_chars=True)[0]
        assert {round(char["size"], 1) for char in phrase["chars"]} == {body_size}
        assert min(char["size"] for page in document.pages for char in page.chars) >= 9
    _assert_prose_retained(path, cv)
    assert sorted(path.name for path in tmp_path.iterdir()) == [Path(path).name]


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_short_cv_stays_one_page_with_comfortable_type_and_intact_long_headline(
    tmp_path, analyst_profile
):
    cv = _cv()
    cv.title = "Senior Data Analyst | Business Intelligence & Growth Analytics"
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    path = renderer.render_cv(cv, analyst_profile)
    reader, layout = _metadata(path)
    assert len(reader.pages) == 1
    assert layout["preset"] == "comfortable"
    assert not layout["clipping"]
    assert not layout["orphan_headings"]
    for text in _texts(path):
        assert cv.title in text
        for field in (
            analyst_profile.identity.full_name.upper(),
            analyst_profile.identity.email,
            analyst_profile.identity.phone,
            analyst_profile.identity.location,
            "linkedin.com/in/example-alex-sample",
            "github.com/example-alex-sample",
        ):
            assert field in text
    _assert_prose_retained(path, cv)


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_layout_selection_is_deterministic_and_metadata_contains_no_source_prose(
    tmp_path, analyst_profile
):
    cv = _cv()
    before = cv.model_dump()
    reports = []
    for number in range(2):
        renderer = LaTeXRenderer(outputs_dir=tmp_path / str(number))
        path = renderer.render_cv(cv, analyst_profile)
        _, layout = _metadata(path)
        reports.append(layout)
    assert reports[0] == reports[1]
    assert cv.model_dump() == before
    serialized = json.dumps(reports[0])
    for private_value in (
        analyst_profile.identity.full_name,
        analyst_profile.identity.email,
        cv.experience[0].company,
        cv.experience[0].bullets[0],
        cv.experience[0].projects[0].name,
    ):
        assert private_value not in serialized


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_overflow_is_returned_for_existing_shortening_gate_without_dropping_prose(
    tmp_path, analyst_profile
):
    cv, profile = _expanded_cv(analyst_profile, employers=8, bullets=8)
    path = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, profile)
    reader, layout = _metadata(path)
    assert len(reader.pages) > 2
    assert layout["page_count"] == len(reader.pages)
    assert layout["body_size"] >= 10.5
    _assert_prose_retained(path, cv)


def test_unknown_layout_preset_fails_before_compilation(tmp_path, analyst_profile, monkeypatch):
    def unexpected_compile(*args, **kwargs):
        pytest.fail("Unknown presets must be rejected before running LaTeX")

    monkeypatch.setattr(LaTeXRenderer, "_compile_pdf", unexpected_compile)
    with pytest.raises(ValueError, match="Unknown CV layout preset"):
        LaTeXRenderer(outputs_dir=tmp_path).render_cv(
            _cv(), analyst_profile, layout_preset="microscopic"
        )
    assert list(tmp_path.iterdir()) == []


def test_preview_compares_bounded_splits_without_writing_to_saved_outputs(
    tmp_path, analyst_profile, monkeypatch
):
    from renderers import cv_layout
    from services import document_quality

    cv, profile = _expanded_cv(analyst_profile, employers=2)
    cv.experience[1].projects = _cv().experience[0].projects
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(b"previous CV")
    invocations = []

    def compile_trial(compiler, tex_path, base_name):
        tex = tex_path.read_text(encoding="utf-8")
        invocations.append((tex_path, tex))
        path = compiler.outputs_dir / f"{base_name}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        writer.write(path)
        return path

    def measure_trial(path, **kwargs):
        ordinal = int(path.parent.name)
        return {
            "page_count": 2, "pages": [{"blank_tail_mm": tail} for tail in (
                [55, 25] if ordinal == 0 else [32, 35]
            )],
            "quality_score": 6 if ordinal == 0 else 2,
            "split_employer_indices": [], "second_page_employer_indices": [1],
            "clipping": False, "orphan_headings": False, "warnings": [],
        }

    def inspect_trial(path, **kwargs):
        check = dict(status="ok", page_count=2, word_retention=1.0,
                     reading_order=True, missing_fields=[], suspicious_glyphs=[])
        # The third trial has an attractive layout but fails source extraction.
        second_check = {**check, "word_retention": 0.9} if path.parent.name == "2" else check
        return {"engines": {"pypdf": check, "pdfplumber": second_check}}

    monkeypatch.setattr(LaTeXRenderer, "_compile_pdf", compile_trial)
    monkeypatch.setattr(cv_layout, "measure_layout", measure_trial)
    monkeypatch.setattr(document_quality, "inspect_document", inspect_trial)

    preview, report = renderer.preview_cv_layout(cv, profile, layout_preset="standard")
    assert preview.startswith(b"%PDF")
    assert report["blank_tails_mm"] == [32, 35]
    assert report["baseline"]["blank_tails_mm"] == [55, 25]
    assert report["split_before"] == {"role_index": 1, "kind": "bullet", "index": 1}
    assert [attempt["text_preserved"] for attempt in report["attempts"]] == [True, True, False]
    assert len(invocations) == 3
    assert "(\\lblcontinued)\\par" not in invocations[0][1]
    bullet_split = invocations[1][1]
    first_bullet, second_bullet = cv.experience[1].bullets[:2]
    assert bullet_split.index(first_bullet) < bullet_split.index("\\newpage")
    assert bullet_split.index("(\\lblcontinued)\\par") < bullet_split.index(second_bullet)
    project_split = invocations[2][1]
    assert project_split.index(cv.experience[1].bullets[-1]) < project_split.index("\\newpage")
    assert project_split.index("(\\lblcontinued)\\par") < project_split.index(cv.experience[1].projects[0].name)
    assert all(not path.exists() for path, _ in invocations)
    assert list(tmp_path.iterdir()) == [saved]
    assert saved.read_bytes() == b"previous CV"
    assert renderer.last_layout is None


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_dense_cv_falls_back_to_two_pages_without_rewriting_or_tiny_type(
    tmp_path, analyst_profile
):
    # The larger two presets need three pages for these seven short roles;
    # compact fits two. This guards the actual fallback rather than just its label.
    cv, profile = _expanded_cv(analyst_profile, employers=7, bullets=4)
    original = cv.model_dump()
    path = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, profile)
    reader, layout = _metadata(path)
    assert len(reader.pages) == 2
    assert layout["preset"] == "compact"
    assert layout["body_size"] == 10.5
    assert cv.model_dump() == original
    natural_attempts = {
        attempt["preset"]: attempt["page_count"]
        for attempt in layout["attempts"]
        if attempt["break_before_employer_index"] is None
    }
    assert natural_attempts == {"comfortable": 3, "standard": 3, "compact": 2}
    _assert_prose_retained(path, cv)


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_failed_extraction_checks_preserve_the_previous_pdf_and_leave_no_trials(
    tmp_path, analyst_profile, monkeypatch
):
    from renderers.latex_renderer import LaTeXRendererError
    from services import document_quality

    cv = _cv()
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    path = Path(renderer.render_cv(cv, analyst_profile))
    original = path.read_bytes()
    inspect = document_quality.inspect_document

    def reject_text(*args, **kwargs):
        report = inspect(*args, **kwargs)
        report["engines"]["pdfplumber"]["word_retention"] = 0.9
        return report

    monkeypatch.setattr(document_quality, "inspect_document", reject_text)
    with pytest.raises(LaTeXRendererError, match="preserved the source text"):
        renderer.render_cv(cv, analyst_profile)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    assert renderer.last_layout is None


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_cv_without_prose_still_renders_and_retains_structured_fields(
    tmp_path, analyst_profile
):
    cv = _cv()
    cv.summary = []
    for experience in cv.experience:
        experience.bullets = []
        experience.projects = []
    path = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, analyst_profile)
    reader, layout = _metadata(path)
    assert len(reader.pages) == 1
    assert layout["text_preserved"] is True
    for check in layout["extraction"]["engines"].values():
        assert check["status"] == "ok"
        assert check["missing_fields"] == []
        assert check["word_retention"] is None
        assert check["reading_order"] is None
    for text in _texts(path):
        assert analyst_profile.identity.email in text
        for experience in cv.experience:
            assert experience.company in text
            assert experience.role in text
        assert analyst_profile.education[0].degree in text
        assert cv.skills["Core Analytics"][0] in text


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_cli_routes_fixed_preset_and_records_it_in_provenance(
    tmp_path, repo_root, capsys
):
    from cli.main import main
    from support import copy_content_json

    content = copy_content_json(tmp_path / "application")
    original = content.read_bytes()
    assert main([
        "--project", str(repo_root), "--profile-id", "analyst_a",
        "render", "--content", str(content), "--cv-only",
        "--layout-preset", "standard",
    ]) == 0
    assert "CV:" in capsys.readouterr().out
    manifest = json.loads((content.parent / "generation_result.json").read_text())
    pdf = Path(manifest["cv_path"])
    _, layout = _metadata(pdf)
    assert layout["preset"] == "standard"
    assert layout["body_size"] == 10.5
    assert layout["leading"] == 12.6
    assert manifest["artifact_provenance"][pdf.name]["layout"] == layout
    assert content.read_bytes() == original
    assert not list(content.parent.parent.glob("*cover_letter*"))


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_project_continuation_label_appears_only_when_parent_role_is_on_prior_page(
    tmp_path, analyst_profile
):
    short = _cv()
    short_path = LaTeXRenderer(outputs_dir=tmp_path / "short").render_cv(
        short, analyst_profile, layout_preset="compact"
    )
    assert all("continued" not in text for text in _texts(short_path))

    cv, profile = _expanded_cv(analyst_profile, employers=1, bullets=14)
    project = short.experience[0].projects[0].model_copy(update={
        "name": "Continuing Warehouse Project",
        "bullets": [
            f"Documented project validation step {index} using reproducible warehouse "
            "models and controlled data refreshes, supporting consistent reporting "
            "across operational analytics workflows."
            for index in range(8)
        ],
    })
    cv.experience[0].projects = [project]
    path = LaTeXRenderer(outputs_dir=tmp_path / "continuation").render_cv(
        cv, profile, layout_preset="compact"
    )
    reader, layout = _metadata(path)
    assert len(reader.pages) == 2
    assert layout["employer_project_splits"] == 1
    assert layout["break_before_employer_index"] is None
    with pdfplumber.open(path) as document:
        plumber_pages = [page.extract_text() or "" for page in document.pages]
    for pages in ([page.extract_text() or "" for page in reader.pages], plumber_pages):
        assert "continued" not in pages[0]
        assert "Continuing Warehouse Project" in pages[1]
        assert f"({cv.experience[0].company} - continued)" in pages[1]
    _assert_prose_retained(path, cv)
