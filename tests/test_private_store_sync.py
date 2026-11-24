"""Exercise saved applications under synthetic, file-by-file sync conditions."""

from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from config import Config
from services.application_store import ApplicationStore, write_json
from services.artifact_provenance import record_artifact_provenance
from support import fixture_path, job_description, make_blank_pdf, read_json
from ui import services_bridge as bridge


PROFILE_ID = "analyst_a"
CV_NAME = "cv.pdf"
LETTER_NAME = "cover_letter.pdf"


def _hashes(root):
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def stores(tmp_path, repo_root):
    return tuple(
        Config.from_env(
            load_env_file=False,
            overrides={
                "project_root": repo_root,
                "profile_store_dir": tmp_path / name,
                "profile_id": PROFILE_ID,
            },
        )
        for name in ("windows-store", "mac store")
    )


def _save_application(config, job_id, original_directory):
    profile_path = config.store.profile_path(PROFILE_ID)
    if not profile_path.exists():
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture_path("profiles", "synthetic_analyst.yaml"), profile_path)
    snapshot = config.load_profile().model_dump(mode="json")
    content = read_json("content", "valid_content.json")

    application = ApplicationStore(config.store.root / "outputs", job_id, PROFILE_ID)
    application.create(snapshot, job_description("nordwind_analytics_engineer"))
    application.save_content(content)
    make_blank_pdf(application.job_folder / CV_NAME, pages=2)
    make_blank_pdf(application.job_folder / LETTER_NAME, pages=1)
    _save_manifest(config, application, original_directory, content, snapshot)
    return application


def _save_manifest(config, application, original_directory, content, snapshot):
    application.save_manifest(
        {
            "status": "success",
            "cv_path": original_directory + CV_NAME,
            "cl_pdf_path": original_directory + LETTER_NAME,
            "artifact_provenance": record_artifact_provenance(
                config.project_root,
                content,
                [
                    (application.job_folder / CV_NAME, "cv"),
                    (application.job_folder / LETTER_NAME, "cover_letter"),
                ],
                profile_snapshot=snapshot,
            ),
        },
        page_history=[2],
    )


def test_store_round_trip_uses_local_artifacts_with_legacy_paths(stores):
    windows, mac = stores
    for origin, destination, job_id, original_directory in (
        (windows, mac, "from_windows", "Z:\\Old Store\\from_windows\\"),
        (mac, windows, "from_mac", "/Volumes/Old Store/from_mac/"),
    ):
        application = _save_application(origin, job_id, original_directory)
        for tree in ("profiles", "outputs"):
            shutil.copytree(
                origin.store.root / tree, destination.store.root / tree, dirs_exist_ok=True
            )
        assert _hashes(origin.store.root) == _hashes(destination.store.root)

        detail = bridge.load_application(destination, PROFILE_ID, job_id)
        assert Path(detail["path"]) == destination.store.outputs_dir(PROFILE_ID) / job_id
        assert detail["snapshot"]["identity"]["tagline"] == (
            destination.load_profile().identity.tagline
        )
        assert bridge.saved_posting(destination, PROFILE_ID, job_id) == job_description(
            "nordwind_analytics_engineer"
        )
        assert detail["artifact_freshness"][CV_NAME]["status"] == "current"
        assert detail["artifact_freshness"][LETTER_NAME]["status"] == "current"
        for name in (CV_NAME, LETTER_NAME):
            assert bridge.read_artifact(destination, PROFILE_ID, job_id, name) == (
                application.job_folder / name
            ).read_bytes()
        if job_id == "from_windows":
            profile_path = mac.store.profile_path(PROFILE_ID)
            profile_path.write_text(
                profile_path.read_text(encoding="utf-8").replace(
                    "Synthetic Fixture Profile", "Edited on the second peer"
                ),
                encoding="utf-8",
            )

    assert windows.load_profile().identity.tagline.endswith("Edited on the second peer")
    original = bridge.load_application(windows, PROFILE_ID, "from_windows")
    assert original["snapshot"]["identity"]["tagline"].endswith("Synthetic Fixture Profile")


