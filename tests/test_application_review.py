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
    assert detail["artifact_freshness"]["cv.pdf"]["status"] == "unknown"


def test_review_marks_edited_content_stale_but_keeps_artifact_downloadable(review_config):
    from services.artifact_provenance import record_artifact_provenance

    folder = save_application(
        review_config,
        content={"cv": {"summary": ["Original"]}, "cover_letter": {}},
    )
    artifact = folder / "cv.pdf"
    artifact.write_bytes(b"saved PDF")
    content = {"cv": {"summary": ["Original"]}, "cover_letter": {}}
    manifest_path = folder / "source/generation_result.json"
    manifest = {
        "status": "success",
        "artifact_provenance": record_artifact_provenance(
            review_config.project_root, content, [(artifact, "cv")]
        ),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "source/content.json").write_text(
        json.dumps({"cv": {"summary": ["Manual edit"]}, "cover_letter": {}}),
        encoding="utf-8",
    )

    detail = bridge.load_application(review_config, "analyst_a", "northwind")

    assert detail["artifact_freshness"]["cv.pdf"]["status"] == "stale"
    assert "cv.pdf" in {item["name"] for item in detail["artifacts"]}


def test_word_pagination_check_is_explicit_and_manifest_merge_preserves_sources(
    review_config, monkeypatch
):
    import hashlib
    from services.application_review import check_saved_word_layout

    folder = save_application(
        review_config,
        content={"company_name": "Northwind", "role_title": "Analyst"},
        generation_result={"status": "success", "provider": "historical"},
    )
    (folder / "cover_letter.docx").write_bytes(b"letter bytes")
    source_content = (folder / "source/content.json").read_bytes()

    def inspect(path, *, page_limit):
        return {
            "status": "checked",
            "page_count": 1,
            "page_limit": page_limit,
            "engine": "LibreOffice",
            "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "warnings": [],
        }

    monkeypatch.setattr("services.word_layout.inspect_word_layout", inspect)
    reports = check_saved_word_layout(review_config, "analyst_a", "northwind")

    assert reports["cover_letter.docx"]["page_limit"] == 1
    assert (folder / "source/content.json").read_bytes() == source_content
    detail = bridge.load_application(review_config, "analyst_a", "northwind")
    assert detail["manifest"]["provider"] == "historical"
    assert detail["word_layout"]["cover_letter.docx"]["status"] == "current"

    (folder / "cover_letter.docx").write_bytes(b"edited")
    detail = bridge.load_application(review_config, "analyst_a", "northwind")
    assert detail["word_layout"]["cover_letter.docx"]["status"] == "stale"


def test_saved_pdf_quality_review_uses_expected_source_and_snapshot(review_config, monkeypatch):
    from services.application_review import load_review

    profile_snapshot = {"identity": {"full_name": "Candidate", "email": "c@example.invalid"}}
    content = {
        "role_title": "Analyst",
        "company_name": "Northwind",
        "cv": {"summary": ["CV summary"], "experience": []},
        "cover_letter": {
            "role_title": "Analyst",
            "company_name": "Northwind",
            "paragraphs": ["Letter body"],
            "signature_name": "Candidate",
        },
    }
    folder = save_application(
        review_config,
        content=content,
        profile_snapshot=profile_snapshot,
        generation_result={"cv_path": str(review_config.store.outputs_dir("analyst_a") / "northwind" / "cv.pdf")},
    )
    (folder / "cv.pdf").write_bytes(b"PDF")
    (folder / "cover_letter.pdf").write_bytes(b"PDF")
    seen = []

    def inspect(path, *, expected_paragraphs, expected_fields):
        seen.append((path.name, expected_paragraphs, expected_fields))
        return {"page_count": 3 if path.name == "cv.pdf" else 1,
                "engines": {}, "warnings": []}

    monkeypatch.setattr("services.document_quality.inspect_document", inspect)
    detail = load_review(review_config, "analyst_a", "northwind", include_quality=True)

    assert len(seen) == 2
    expected_by_file = {name: paragraphs for name, paragraphs, _fields in seen}
    assert "CV summary" in expected_by_file["cv.pdf"]
    assert "Letter body" in expected_by_file["cover_letter.pdf"]
    assert detail["document_quality"]["cv.pdf"]["warnings"]
    assert not detail["document_quality"]["cover_letter.pdf"]["warnings"]


def test_pdf_quality_review_tolerates_invalid_optional_source_shapes(review_config, monkeypatch):
    from services.application_review import load_review

    folder = save_application(
        review_config,
        content={"cv": {"summary": None, "experience": [None], "skills": None},
                 "cover_letter": {"paragraphs": None}},
        profile_snapshot={"identity": None, "education": None},
    )
    (folder / "cv.pdf").write_bytes(b"PDF")
    monkeypatch.setattr(
        "services.document_quality.inspect_document",
        lambda path, **kwargs: {"page_count": None, "engines": {}, "warnings": []},
    )
    detail = load_review(review_config, "analyst_a", "northwind", include_quality=True)
    assert detail["document_quality"]["cv.pdf"]


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
    provenance = manifest["artifact_provenance"]
    assert Path(second.cv_path).name in provenance
    assert provenance[Path(second.cv_path).name]["schema_version"] == 1
    assert provenance[Path(second.cv_path).name]["profile_sha256"]
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


