"""Render one approved claim edit as a version of its saved application."""

import json
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from models.profile import Profile
from models.tailored_output import TailoredCV, TailoredProject
from renderers import LaTeXRendererError, create_latex_renderer
from renderers.upload_cv import render_upload_cv
from services import suggested_claims
from services.application_layout_preview import layout_source_revision
from services.application_review import application_folder, read_json
from services.application_store import write_json
from services.candidate_guidance import load_candidate_acronyms
from services.claim_acceptance import _apply_to_data, _resolve, confirmed_claim_text
from services.validation import ProfileRules, validate_cv

_REVISION = re.compile(r"\d{19}-[0-9a-f]{10}")
ARTIFACTS = {"PDF": "cv.pdf", "Word": "cv.docx", "Text": "cv.txt"}


def _revision_root(folder):
    root = folder / "source" / "cv_revisions"
    if root.resolve() != root:
        raise ValueError("The CV revision folder resolves outside its application.")
    return root


def list_claim_cv_revisions(config, profile_id, job_id):
    root = _revision_root(application_folder(config, profile_id, job_id))
    rows = []
    for revision in sorted(root.iterdir(), reverse=True) if root.is_dir() else ():
        manifest = revision / "revision.json"
        if not (_REVISION.fullmatch(revision.name) and revision.resolve() == revision
                and manifest.is_file() and not manifest.is_symlink()):
            continue
        try:
            data = json.loads(manifest.read_bytes())
            if data["id"] == revision.name and isinstance(data["claim"], int):
                rows.append(data)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return rows


def read_claim_cv_artifact(config, profile_id, job_id, revision, label):
    root = _revision_root(application_folder(config, profile_id, job_id))
    if not _REVISION.fullmatch(revision) or label not in ARTIFACTS:
        raise ValueError("Invalid CV revision or document format.")
    path = root / revision / ARTIFACTS[label]
    if path.resolve() != path or not path.is_file():
        raise ValueError("The revised document could not be found.")
    return path.read_bytes()


def _single(matches):
    if len(matches) != 1:
        raise ValueError("This claim's target has no unique visible entry in the saved CV.")
    return matches[0]


def _cv_items(cv, profile, target):
    kind = target["type"]
    sections = profile.visible_cv_sections()
    if kind == "skill" and "skills" in sections:
        return cv.skills.setdefault(target["category"], [])
    if kind in ("experience", "experience_project") and "experience" in sections:
        role = _single([entry for entry in cv.experience if entry.company == target["company"]])
        if kind == "experience":
            return role.bullets
        if "employer_projects" not in profile.cv_hidden_sections:
            return _single([p for p in role.projects if p.name == target["project"]]).bullets
    if kind == "standalone_project" and "projects" in sections:
        index = _single([i for i, name in enumerate(cv.standalone_project_names()) if name == target["project"]])
        chosen = cv.standalone_projects[index]
        if isinstance(chosen, str):
            source = cv.resolve_standalone_projects(profile)[index]
            chosen = TailoredProject(name=source.name, bullets=list(source.bullets))
            cv.standalone_projects[index] = chosen
        return chosen.bullets
    raise ValueError("The claim's section is hidden in the saved CV.")


