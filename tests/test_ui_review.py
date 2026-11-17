"""Actual Streamlit reruns: no silent candidate selection or paid review calls."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from ui import services_bridge as bridge

APP = Path(__file__).resolve().parents[1] / "ui/app.py"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for candidate in ("analyst_a", "analyst_b"):
        folder = tmp_path / "profiles" / candidate
        folder.mkdir(parents=True)
        shutil.copy2(
            Path(__file__).parent / "fixtures/profiles/synthetic_analyst.yaml",
            folder / "profile.yaml",
        )
    monkeypatch.setenv("CVTAILOR_STORE", str(tmp_path))
    monkeypatch.setenv("CVTAILOR_PROFILE_ID", "analyst_a")

    def preflight(config):
        assert (
            config.store.root == tmp_path
        ), f"Wrong store: {config.store.root}; expected {tmp_path}"
        return {
            "key_configured": True,
            "pdf_engine": True,
            "models": {"cv": config.model},
        }

    monkeypatch.setattr(bridge, "preflight", preflight)
    st.cache_resource.clear()
    yield tmp_path
    st.cache_resource.clear()


def save_review(store, candidate="analyst_a", job="synthetic_job", explanation=True):
    source = store / "outputs" / candidate / job / "source"
    source.mkdir(parents=True)
    for name, value in {
        "content": {
            "company_name": "Northwind",
            "role_title": "Reporting analyst",
            "cv": {"summary": ["Tailored reporting summary"]},
        },
        "profile_snapshot": {"summary_base": ["Original analyst summary"]},
        "generation_result": {
            "status": "success",
            "models": {"cv": "historical-model"},
            "provider": "openrouter",
            "cache_hit": True,
            "cost_source": "cache",
            "token_usage": {"total_tokens": 0, "estimated_cost_usd": 0},
            "tailoring_explanation": (
                {"overall_strategy": "Prioritise reporting evidence"}
                if explanation
                else None
            ),
        },
    }.items():
        (source / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    return job


def selected_app():
    at = AppTest.from_file(str(APP)).run(timeout=30)
    assert not at.exception
    at.sidebar.selectbox[0].select("analyst_a").run()
    assert not at.exception
    return at


def test_configured_candidate_is_not_selected_without_user_action(workspace):
    at = AppTest.from_file(str(APP)).run()
    assert at.sidebar.selectbox[0].value is None
    assert not at.text_area
    assert at.session_state["profile_id"] is None


def test_gui_restores_last_selected_candidate_in_a_new_session(workspace):
    at = selected_app()
    at.sidebar.selectbox[0].select("analyst_b").run()
    fresh = AppTest.from_file(str(APP)).run()
    assert not fresh.exception
    assert fresh.sidebar.selectbox[0].value == "analyst_b"
    assert any(
        "Active profile:" in item.value and "analyst_b" in item.value
        for item in fresh.text
    )


def test_generated_review_survives_form_reruns_without_new_call(workspace, monkeypatch):
    job = save_review(workspace)
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return bridge.GenerationOutcome(ok=True, job_id=job)

    monkeypatch.setattr(bridge, "run_generation", generate)
    at = selected_app()
    at.text_area[0].input(
        "An analytics posting with sufficient real responsibilities. " * 3
    ).run()
    next(
        b for b in at.button if b.label == "Generate CV and cover letter"
    ).click().run()
    assert not at.exception
    assert len(calls) == 1
    assert [t.label for t in at.tabs] == [
        "Documents",
        "What changed",
        "Why these changes",
        "Run details",
    ], [e.value for e in at.error]
    at.text_input(key="company").input("Changed form value").run()
    assert not at.exception
    assert len(calls) == 1
    assert any("Prioritise reporting evidence" in t.value for t in at.text)
    assert any("historical-model" in str(t.value) for t in at.table)


def test_profile_switch_clears_review_search_and_posting(workspace):
    job = save_review(workspace)
    at = selected_app()
    at.session_state["active_application"] = job
    at.session_state["search_outcome"] = SimpleNamespace(results=[])
    at.text_area[0].input("Private draft for candidate A").run()
    assert at.tabs, [e.value for e in at.error]
    at.sidebar.selectbox[0].select("analyst_b").run()
    assert not at.exception
    assert at.text_area[0].value == ""
    assert not at.tabs
    assert "search_outcome" not in at.session_state


def test_preview_switch_with_downloads_survives_repeated_reruns(workspace, monkeypatch):
    """Real download widgets must never be assigned values by retain_inputs."""
    from pypdf import PdfWriter

    job = save_review(workspace)
    folder = workspace / "outputs" / "analyst_a" / job
    for name in ("cv.pdf", "cover_letter.pdf"):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=250)
        writer.write(folder / name)
    (folder / "cover_letter.docx").write_bytes(b"synthetic download content")
    monkeypatch.setattr(
        bridge,
        "run_generation",
        lambda *a, **k: pytest.fail("preview called generation"),
    )
    at = selected_app()
    at.session_state["active_application"] = job
    at.run()
    assert not at.exception
    assert len(at.get("download_button")) == 3
    preview = next(s for s in at.selectbox if s.label == "Preview document")
    preview.select("cover_letter.pdf").run()
    assert not at.exception, [e.message for e in at.exception]
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert (
        next(s for s in at.selectbox if s.label == "Preview document").value
        == "cover_letter.pdf"
    )
    next(s for s in at.selectbox if s.label == "Preview document").select(
        "cv.pdf"
    ).run()
    assert not at.exception


def test_retention_does_not_assign_a_search_action_button(workspace):
    def render_actions():
        import streamlit as st
        from ui.app import retain_inputs

        retain_inputs()
        st.button("Use this posting", key="search_use_0")

    at = AppTest.from_function(render_actions).run()
    assert not at.exception
    at.run()
    assert not at.exception, [e.message for e in at.exception]


def test_retention_does_not_write_download_or_component_state(monkeypatch):
    """AppTest omits some client widget states; guard that invariant explicitly."""
    from ui.app import retain_inputs

    class ClientState(dict):
        def __setitem__(self, key, value):
            if key in {
                "review_a_job_dl_letter.docx",
                "review_a_job_letter.pdf",
                "search_use_0",
            }:
                raise AssertionError(
                    f"Attempted assignment to non-editable widget: {key}"
                )
            super().__setitem__(key, value)

    state = ClientState(
        {
            "review_a_job_dl_letter.docx": False,
            "review_a_job_letter.pdf": {"component": "state"},
            "search_use_0": False,
            "preview_document_a_job": "letter.pdf",
            "search_country": "DE",
            "job_description": "Synthetic posting",
        }
    )
    monkeypatch.setattr(st, "session_state", state)
    retain_inputs()
    assert state["preview_document_a_job"] == "letter.pdf"
    assert state["search_country"] == "DE"
    assert state["job_description"] == "Synthetic posting"


def test_handoff_populates_form_without_generation(workspace, monkeypatch):
    monkeypatch.setattr(
        bridge,
        "run_generation",
        lambda *a, **k: pytest.fail("handoff generated documents"),
    )
    at = selected_app()
    at.session_state["pending_handoff"] = {
        "job_description": "Published job description",
        "company": "Northwind",
        "role": "Analyst",
        "work_country": "DE",
        "provenance": {"source": "synthetic", "url": "https://example.test/role"},
    }
    at.run()
    assert not at.exception
    assert at.text_area[0].value == "Published job description"
    assert at.text_input(key="company").value == "Northwind"
    assert at.selectbox(key="work_country").value == "Germany"


def test_review_renders_legacy_explanation_state_without_paid_call(
    workspace, monkeypatch
):
    job = save_review(workspace, explanation=False)
    monkeypatch.setattr(
        "services.tailor_service.tailor_documents",
        lambda **k: pytest.fail("review called model"),
    )
    at = selected_app()
    at.session_state["active_application"] = job
    at.run()
    assert not at.exception
    assert any("No explanation was saved" in item.value for item in at.info)


def test_search_results_survive_reruns_and_handoff_does_not_generate(
    workspace, monkeypatch
):
    from models.job import Job, SearchQuery
    from services.job_match import MatchResult
    from services.job_search import SearchOutcome

    job = Job(
        source="synthetic",
        source_id="job1",
        url="https://example.test/job1",
        title="Reporting analyst",
        company="Northwind",
        description="Published synthetic job description",
    )
    outcome = SearchOutcome(
        query=SearchQuery(), results=[MatchResult(job=job)], jobs_read=1
    )
    searches = []

    def search(*args):
        searches.append(args)
        return outcome

    monkeypatch.setattr(bridge, "search_from_fields", search)
    monkeypatch.setattr(
        bridge,
        "run_generation",
        lambda *a, **k: pytest.fail("search generated documents"),
    )

    def render_search():
        import streamlit as st
        from ui.app import page_find_jobs, get_config

        st.session_state["profile_id"] = "analyst_a"
        page_find_jobs(get_config())

    at = AppTest.from_function(render_search).run()
    next(b for b in at.button if b.label == "Search").click().run()
    assert not at.exception
    assert len(searches) == 1
    at.run()
    assert not at.exception
    assert len(searches) == 1
    assert any(h.value == "Reporting analyst" for h in at.subheader)
    next(b for b in at.button if b.label == "Use this posting").click().run()
    assert not at.exception
    assert at.session_state["pending_handoff"]["role"] == "Reporting analyst"
    assert at.session_state["pending_handoff"]["job_description"] == job.description
