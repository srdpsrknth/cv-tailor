"""Tests for the UI's service layer (Phase 6).

Offline, and deliberately framework-free: :mod:`ui.services_bridge` imports no UI
framework, so the logic the interface depends on can be tested without a browser, a
server or Streamlit. That separation is the point — it is what makes the roadmap's
"the UI reuses the same services as the CLI — no duplicated business rules"
criterion checkable rather than aspirational.

Synthetic profiles only; never the owner's real store (ADR 0011).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ui import services_bridge as bridge
from ui.services_bridge import (
    ProfileOption,
    describe_configuration,
    format_cost_breakdown,
    list_applications,
    list_artifacts,
    list_profiles,
    load_profile,
    require_profile_id,
)

FIXTURES = Path(__file__).parent / "fixtures" / "profiles"


class FakeStore:
    """A store whose profiles really exist on disk under ``root``.

    Deliberately delegates to the real ``ProfileStore`` for path layout, so these
    tests exercise the same resolution the application uses rather than a
    hand-written imitation of it. ``present`` names the profiles to copy in.
    """

    def __init__(self, present=("analyst_a",), root="/tmp/store",
                 fixture="synthetic_analyst.yaml"):
        from services.profile_store import ProfileStore

        self.root = Path(root)
        self._real = ProfileStore.at(self.root)
        for profile_id in present:
            destination = self._real.profile_path(profile_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURES / fixture, destination)

    # --- the surface services_bridge actually uses ---
    def iter_profiles(self):
        return self._real.iter_profiles()

    def profile_path(self, profile_id):
        return self._real.profile_path(profile_id)

    def outputs_dir(self, profile_id):
        return self._real.outputs_dir(profile_id)

    def exists(self, profile_id):
        return self._real.exists(profile_id)

    def unknown_message(self, profile_id):
        return self._real.unknown_message(profile_id)

    def load(self, profile_id):
        return self._real.load(profile_id)


class FakeConfig:
    def __init__(self, store, profile_id=None, model="openai/gpt-6-luna",
                 provider="openrouter"):
        self.store = store
        self.profile_id = profile_id
        self.model = model
        self.provider = provider


@pytest.fixture
def store(tmp_path):
    """A real, populated store in a temp directory. Never the owner's (ADR 0011)."""
    return FakeStore(root=str(tmp_path))


@pytest.fixture
def config(store):
    return FakeConfig(store)


# --- profile listing ----------------------------------------------------------------------

def test_list_profiles_reports_each_profile_with_its_name_and_role_count(config):
    options = list_profiles(config)
    assert len(options) == 1
    assert options[0].profile_id == "analyst_a"
    assert options[0].name == "Alex Sample"
    assert options[0].roles == 3
    assert options[0].is_usable is True


def test_a_broken_profile_is_listed_with_its_problem_not_hidden(tmp_path):
    """Silently omitting a broken profile looks identical to having none."""
    store = FakeStore(root=str(tmp_path))
    # Corrupt the copied profile so the loader fails on it.
    store.profile_path("analyst_a").write_text(
        "version: '1.0'\nidentity: {this: is, not: valid}\n", encoding="utf-8")

    options = list_profiles(FakeConfig(store))
    assert len(options) == 1, "a broken profile must still be listed"
    assert options[0].profile_id == "analyst_a"
    assert options[0].is_usable is False
    assert options[0].problem
    assert "unusable" in options[0].label()


def test_profile_option_label_is_readable_when_usable():
    option = ProfileOption(profile_id="analyst_a", name="Alex Sample", roles=3)
    assert "analyst_a" in option.label()
    assert "Alex Sample" in option.label()
    assert "3 roles" in option.label()


def test_profile_option_label_explains_an_unusable_profile():
    option = ProfileOption(profile_id="x", name="", roles=0, problem="ValueError: bad")
    label = option.label()
    assert "unusable" in label and "ValueError" in label


def test_an_empty_store_lists_nothing(tmp_path):
    assert list_profiles(FakeConfig(FakeStore(present=(), root=str(tmp_path)))) == []


# --- fail-closed profile resolution (ADR 0003) ----------------------------------------------

