"""pdflatex discovery across per-year TeX Live directories."""
from __future__ import annotations

from pathlib import Path

from renderers import latex_renderer
from renderers.latex_renderer import LaTeXRenderer, discover_texlive_pdflatex


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return str(path)


def test_windows_year_directories_are_found_newest_first(tmp_path):
    root = tmp_path / "texlive"
    old = _touch(root / "2023" / "bin" / "windows" / "pdflatex.exe")
    new = _touch(root / "2025" / "bin" / "win64" / "pdflatex.exe")
    assert discover_texlive_pdflatex([root], []) == [new, old]


def test_unix_year_directories_are_found(tmp_path):
    root = tmp_path / "texlive"
    mac = _touch(root / "2025" / "bin" / "universal-darwin" / "pdflatex")
    linux = _touch(root / "2024" / "bin" / "x86_64-linux" / "pdflatex")
    assert discover_texlive_pdflatex([], [root]) == [mac, linux]


def test_missing_roots_give_nothing(tmp_path):
    assert discover_texlive_pdflatex([tmp_path / "nope"], [tmp_path / "nope2"]) == []


def test_stale_candidate_is_gone(tmp_path):
    renderer = LaTeXRenderer(templates_dir=tmp_path, outputs_dir=tmp_path)
    assert "/usr/local/texlive/bin/pdflatex" not in renderer._pdflatex_candidates


def test_discovered_texlive_is_used_when_nothing_else_is(tmp_path, monkeypatch):
    fake = _touch(tmp_path / "texlive" / "2025" / "bin" / "win64" / "pdflatex.exe")
    monkeypatch.delenv("LATEX_COMPILER", raising=False)
    monkeypatch.setattr(latex_renderer.shutil, "which", lambda name: None)
    renderer = LaTeXRenderer(templates_dir=tmp_path, outputs_dir=tmp_path)
    renderer._pdflatex_candidates = ["pdflatex", fake]
    assert renderer._resolve_pdflatex_path() == fake


def test_latex_compiler_override_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("LATEX_COMPILER", "/custom/pdflatex")
    renderer = LaTeXRenderer(templates_dir=tmp_path, outputs_dir=tmp_path)
    assert renderer._resolve_pdflatex_path() == "/custom/pdflatex"
