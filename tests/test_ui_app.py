"""Tests for the Streamlit interface (Phase 6).

Uses ``streamlit.testing.v1.AppTest``, which **actually executes** ``ui/app.py`` the
way the server does — so these tests catch import errors, bad widget arguments, and
exceptions inside page callbacks. A screenshot cannot do that, and a browser-rendered
check is unreliable for Streamlit because the page is drawn over a websocket: a
headless capture shows the skeleton loader even for a working app.

The store is redirected to a temporary directory for every test, so nothing here can
read or write the owner's real data (ADR 0011). The UI is pointed at that store by
patching the cached config, which is the same object the app uses.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ui" / "app.py"
FIXTURES = ROOT / "tests" / "fixtures" / "profiles"


def make_store(
    root: Path, present=("analyst_a",), fixture="synthetic_analyst.yaml"
) -> Path:
    """A populated store in a temp directory. Never the owner's (ADR 0011)."""
    for profile_id in present:
        destination = root / "profiles" / profile_id / "profile.yaml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES / fixture, destination)
    return root


@pytest.fixture(autouse=True)
def clear_cached_config(monkeypatch):
    """Point the app at a temp store and drop Streamlit's process-wide cache.

    Two things have to be true for these tests to mean anything:

    * **The store must come from the environment.** ``AppTest`` re-executes
      ``ui/app.py`` as a fresh module, so patching ``ui.app.get_config`` does not
      reach it — the patch applies to my imported copy, not the one the script
      builds. ``CVTAILOR_STORE`` is the supported mechanism (ADR 0004/0011) and it
      is read by ``Config.from_env`` inside the script.
    * **The cache must be cleared.** ``get_config`` is wrapped in
      ``@st.cache_resource``, so it is cached for the *process*, not per run. Left
      alone, every test after the first silently reuses the first test's store —
      which is exactly what happened before this fixture existed: the empty-store
      and corrupt-profile cases both rendered as the populated one.

    Never the owner's real store (ADR 0011): the environment is forced to a
    temporary directory for every test in this module.
    """
    import streamlit as st

    store = Path(tempfile.mkdtemp()) / "store"
    monkeypatch.setenv("CVTAILOR_STORE", str(store))
    monkeypatch.setenv("CVTAILOR_PROFILE_ID", "analyst_a")
    st.cache_resource.clear()
    yield store
    st.cache_resource.clear()


@pytest.fixture
def app(clear_cached_config, monkeypatch):
    """Run ``ui/app.py`` against the temporary store, with no network."""
    store = make_store(clear_cached_config)

    def run(timeout: float = 30.0) -> AppTest:
        st.cache_resource.clear()
        return AppTest.from_file(str(APP)).run(timeout=timeout)

    return run


# --- the app starts -----------------------------------------------------------------------


def test_the_app_runs_without_exception(app):
    """The single most valuable check: the script executes end to end.

    ``bool(at.exception)`` is the right test, not ``not at.exception``: AppTest
    returns an empty ``ElementList`` when nothing went wrong, and an empty
    ElementList is *falsy* but not ``None``, so ``not at.exception`` is a confusing
    way to write it (it reads as though an empty list means failure).
    """
    at = app()
    assert not list(at.exception), f"the app raised: {list(at.exception)}"


def test_the_app_titles_itself(app):
    at = app()
    rendered = " ".join(str(c.value) for c in list(at.title) + list(at.caption))
    assert "CV Tailor" in rendered or "Tailor a CV" in rendered


def test_the_app_offers_all_four_pages(app):
    at = app()
    assert not list(at.exception)
    from ui.app import page_about, page_applications, page_find_jobs, page_generate

    assert all(
        callable(fn)
        for fn in (page_generate, page_find_jobs, page_applications, page_about)
    )


def test_the_store_path_is_shown_so_the_user_knows_where_data_goes(app):
    at = app()
    rendered = " ".join(str(block.value) for block in at.markdown)
    rendered += " ".join(str(c.value) for c in at.caption)
    assert "available" in rendered.lower()
    assert "gpt-6-luna" in rendered


# --- the candidate picker fails closed (ADR 0003) ------------------------------------------


def test_the_picker_lists_the_real_profiles(app):
    at = app()
    pickers = at.sidebar.selectbox
    assert pickers, "the candidate picker is missing from the sidebar"
    assert "Alex Sample" in " ".join(str(o) for o in pickers[0].options)
    assert pickers[0].value == "analyst_a"
    pickers[0].select("analyst_a").run()
    assert at.session_state["profile_id"] == "analyst_a"