def test_partial_replica_keeps_received_download_during_mixed_revision(stores):
    windows, mac = stores
    original_directory = "Z:\\Old Store\\"
    application = _save_application(windows, "partial", original_directory)
    remote_folder = mac.store.outputs_dir(PROFILE_ID) / application.job_id
    shutil.copytree(application.source_folder, remote_folder / "source")
    shutil.copyfile(application.job_folder / CV_NAME, remote_folder / CV_NAME)

    before = _hashes(remote_folder)
    detail = bridge.load_application(mac, PROFILE_ID, application.job_id)
    assert {item["name"] for item in detail["artifacts"]} == {CV_NAME}
    with pytest.raises(ValueError):
        bridge.read_artifact(mac, PROFILE_ID, application.job_id, LETTER_NAME)
    assert _hashes(remote_folder) == before

    content = detail["content"]
    content["cv"]["summary"] = ["A newer revision reached this device first."]
    application.save_content(content)
    shutil.copyfile(
        application.source_folder / "content.json", remote_folder / "source" / "content.json"
    )
    detail = bridge.load_application(mac, PROFILE_ID, application.job_id)
    assert detail["artifact_freshness"][CV_NAME]["status"] == "stale"
    assert bridge.read_artifact(mac, PROFILE_ID, application.job_id, CV_NAME) == (
        application.job_folder / CV_NAME
    ).read_bytes()

    _save_manifest(windows, application, original_directory, content, detail["snapshot"])
    shutil.copytree(application.job_folder, remote_folder, dirs_exist_ok=True)
    assert _hashes(remote_folder) == _hashes(application.job_folder)
    detail = bridge.load_application(mac, PROFILE_ID, application.job_id)
    assert detail["content"] == content
    assert detail["artifact_freshness"][CV_NAME]["status"] == "current"
    assert detail["artifact_freshness"][LETTER_NAME]["status"] == "current"


def test_conflict_copy_survives_hash_verified_restore(stores, tmp_path):
    windows, mac = stores
    application = _save_application(windows, "conflict", "Z:\\Old Store\\")
    backup = tmp_path / "offline-backup"
    shutil.copytree(application.job_folder, backup)
    shutil.copytree(windows.store.root, mac.store.root)
    remote_folder = mac.store.outputs_dir(PROFILE_ID) / application.job_id
    content_file = remote_folder / "source" / "content.json"
    conflict = content_file.with_name("content.sync-conflict-20261124-163000-TESTDEV.json")

    local_edit = read_json("content", "valid_content.json")
    remote_edit = read_json("content", "valid_content.json")
    local_edit["cv"]["summary"] = ["Edited on the first peer."]
    remote_edit["cv"]["summary"] = ["Edited separately on the second peer."]
    write_json(content_file, local_edit)
    write_json(conflict, remote_edit)
    before = _hashes(remote_folder)
    detail = bridge.load_application(mac, PROFILE_ID, application.job_id)
    assert detail["content"] == local_edit
    assert detail["artifact_freshness"][CV_NAME]["status"] == "stale"
    assert _hashes(remote_folder) == before

    both_edits = tmp_path / "conflicting-edits"
    both_edits.mkdir()
    for path in (content_file, conflict):
        shutil.copyfile(path, both_edits / path.name)
    shutil.copyfile(backup / "source" / content_file.name, content_file)

    detail = bridge.load_application(mac, PROFILE_ID, application.job_id)
    assert detail["artifact_freshness"][CV_NAME]["status"] == "current"
    after = _hashes(remote_folder)
    conflict_relative = f"source/{conflict.name}"
    assert after == _hashes(backup) | {conflict_relative: before[conflict_relative]}
    assert _hashes(both_edits) == {
        path.name: before[f"source/{path.name}"] for path in (content_file, conflict)
    }
