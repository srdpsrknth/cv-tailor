"""Render and optionally save a layout comparison for an application."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from models.profile import Profile
from models.tailored_output import TailoredCV
from renderers import create_latex_renderer
from services.application_review import application_folder, read_json


def layout_source_revision(content, snapshot) -> str:
    sources = [content.get("cv"), content.get("role_title"), snapshot]
    return sha256(json.dumps(sources, sort_keys=True).encode("utf-8")).hexdigest()


def _read_layout_sources(folder):
    warnings = []
    content = read_json(folder, "content.json", warnings)
    snapshot = read_json(folder, "profile_snapshot.json", warnings)
    if warnings or not content.get("cv") or not snapshot:
        raise ValueError("Layout preview needs valid saved CV text and a profile snapshot.")
    return content, snapshot


def preview_saved_cv_layout(config, profile_id, job_id) -> tuple[bytes, dict]:
    folder = application_folder(config, profile_id, job_id)
    content, snapshot = _read_layout_sources(folder)
    cv = TailoredCV.model_validate(content["cv"])
    profile = Profile.model_validate(snapshot)
    with TemporaryDirectory(prefix="cvtailor-saved-layout-") as scratch:
        renderer = create_latex_renderer(outputs_dir=scratch)
        preview = getattr(renderer, "preview_cv_layout", None)
        if preview is None:
            raise ValueError("Restart CV Tailor to load the updated PDF renderer.")
        pdf, report = preview(cv, profile, job_position=content.get("role_title"))
        return pdf, {**report, "source_revision": layout_source_revision(content, snapshot)}


def save_cv_layout_preview(config, profile_id, job_id, pdf: bytes, report: dict) -> Path:
    """Publish the checked preview as a separate PDF beside the original."""
    folder = application_folder(config, profile_id, job_id)
    if (
        report.get("page_count") not in (1, 2)
        or report.get("text_preserved") is not True
        or report.get("clipping") is not False
        or report.get("orphan_headings") is not False
        or not pdf.startswith(b"%PDF-")
    ):
        raise ValueError("Only a preview that passed the CV layout checks can be saved.")

    content, snapshot = _read_layout_sources(folder)
    if report.get("source_revision") != layout_source_revision(content, snapshot):
        raise ValueError("The saved CV changed. Generate a fresh preview before saving.")

    path = folder / f"cv_balanced_{sha256(pdf).hexdigest()[:16]}.pdf"
    if path.is_symlink() or (path.exists() and path.read_bytes() != pdf):
        raise ValueError("The alternate CV filename is already in use.")
    if path.exists():
        return path
    staged = None
    try:
        with NamedTemporaryFile(dir=folder, suffix=".pdf.tmp", delete=False) as pending:
            staged = Path(pending.name)
            pending.write(pdf)
        staged.replace(path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return path
