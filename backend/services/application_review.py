"""Read-only application review and deterministic comparisons. No provider calls."""

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import hashlib

from services.artifact_provenance import artifact_freshness
from services.profile_store import validate_profile_id


def application_folder(config, profile_id, job_id):
    candidate = validate_profile_id(profile_id)
    expected = (Path(config.store.root) / "outputs").resolve() / candidate
    root = config.store.outputs_dir(candidate).resolve()
    if root != expected:
        raise ValueError(
            "Candidate output directory resolves outside its own namespace."
        )
    if (
        not isinstance(job_id, str)
        or not re.fullmatch(r"[\w.-]+", job_id)
        or job_id in (".", "..")
    ):
        raise ValueError("Invalid application identifier.")
    folder = root / job_id
    if folder.resolve() != folder or not folder.is_dir():
        raise ValueError(
            f"Application {job_id!r} not found for candidate {profile_id!r}."
        )
    return folder


def read_json(folder, name, warnings):
    path = folder / "source" / name
    if not path.exists():
        return {}
    try:
        if (
            not path.resolve().is_relative_to(folder.resolve())
            or path.stat().st_size > 10_000_000
        ):
            raise ValueError("file is outside the application or too large")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    except (OSError, ValueError) as error:
        warnings.append(f"Could not read {name}: {error}")
        return {}


def read_saved_posting(folder):
    path = folder / "source" / "job_description.txt"
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError("Posting resolves outside the application.")
    if not path.is_file():
        return ""
    if path.stat().st_size > 10_000_000:
        raise ValueError("Saved posting is too large.")
    return path.read_text(encoding="utf-8")


def load_saved_sources(config, profile_id, job_id):
    """Read drafting inputs from the selected application revision."""
    folder = application_folder(config, profile_id, job_id)
    warnings = []
    try:
        posting = read_saved_posting(folder)
    except (OSError, ValueError) as error:
        posting = ""
        warnings.append(f"Could not read the saved posting: {error}")
    return {
        "folder": folder,
        "posting": posting,
        "content": read_json(folder, "content.json", warnings),
        "snapshot": read_json(folder, "profile_snapshot.json", warnings),
        "warnings": warnings,
    }


def text(value):
    if isinstance(value, list):
        return "\n".join(
            str(item) for item in value if isinstance(item, (str, int, float))
        )
    return value if isinstance(value, str) else ""


def compare_cv(snapshot, cv):
    """Compare sections and uniquely named roles/projects; never guess an alignment."""
    changes = []

    def add(section, before, after, kind=None):
        before, after = text(before), text(after)
        if before != after or kind:
            changes.append(
                {
                    "section": section,
                    "before": before,
                    "after": after,
                    "kind": kind
                    or (
                        "Added" if not before else "Omitted" if not after else "Changed"
                    ),
                }
            )

    add("Summary", snapshot.get("summary_base", []), cv.get("summary", []))
    original_skills, final_skills = snapshot.get("skills") or {}, cv.get("skills") or {}
    if isinstance(original_skills, dict) and isinstance(final_skills, dict):
        add(
            "Skills · order and emphasis",
            [f"{k}: {text(v)}" for k, v in original_skills.items()],
            [f"{k}: {text(v)}" for k, v in final_skills.items()],
        )

    def align(before, after, identity, label, compare):
        old, new = defaultdict(list), defaultdict(list)
        for row in before if isinstance(before, list) else []:
            if isinstance(row, dict):
                old[identity(row)].append(row)
        for row in after if isinstance(after, list) else []:
            if isinstance(row, dict):
                new[identity(row)].append(row)
        for key in dict.fromkeys([*old, *new]):
            name = label(key)
            if len(old[key]) > 1 or len(new[key]) > 1:
                add(
                    name,
                    "Multiple source or output entries share this identity.",
                    "Review the saved documents; no automatic alignment was made.",
                    "Ambiguous alignment",
                )
            else:
                compare(
                    old[key][0] if old[key] else {},
                    new[key][0] if new[key] else {},
                    name,
                )

    def project(before, after, name):
        add(name, before.get("bullets", []), after.get("bullets", []))

    def role(before, after, name):
        add(name + " · bullets", before.get("bullets", []), after.get("bullets", []))
        align(
            before.get("selected_projects", []),
            after.get("projects", []),
            lambda r: str(r.get("name", "")).strip().casefold(),
            lambda k: name + " · project: " + k,
            project,
        )

    align(
        snapshot.get("experience", []),
        cv.get("experience", []),
        lambda r: tuple(
            str(r.get(k, "")).strip().casefold()
            for k in ("company", "role", "start_date", "end_date")
        ),
        lambda k: " / ".join(k),
        role,
    )
    for key in ("education", "certifications"):
        if cv.get("include_" + key) is False:
            add(
                key.title(),
                "Included in saved profile",
                "Excluded from tailored CV",
                "Omitted",
            )
    return changes


