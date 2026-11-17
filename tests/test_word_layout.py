"""Optional Word pagination checks are isolated, offline and advisory."""

import hashlib
from pathlib import Path
import subprocess

import pytest
from pypdf import PdfWriter


def _source(tmp_path):
    path = tmp_path / "Synthetic Candidate CV.docx"
    path.write_bytes(b"synthetic word bytes")
    return path


def test_optional_word_conversion_is_isolated_and_reports_own_page_limit(
    tmp_path, monkeypatch
):
    from services import word_layout

    path = _source(tmp_path)
    seen = {}
    monkeypatch.setattr(word_layout, "_find_soffice", lambda: "fake-soffice")

    def convert(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        assert any(arg.startswith("-env:UserInstallation=file:") for arg in args)
        out = Path(args[args.index("--outdir") + 1])
        assert not out.is_relative_to(tmp_path)
        assert out.exists()
        seen["out"] = out
        copied_source = Path(args[-1])
        assert copied_source != path
        assert copied_source.read_bytes() == path.read_bytes()
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=612, height=792)
        writer.write(out / (path.stem + ".pdf"))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(word_layout.subprocess, "run", convert)
    before = path.read_bytes()
    result = word_layout.inspect_word_layout(path)
    assert result["page_count"] == 3
    assert result["exceeds_page_limit"] is True
    assert result["engine"] == "LibreOffice"
    assert result["status"] == "checked"
    assert result["artifact_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["warnings"]
    assert path.read_bytes() == before
    assert not seen["out"].exists()
    assert seen["kwargs"]["timeout"] == 60
    assert not seen["kwargs"].get("shell", False)
    assert list(tmp_path.iterdir()) == [path]


def test_missing_office_reports_unchecked_without_process(tmp_path, monkeypatch):
    from services import word_layout

    monkeypatch.setattr(word_layout, "_find_soffice", lambda: None)
    monkeypatch.setattr(
        word_layout.subprocess, "run", lambda *a, **k: pytest.fail("must not launch")
    )
    result = word_layout.inspect_word_layout(_source(tmp_path))
    assert result["page_count"] is None
    assert result["exceeds_page_limit"] is None
    assert result["engine"] is None
    assert result["status"] == "unchecked"
    assert any("unavailable" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    "failure", ["exit", "timeout", "missing_pdf", "bad_pdf", "launch"]
)
def test_conversion_failures_are_advisory_and_temporary_files_removed(
    tmp_path, monkeypatch, failure
):
    from services import word_layout

    path = _source(tmp_path)
    monkeypatch.setattr(word_layout, "_find_soffice", lambda: "fake-soffice")
    seen = []

    def convert(args, **kwargs):
        out = Path(args[args.index("--outdir") + 1])
        seen.append(out)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 60, output="private text")
        if failure == "launch":
            raise OSError("private path")
        if failure == "bad_pdf":
            (out / (path.stem + ".pdf")).write_bytes(b"bad pdf")
        return subprocess.CompletedProcess(args, 1 if failure == "exit" else 0)

    monkeypatch.setattr(word_layout.subprocess, "run", convert)
    result = word_layout.inspect_word_layout(path)
    assert result["page_count"] is None
    assert result["exceeds_page_limit"] is None
    assert result["status"] == "error"
    assert result["warnings"]
    assert "private" not in str(result)
    assert all(not out.exists() for out in seen)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", ["missing", "unsupported"])
def test_unreadable_or_unsupported_source_does_not_launch(tmp_path, monkeypatch, kind):
    from services import word_layout

    path = tmp_path / ("missing.docx" if kind == "missing" else "other.pdf")
    if kind == "unsupported":
        path.write_bytes(b"pdf")
    monkeypatch.setattr(
        word_layout.subprocess, "run", lambda *a, **k: pytest.fail("must not launch")
    )
    result = word_layout.inspect_word_layout(path)
    assert result["page_count"] is None
    assert result["warnings"]


def test_finds_soffice_on_path_first(monkeypatch):
    from services import word_layout

    monkeypatch.setattr(word_layout.shutil, "which", lambda name: "/tools/soffice")
    assert word_layout._find_soffice() == "/tools/soffice"


def test_finds_standard_windows_office_path(monkeypatch):
    from services import word_layout

    monkeypatch.setattr(word_layout.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", "C:/SyntheticPrograms")
    expected = Path("C:/SyntheticPrograms/LibreOffice/program/soffice.exe")
    monkeypatch.setattr(Path, "is_file", lambda self: self == expected)
    assert word_layout._find_soffice() == str(expected)
