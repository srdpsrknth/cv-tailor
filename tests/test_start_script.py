"""scripts/start.py: PID file, --status and --stop, with all process access mocked."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def start_mod():
    spec = importlib.util.spec_from_file_location("_t_start", ROOT / "scripts" / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cmd(repo, name):
    return f"python -m {name} run {repo}/ui/app.py"


def test_pid_file_round_trip(start_mod, tmp_path):
    start_mod.write_pids(tmp_path, {"backend": 11, "streamlit": 22})
    assert (tmp_path / ".runtime" / "services.json").exists()
    assert start_mod.read_pids(tmp_path) == {"backend": 11, "streamlit": 22}


def test_unreadable_pid_file_reads_as_empty(start_mod, tmp_path):
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime" / "services.json").write_text("not json", encoding="utf-8")
    assert start_mod.read_pids(tmp_path) == {}


def test_is_ours_requires_marker_and_repo_path(start_mod, tmp_path):
    repo = str(tmp_path)
    assert start_mod.is_ours(1, tmp_path, lambda p: _cmd(repo, "streamlit"))
    assert not start_mod.is_ours(1, tmp_path, lambda p: _cmd("/somewhere/else", "streamlit"))
    assert not start_mod.is_ours(1, tmp_path, lambda p: f"vim {repo}/notes.txt")
    assert not start_mod.is_ours(1, tmp_path, lambda p: "")


def test_stop_terminates_only_our_processes(start_mod, tmp_path):
    start_mod.write_pids(tmp_path, {"backend": 11, "streamlit": 22})
    commands = {11: _cmd(str(tmp_path), "uvicorn"), 22: "some unrelated listener on 8501"}
    killed = []
    out = []
    code = start_mod.stop(tmp_path, lambda p: commands.get(p, ""), killed.append, out.append)
    assert code == 0
    assert killed == [11]
    assert not (tmp_path / ".runtime" / "services.json").exists()
    assert any("left alone" in line for line in out)


def test_stop_with_nothing_recorded_does_nothing(start_mod, tmp_path):
    killed = []
    assert start_mod.stop(tmp_path, lambda p: "", killed.append, lambda *_: None) == 0
    assert killed == []


def test_status_reports_running_and_stale(start_mod, tmp_path):
    start_mod.write_pids(tmp_path, {"backend": 11, "streamlit": 22})
    commands = {11: _cmd(str(tmp_path), "uvicorn")}
    out = []
    code = start_mod.status(tmp_path, lambda p: commands.get(p, ""), out.append)
    assert code == 0
    assert "backend: running" in out[0] and "streamlit: not running" in out[1]


def test_status_nonzero_when_nothing_running(start_mod, tmp_path):
    assert start_mod.status(tmp_path, lambda p: "", lambda *_: None) == 1


def test_terminate_uses_taskkill_on_windows(start_mod, monkeypatch):
    monkeypatch.setattr(start_mod.sys, "platform", "win32")
    calls = []
    start_mod.terminate(99, run=lambda cmd, **kw: calls.append(cmd), kill=lambda *a: pytest.fail("os.kill"))
    assert calls == [["taskkill", "/PID", "99", "/T", "/F"]]


def test_terminate_uses_sigterm_on_posix(start_mod, monkeypatch):
    monkeypatch.setattr(start_mod.sys, "platform", "linux")
    sent = []
    start_mod.terminate(99, run=lambda *a, **k: pytest.fail("taskkill"), kill=lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(99, start_mod.signal.SIGTERM)]


def test_missing_dotenv_gives_actionable_message(start_mod, monkeypatch):
    monkeypatch.setitem(sys.modules, "dotenv", None)
    with pytest.raises(SystemExit) as exit_info:
        start_mod.load_environment()
    message = str(exit_info.value)
    assert "setup.py" in message
    assert ".venv/bin/python" in message and ".venv\\Scripts\\python.exe" in message


def test_pid_file_is_json_object(start_mod, tmp_path):
    start_mod.write_pids(tmp_path, {"backend": 1})
    assert isinstance(json.loads((tmp_path / ".runtime" / "services.json").read_text(encoding="utf-8")), dict)
