"""Synthetic archive conversion and no-overwrite publication checks."""

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from models.profile import Profile
from scripts import migrate_candidate_guidance as migration
from services.validation import ProfileRules


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    directory = tmp_path / "profiles" / "sample"
    directory.mkdir(parents=True)
    source = Path(__file__).parent / "fixtures/profiles/synthetic_analyst.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["rules"] = {"employers": {}, "banned_tools": [], "summary_forbidden_verbs": None,
                    "visa_label": None, "home_countries": [], "local_permit_countries": []}
    (directory / "profile.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    cv = "generic opening\nsynthetic cv policy\ngeneric ending\n"
    cl = "generic opening\nsynthetic letter policy\ngeneric ending\n"
    monkeypatch.setattr(migration, "CV_SHA256", hashlib.sha256(cv.encode()).hexdigest())
    monkeypatch.setattr(migration, "CL_SHA256", hashlib.sha256(cl.encode()).hexdigest())
    monkeypatch.setattr(migration, "CV_RANGES", ((2, 2),))
    monkeypatch.setattr(migration, "CL_RANGES", ((2, 2),))
    archive = {"version": 1,
               "effective_validation_rules": dataclasses.asdict(ProfileRules.from_profile(Profile.model_validate(raw))),
               "cv": {"shared_prompt": cv}, "cover_letter": {"shared_prompt": cl},
               "layout": {"effective_pinned_project_clause": " Keep synthetic constraint.",
                          "effective_correction_example": "Prior text. Keep synthetic constraint. End."}}
    archive = json.loads(json.dumps(archive))
    (directory / "candidate_guidance_snapshot.json").write_text(json.dumps(archive), encoding="utf-8")
    return tmp_path, directory, archive


def test_check_publication_and_identical_retry(prepared):
    store, directory, archive = prepared
    target = directory / "candidate_guidance.json"
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert migration.migrate(store, "sample", check=True) == "ready"
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == original
    assert migration.migrate(store, "sample") == "installed"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"version": 1, "cv": ["synthetic cv policy"],
                    "cover_letter": ["synthetic letter policy"], "layout": ["Keep synthetic constraint."]}
    assert migration.migrate(store, "sample") == "already installed"
    assert migration.migrate(store, "sample", check=True) == "already installed"
    assert all((directory / name).read_bytes() == contents for name, contents in original.items())


def test_refuses_existing_different_guidance(prepared):
    store, directory, _ = prepared
    target = directory / "candidate_guidance.json"
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        migration.migrate(store, "sample")
    assert target.read_text(encoding="utf-8") == "existing"


@pytest.mark.parametrize("change", ["prompt", "rules", "version", "layout"])
def test_rejects_unrecognized_or_inconsistent_archive(prepared, change):
    store, directory, archive = prepared
    if change == "prompt":
        archive["cv"]["shared_prompt"] += "changed"
    elif change == "rules":
        archive["effective_validation_rules"]["visa_label"] = "inconsistent"
    elif change == "version":
        archive["version"] = 2
    else:
        archive["layout"]["effective_correction_example"] = "different"
    (directory / "candidate_guidance_snapshot.json").write_text(json.dumps(archive), encoding="utf-8")
    with pytest.raises(ValueError):
        migration.migrate(store, "sample", check=True)
    assert not (directory / "candidate_guidance.json").exists()


def test_failed_publication_cleans_temp_and_can_retry(prepared, monkeypatch):
    store, directory, _ = prepared
    function = "rename" if migration.os.name == "nt" else "link"
    original = getattr(migration.os, function)
    def fail(*args):
        raise OSError("synthetic failure")
    monkeypatch.setattr(migration.os, function, fail)
    with pytest.raises(OSError):
        migration.migrate(store, "sample")
    assert not list(directory.glob(".candidate-guidance-*.tmp"))
    monkeypatch.setattr(migration.os, function, original)
    assert migration.migrate(store, "sample") == "installed"


def test_rejects_profile_directory_alias(prepared):
    store, directory, _ = prepared
    alias = directory.parent / "alias"
    try:
        alias.symlink_to(directory, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="alias"):
        migration.migrate(store, "alias", check=True)