def _sources(config, profile_id, job_id, number):
    folder = application_folder(config, profile_id, job_id)
    record = suggested_claims.load_suggestions(folder / "source" / "content.json")
    if not 1 <= number <= len(record["suggestions"]):
        raise ValueError("The claim is unavailable.")
    claim = record["suggestions"][number - 1]
    if claim.get("status") != "accepted":
        raise ValueError("Confirm the claim and save it to the profile first.")
    target = claim.get("accepted_attach_to") or claim["attach_to"]
    text = claim.get("accepted_text") or claim["proposed_text"]
    current = config.store.load(profile_id)
    canonical, reason = suggested_claims.find_target(current, target)
    if canonical is None or text not in suggested_claims.target_texts(current, canonical):
        raise ValueError(reason or "The confirmed statement is no longer in your profile.")
    revisions = list_claim_cv_revisions(config, profile_id, job_id)
    base = _revision_root(folder) / revisions[0]["id"] if revisions else folder
    warnings = []
    content = read_json(base, "content.json", warnings)
    snapshot = read_json(base, "profile_snapshot.json", warnings)
    if warnings or not content.get("cv") or not snapshot:
        raise ValueError("This revision requires saved CV wording and a profile snapshot.")
    source_id = layout_source_revision(content, snapshot)
    profile = Profile.model_validate(snapshot)
    cv = TailoredCV.model_validate(content["cv"])
    items = _cv_items(cv, profile, canonical)
    # Add only the confirmed fact to the original rendering context.
    path, category = _resolve(snapshot, canonical, canonical.get("category"))
    saved_target, _ = suggested_claims.find_target(profile, canonical)
    if saved_target is None or text not in suggested_claims.target_texts(profile, saved_target):
        _apply_to_data(snapshot, path, category, text)
    return folder, source_id, content, snapshot, cv, items, canonical, record


def claim_cv_options(config, profile_id, job_id, number):
    _, source_id, _, _, _, items, _, _ = _sources(config, profile_id, job_id, number)
    return source_id, list(items)


def save_claim_cv_revision(config, profile_id, job_id, number, wording, replace_at, source_id):
    folder, current_id, content, snapshot, cv, items, target, record = _sources(config, profile_id, job_id, number)
    if source_id != current_id:
        raise ValueError("The saved CV changed. Review your edit against the latest revision.")
    text = confirmed_claim_text(wording, target["type"])
    if len(text) > suggested_claims.MAX_BULLET_CHARS:
        raise ValueError("Shorten the CV wording before saving.")
    if text in items:
        raise ValueError("The CV already contains this wording.")
    if replace_at is None:
        items.append(text)
    elif 0 <= replace_at < len(items):
        items[replace_at] = text
    else:
        raise ValueError("The selected CV entry is no longer available.")
    profile = Profile.model_validate(snapshot)
    validate_cv(cv.model_copy(deep=True), profile, ProfileRules.from_profile(profile))
    suggested_claims.reject_suggestion_leak(
        cv, suggested_claims.claim_texts(record["suggestions"]), profile,
    )
    content["cv"] = cv.model_dump()
    root = _revision_root(folder)
    root.mkdir(exist_ok=True)
    revision = f"{time.time_ns()}-{uuid4().hex[:10]}"
    acronyms = load_candidate_acronyms(config, profile_id)
    with TemporaryDirectory(prefix=".draft-", dir=root) as scratch:
        stage = Path(scratch) / "revision"
        stage.mkdir()
        source = stage / "source"
        source.mkdir()
        role = content.get("role_title")
        renderer = create_latex_renderer(
            outputs_dir=stage, timezone_name=config.timezone_name, extra_acronyms=acronyms,
        )
        try:
            pdf = Path(renderer.render_cv(cv, profile, job_position=role))
        except LaTeXRendererError as error:
            raise ValueError("The revised PDF could not be rendered. Check the local PDF compiler.") from error
        layout = renderer.last_layout or {}
        if (layout.get("page_count") not in (1, 2) or layout.get("text_preserved") is not True
                or layout.get("clipping") is not False or layout.get("orphan_headings") is not False):
            raise ValueError("The revised CV did not pass its two-page layout and text checks. Try a shorter edit.")
        pdf.replace(stage / ARTIFACTS["PDF"])
        upload = render_upload_cv(
            cv, profile, stage, role, timezone_name=config.timezone_name, extra_acronyms=acronyms,
        )
        Path(upload["cv_upload_docx_path"]).replace(stage / ARTIFACTS["Word"])
        Path(upload["cv_upload_text_path"]).replace(stage / ARTIFACTS["Text"])
        write_json(source / "content.json", content)
        write_json(source / "profile_snapshot.json", snapshot)
        write_json(stage / "revision.json", {"id": revision, "claim": number, "pages": layout["page_count"]})
        if claim_cv_options(config, profile_id, job_id, number)[0] != source_id:
            raise ValueError("Another CV revision was saved. Review your edit against the latest version.")
        stage.rename(root / revision)
    return revision
