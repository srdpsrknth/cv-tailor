"""Explicit, offline companion export for an existing private application."""

from models.profile import Profile
from models.tailored_output import TailoredCV
from renderers.upload_cv import render_upload_cv
from services.application_review import application_folder, read_json


def export_saved_upload_cv(config, profile_id, job_id):
    folder = application_folder(config, profile_id, job_id)
    warnings = []
    content = read_json(folder, 'content.json', warnings)
    snapshot = read_json(folder, 'profile_snapshot.json', warnings)
    if warnings or not content.get('cv') or not snapshot:
        raise ValueError('Autofill export needs valid saved CV content and a profile snapshot. '
                         'Restore those sources before exporting.')
    cv = TailoredCV.model_validate(content['cv'])
    profile = Profile.model_validate(snapshot)
    # Do not rewrite the old manifest, source or polished PDF.
    return render_upload_cv(cv, profile, folder, content.get('role_title'))
