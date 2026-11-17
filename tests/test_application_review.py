"""Saved review data is profile-scoped, offline and honest about missing evidence."""

import json
import shutil
from pathlib import Path

import pytest

from config import Config
from ui import services_bridge as bridge


@pytest.fixture
def review_config(tmp_path):
    for candidate in ("analyst_a", "analyst_b"):
        folder = tmp_path / "profiles" / candidate
        folder.mkdir(parents=True)
        shutil.copy2(
            Path(__file__).parent / "fixtures/profiles/synthetic_analyst.yaml",
            folder / "profile.yaml",
        )
    return Config.from_env(
        load_env_file=False,
        overrides={
            "project_root": tmp_path,
            "profile_store_dir": tmp_path,
            "profile_id": "analyst_a",
        },
    )


def save_application(config, candidate="analyst_a", job="northwind", **files):
    folder = config.store.outputs_dir(candidate) / job / "source"
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return folder.parent


def test_review_loads_saved_model_explanation_and_does_not_use_current_model(
    review_config,
):
    save_application(
        review_config,
        generation_result={
            "models": {"cv": "historical"},
            "tailoring_explanation": {"overall_strategy": "Prioritise reporting"},
        },
        content={"company_name": "Northwind", "role_title": "Analyst"},
    )
    detail = bridge.load_application(review_config, "analyst_a", "northwind")
    assert detail["title"] == "Analyst"
    assert detail["manifest"]["models"]["cv"] == "historical"
    assert detail["explanation"]["overall_strategy"] == "Prioritise reporting"
    assert detail["run_type"] == "Not recorded"


def test_legacy_and_corrupt_files_remain_viewable(review_config):
    folder = save_application(review_config)
    (folder / "cv.pdf").write_bytes(b"legacy download")
    (folder / "source/content.json").write_text("{broken", encoding="utf-8")
    detail = bridge.load_application(review_config, "analyst_a", "northwind")
    assert detail["artifacts"]
    assert detail["explanation"] == {}
    assert detail["warnings"]
    assert detail["status"] == "Legacy / incomplete"


@pytest.mark.parametrize(
    "job", ["../analyst_b/private", "..", "/outside", "a/b", "a\\b"]
)
def test_review_rejects_paths_outside_one_application(review_config, job):
    with pytest.raises(ValueError):
        bridge.load_application(review_config, "analyst_a", job)


def test_review_does_not_return_another_candidates_application(review_config):
    save_application(
        review_config,
        candidate="analyst_b",
        generation_result={"tailoring_explanation": {"overall_strategy": "private"}},
    )
    with pytest.raises(ValueError):
        bridge.load_application(review_config, "analyst_a", "northwind")


def test_comparison_aligns_roles_and_projects_by_identity_not_position():
    from services.application_review import compare_cv

    original = {
        "summary_base": ["Original"],
        "experience": [
            {
                "company": "A",
                "role": "Analyst",
                "start_date": "2020",
                "end_date": "2022",
                "bullets": ["A original"],
            },
            {
                "company": "B",
                "role": "Engineer",
                "start_date": "2022",
                "end_date": "present",
                "bullets": ["B original"],
                "selected_projects": [{"name": "Reporting", "bullets": ["Old report"]}],
            },
        ],
    }
    final = {
        "summary": ["Tailored"],
        "experience": [
            {
                **original["experience"][1],
                "bullets": ["B tailored"],
                "projects": [{"name": "Reporting", "bullets": ["New report"]}],
            },
            original["experience"][0],
        ],
    }
    differences = compare_cv(original, final)
    assert any(
        d["before"] == "B original" and d["after"] == "B tailored" for d in differences
    )
    assert any(
        d["before"] == "Old report" and d["after"] == "New report" for d in differences
    )
    assert not any("A original" in d["before"] for d in differences)


def test_comparison_reports_ambiguous_roles_without_guessing():
    from services.application_review import compare_cv

    role = {"company": "A", "role": "Analyst", "bullets": ["Original"]}
    differences = compare_cv({"experience": [role, role]}, {"experience": [role]})
    assert any(d["kind"] == "Ambiguous alignment" for d in differences)


