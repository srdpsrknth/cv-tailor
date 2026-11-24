import json
from pathlib import Path

import pytest
import yaml

from scripts.capture_candidate_policy import capture


def test_capture_preserves_profile_and_voice_and_never_overwrites(tmp_path):
    directory = tmp_path / "profiles" / "synthetic"
    directory.mkdir(parents=True)
    fixture = Path("tests/fixtures/profiles/synthetic_analyst.yaml")
    data = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    data["rules"] = {"employers": {}, "banned_tools": [], "summary_forbidden_verbs": None,
                     "visa_label": None, "home_countries": [], "local_permit_countries": []}
    profile = directory / "profile.yaml"
    profile.write_text(yaml.safe_dump(data), encoding="utf-8")
    original = profile.read_bytes()
    voice = directory / "writing_style.json"
    voice.write_text('{"version": 1, "tone": "clear"}', encoding="utf-8")
    capture(tmp_path, "synthetic")
    assert profile.read_bytes() == original
    snapshot = json.loads((directory / "candidate_guidance_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["cv"]["shared_prompt"]
    assert snapshot["cover_letter"]["shared_prompt"]
    assert snapshot["layout"]["retry_function"]
    backup = next(directory.glob("before-candidate-isolation-*"))
    assert (backup / "profile.yaml").read_bytes() == original
    assert (backup / "writing_style.json").read_bytes() == voice.read_bytes()
    with pytest.raises(FileExistsError):
        capture(tmp_path, "synthetic")


def test_capture_refuses_implicit_rules(tmp_path):
    directory = tmp_path / "profiles" / "synthetic"
    directory.mkdir(parents=True)
    (directory / "profile.yaml").write_bytes(Path("tests/fixtures/profiles/synthetic_analyst.yaml").read_bytes())
    with pytest.raises(ValueError, match="explicitly declare"):
        capture(tmp_path, "synthetic")
    assert not list(directory.glob("before-candidate-isolation-*"))


def test_failed_publication_can_be_retried(tmp_path, monkeypatch):
    import os
    directory = tmp_path / "profiles" / "synthetic"
    directory.mkdir(parents=True)
    data = yaml.safe_load(Path("tests/fixtures/profiles/synthetic_analyst.yaml").read_text(encoding="utf-8"))
    data["rules"] = {"employers": {}, "banned_tools": [], "summary_forbidden_verbs": None,
                     "visa_label": None, "home_countries": [], "local_permit_countries": []}
    (directory / "profile.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    publish_name = "rename" if os.name == "nt" else "link"
    original_link = getattr(os, publish_name)
    def fail(*args):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(os, publish_name, fail)
    with pytest.raises(OSError, match="publication failure"):
        capture(tmp_path, "synthetic")
    assert not (directory / "candidate_guidance_snapshot.json").exists()
    assert not list(directory.glob(".candidate-guidance-*.tmp"))
    monkeypatch.setattr(os, publish_name, original_link)
    capture(tmp_path, "synthetic")
    assert (directory / "candidate_guidance_snapshot.json").is_file()
