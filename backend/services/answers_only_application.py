"""Create a saved application workspace without generation or rendering."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from services.application_store import ApplicationStore, make_job_id
from services.posting import validate_posting
from services.profile_store import validate_profile_id
from utils.text import slugify


def create_answers_only_application(
    config, profile_id, job_description, *, company=None, role=None, work_country=None
) -> str:
    candidate = validate_profile_id(profile_id)
    posting = validate_posting(job_description)
    store = config.store
    profile_path = store.profile_path(candidate)
    if profile_path.resolve() != store.profiles_dir.resolve() / candidate / profile_path.name:
        raise ValueError("The profile file resolves outside its candidate namespace.")
    snapshot = store.load(candidate).model_dump(mode="json")

    outputs = store.outputs_dir(candidate).resolve()
    if outputs != (store.root / "outputs").resolve() / candidate:
        raise ValueError("Candidate output directory resolves outside its own namespace.")
    company = (company or "").strip()
    role = (role or "").strip()
    job_id = make_job_id(
        company[:40], role[:60], slugify, candidate, timezone_name=config.timezone_name
    ) + f"_answers_{uuid4().hex[:8]}"
    outputs.mkdir(parents=True, exist_ok=True)

    # Publish the whole application at once so history never sees a half-written record.
    with TemporaryDirectory(dir=outputs, prefix=".answers-only ") as scratch:
        application = ApplicationStore(Path(scratch), job_id, candidate)
        application.create(snapshot, posting)
        application.save_content({
            "company_name": company,
            "role_title": role or "Portal answers",
            "work_country": (work_country or "").strip(),
        })
        application.save_manifest({
            "job_id": job_id,
            "status": "answers_only",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, [])
        application.job_folder.rename(outputs / job_id)
    return job_id
