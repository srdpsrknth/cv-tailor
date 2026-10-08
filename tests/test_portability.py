from renderers.latex_renderer import LaTeXRenderer


def test_compiler_discovery_uses_current_windows_user(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'different-user'))
    renderer = LaTeXRenderer(outputs_dir=str(tmp_path / 'outputs'))
    assert str(tmp_path / 'different-user/Programs/MiKTeX/miktex/bin/x64/pdflatex.exe') in renderer._pdflatex_candidates


def test_compiler_override_is_used(tmp_path, monkeypatch):
    compiler = tmp_path / 'custom-tex/pdflatex.exe'
    compiler.parent.mkdir()
    compiler.touch()
    monkeypatch.setenv('LATEX_COMPILER', str(compiler))
    assert LaTeXRenderer(outputs_dir=str(tmp_path / 'outputs'))._resolve_pdflatex_path() == str(compiler)
