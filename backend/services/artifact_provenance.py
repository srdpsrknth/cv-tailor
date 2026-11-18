"""Record and compare provenance for rendered application files.

Freshness is advisory. Missing metadata remains ``unknown`` so saved legacy files
stay downloadable without pretending that their source or renderer is current.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_digest(content: dict, scope: str) -> str:
    """Hash only the editable section that produced this artifact."""
    section = content.get(scope)
    if not isinstance(section, dict):
        return ""
    serialized = json.dumps(
        section, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return _digest_bytes(serialized)


def _dependencies(project_root: Path, scope: str) -> list[Path]:
    """Files that can affect the rendered content for a CV or cover letter."""
    root = Path(project_root)
    if scope == "cv":
        fixed = (
            "backend/renderers/latex_renderer.py",
            "backend/renderers/upload_cv.py",
            "backend/utils/text.py",
        )
        directories = ("templates/cv",)
    elif scope == "cover_letter":
        fixed = (
            "backend/renderers/docx_renderer.py",
            "backend/renderers/latex_renderer.py",
            "backend/utils/text.py",
        )
        directories = ("cover_letter_latex_template", "templates/cover_letter")
    else:
        raise ValueError(f"Unsupported artifact content scope: {scope}")
    found = [root / name for name in fixed]
    for directory in directories:
        base = root / directory
        if base.is_dir():
            found.extend(path for path in base.rglob("*") if path.is_file())
        else:
            found.append(base)
    return sorted(set(found), key=lambda path: path.relative_to(root).as_posix())


def rendering_fingerprint(project_root: Path, scope: str) -> str:
    """Hash dependency paths and bytes, including a stable marker for missing files."""
    root = Path(project_root)
    digest = hashlib.sha256()
    for path in _dependencies(root, scope):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        try:
            payload = path.read_bytes()
        except OSError:
            payload = b"<missing>"
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def record_artifact_provenance(
    project_root: Path,
    content: dict,
    artifacts: Iterable[tuple[Path, str]],
    *,
    profile_snapshot: dict | None = None,
) -> dict:
    """Create provenance rows for the artifacts rendered in this operation.

    Each item is ``(artifact_path, content_scope)`` where scope is ``cv`` or
    ``cover_letter``. Callers merge returned rows into the existing manifest so
    scoped renders preserve provenance for untouched files.
    """
    rows = {}
    profile_sha256 = _digest_bytes(
        json.dumps(
            profile_snapshot or {},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    for artifact, scope in artifacts:
        path = Path(artifact)
        if not path.is_file():
            continue
        rows[path.name] = {
            "content_scope": scope,
            "content_sha256": content_digest(content, scope),
            "render_context_sha256": _digest_bytes(
                json.dumps(
                    {
                        "content_sha256": content_digest(content, scope),
                        "role_title": content.get("role_title"),
                        "company_name": content.get("company_name"),
                        "work_country": content.get("work_country"),
                        "profile_sha256": profile_sha256,
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "profile_sha256": profile_sha256,
            "rendering_sha256": rendering_fingerprint(project_root, scope),
            "artifact_sha256": _digest_bytes(path.read_bytes()),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema_version": 1,
        }
    return rows


def artifact_freshness(
    project_root: Path,
    content: dict,
    artifacts: Iterable[Path],
    provenance: dict,
    *,
    profile_snapshot: dict | None = None,
) -> dict:
    """Classify saved files as current, stale, or unknown without blocking access."""
    result = {}
    for artifact in artifacts:
        path = Path(artifact)
        row = provenance.get(path.name) if isinstance(provenance, dict) else None
        if not isinstance(row, dict):
            result[path.name] = {
                "status": "unknown",
                "reasons": ["No provenance recorded"],
            }
            continue
        scope = row.get("content_scope")
        if scope not in {"cv", "cover_letter"}:
            result[path.name] = {
                "status": "unknown",
                "reasons": ["Unsupported provenance record"],
            }
            continue
        reasons = []
        if not path.is_file():
            reasons.append("Artifact file is missing")
        else:
            if row.get("artifact_sha256") != _digest_bytes(path.read_bytes()):
                reasons.append("Artifact bytes changed since rendering")
        if row.get("content_sha256") != content_digest(content, scope):
            reasons.append("Saved editable content changed since rendering")
        profile_sha256 = _digest_bytes(
            json.dumps(
                profile_snapshot or {},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if row.get("profile_sha256") != profile_sha256:
            reasons.append("Saved profile context changed since rendering")
        context = _digest_bytes(
            json.dumps(
                {
                    "content_sha256": content_digest(content, scope),
                    "role_title": content.get("role_title"),
                    "company_name": content.get("company_name"),
                    "work_country": content.get("work_country"),
                    "profile_sha256": profile_sha256,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if row.get("render_context_sha256") != context:
            reasons.append("Rendering context changed since rendering")
        if row.get("rendering_sha256") != rendering_fingerprint(project_root, scope):
            reasons.append("Rendering dependencies changed since rendering")
        result[path.name] = {
            "status": "stale" if reasons else "current",
            "reasons": reasons,
        }
    return result