def test_an_explicit_profile_id_wins(config):
    assert require_profile_id(config, "analyst_a") == "analyst_a"


def test_a_configured_profile_id_is_used_when_none_is_given(store):
    config = FakeConfig(store, profile_id="analyst_a")
    assert require_profile_id(config, None) == "analyst_a"


def test_no_profile_anywhere_is_refused(config):
    """Fail closed: never pick 'the only one', even when only one exists."""
    with pytest.raises(Exception) as caught:
        require_profile_id(config, None)
    assert "never picks one" in str(caught.value)


def test_a_malformed_profile_id_is_refused(config):
    with pytest.raises(Exception):
        require_profile_id(config, "../escape")


def test_a_well_formed_but_unknown_profile_id_is_refused(config):
    """Regression: format validation is not existence validation.

    ``validate_profile_id`` only rejects a malformed id; it happily returns a
    well-formed one that names nobody. The bridge must check existence too, or a
    stale id from a saved session would pass here and fail much later — after
    paid generation work.
    """
    from services.profile_store import UnknownProfileError

    with pytest.raises(UnknownProfileError) as caught:
        require_profile_id(config, "does-not-exist")
    assert "does-not-exist" in str(caught.value)


def test_a_blank_profile_id_falls_back_to_the_configured_one(store):
    config = FakeConfig(store, profile_id="analyst_a")
    assert require_profile_id(config, "   ") == "analyst_a"


def test_the_refusal_names_the_available_profiles(config):
    with pytest.raises(Exception) as caught:
        require_profile_id(config, None)
    assert "analyst_a" in str(caught.value)


# --- loading ------------------------------------------------------------------------------

def test_load_profile_returns_a_profile(config):
    profile = load_profile(config, "analyst_a")
    assert profile.identity.full_name == "Alex Sample"


def test_load_profile_rejects_a_malformed_id(config):
    with pytest.raises(Exception):
        load_profile(config, "../etc")


# --- configuration description ------------------------------------------------------------

def test_describe_configuration_reports_facts_only(config):
    described = describe_configuration(config)
    assert described["profile_count"] == 1
    assert described["usable_profiles"] == 1
    assert described["model"] == "openai/gpt-6-luna"
    assert described["provider"] == "openrouter"


def test_describe_configuration_does_not_claim_generation_will_work(config):
    """It reports what is configured, which is not the same as what is accepted."""
    assert "ok" not in describe_configuration(config)


# --- cost display -------------------------------------------------------------------------

class Usage:
    model_name = "openai/gpt-6-luna"
    provider = "openrouter"
    cv_input_tokens = 6400
    cl_input_tokens = 5200
    cv_output_tokens = 1500
    cl_output_tokens = 700
    estimated_cost_usd = 0.0032


def test_format_cost_breakdown_totals_input_and_output():
    lines = " | ".join(format_cost_breakdown(Usage()))
    assert "11,600" in lines   # 6400 + 5200
    assert "2,200" in lines    # 1500 + 700


def test_format_cost_breakdown_reads_the_shared_pricing_module():
    """The old UI kept its own table and it drifted. Sharing the module prevents that."""
    lines = " | ".join(format_cost_breakdown(Usage()))
    assert "openai/gpt-6-luna" in lines
    assert "standard tier" in lines


def test_format_cost_breakdown_reports_an_unpriced_model_honestly():
    class Unpriced(Usage):
        model_name = "some/unlisted-model"

    lines = " | ".join(format_cost_breakdown(Unpriced()))
    assert "not in the verified price table" in lines


def test_format_cost_breakdown_survives_a_missing_usage():
    assert format_cost_breakdown(None) == []


def test_format_cost_breakdown_does_not_raise_on_a_broken_usage():
    """A display helper must never break the page it is describing."""
    class Broken:
        pass

    lines = format_cost_breakdown(Broken())
    assert isinstance(lines, list)


# --- artifacts and applications -----------------------------------------------------------

def test_list_artifacts_returns_nothing_for_a_missing_folder():
    assert list_artifacts(None) == []
    assert list_artifacts(Path("/definitely/not/here")) == []