def test_library_reads_summary_without_loading_document_details(review_config, monkeypatch):
    save_application(
        review_config,
        content={"company_name": "Northwind", "role_title": "Analyst"},
        generation_result={"status": "failed", "models": {"cv": "historical"}},
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Listing history should not inspect saved documents")

    monkeypatch.setattr("services.application_review.artifact_freshness", unexpected)
    record, = bridge.application_library(review_config, "analyst_a")
    assert (record["title"], record["company"], record["status"]) == (
        "Analyst", "Northwind", "Failed"
    )
    assert record["manifest"]["models"] == {"cv": "historical"}


def test_quality_fingerprint_changes_with_saved_sources_and_pdf(review_config):
    folder = save_application(review_config, content={"cv": {"summary": ["Original"]}})
    artifact = folder / "cv.pdf"
    artifact.write_bytes(b"saved PDF")

    def fingerprint():
        return bridge.load_application(review_config, "analyst_a", "northwind")[
            "quality_fingerprint"
        ]

    before = fingerprint()
    (folder / "source/content.json").write_text(
        json.dumps({"cv": {"summary": ["Manual edit"]}}), encoding="utf-8"
    )
    after_edit = fingerprint()
    artifact.write_bytes(b"new PDF!!")
    assert before != after_edit != fingerprint()


def test_saved_sources_come_from_one_candidate_job(review_config):
    from services.application_review import load_saved_sources

    folder = save_application(review_config, content={"role_title": "Analyst"})
    (folder / "source/job_description.txt").write_text("Saved posting", encoding="utf-8")
    save_application(review_config, candidate="analyst_b")

    sources = load_saved_sources(review_config, "analyst_a", "northwind")
    assert sources["folder"] == folder.resolve()
    assert sources["posting"] == "Saved posting"
    assert sources["content"] == {"role_title": "Analyst"}
    assert sources["snapshot"] == {}
    assert load_saved_sources(review_config, "analyst_b", "northwind")["posting"] == ""


def test_answers_only_application_opens_without_rendered_files(review_config):
    from services.answers_only_application import create_answers_only_application
    from services.application_review import load_saved_sources

    description = "Northwind seeks an analyst to report on operations and metrics."
    job_id = create_answers_only_application(
        review_config, "analyst_b", description,
        company="Northwind", role="Analyst", work_country="Germany",
    )
    detail = bridge.load_application(review_config, "analyst_b", job_id)
    sources = load_saved_sources(review_config, "analyst_b", job_id)
    assert detail["status"] == "Answers only"
    assert detail["title"] == "Analyst"
    assert detail["company"] == "Northwind"
    assert detail["artifacts"] == []
    assert sources["posting"] == description
    assert sources["snapshot"]["identity"]
    assert sources["content"]["work_country"] == "Germany"
    assert "cv" not in sources["content"]
    assert bridge.application_library(review_config, "analyst_a") == []


def test_answers_only_application_validates_before_creating_a_folder(review_config):
    from services.answers_only_application import create_answers_only_application
    from services.profile_store import UnknownProfileError

    with pytest.raises(ValueError, match="too short"):
        create_answers_only_application(review_config, "analyst_a", "Analyst")
    with pytest.raises(UnknownProfileError):
        create_answers_only_application(
            review_config, "missing", "Northwind seeks analysts to report on operations and metrics."
        )
    assert not (review_config.store.root / "outputs").exists()


def test_answers_only_creation_keeps_failed_writes_out_of_history(review_config, monkeypatch):
    from services.answers_only_application import create_answers_only_application
    from services.application_store import ApplicationStore

    def fail_write(*args, **kwargs):
        raise OSError("Write failed")

    monkeypatch.setattr(ApplicationStore, "save_manifest", fail_write)
    with pytest.raises(OSError, match="Write failed"):
        create_answers_only_application(
            review_config, "analyst_a", "Northwind seeks analysts to report on operations and metrics."
        )
    assert bridge.application_library(review_config, "analyst_a") == []


def test_layout_preview_uses_saved_revision_without_replacing_the_pdf(review_config, monkeypatch):
    from types import SimpleNamespace

    from services import application_layout_preview
    from support import read_json

    snapshot = review_config.store.load("analyst_a").model_dump(mode="json")
    content = read_json("content", "valid_content.json")
    folder = save_application(review_config, content=content, profile_snapshot=snapshot)
    artifact = folder / "cv.pdf"
    artifact.write_bytes(b"existing CV")

    def create_renderer(*, outputs_dir, **_kwargs):
        assert Path(outputs_dir).is_dir()
        assert not Path(outputs_dir).is_relative_to(folder)

        def preview(cv, profile, *, job_position):
            assert cv.summary == content["cv"]["summary"]
            assert profile.model_dump(mode="json") == snapshot
            assert job_position == content.get("role_title")
            return b"%PDF-1.7\npreview", {
                "page_count": 2, "text_preserved": True, "clipping": False,
                "orphan_headings": False,
            }

        return SimpleNamespace(preview_cv_layout=preview)

    monkeypatch.setattr(application_layout_preview, "create_latex_renderer", create_renderer)
    pdf, report = application_layout_preview.preview_saved_cv_layout(
        review_config, "analyst_a", "northwind"
    )
    assert report["page_count"] == 2
    assert not list(folder.glob("cv_balanced_*"))
    saved = application_layout_preview.save_cv_layout_preview(
        review_config, "analyst_a", "northwind", pdf, report
    )
    assert saved.parent == folder.resolve()
    assert saved.read_bytes() == pdf
    assert application_layout_preview.save_cv_layout_preview(
        review_config, "analyst_a", "northwind", pdf, report
    ) == saved
    assert len(list(folder.glob("cv_balanced_*"))) == 1
    assert artifact.read_bytes() == b"existing CV"

    content["cv"]["summary"].append("A new revision.")
    (folder / "source/content.json").write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="CV changed"):
        application_layout_preview.save_cv_layout_preview(
            review_config, "analyst_a", "northwind", pdf, report
        )


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