def _expected_cv_text(content):
    cv = content.get("cv") if isinstance(content.get("cv"), dict) else {}
    summary = cv.get("summary")
    paragraphs = [item for item in summary if isinstance(item, str)] if isinstance(summary, list) else []
    fields = {}
    if isinstance(cv.get("title"), str) and cv["title"].strip():
        fields["CV title"] = cv["title"]
    experiences = cv.get("experience")
    for experience in experiences if isinstance(experiences, list) else []:
        if not isinstance(experience, dict):
            continue
        for key in ("role", "company"):
            value = experience.get(key)
            if isinstance(value, str) and value.strip():
                fields[f"{key.title()} {len(fields) + 1}"] = value
        for date_key in ("start_date", "end_date"):
            value = experience.get(date_key)
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
                try:
                    value = datetime.strptime(value, "%Y-%m").strftime("%b %Y")
                except ValueError:
                    continue
                fields[f"Employment date {len(fields) + 1}"] = value
        bullets = experience.get("bullets")
        for bullet in bullets if isinstance(bullets, list) else []:
            if isinstance(bullet, str):
                paragraphs.append(bullet)
        projects = experience.get("projects")
        for project in projects if isinstance(projects, list) else []:
            if isinstance(project, dict):
                if isinstance(project.get("name"), str):
                    paragraphs.append(project["name"])
                project_bullets = project.get("bullets")
                if isinstance(project_bullets, list):
                    paragraphs.extend(
                        bullet for bullet in project_bullets if isinstance(bullet, str)
                    )
    skill_map = cv.get("skills")
    for skills in skill_map.values() if isinstance(skill_map, dict) else []:
        for skill in skills if isinstance(skills, list) else []:
            if isinstance(skill, str) and skill.strip():
                fields[f"Skill {len(fields) + 1}"] = skill
    snapshot = content.get("_profile_snapshot")
    selected_projects = cv.get("standalone_projects")
    if isinstance(snapshot, dict) and isinstance(selected_projects, list):
        source_projects = snapshot.get("standalone_projects")
        if isinstance(source_projects, list):
            project_rows = {
                row["name"]: row for row in source_projects
                if isinstance(row, dict) and isinstance(row.get("name"), str)
            }
            for name in selected_projects:
                if not isinstance(name, str) or name not in project_rows:
                    continue
                paragraphs.append(name)
                bullets = project_rows[name].get("bullets")
                if isinstance(bullets, list):
                    paragraphs.extend(bullet for bullet in bullets if isinstance(bullet, str))
    if isinstance(snapshot, dict) and cv.get("include_education") is not False:
        education_rows = snapshot.get("education")
        for education in education_rows if isinstance(education_rows, list) else []:
            if not isinstance(education, dict):
                continue
            for key in ("degree", "institution"):
                value = education.get(key)
                if isinstance(value, str) and value.strip():
                    fields[f"Education {len(fields) + 1}"] = value
    if isinstance(snapshot, dict) and cv.get("include_certifications") is not False:
        certifications = snapshot.get("certifications")
        for certification in certifications if isinstance(certifications, list) else []:
            if isinstance(certification, str) and certification.strip():
                fields[f"Certification {len(fields) + 1}"] = certification
    return paragraphs, fields


def _expected_letter_text(content):
    letter = (
        content.get("cover_letter")
        if isinstance(content.get("cover_letter"), dict)
        else {}
    )
    letter_paragraphs = letter.get("paragraphs")
    paragraphs = (
        [item for item in letter_paragraphs if isinstance(item, str)]
        if isinstance(letter_paragraphs, list)
        else []
    )
    fields = {}
    for label, value in (
        ("Candidate name", letter.get("signature_name")),
        ("Job title", letter.get("role_title") or content.get("role_title")),
        ("Company", letter.get("company_name") or content.get("company_name")),
    ):
        if isinstance(value, str) and value.strip():
            fields[label] = value
    return paragraphs, fields


