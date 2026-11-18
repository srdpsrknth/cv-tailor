"""Rendered-file freshness is explicit and never inferred for legacy files."""

from pathlib import Path

from services.artifact_provenance import artifact_freshness, record_artifact_provenance


def _project(tmp_path):
    (tmp_path / "backend/renderers").mkdir(parents=True)
    (tmp_path / "backend/renderers/latex_renderer.py").write_text("renderer v1")
    (tmp_path / "backend/renderers/docx_renderer.py").write_text("docx v1")
    (tmp_path / "backend/renderers/upload_cv.py").write_text("upload v1")
    (tmp_path / "backend/utils").mkdir()
    (tmp_path / "backend/utils/text.py").write_text("text v1")
    (tmp_path / "templates/cv").mkdir(parents=True)
    (tmp_path / "templates/cv/main.tex.jinja2").write_text("cv template v1")
    (tmp_path / "templates/cover_letter").mkdir(parents=True)
    (tmp_path / "templates/cover_letter/cover_letter.docx").write_bytes(
        b"docx template v1"
    )
    (tmp_path / "cover_letter_latex_template/setup").mkdir(parents=True)
    (tmp_path / "cover_letter_latex_template/setup/macros.tex").write_text(
        "cl template v1"
    )


def test_provenance_is_current_and_scoped_to_relevant_content(tmp_path):
    _project(tmp_path)
    folder = tmp_path / "application"
    folder.mkdir()
    pdf = folder / "cv.pdf"
    pdf.write_bytes(b"rendered bytes")
    content = {
        "cv": {"summary": ["Tailored"]},
        "cover_letter": {"paragraphs": ["Letter"]},
    }
    provenance = record_artifact_provenance(tmp_path, content, [(pdf, "cv")])

    edited_letter = {**content, "cover_letter": {"paragraphs": ["Manually edited"]}}
    result = artifact_freshness(tmp_path, edited_letter, [pdf], provenance)
    assert result["cv.pdf"]["status"] == "current"


def test_content_dependency_and_artifact_changes_are_stale(tmp_path):
    _project(tmp_path)
    folder = tmp_path / "application"
    folder.mkdir()
    pdf = folder / "letter.pdf"
    pdf.write_bytes(b"rendered bytes")
    content = {"cv": {}, "cover_letter": {"paragraphs": ["Original"]}}
    provenance = record_artifact_provenance(tmp_path, content, [(pdf, "cover_letter")])

    changed_content = {**content, "cover_letter": {"paragraphs": ["Edited"]}}
    assert (
        artifact_freshness(tmp_path, changed_content, [pdf], provenance)["letter.pdf"][
            "status"
        ]
        == "stale"
    )

    changed_content = content
    (tmp_path / "cover_letter_latex_template/setup/macros.tex").write_text(
        "cl template v2"
    )
    assert (
        artifact_freshness(tmp_path, changed_content, [pdf], provenance)["letter.pdf"][
            "status"
        ]
        == "stale"
    )

    (tmp_path / "cover_letter_latex_template/setup/macros.tex").write_text(
        "cl template v1"
    )
    pdf.write_bytes(b"manually replaced file")
    assert (
        artifact_freshness(tmp_path, changed_content, [pdf], provenance)["letter.pdf"][
            "status"
        ]
        == "stale"
    )


def test_role_title_and_profile_snapshot_are_part_of_render_context(tmp_path):
    _project(tmp_path)
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"rendered")
    content = {"role_title": "Analyst", "cv": {"summary": ["Same"]}}
    profile = {"identity": {"full_name": "Candidate"}}
    provenance = record_artifact_provenance(
        tmp_path, content, [(pdf, "cv")], profile_snapshot=profile
    )

    changed = {**content, "role_title": "Senior Analyst"}
    assert (
        artifact_freshness(
            tmp_path, changed, [pdf], provenance, profile_snapshot=profile
        )["cv.pdf"]["status"]
        == "stale"
    )

    assert (
        artifact_freshness(
            tmp_path,
            content,
            [pdf],
            provenance,
            profile_snapshot={"identity": {"full_name": "Different candidate"}},
        )["cv.pdf"]["status"]
        == "stale"
    )


def test_missing_provenance_is_unknown_not_stale(tmp_path):
    pdf = tmp_path / "legacy.pdf"
    pdf.write_bytes(b"legacy")
    result = artifact_freshness(tmp_path, {}, [pdf], {})
    assert result["legacy.pdf"]["status"] == "unknown"
