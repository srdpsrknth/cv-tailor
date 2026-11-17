"""GUI convenience defaults never weaken explicit service profile identity."""

import json
import shutil
from pathlib import Path

import pytest
from config import Config
from ui import services_bridge as bridge


@pytest.fixture
def config(tmp_path):
    for candidate in ("analyst_a", "analyst_b"):
        folder = tmp_path / "profiles" / candidate
        folder.mkdir(parents=True)
        shutil.copy2(
            Path(__file__).parent / "fixtures/profiles/synthetic_analyst.yaml",
            folder / "profile.yaml",
        )
    return Config.from_env(
        load_env_file=False,
        overrides={"project_root": tmp_path, "profile_store_dir": tmp_path},
    )


def test_gui_selects_the_only_available_profile(config):
    assert bridge.initial_gui_profile(config, ["analyst_a"]) == "analyst_a"


def test_gui_restores_last_choice_from_disk_in_a_new_config(config):
    bridge.remember_gui_profile(config, "analyst_b")
    other = Config.from_env(
        load_env_file=False,
        overrides={
            "project_root": config.project_root,
            "profile_store_dir": config.store.root,
        },
    )
    assert bridge.initial_gui_profile(other, ["analyst_a", "analyst_b"]) == "analyst_b"


def test_no_arbitrary_choice_with_multiple_profiles_and_no_memory(config):
    assert bridge.initial_gui_profile(config, ["analyst_a", "analyst_b"]) is None


def test_stale_or_corrupt_memory_does_not_choose_a_different_candidate(config):
    bridge.remember_gui_profile(config, "analyst_b")
    assert bridge.initial_gui_profile(config, ["analyst_a", "analyst_c"]) is None
    path = config.store.root / "preferences" / "gui.json"
    path.write_text("{broken", encoding="utf-8")
    assert bridge.initial_gui_profile(config, ["analyst_a", "analyst_b"]) is None
    assert bridge.initial_gui_profile(config, ["analyst_a"]) == "analyst_a"


def test_remembered_profile_is_validated_before_writing(config):
    from services.profile_store import InvalidProfileIdError

    with pytest.raises(InvalidProfileIdError):
        bridge.remember_gui_profile(config, "../escape")
    with pytest.raises(ValueError):
        bridge.remember_gui_profile(config, "unknown")
    assert not (config.store.root / "preferences").exists()


def test_profile_memory_contains_only_the_id_not_profile_contents(config):
    bridge.remember_gui_profile(config, "analyst_a")
    saved = json.loads((config.store.root / "preferences" / "gui.json").read_text())
    assert saved == {"last_profile_id": "analyst_a"}
