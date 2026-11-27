"""scripts/setup.py venv checks, doctor additions and python floor."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def setup_mod():
    return _load("setup")


def test_floor_is_shared_between_setup_and_doctor(setup_mod, monkeypatch):
    from cli.commands import doctor
    from python_floor import MIN_PYTHON

    assert setup_mod.MIN_PYTHON == MIN_PYTHON == (3, 12)
    monkeypatch.setattr(doctor.sys, "version_info", (3, 11, 9, "final", 0))
    check = doctor.check_python()
    assert check.status == doctor.FAIL and "3.12" in check.fix


def test_arch_aliases(setup_mod):
    assert setup_mod.normalise_arch("AMD64") == "x86_64"
    assert setup_mod.normalise_arch("aarch64") == "arm64"


def _probe(monkeypatch, setup_mod, version, machine):
    monkeypatch.setattr(setup_mod, "probe_interpreter", lambda python: (version, machine))


def test_matching_venv_has_no_problems(setup_mod, monkeypatch, tmp_path):
    _probe(monkeypatch, setup_mod, (3, 12), "arm64")
    assert setup_mod.venv_problems(tmp_path / "python", "arm64", tmp_path) == []


def test_rosetta_venv_on_arm_host_is_reported(setup_mod, monkeypatch, tmp_path):
    _probe(monkeypatch, setup_mod, (3, 12), "x86_64")
    problems = setup_mod.venv_problems(tmp_path / "python", "arm64", tmp_path)
    assert len(problems) == 1
    assert "x86_64" in problems[0] and "arm64" in problems[0]
    assert "Delete" in problems[0] and "automatically" in problems[0]


def test_old_python_venv_is_reported(setup_mod, monkeypatch, tmp_path):
    _probe(monkeypatch, setup_mod, (3, 11), "arm64")
    problems = setup_mod.venv_problems(tmp_path / "python", "arm64", tmp_path)
    assert any("3.11" in p and "3.12" in p for p in problems)


def test_unrunnable_venv_is_reported(setup_mod, monkeypatch, tmp_path):
    monkeypatch.setattr(setup_mod, "probe_interpreter", lambda python: None)
    assert setup_mod.venv_problems(tmp_path / "python", "arm64", tmp_path)


def test_probe_reports_this_interpreter(setup_mod):
    version, machine = setup_mod.probe_interpreter(Path(sys.executable))
    assert version == tuple(sys.version_info[:2])
    assert machine


def test_main_does_not_delete_a_mismatched_venv(setup_mod, monkeypatch, tmp_path):
    folder = tmp_path / ".venv"
    folder.mkdir()
    monkeypatch.setattr(setup_mod, "ROOT", tmp_path)
    monkeypatch.setattr(setup_mod, "host_arch", lambda: "arm64")
    _probe(monkeypatch, setup_mod, (3, 12), "x86_64")
    ran = []
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(SystemExit) as exit_info:
        setup_mod.main()
    assert "x86_64" in str(exit_info.value)
    assert folder.exists() and not ran


# --- doctor: fonts -------------------------------------------------------------------


def _runner(installed):
    def run(command, **kwargs):
        found = command[1] in installed
        return subprocess.CompletedProcess(
            command, 0 if found else 1, f"/x/{command[1]}\n" if found else "", ""
        )
    return run


def test_fonts_check_skipped_without_kpsewhich():
    from cli.commands import doctor
    assert doctor.check_fonts(which=lambda name: None) is None


def test_fonts_ok_when_carlito_present():
    from cli.commands import doctor
    check = doctor.check_fonts(which=lambda n: "kpsewhich", run=_runner({"carlito.sty"}))
    assert check.status == doctor.OK


def test_fonts_warn_when_carlito_missing_lato_present():
    from cli.commands import doctor
    check = doctor.check_fonts(which=lambda n: "kpsewhich", run=_runner({"lato.sty"}))
    assert check.status == doctor.WARN and "Lato" in check.detail


def test_fonts_warn_when_both_missing():
    from cli.commands import doctor
    check = doctor.check_fonts(which=lambda n: "kpsewhich", run=_runner(set()))
    assert check.status == doctor.WARN