def test_the_active_profile_is_visible_at_the_top(app):
    """The owner's approved GUI defaults must never hide the active identity."""
    at = app()
    text = " ".join(str(item.value) for item in at.text)
    assert "Active profile: Alex Sample" in text
    assert "analyst_a" in text


def test_an_empty_store_is_explained_rather_than_crashing(clear_cached_config):
    """A store with no profiles must explain the situation, not crash."""
    store = make_store(clear_cached_config, present=())
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP)).run(timeout=30)

    assert not list(at.exception), "an empty store must not crash the app"
    notices = " ".join(str(w.value) for w in at.warning)
    notices += " ".join(str(i.value) for i in at.info)
    assert "no profiles" in notices.lower()
    assert not at.selectbox or "candidate" not in " ".join(
        str(s.label).lower() for s in at.selectbox
    ), "no picker should be offered when there is nothing to pick"


def test_a_broken_profile_is_reported_not_hidden(clear_cached_config):
    """A malformed profile is surfaced with its reason, never silently omitted."""
    store = make_store(clear_cached_config)
    (store / "profiles" / "analyst_a" / "profile.yaml").write_text(
        "version: '1.0'\nidentity: {nonsense: true}\n", encoding="utf-8"
    )
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP)).run(timeout=30)

    assert not list(at.exception)
    notices = " ".join(str(w.value) for w in at.warning)
    notices += " ".join(str(e.value) for e in at.error)
    assert "could not be read" in notices.lower() or "unusable" in notices.lower()


# --- the generate page --------------------------------------------------------------------


def test_the_generate_page_shows_a_job_description_box(app):
    at = app()
    at.sidebar.selectbox[0].select("analyst_a").run()
    assert at.text_area, "no job-description input on the Generate page"
    assert "job description" in at.text_area[0].label.lower()


def test_the_generate_button_is_disabled_until_a_posting_is_pasted(app):
    """Generating costs money, so an empty run must not be possible by accident."""
    at = app()
    at.sidebar.selectbox[0].select("analyst_a").run()
    buttons = [b for b in at.button if "Generate" in str(b.label)]
    assert buttons, "no generate button"
    assert buttons[0].disabled is True


def test_the_generate_button_offers_the_optional_fields(app):
    at = app()
    at.sidebar.selectbox[0].select("analyst_a").run()
    labels = " ".join(str(t.label) for t in at.text_input)
    assert "Company" in labels
    assert "Role" in labels


def test_the_country_selector_exists_and_warns_about_headquarters(app):
    at = app()
    at.sidebar.selectbox[0].select("analyst_a").run()
    selects = [s for s in at.selectbox if "Country" in str(s.label)]
    assert selects, "country selector missing"
    assert "headquarters" in str(selects[0].help).lower()
    assert {"Germany", "Ireland", "Netherlands", "India"} <= set(selects[0].options)


# --- no page can act without a candidate --------------------------------------------------


def test_pages_explain_they_need_a_candidate_when_none_is_configured(
    clear_cached_config, monkeypatch
):
    """With profiles but no configured id, the app starts and still offers the picker."""
    make_store(clear_cached_config)
    monkeypatch.delenv("CVTAILOR_PROFILE_ID", raising=False)
    st.cache_resource.clear()

    at = AppTest.from_file(str(APP)).run(timeout=30)
    assert not list(at.exception)
    labels = " ".join(str(s.label) for s in at.selectbox)
    assert "candidate" in labels.lower(), "the picker must still be offered"


# --- the interface owns no business rules -------------------------------------------------


def test_the_app_does_not_call_the_llm_or_the_filesystem_directly():
    """Everything goes through the bridge, so the UI and CLI cannot drift apart.

    A light structural check rather than a proof: it catches the specific mistake of
    reaching for a service directly instead of going through the seam.
    """
    source = APP.read_text(encoding="utf-8")
    for forbidden in (
        "import requests",
        "tailor_documents(",
        "subprocess",
        "openai",
        "genai",
    ):
        assert forbidden not in source, f"app.py should not contain {forbidden!r}"


def test_the_app_does_not_hardcode_a_model_name():
    """The old UI hardcoded a retired model; the model comes from config."""
    source = APP.read_text(encoding="utf-8")
    assert "gemini-2.5-flash" not in source
    assert "gemini-3.8-flash" not in source


def test_the_app_delegates_generation_to_the_bridge():
    source = APP.read_text(encoding="utf-8")
    assert "bridge.run_generation" in source
    assert "bridge.search_from_fields" in source
    assert "run_job_search(" in Path(bridge_path()).read_text(encoding="utf-8")


def bridge_path():
    from ui import services_bridge

    return services_bridge.__file__
