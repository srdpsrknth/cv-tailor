"""Actual Streamlit reruns: no silent candidate selection or paid review calls."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_md5
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


def applications_page(at):
    # AppTest.switch_page only accepts file-based pages. This app uses st.Page functions.
    at._page_hash = calc_md5("applications")
    return at.run()


def open_saved_application(at, job):
    applications_page(at)
    at.button(key=f"open_analyst_a_{job}").click().run()
    assert not at.exception
    return at


def choose_section(at, job, section):
    at.radio(key=f"review_analyst_a_{job}_section").set_value(section).run()
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
    folder = workspace / "outputs" / "analyst_a" / job
    (folder / "2026_CV_Alex_cover_letter_specialist.pdf").write_bytes(b"synthetic CV")
    (folder / "2026_cover_letter_Northwind_Analyst.pdf").write_bytes(
        b"synthetic letter"
    )
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return bridge.GenerationOutcome(ok=True, job_id=job)

    monkeypatch.setattr(bridge, "run_generation", generate)
    at = selected_app()
    posting = "An analytics posting with sufficient real responsibilities. " * 3
    at.text_area[0].input(posting).run()
    next(
        b for b in at.button if b.label == "Generate CV and cover letter"
    ).click().run()
    assert not at.exception
    assert len(calls) == 1
    assert at.query_params == {"profile": ["analyst_a"], "application": [job]}
    assert not at.text_area, [e.value for e in at.error]
    assert any(h.value == "Northwind · Reporting analyst" for h in at.header)
    assert [b.proto.label for b in at.get("download_button")] == [
        "Download CV PDF",
        "Download cover letter PDF",
    ]
    applications_page(at)
    assert not at.exception
    assert len(calls) == 1
    choose_section(at, job, "details")
    assert any("Prioritise reporting evidence" in t.value for t in at.text)
    assert any("historical-model" in str(t.value) for t in at.table)
    at._page_hash = calc_md5("generate")
    at.query_params = {}
    at.run()
    assert not at.exception
    assert at.text_area[0].value == posting
    assert len(calls) == 1


@pytest.mark.requires_latex
def test_generation_opens_locally_rendered_application(
    workspace, offline_service, analyst_session, monkeypatch
):
    from pypdf import PdfReader
    from renderers.cv_layout import read_layout_metadata

    monkeypatch.setenv("OUTPUTS_DIR", str(workspace / "outputs"))
    provider = offline_service(analyst_session.texts())
    at = selected_app()
    at.text_area[0].input(analyst_session.job_description_text).run()
    at.text_input(key="company").input("Nordwind Analytics GmbH").run()
    at.text_input(key="role").input("Analytical Engineer").run()
    at.selectbox(key="cv_page_layout").select("Balanced page breaks").run()
    next(b for b in at.button if b.label == "Generate CV and cover letter").click().run(timeout=180)

    assert not at.exception
    assert not at.error
    assert provider.call_count == 2
    job_id, = at.query_params["application"]
    folder = workspace / "outputs" / "analyst_a" / job_id
    assert any("Nordwind Analytics GmbH" in heading.value for heading in at.header)
    cv = next(folder.glob("*_CV_*.pdf"))
    assert len(PdfReader(cv).pages) <= 2
    assert read_layout_metadata(cv)["baseline"]["page_count"] <= 2
    assert len(PdfReader(next(folder.glob("*_cover_letter_*.pdf"))).pages) == 1


def test_save_layout_preview_from_application(workspace, monkeypatch):
    from ui import layout_preview

    job = save_review(workspace)
    folder = workspace / "outputs" / "analyst_a" / job
    (folder / "cv.pdf").write_bytes(b"original")
    content = json.loads((folder / "source/content.json").read_text(encoding="utf-8"))
    snapshot = json.loads((folder / "source/profile_snapshot.json").read_text(encoding="utf-8"))
    report = {
        "page_count": 2, "text_preserved": True, "clipping": False,
        "orphan_headings": False, "blank_tails_mm": [36, 29],
        "source_revision": layout_preview.layout_source_revision(content, snapshot),
    }
    monkeypatch.setattr(layout_preview, "preview_saved_cv_layout", lambda *args: (b"%PDF-1.7\npreview", report))

    def unavailable_viewer(*args, **kwargs):
        raise RuntimeError("Viewer unavailable")

    monkeypatch.setattr(st, "pdf", unavailable_viewer)
    at = open_saved_application(selected_app(), job)
    at.button(key=f"review_analyst_a_{job}_layout_preview_run").click().run()
    assert not list(folder.glob("cv_balanced_*"))
    at.button(key=f"review_analyst_a_{job}_layout_preview_save").click().run()
    assert not at.exception
    assert not at.error
    assert any("PDF viewer is unavailable" in item.value for item in at.info)
    assert next(folder.glob("cv_balanced_*.pdf")).read_bytes() == b"%PDF-1.7\npreview"
    assert (folder / "cv.pdf").read_bytes() == b"original"


def test_profile_switch_clears_review_search_and_posting(workspace):
    job = save_review(workspace, "analyst_a")
    save_review(workspace, "analyst_b")
    at = selected_app()
    at.text_area[0].input("Private draft for candidate A").run()
    open_saved_application(at, job)
    at.session_state["search_outcome"] = SimpleNamespace(results=[])
    at.sidebar.selectbox[0].select("analyst_b").run()
    assert not at.exception
    assert not at.query_params
    assert at.button(key=f"open_analyst_b_{job}")
    assert "search_outcome" not in at.session_state
    assert "job_description" not in at.session_state


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
    at = open_saved_application(selected_app(), job)
    assert not at.exception
    assert len(at.get("download_button")) == 3
    labels = [button.proto.label for button in at.get("download_button")]
    assert labels[:2] == ["Download CV PDF", "Download cover letter PDF"]
    assert not at.get("pdf")
    at.checkbox(key=f"review_analyst_a_{job}_show_pdf").check().run()
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


@pytest.mark.parametrize(("code", "choice"), [("DE", "Germany"), ("CA", "CA")])
def test_handoff_populates_form_without_generation(workspace, monkeypatch, code, choice):
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
        "work_country": code,
        "provenance": {"source": "synthetic", "url": "https://example.test/role"},
    }
    at.run()
    assert not at.exception
    assert at.text_area[0].value == "Published job description"
    assert at.text_input(key="company").value == "Northwind"
    assert at.selectbox(key="work_country").value == choice


def test_review_renders_legacy_explanation_state_without_paid_call(
    workspace, monkeypatch
):
    job = save_review(workspace, explanation=False)
    monkeypatch.setattr(
        "services.tailor_service.tailor_documents",
        lambda **k: pytest.fail("review called model"),
    )
    at = open_saved_application(selected_app(), job)
    assert not at.exception
    choose_section(at, job, "details")
    assert any("No explanation was saved" in item.value for item in at.info)


def test_workspace_url_restores_only_the_selected_candidate(workspace):
    job = save_review(workspace)
    open_saved_application(selected_app(), job)
    fresh = AppTest.from_file(str(APP))
    fresh.query_params = {"profile": ["analyst_a"], "application": [job]}
    applications_page(fresh)
    assert not fresh.exception
    assert any(h.value == "Northwind · Reporting analyst" for h in fresh.header)

    fresh.button(key="back_to_applications").click().run()
    assert not fresh.query_params
    assert fresh.button(key=f"open_analyst_a_{job}")

    fresh.query_params = {"profile": ["analyst_b"], "application": [job]}
    applications_page(fresh)
    assert not fresh.exception
    assert any("different candidate" in message.value for message in fresh.info)
    assert not fresh.radio


def test_workspace_reports_an_unavailable_application(workspace):
    at = selected_app()
    at.query_params = {"profile": ["analyst_a"], "application": ["missing"]}
    applications_page(at)
    assert not at.exception
    assert any("not found" in message.value for message in at.error)
    assert at.button(key="back_to_applications")


def test_failed_attempt_opens_same_workspace_with_available_download(workspace):
    job = save_review(workspace)
    folder = workspace / "outputs" / "analyst_a" / job
    (folder / "source" / "generation_result.json").write_text(
        json.dumps({"status": "failed", "error": "Rendering stopped"}),
        encoding="utf-8",
    )
    (folder / "cv.pdf").write_bytes(b"synthetic CV")
    at = open_saved_application(selected_app(), job)
    assert any("Rendering stopped" in message.value for message in at.warning)
    assert [b.proto.label for b in at.get("download_button")] == ["Download CV PDF"]


def test_legacy_pdf_downloads_use_local_files_after_relocation(workspace):
    job = save_review(workspace)
    folder = workspace / "outputs" / "analyst_a" / job
    (folder / "source" / "generation_result.json").write_text(
        json.dumps(
            {
                "status": "success",
                "cv_path": r"C:\old-store\resume.pdf",
                "cl_pdf_path": "/old-store/motivation.pdf",
            }
        ),
        encoding="utf-8",
    )
    (folder / "resume.pdf").write_bytes(b"synthetic CV")
    (folder / "motivation.pdf").write_bytes(b"synthetic letter")
    at = open_saved_application(selected_app(), job)
    assert [b.proto.label for b in at.get("download_button")] == [
        "Download CV PDF",
        "Download cover letter PDF",
    ]


def test_failed_generation_links_to_saved_attempt(workspace, monkeypatch):
    job = save_review(workspace)
    folder = workspace / "outputs" / "analyst_a" / job
    (folder / "source" / "generation_result.json").write_text(
        json.dumps({"status": "failed", "error": "Rendering stopped"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bridge,
        "run_generation",
        lambda *args, **kwargs: bridge.GenerationOutcome(
            ok=False,
            error="Rendering stopped",
            drafts_saved=True,
            details={"applications": [job]},
        ),
    )
    at = selected_app()
    at.text_area[0].input(
        "An analytics posting with reporting responsibilities. " * 3
    ).run()
    next(
        b for b in at.button if b.label == "Generate CV and cover letter"
    ).click().run()
    assert any("Rendering stopped" in message.value for message in at.error)
    at.button(key=f"failed_analyst_a_{job}").click().run()
    assert not at.exception
    assert at.query_params == {"profile": ["analyst_a"], "application": [job]}
    assert any("Rendering stopped" in message.value for message in at.warning)
    assert any("no saved PDFs" in message.value for message in at.info)


def test_pdf_checks_are_explicit_and_cached_for_same_revision(workspace, monkeypatch):
    job = save_review(workspace)
    folder = workspace / "outputs" / "analyst_a" / job
    (folder / "cv.pdf").write_bytes(b"synthetic CV")
    calls = []
    load = bridge.load_application

    def observe(*args, **kwargs):
        if kwargs.get("include_quality"):
            calls.append(args[2])
        return load(*args, **kwargs)

    monkeypatch.setattr(bridge, "load_application", observe)
    at = open_saved_application(selected_app(), job)
    assert calls == []
    check_key = f"review_analyst_a_{job}_check_pdfs"
    at.button(key=check_key).click().run()
    assert not at.exception
    assert calls == [job]
    assert any("Two local PDF parsers" in message.value for message in at.caption)
    at.run()
    assert calls == [job]
    assert any("Two local PDF parsers" in message.value for message in at.caption)
    (folder / "cv.pdf").write_bytes(b"new revision")
    at.run()
    assert calls == [job]
    assert not any("Two local PDF parsers" in message.value for message in at.caption)


def test_answers_only_works_without_tex_or_provider_key(workspace, monkeypatch):
    monkeypatch.setattr(
        bridge,
        "preflight",
        lambda config: {"key_configured": False, "pdf_engine": False, "models": {}},
    )
    monkeypatch.setattr(
        bridge, "run_generation", lambda *a, **k: pytest.fail("generated documents")
    )
    monkeypatch.setattr(
        "services.provider.build_provider",
        lambda *a, **k: pytest.fail("built a provider"),
    )
    at = selected_app()
    at.text_area[0].input(
        "Build reporting dashboards with retail analysts. " * 10
    ).run()
    at.text_input(key="company").input("Northwind").run()
    next(button for button in at.button if button.label == "Answers only").click().run()
    assert not at.exception
    assert at.query_params["tab"] == ["answers"]
    assert "application" in at.query_params
    assert any("Answers only" in item.value for item in at.caption)
    assert any(item.label == "Application folder" for item in at.expander)
    assert not at.get("download_button")


def test_portal_answers_draft_edit_save_and_reopen(workspace, monkeypatch):
    from services.provider import ProviderResponse

    calls = []
    copied = {}
    # AppTest mocks the browser component registry. Check the text handed to the
    # clipboard control while driving the real Streamlit editor and save actions.
    monkeypatch.setattr(
        "ui.answers.copy_controls", lambda *, key, data: copied.update({key: data})
    )

    class FakeProvider:
        name = "openrouter"

        def generate(self, prompt, *, schema, model, max_tokens):
            payload = json.loads("{" + prompt.split("\n{", 1)[1])
            calls.append(payload)
            return ProviderResponse(
                text=json.dumps(
                    {
                        "answers": [
                            {
                                "question_id": payload["questions"][0]["id"],
                                "text": "I enjoy practical reporting.",
                                "evidence_ids": ["posting"],
                                "missing_facts": [
                                    "What reporting result can you quantify?"
                                ],
                            }
                        ]
                    }
                ),
                input_tokens=100,
                output_tokens=30,
            )

    monkeypatch.setattr(
        "services.provider.build_provider", lambda config: FakeProvider()
    )
    at = selected_app()
    at.text_area[0].input(
        "Build reporting dashboards with retail analysts. " * 10
    ).run()
    next(button for button in at.button if button.label == "Answers only").click().run()
    job = at.query_params["application"][0]
    applications_page(at)
    prefix = f"review_analyst_a_{job}"
    next(widget for widget in at.text_area if "separated by" in widget.label).input(
        "Why this role?\nPlease be specific.\n\nWhat is your salary expectation?"
    ).run()
    at.button(key=f"{prefix}_add_pasted").click().run()
    assert not at.exception
    assert calls == []
    assert (
        next(t for t in at.text_area if t.label == "Question 1").value
        == "Why this role?\nPlease be specific."
    )
    [widget for widget in at.checkbox if widget.label == "Enter this answer myself"][
        1
    ].check().run()
    at.button(key=f"{prefix}_draft_answers").click().run()
    assert not at.exception
    assert not at.error
    assert [row["text"] for row in calls[0]["questions"]] == [
        "Why this role?\nPlease be specific."
    ]
    assert any("What reporting result" in item.value for item in at.warning)
    next(widget for widget in at.text_area if widget.label == "Answer 1").input(
        "My exact words."
    ).run()
    assert any(item["text"] == "My exact words." for item in copied.values())
    choose_section(at, job, "details")
    choose_section(at, job, "answers")
    assert (
        next(widget for widget in at.text_area if widget.label == "Answer 1").value
        == "My exact words."
    )
    at.button(key=f"{prefix}_save_answers").click().run()
    assert not at.exception
    assert any("Answers saved" in item.value for item in at.success)

    fresh = AppTest.from_file(str(APP))
    fresh.query_params = at.query_params
    applications_page(fresh)
    assert not fresh.exception
    assert (
        next(widget for widget in fresh.text_area if widget.label == "Answer 1").value
        == "My exact words."
    )
    assert len(calls) == 1


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
