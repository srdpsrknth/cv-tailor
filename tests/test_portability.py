"""Cross-platform portability guards.

These tests exist because the project is developed on Windows and *used* on macOS.
A path list that only covers Windows passes every test on the development machine
and fails on the owner's Mac, which is the worst possible time to find out.

Nothing here executes a real compiler; the tests only assert which candidates are
searched and that the override is honoured.
"""
import sys

import pytest

from renderers.latex_renderer import LaTeXRenderer


def _candidates(tmp_path) -> list:
    return LaTeXRenderer(outputs_dir=str(tmp_path / "outputs"))._pdflatex_candidates


# --- the override wins everywhere --------------------------------------------------------

def test_compiler_override_is_used(tmp_path, monkeypatch):
    """LATEX_COMPILER is the documented escape hatch and must work on every OS."""
    compiler = tmp_path / "custom-tex" / "pdflatex"
    compiler.parent.mkdir()
    compiler.touch()
    monkeypatch.setenv("LATEX_COMPILER", str(compiler))
    assert LaTeXRenderer(outputs_dir=str(tmp_path / "outputs"))._resolve_pdflatex_path() == str(compiler)


def test_compiler_override_wins_over_any_installed_compiler(tmp_path, monkeypatch):
    monkeypatch.setenv("LATEX_COMPILER", "/nonexistent/but/explicit/pdflatex")
    resolved = LaTeXRenderer(outputs_dir=str(tmp_path / "outputs"))._resolve_pdflatex_path()
    assert resolved == "/nonexistent/but/explicit/pdflatex"


# --- macOS ------------------------------------------------------------------------------

def test_the_mactex_location_is_searched(tmp_path):
    """MacTeX installs to /Library/TeX/texbin and does NOT add it to PATH.

    A non-login shell -- a script, an IDE, CI -- therefore finds no pdflatex on a
    machine where LaTeX is correctly installed. This path must be searched
    explicitly rather than relying on PATH.
    """
    assert "/Library/TeX/texbin/pdflatex" in _candidates(tmp_path)


def test_both_homebrew_architectures_are_searched(tmp_path):
    """Apple Silicon and Intel use different Homebrew prefixes; do not assume one."""
    candidates = _candidates(tmp_path)
    assert "/opt/homebrew/bin/pdflatex" in candidates
    assert "/usr/local/bin/pdflatex" in candidates


def test_pdftex_fallback_is_not_mistaken_for_the_primary(tmp_path):
    """pdflatex must be looked for by name; a bare name is always tried first."""
    assert _candidates(tmp_path)[0] == "pdflatex"


# --- Linux ------------------------------------------------------------------------------

def test_the_linux_location_is_searched(tmp_path):
    assert "/usr/bin/pdflatex" in _candidates(tmp_path)


# --- Windows (the development platform) --------------------------------------------------

def test_compiler_discovery_uses_current_windows_user(tmp_path, monkeypatch):
    """Regression guard: LOCALAPPDATA must be read, not hardcoded."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "different-user"))
    assert str(tmp_path / "different-user/Programs/MiKTeX/miktex/bin/x64/pdflatex.exe") in _candidates(tmp_path)


def test_the_windows_locations_are_still_searched(tmp_path, monkeypatch):
    """Adding the other platforms must not remove the one that works here."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    candidates = _candidates(tmp_path)
    assert str(tmp_path / "lad/Programs/MiKTeX/miktex/bin/x64/pdflatex.exe") in candidates
    assert any("MiKTeX" in candidate for candidate in candidates)


# --- no platform is assumed anywhere in the candidate list -------------------------------

def test_the_candidate_list_covers_all_three_platforms(tmp_path):
    """A Windows-only list is how a macOS-only failure hides until it ships."""
    candidates = _candidates(tmp_path)
    assert any("/Library/TeX" in c for c in candidates), "macOS (MacTeX)"
    assert any("MiKTeX" in c for c in candidates), "Windows"
    assert any(c.startswith("/usr/bin") for c in candidates), "Linux"


def test_resolution_reports_a_clear_error_when_nothing_is_found(tmp_path, monkeypatch):
    """The message must tell the user how to fix it, on any platform."""
    monkeypatch.delenv("LATEX_COMPILER", raising=False)
    renderer = LaTeXRenderer(outputs_dir=str(tmp_path / "outputs"))
    # Simulate no compiler anywhere, without touching the real PATH.
    monkeypatch.setattr(renderer, "_pdflatex_candidates", [])
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError) as caught:
        renderer._resolve_pdflatex_path()
    assert "pdflatex" in str(caught.value)
    assert "PATH" in str(caught.value)


# --- end-to-end resolution on a simulated Mac --------------------------------------------

@pytest.mark.parametrize("mactex_path", [
    "/Library/TeX/texbin/pdflatex",   # MacTeX / TeX Live installer
    "/opt/homebrew/bin/pdflatex",     # Homebrew on Apple Silicon
    "/usr/local/bin/pdflatex",        # Homebrew on Intel
])
def test_resolution_finds_a_compiler_on_a_mac_with_nothing_on_path(
        tmp_path, monkeypatch, mactex_path):
    """The case that actually bites: a Mac where LaTeX is installed and PATH is bare.

    MacTeX does not put pdflatex on PATH for non-login shells, so a search that
    relies on PATH alone fails on a correctly configured machine. This drives the
    real resolution logic with nothing on PATH and exactly one candidate present,
    which is what a fresh macOS checkout looks like to a script.
    """
    from pathlib import PurePosixPath

    monkeypatch.delenv("LATEX_COMPILER", raising=False)
    renderer = LaTeXRenderer(outputs_dir=str(tmp_path / "outputs"))
    expected = PurePosixPath(mactex_path)

    def only_this_one_exists(self):
        return PurePosixPath(str(self).replace("\\", "/")) == expected

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", only_this_one_exists)

    assert renderer._resolve_pdflatex_path() == mactex_path