def test_failed_generation_does_not_claim_drafts_were_saved(review_config, monkeypatch):
    def fail(**kwargs):
        raise ValueError("failed before persistence")

    monkeypatch.setattr("services.tailor_service.tailor_documents", fail)
    outcome = bridge.run_generation(
        review_config, "analyst_a", "A detailed real job description " * 10
    )
    assert not outcome.ok
    assert not outcome.drafts_saved


def test_shared_posting_validation_rejects_copied_command():
    from services.posting import validate_posting

    with pytest.raises(ValueError, match="command"):
        validate_posting(
            "python cvtailor.py --profile-id analyst_a generate --job-file role.txt"
        )


def test_cache_manifest_distinguishes_current_from_original_usage(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session
):
    from services.tailor_service import tailor_documents

    offline_service(analyst_session.texts())
    stub_renderers([2, 2, 2])
    first = tailor_documents(analyst_session.job_description_text, analyst_profile)
    second = tailor_documents(analyst_session.job_description_text, analyst_profile)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.original_usage["total_tokens"] > 0
    assert second.token_usage.total_tokens == 0
    assert second.cost_source == "cache"
    manifest = json.loads(
        (Path(second.source_path).parent / "generation_result.json").read_text()
    )
    assert manifest["cache_hit"] is True
    assert manifest["created_at"]
    third = tailor_documents(analyst_session.job_description_text, analyst_profile)
    assert third.original_usage["total_tokens"] == second.original_usage["total_tokens"]


def test_validation_failure_keeps_raw_drafts_and_failure_status(
    isolated_service, offline_service, analyst_profile
):
    from services.tailor_service import tailor_documents

    offline_service(["{}", "{}", "{}"])
    with pytest.raises(ValueError):
        tailor_documents(
            "A detailed analytics job description with responsibilities. " * 3,
            analyst_profile,
        )
    sources = list(isolated_service.glob("outputs/analyst_a/*/source"))
    assert len(sources) == 1
    assert len(json.loads((sources[0] / "drafts.json").read_text())["drafts"]) == 3
    manifest = json.loads((sources[0] / "generation_result.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["models"]["cv"]
    assert not (sources[0] / "content.json").exists()


def test_malformed_optional_manifest_fields_do_not_crash_the_library(review_config):
    save_application(
        review_config,
        generation_result={
            "models": ["unsupported"],
            "token_usage": 3,
            "created_at": 123,
        },
    )
    detail = bridge.load_application(review_config, "analyst_a", "northwind")
    assert detail["manifest"]["models"] == {}
    assert isinstance(detail["created_at"], str)
    assert detail["warnings"]


def test_escaped_comparison_does_not_execute_model_markup():
    from ui.review import highlighted

    left, right = highlighted("<script>old</script>", "<img src=x onerror=alert(1)>")
    assert "<script>" not in left and "<img" not in right
    assert "&lt;" in left and "&lt;" in right


def test_library_includes_more_than_twenty_saved_applications(review_config):
    for i in range(24):
        save_application(review_config, job=f"job_{i}")
    assert len(bridge.application_library(review_config, "analyst_a")) == 24


def test_received_provider_reply_retains_task_model_and_cost(review_config):
    from services.llm_service import LLMService
    from services.provider import ProviderResponse
    from types import SimpleNamespace

    config = review_config.with_overrides(
        openrouter_api_key="synthetic", task_models={"cv": "requested-cv"}
    )
    service = LLMService(config=config)
    service.provider = SimpleNamespace(
        generate=lambda *a, **k: ProviderResponse(
            "{}", 12, 5, 0.002, "reported-cv", "reply-synthetic"
        )
    )
    service._call_provider("synthetic prompt", kind="cv")
    assert service.call_records[0]["task"] == "cv"
    assert service.call_records[0]["requested_model"] == "requested-cv"
    assert service.call_records[0]["reported_model"] == "reported-cv"
    assert service.call_records[0]["request_id"] == "reply-synthetic"
    assert service.call_records[0]["cost_source"] == "reported"
    assert service.calculate_token_usage(12, 5, 0, 0).estimated_cost_usd == 0.002
