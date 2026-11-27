"""Explicit, offline companion export for an existing private application."""

import json
from pathlib import Path

from models.profile import Profile
from models.tailored_output import TailoredCV
from renderers.upload_cv import render_upload_cv
from services.artifact_provenance import record_artifact_provenance
from services.candidate_guidance import load_candidate_acronyms
from services.application_review import application_folder, read_json


def export_saved_upload_cv(config, profile_id, job_id):
    folder = application_folder(config, profile_id, job_id)
    warnings = []
    content = read_json(folder, 'content.json', warnings)
    snapshot = read_json(folder, 'profile_snapshot.json', warnings)
    if warnings or not content.get('cv') or not snapshot:
        raise ValueError('Autofill export needs valid saved CV content and a profile snapshot. '
                         'Restore those sources before exporting.')
    manifest_path = folder / 'source' / 'generation_result.json'
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ValueError('Autofill export cannot update provenance because the saved manifest is unreadable.') from error
        if not isinstance(manifest, dict):
            raise ValueError('Autofill export cannot update provenance because the saved manifest is not an object.')
    cv = TailoredCV.model_validate(content['cv'])
    profile = Profile.model_validate(snapshot)
    paths = render_upload_cv(
        cv, profile, folder, content.get('role_title'), timezone_name=config.timezone_name,
        extra_acronyms=load_candidate_acronyms(config, profile_id),
    )
    rows = record_artifact_provenance(
        config.project_root,
        content,
        [(Path(path), 'cv') for path in paths.values()],
        profile_snapshot=snapshot,
    )
    saved_rows = manifest.get('artifact_provenance')
    saved_rows = saved_rows if isinstance(saved_rows, dict) else {}
    saved_rows.update(rows)
    manifest['artifact_provenance'] = saved_rows
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return paths