def inspect_application_pdfs(folder, content, snapshot, manifest):
    """Run local advisory extraction checks on saved PDFs, without invoking Office."""
    from services.document_quality import inspect_document

    identity = snapshot.get("identity") if isinstance(snapshot, dict) else {}
    identity = identity if isinstance(identity, dict) else {}
    pdfs = [path for path in _document_files(folder) if path.suffix.lower() == ".pdf"]
    key_scopes = {
        "cv_path": "cv",
        "cl_pdf_path": "cover_letter",
    }
    manifest_paths = {
        Path(manifest[key]).resolve(): scope
        for key, scope in key_scopes.items()
        if isinstance(manifest.get(key), str) and manifest[key].strip()
    }
    reports = {}
    for path in pdfs:
        scope = manifest_paths.get(path.resolve())
        if scope is None:
            scope = "cover_letter" if "cover_letter" in path.stem.lower() else "cv"
        if scope == "cover_letter":
            paragraphs, fields = _expected_letter_text(content)
        else:
            content_with_snapshot = dict(content)
            content_with_snapshot["_profile_snapshot"] = snapshot
            paragraphs, fields = _expected_cv_text(content_with_snapshot)
        for label in ("Candidate name", "Email"):
            value = identity.get("full_name" if label == "Candidate name" else "email")
            if isinstance(value, str) and value.strip():
                fields[label] = value
        report = inspect_document(
            path, expected_paragraphs=paragraphs, expected_fields=fields
        )
        if scope == "cv":
            from renderers.cv_layout import read_layout_metadata

            report["layout"] = read_layout_metadata(path)
        limit = 1 if scope == "cover_letter" else 2
        if isinstance(report.get("page_count"), int) and report["page_count"] > limit:
            report["warnings"].append(
                f"This {scope.replace('_', ' ')} PDF has {report['page_count']} pages; the target is {limit}."
            )
        reports[path.name] = report
    return reports


def _word_layout_freshness(folder, manifest):
    saved = manifest.get("word_layout")
    saved = saved if isinstance(saved, dict) else {}
    result = {}
    for path in _document_files(folder):
        if path.suffix.lower() != ".docx":
            continue
        row = saved.get(path.name)
        if not isinstance(row, dict) or not isinstance(row.get("artifact_sha256"), str):
            result[path.name] = {"status": "unknown", "report": row or {}}
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            result[path.name] = {"status": "unknown", "report": row}
            continue
        result[path.name] = {
            "status": "current" if digest == row["artifact_sha256"] else "stale",
            "report": row,
        }
    return result


def check_saved_word_layout(config, profile_id, job_id):
    """Run opt-in Word pagination checks and merge them into the run manifest."""
    from services.word_layout import inspect_word_layout

    folder = application_folder(config, profile_id, job_id)
    manifest_path = folder / "source" / "generation_result.json"
    manifest = {}
    if manifest_path.exists():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("Cannot save Word pagination because the application manifest is unreadable.") from error
        if not isinstance(value, dict):
            raise ValueError("Cannot save Word pagination because the application manifest is not an object.")
        manifest = value
    saved = manifest.get("word_layout")
    if not isinstance(saved, dict):
        saved = {}
    report_by_name = {}
    cover_letter_path = manifest.get("cover_letter_path")
    cover_letter_name = Path(cover_letter_path).name if isinstance(cover_letter_path, str) else None
    for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() != ".docx":
            continue
        is_letter = path.name == cover_letter_name or "cover_letter" in path.stem.casefold()
        report = inspect_word_layout(path, page_limit=1 if is_letter else 2)
        saved[path.name] = report
        report_by_name[path.name] = report
    manifest["word_layout"] = saved
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_by_name


def _document_files(folder):
    return [
        path
        for path in folder.iterdir()
        if path.suffix.lower() in {".pdf", ".docx", ".txt"}
        and ".sync-conflict-" not in path.name.lower()
        and path.is_file()
        and path.resolve().is_relative_to(folder)
    ]


