"""Synthetic tests for the inactive candidate guidance reader."""

import json
import shutil
from pathlib import Path

import pytest

from config import Config
from services.candidate_guidance import CandidateGuidance, load_candidate_guidance
from services.profile_store import InvalidProfileIdError, ProfileStore


@pytest.fixture
def setup_store(tmp_path):
    store = ProfileStore.at(tmp_path)
    source = Path(__file__).parent / "fixtures/profiles/synthetic_analyst.yaml"
    for candidate in ("one", "two"):
        path = store.profile_path(candidate)
        path.parent.mkdir(parents=True)
        shutil.copy2(source, path)
    config = Config.from_env(load_env_file=False, overrides={"profile_store_dir": store.root})
    return store, config


def write_guidance(store, candidate, value):
    path = store.profile_path(candidate).with_name("candidate_guidance.json")
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_missing_and_empty_guidance_is_neutral(setup_store):
    store, config = setup_store
    assert load_candidate_guidance(config, "one") == CandidateGuidance()
    write_guidance(store, "one", {"version": 1})
    assert load_candidate_guidance(config, "one") == CandidateGuidance()


def test_guidance_is_scoped_to_selected_profile_and_sections(setup_store):
    store, config = setup_store
    write_guidance(store, "one", {
        "version": 1, "cv": ["  CV instruction  "],
        "cover_letter": ["Letter instruction"], "layout": ["Retry instruction"],
    })
    assert load_candidate_guidance(config, "one") == CandidateGuidance(
        cv=("CV instruction",), cover_letter=("Letter instruction",), layout=("Retry instruction",)
    )
    assert load_candidate_guidance(config, "two") == CandidateGuidance()


@pytest.mark.parametrize("payload", [
    [], {}, {"version": True}, {"version": 2}, {"version": 1, "cv": "text"},
    {"version": 1, "layout": [""]}, {"version": 1, "cv": ["x" * 2001]},
    {"version": 1, "cover_letter": ["x"] * 21}, {"version": 1, "other": []},
])
def test_invalid_guidance_fails_closed(setup_store, payload):
    store, config = setup_store
    write_guidance(store, "one", payload)
    with pytest.raises(ValueError, match="candidate_guidance.json"):
        load_candidate_guidance(config, "one")


def test_invalid_json_and_oversize_file_fail_closed(setup_store):
    store, config = setup_store
    path = write_guidance(store, "one", {"version": 1})
    for contents in ("{", " " * 65537):
        path.write_text(contents, encoding="utf-8")
        with pytest.raises(ValueError, match="candidate_guidance.json"):
            load_candidate_guidance(config, "one")


def test_profile_id_fails_closed_and_loose_profile_does_not_inherit(setup_store):
    store, config = setup_store
    write_guidance(store, "one", {"version": 1, "cv": ["private instruction"]})
    with pytest.raises(InvalidProfileIdError):
        load_candidate_guidance(config, None)
    with pytest.raises(ValueError, match="known profile"):
        load_candidate_guidance(config, "missing")
    loose = Config.from_env(load_env_file=False, overrides={
        "profile_store_dir": store.root, "profile_path": store.profile_path("one"),
    })
    assert load_candidate_guidance(loose, "one") == CandidateGuidance()


def test_guidance_file_symlink_is_rejected(setup_store):
    store, config = setup_store
    other = write_guidance(store, "two", {"version": 1, "cv": ["other profile"]})
    path = store.profile_path("one").with_name("candidate_guidance.json")
    try:
        path.symlink_to(other)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="candidate_guidance.json"):
        load_candidate_guidance(config, "one")


