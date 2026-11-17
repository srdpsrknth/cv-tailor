"""Read-only application review and deterministic comparisons. No provider calls."""

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json
import re

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
    folder = (root / job_id).resolve()
    if folder.parent != root or not folder.is_dir():
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


def load_review(config, profile_id, job_id):
    folder = application_folder(config, profile_id, job_id)
    warnings = []
    manifest = read_json(folder, "generation_result.json", warnings)
    for key in ("models", "token_usage"):
        if key in manifest and not isinstance(manifest[key], dict):
            warnings.append(
                f"{key} has an unsupported shape; historical values are unavailable."
            )
            manifest[key] = {}
    content = read_json(folder, "content.json", warnings)
    snapshot = read_json(folder, "profile_snapshot.json", warnings)
    provenance = read_json(folder, "posting_provenance.json", warnings)
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
        "job_id": job_id,
        "path": str(folder),
        "manifest": manifest,
        "content": content,
        "snapshot": snapshot,
        "posting_provenance": provenance,
        "explanation": explanation,
        "warnings": warnings,
        "title": text(content.get("role_title"))
        or text(letter.get("role_title"))
        or job_id.replace("_", " "),
        "company": text(content.get("company_name"))
        or text(letter.get("company_name")),
        "created_at": text(manifest.get("created_at"))
        or datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        ),
        "date_source": (
            "recorded" if text(manifest.get("created_at")) else "folder modified"
        ),
        "status": (
            "Failed"
            if manifest.get("status") == "failed"
            else (
                "Generated"
                if manifest.get("status") == "success"
                else "Legacy / incomplete"
            )
        ),
        "run_type": run_type,
        "changes": compare_cv(snapshot, cv) if snapshot and cv else [],
        "comparison_available": bool(snapshot and cv),
        "letter_words": (
            len(text(letter.get("paragraphs", [])).split()) if letter else None
        ),
    }
