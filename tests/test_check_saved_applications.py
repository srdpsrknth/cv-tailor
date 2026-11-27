"""``cvtailor applications check`` and ``scripts/check_saved_applications.py``.

Offline and synthetic: a temporary store, the synthetic analyst profile, mocked renderers.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from cli.main import main  # noqa: E402
from services import application_check  # noqa: E402
from support import read_json  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "profiles" / "synthetic_analyst.yaml"


def save(store: Path, job: str, content, profile_id: str = "analyst_a") -> Path:
    source = store / "outputs" / profile_id / job / "source"
    source.mkdir(parents=True)
    path = source / "content.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    for profile_id in ("analyst_a", "analyst_b"):
        folder = tmp_path / "profiles" / profile_id
        folder.mkdir(parents=True)
        shutil.copy2(FIXTURE, folder / "profile.yaml")
    monkeypatch.setenv("CVTAILOR_STORE", str(tmp_path))
    monkeypatch.delenv("CVTAILOR_PROFILE_ID", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("the check must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    return tmp_path


def good() -> dict:
    return read_json("content", "valid_content.json")


def bad_skill() -> dict:
    data = good()
    category = next(iter(data["cv"]["skills"]))
    data["cv"]["skills"][category].append("Kubernetes Operators")
    return data


def test_pass_and_fail_are_reported_per_application(store, capsys):
    save(store, "job_good", good())
    save(store, "job_bad", bad_skill())
    save(store, "job_broken", "{not json")
    save(store, "job_other_candidate", bad_skill(), profile_id="analyst_b")
    before = snapshot(store)

    code = main(["--profile-id", "analyst_a", "applications", "check"])
    out = capsys.readouterr().out

    assert code == 1
    assert "PASS  job_good" in out
    assert "FAIL  job_bad" in out and "CV:" in out
    assert "FAIL  job_broken" in out and "Could not read content.json" in out
    assert "job_other_candidate" not in out
    assert "3 checked: 1 passed, 2 failed." in out
    assert snapshot(store) == before  # the store is never modified


def test_all_passing_exits_zero_and_json_is_pure(store, capsys):
    save(store, "job_good", good())
    assert main(["--json", "--profile-id", "analyst_a", "applications", "check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checked"] == 1 and payload["failed"] == 0
    assert payload["applications"][0]["status"] == "PASS"


def test_no_applications_is_not_a_failure(store, capsys):
    assert main(["--profile-id", "analyst_a", "applications", "check"]) == 0
    assert "No saved applications" in capsys.readouterr().out


def test_the_profile_id_is_required_and_unknown_ids_are_reported(store, capsys):
    assert main(["applications", "check"]) != 0
    assert "profile" in capsys.readouterr().err.lower()
    assert main(["--profile-id", "nobody", "applications", "check"]) == 4


def test_the_profile_id_can_come_from_the_environment(store, monkeypatch, capsys):
    save(store, "job_good", good())
    monkeypatch.setenv("CVTAILOR_PROFILE_ID", "analyst_a")
    assert main(["applications", "check"]) == 0


def test_validation_runs_on_copies_so_the_saved_content_is_not_mutated(store):
    data = good()
    data["cv"]["experience"].reverse()
    before = json.dumps(data, sort_keys=True)
    from services.profile_loader import load_profile

    application_check.validate_content(data, load_profile(str(FIXTURE)))
    assert json.dumps(data, sort_keys=True) == before


class FakeLatex:
    created: list = []

    def __init__(self, outputs_dir):
        self.outputs_dir = outputs_dir
        FakeLatex.created.append(outputs_dir)

    def render_cv(self, cv, profile, job_position=None, **kwargs):
        path = Path(self.outputs_dir) / "cv.pdf"
        path.write_bytes(b"%PDF-fake")
        return str(path)


class FakeDocx:
    def __init__(self, outputs_dir, timezone_name=None):
        self.outputs_dir = outputs_dir

    def render_cover_letter(self, cl, profile, job_position=None):
        path = Path(self.outputs_dir) / "cl.pdf"
        path.write_bytes(b"%PDF-fake")
        return str(Path(self.outputs_dir) / "cl.docx"), str(path)


def test_render_reports_pages_in_a_temporary_folder(store, monkeypatch, capsys):
    import renderers

    FakeLatex.created = []
    monkeypatch.setattr(renderers, "create_latex_renderer", lambda outputs_dir: FakeLatex(outputs_dir))
    monkeypatch.setattr(renderers, "create_docx_renderer", FakeDocx)
    monkeypatch.setattr(application_check, "_count_pages",
                        lambda pdf: 2 if pdf.name == "cv.pdf" else 1)
    save(store, "job_good", good())
    before = snapshot(store)

    assert main(["--profile-id", "analyst_a", "applications", "check", "--render"]) == 0
    out = capsys.readouterr().out

    assert "PASS  job_good  [CV 2 page(s), cover letter 1]" in out
    assert len(FakeLatex.created) == 1
    assert not str(FakeLatex.created[0]).startswith(str(store))
    assert not Path(FakeLatex.created[0]).exists()  # the temporary folder is removed
    assert snapshot(store) == before


def test_a_render_error_is_a_failure_with_the_message(store, monkeypatch, capsys):
    import renderers

    def explode(outputs_dir):
        raise RuntimeError("pdflatex is missing")

    monkeypatch.setattr(renderers, "create_latex_renderer", explode)
    save(store, "job_good", good())

    assert main(["--profile-id", "analyst_a", "applications", "check", "--render"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  job_good" in out and "render error: RuntimeError: pdflatex is missing" in out


def load_script():
    spec = importlib.util.spec_from_file_location(
        "check_saved_applications", ROOT / "scripts" / "check_saved_applications.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_is_a_thin_wrapper_over_the_subcommand(store, capsys):
    save(store, "job_good", good())
    save(store, "job_bad", bad_skill())
    script = load_script()
    assert script.run(["--profile-id", "analyst_a", "--store", str(store)]) == 1
    out = capsys.readouterr().out
    assert "PASS  job_good" in out and "FAIL  job_bad" in out


def test_the_script_requires_a_profile_id(store, capsys):
    with pytest.raises(SystemExit) as exit_info:
        load_script().run([])
    assert exit_info.value.code == 2