def test_list_artifacts_reports_name_size_and_type(tmp_path):
    (tmp_path / "cv.pdf").write_bytes(b"x" * 2048)
    (tmp_path / "letter.docx").write_bytes(b"y" * 1024)
    artifacts = {item["kind"]: item for item in list_artifacts(tmp_path)}
    assert artifacts["pdf"]["size_kb"] == 2.0
    assert artifacts["pdf"]["mime"] == "application/pdf"
    assert artifacts["docx"]["mime"].startswith("application/vnd.openxml")


def test_list_artifacts_ignores_unrelated_files(tmp_path):
    (tmp_path / "cv.pdf").write_bytes(b"x")
    (tmp_path / "notes.md").write_text("scratch")
    kinds = {item["kind"] for item in list_artifacts(tmp_path)}
    assert kinds == {"pdf"}


def test_list_applications_returns_nothing_for_a_missing_outputs_dir(tmp_path):
    store = FakeStore(root=str(tmp_path))
    assert list_applications(FakeConfig(store), "analyst_a") == []


def test_list_applications_finds_folders_newest_first(tmp_path):
    import os
    import time

    outputs = tmp_path / "outputs" / "analyst_a"
    for name in ("older_job", "newer_job"):
        folder = outputs / name
        (folder / "source").mkdir(parents=True)
        (folder / "source" / "content.json").write_text("{}", encoding="utf-8")
        time.sleep(0.05)
    store = FakeStore(root=str(tmp_path))
    applications = list_applications(FakeConfig(store), "analyst_a")
    assert [a["job_id"] for a in applications] == ["newer_job", "older_job"]


def test_list_applications_reports_whether_content_is_editable(tmp_path):
    folder = tmp_path / "outputs" / "analyst_a" / "a_job"
    (folder / "source").mkdir(parents=True)
    (folder / "source" / "content.json").write_text("{}", encoding="utf-8")
    bare = tmp_path / "outputs" / "analyst_a" / "no_content_job"
    bare.mkdir(parents=True)
    store = FakeStore(root=str(tmp_path))
    by_id = {a["job_id"]: a for a in list_applications(FakeConfig(store), "analyst_a")}
    assert by_id["a_job"]["has_content"] is True
    assert by_id["no_content_job"]["has_content"] is False


def test_list_applications_respects_the_limit(tmp_path):
    outputs = tmp_path / "outputs" / "analyst_a"
    for index in range(5):
        (outputs / f"job_{index}").mkdir(parents=True)
    store = FakeStore(root=str(tmp_path))
    assert len(list_applications(FakeConfig(store), "analyst_a", limit=2)) == 2


def test_list_applications_rejects_a_malformed_profile_id(tmp_path):
    store = FakeStore(root=str(tmp_path))
    with pytest.raises(Exception):
        list_applications(FakeConfig(store), "../escape")


# --- generation plumbing (no paid call) ----------------------------------------------------

def test_run_generation_refuses_an_empty_job_description(config):
    outcome = bridge.run_generation(config, "analyst_a", "   ")
    assert outcome.ok is False
    assert "Paste the job description" in outcome.error


def test_run_generation_refuses_an_unknown_profile(config):
    outcome = bridge.run_generation(config, "nobody", "A real posting " * 20)
    assert outcome.ok is False
    assert outcome.error


def test_job_folder_is_none_without_a_job_id(config):
    assert bridge.job_folder(config, "analyst_a", None) is None


def test_job_folder_is_none_for_a_malformed_profile_id(config):
    assert bridge.job_folder(config, "../escape", "job") is None


def test_job_folder_carries_the_candidate_segment(config):
    """Two candidates on one posting must never share a folder (ADR 0003)."""
    folder = bridge.job_folder(config, "analyst_a", "some_job")
    assert folder is not None
    assert folder.parent.name == "analyst_a"
    assert folder.name == "some_job"


# --- the bridge owns no UI framework -------------------------------------------------------

def test_the_bridge_imports_no_ui_framework():
    """The separation that makes this logic testable without a browser."""
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    for framework in ("streamlit", "nicegui", "gradio", "flask"):
        assert f"import {framework}" not in source
        assert f"from {framework}" not in source
