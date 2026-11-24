from datetime import datetime, timezone
from pathlib import Path

from cli.commands import doctor
from cli.main import main
from config import Config
from models.profile import JobSearchDefaults, Profile
from models.tailored_output import TailoredCV
from renderers.upload_cv import render_upload_cv
from services import job_search
from services.application_store import make_job_id
from services.cache_store import serialize_profile_bytes
from services.validation import profile_facts_json
from utils import calendar
from utils.text import slugify


def test_cli_job_defaults_follow_selected_profile_and_explicit_options(tmp_path, monkeypatch):
    config = Config.from_env(load_env_file=False, overrides={"profile_store_dir": tmp_path})
    for candidate, defaults in (
        ("one", JobSearchDefaults(keywords="sql", country="CA", city="Toronto", remote_only=True)),
        ("two", JobSearchDefaults(country="Australia", city="Perth")),
        ("three", None),
    ):
        config.store.create(candidate, Profile(
            version="1.0", identity={"full_name": candidate, "email": f"{candidate}@example.test"},
            job_search=defaults,
        ))
    queries = []

    def search(sources, profile, query, **kwargs):
        queries.append(query)
        return job_search.SearchOutcome(query=query)

    monkeypatch.setattr(job_search, "search_jobs", search)
    for candidate, overrides in (
        ("one", []), ("two", []), ("three", []),
        ("one", ["--country", "IN", "--city", "", "--no-remote"]),
    ):
        assert main(["--store", str(tmp_path), "--profile-id", candidate, "jobs", "search", *overrides]) == 0
    assert [(q.country, q.city, q.remote, q.keywords) for q in queries] == [
        ("CA", "Toronto", True, "sql"), ("AU", "Perth", None, None),
        (None, None, None, None), ("IN", None, None, "sql"),
    ]
    assert main(["--store", str(tmp_path), "--profile-id", "one", "jobs", "search", "--country", "invalid"]) == 2
    assert len(queries) == 4


def test_search_preferences_remain_out_of_generation_and_factual_evidence(analyst_profile):
    changed = analyst_profile.model_copy(update={"job_search": JobSearchDefaults(keywords="SyntheticTool")})
    assert serialize_profile_bytes(changed) == serialize_profile_bytes(analyst_profile)
    assert "SyntheticTool" not in profile_facts_json(changed)


def test_configured_calendar_controls_new_ids_upload_names_and_diagnostics(tmp_path, monkeypatch, analyst_profile):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(calendar, "datetime", FrozenDateTime)
    monkeypatch.delenv("CVTAILOR_TIMEZONE", raising=False)
    assert Config.from_env(load_env_file=False).timezone_name == "UTC"
    monkeypatch.setenv("CVTAILOR_TIMEZONE", "Asia/Kolkata")
    config = Config.from_env(load_env_file=False)
    assert doctor.check_timezone(config.timezone_name).detail == "Asia/Kolkata"
    assert doctor.check_timezone("invalid").status == doctor.FAIL
    assert make_job_id("Company", "Role", slugify).startswith("2026_")
    assert make_job_id("Company", "Role", slugify, timezone_name=config.timezone_name).startswith("2027_")
    paths = render_upload_cv(TailoredCV(), analyst_profile, tmp_path, timezone_name=config.timezone_name)
    assert all(Path(path).name.startswith("2027_") for path in paths.values())