def _quality_fingerprint(paths, content, snapshot, manifest):
    pdfs = {}
    for path in paths:
        if path.suffix.lower() == ".pdf":
            try:
                pdfs[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                return None
    inputs = [
        pdfs, content, snapshot, manifest.get("cv_path"), manifest.get("cl_pdf_path")
    ]
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()


def _review_metadata(folder):
    warnings = []
    manifest = read_json(folder, "generation_result.json", warnings)
    for key in ("models", "token_usage"):
        if key in manifest and not isinstance(manifest[key], dict):
            warnings.append(
                f"{key} has an unsupported shape; historical values are unavailable."
            )
            manifest[key] = {}
    content = read_json(folder, "content.json", warnings)
    return manifest, content, warnings


def _application_summary(folder, content, manifest):
    letter = content.get("cover_letter")
    letter = letter if isinstance(letter, dict) else {}
    recorded_date = text(manifest.get("created_at"))
    title = text(content.get("role_title")) or text(letter.get("role_title"))
    status = {"failed": "Failed", "success": "Generated", "answers_only": "Answers only"}.get(
        text(manifest.get("status")), "Legacy / incomplete"
    )
    return {
        "job_id": folder.name,
        "title": title or folder.name.replace("_", " "),
        "company": text(content.get("company_name")) or text(letter.get("company_name")),
        "created_at": recorded_date or datetime.fromtimestamp(
            folder.stat().st_mtime, timezone.utc
        ).isoformat(timespec="seconds"),
        "date_source": "recorded" if recorded_date else "folder modified",
        "status": status,
    }


def load_application_summary(config, profile_id, job_id):
    """Read recent-list labels without inspecting document bytes or layout."""
    folder = application_folder(config, profile_id, job_id)
    manifest, content, _ = _review_metadata(folder)
    return {
        **_application_summary(folder, content, manifest),
        "manifest": {"models": manifest.get("models", {})},
    }


def load_review(config, profile_id, job_id, *, include_quality=False):
    folder = application_folder(config, profile_id, job_id)
    manifest, content, warnings = _review_metadata(folder)
    snapshot = read_json(folder, "profile_snapshot.json", warnings)
    provenance = read_json(folder, "posting_provenance.json", warnings)
    saved_artifact_provenance = manifest.get("artifact_provenance")
    saved_artifact_provenance = (
        saved_artifact_provenance
        if isinstance(saved_artifact_provenance, dict)
        else {}
    )
    renderable_files = _document_files(folder)
    freshness = artifact_freshness(
        config.project_root,
        content,
        renderable_files,
        saved_artifact_provenance,
        profile_snapshot=snapshot or None,
    )
    cv = content.get("cv") if isinstance(content.get("cv"), dict) else {}
    letter = (
        content.get("cover_letter")
        if isinstance(content.get("cover_letter"), dict)
        else {}
    )
    explanation = manifest.get("tailoring_explanation")
    explanation = (
        {k: v for k, v in explanation.items() if isinstance(v, str) and v.strip()}
        if isinstance(explanation, dict)
        else {}
    )
    hit = manifest.get("cache_hit")
    calls = manifest.get("calls") if isinstance(manifest.get("calls"), list) else []
    run_type = (
        ("Reused draft + new calls" if calls else "Cached result")
        if hit is True
        else "Fresh draft" if hit is False else "Not recorded"
    )
    return {
        **_application_summary(folder, content, manifest),
        "path": str(folder),
        "manifest": manifest,
        "content": content,
        "snapshot": snapshot,
        "posting_provenance": provenance,
        "artifact_freshness": freshness,
        "word_layout": _word_layout_freshness(folder, manifest),
        "document_quality": (
            inspect_application_pdfs(folder, content, snapshot, manifest)
            if include_quality
            else {}
        ),
        "quality_fingerprint": _quality_fingerprint(
            renderable_files, content, snapshot, manifest
        ),
        "explanation": explanation,
        "warnings": warnings,
        "run_type": run_type,
        "changes": compare_cv(snapshot, cv) if snapshot and cv else [],
        "comparison_available": bool(snapshot and cv),
        "letter_words": (
            len(text(letter.get("paragraphs", [])).split()) if letter else None
        ),
    }