def test_profile_directory_symlink_is_rejected(tmp_path):
    store = ProfileStore.at(tmp_path)
    other = store.profile_path("two")
    other.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).parent / "fixtures/profiles/synthetic_analyst.yaml", other)
    write_guidance(store, "two", {"version": 1, "cv": ["other profile"]})
    try:
        (other.parent.parent / "one").symlink_to(other.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    config = Config.from_env(load_env_file=False, overrides={"profile_store_dir": store.root})
    with pytest.raises(ValueError, match="candidate_guidance.json"):
        load_candidate_guidance(config, "one")


@pytest.mark.parametrize("changed_section", ["cv", "cover_letter", "layout"])
def test_generation_scopes_each_guidance_section_and_invalidates_cache(
    changed_section, isolated_service, offline_service, stub_renderers,
    analyst_profile, analyst_session,
):
    from services.tailor_service import tailor_documents

    store = ProfileStore.at(isolated_service)
    markers = {
        "cv": "Synthetic draft guidance marker",
        "cover_letter": "Synthetic letter guidance marker",
        "layout": "Synthetic shortening guidance marker",
    }
    guidance = {"version": 1, **{section: [marker] for section, marker in markers.items()}}
    write_guidance(store, "analyst_a", guidance)
    offline = offline_service([
        analyst_session.step_text(step)
        for step in ("cv_draft", "cover_letter", "cv_layout_retry")
    ] * 2)
    stub_renderers([3, 2, 3, 2, 2])

    def generate():
        return tailor_documents(analyst_session.job_description_text, analyst_profile)

    assert generate().cache_hit is False
    for section, prompt in zip(markers, offline.prompts, strict=True):
        assert {key for key, marker in markers.items() if marker in prompt} == {section}

    updated = "Updated synthetic guidance marker"
    guidance[changed_section] = [updated]
    write_guidance(store, "analyst_a", guidance)
    assert generate().cache_hit is False
    assert offline.call_count == 6
    assert updated in offline.prompts[3 + list(markers).index(changed_section)]
    assert generate().cache_hit is True
    assert offline.call_count == 6


def test_archived_clauses_already_in_generation_do_not_change_prompts(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    from models.profile import EmployerRules, ProfileRules as DeclaredRules
    from services.prompts import PROMPT_CL_PATH, PROMPT_CV_PATH, pinned_project_clause
    from services.tailor_service import tailor_documents
    from services.validation import ProfileRules

    employer = analyst_profile.experience[0].company.casefold()
    analyst_profile.rules = DeclaredRules(employers={employer: EmployerRules(project_count=1)})
    offline = offline_service([
        analyst_session.step_text(step)
        for step in ("cv_draft", "cover_letter", "cv_layout_retry")
    ] * 2)
    stub_renderers([3, 2, 3, 2])
    posting = analyst_session.job_description_text
    tailor_documents(posting, analyst_profile, use_cache=False)

    layout = pinned_project_clause(ProfileRules.from_profile(analyst_profile)).strip()
    assert layout
    write_guidance(ProfileStore.at(isolated_service), "analyst_a", {
        "version": 1,
        "cv": [PROMPT_CV_PATH.read_text(encoding="utf-8").splitlines()[0]],
        "cover_letter": [PROMPT_CL_PATH.read_text(encoding="utf-8").splitlines()[0]],
        "layout": [layout],
    })
    tailor_documents(posting, analyst_profile, use_cache=False)
    assert offline.call_count == 6
    assert offline.prompts[:3] == offline.prompts[3:]


# --- per-candidate acronyms -----------------------------------------------------------

def test_acronyms_are_loaded_trimmed_deduplicated_and_scoped(setup_store):
    store, config = setup_store
    write_guidance(store, "one", {"version": 1, "acronyms": [" RWE ", "HEOR", "RWE"]})
    assert load_candidate_guidance(config, "one").acronyms == ("RWE", "HEOR")
    assert load_candidate_guidance(config, "two").acronyms == ()


@pytest.mark.parametrize("acronyms", [
    "RWE", [""], [" "], ["two words"], [1], ["x" * 33], ["A"] * 101,
])
def test_invalid_acronyms_fail_closed(setup_store, acronyms):
    store, config = setup_store
    write_guidance(store, "one", {"version": 1, "acronyms": acronyms})
    with pytest.raises(ValueError, match="candidate_guidance.json"):
        load_candidate_guidance(config, "one")


def test_extra_acronyms_reach_the_skill_heading_without_leaking():
    from utils.text import format_skill_category

    assert format_skill_category("rwe and heor") == "Rwe And Heor"
    assert format_skill_category("rwe and heor", ["RWE", "heor"]) == "RWE And HEOR"
    assert format_skill_category("rwe/heor, rwe", ("RWE", "HEOR")) == "RWE/HEOR, RWE"
    # Nothing was remembered from the call above (no global mutable state).
    assert format_skill_category("rwe and heor") == "Rwe And Heor"


def test_each_renderer_uses_only_its_own_candidates_acronyms(analyst_profile, tmp_path):
    from docx import Document

    from models.tailored_output import TailoredCV
    from renderers import create_latex_renderer
    from renderers.upload_cv import render_upload_cv
    from support import read_json

    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    cv = cv.model_copy(update={"skills": {"rwe studies": ["SQL"]}})
    for name, extra, expected in (("one", ("RWE",), "RWE Studies"), ("two", (), "Rwe Studies")):
        renderer = create_latex_renderer(outputs_dir=str(tmp_path / name), extra_acronyms=extra)
        data = renderer._prepare_template_data(cv, analyst_profile)
        assert list(data["skills"]) == [expected]
        _, fields = renderer._extraction_contract(cv, analyst_profile)
        assert fields["Skill category rwe studies"] == expected
        paths = render_upload_cv(cv, analyst_profile, tmp_path / f"up-{name}", extra_acronyms=extra)
        words = [p.text for p in Document(paths["cv_upload_docx_path"]).paragraphs]
        assert f"{expected}: SQL" in words


def test_acronym_loader_is_empty_for_a_profile_no_longer_in_the_store(setup_store):
    from services.candidate_guidance import load_candidate_acronyms

    store, config = setup_store
    write_guidance(store, "one", {"version": 1, "acronyms": ["RWE"]})
    assert load_candidate_acronyms(config, "one") == ("RWE",)
    assert load_candidate_acronyms(config, "gone") == ()
