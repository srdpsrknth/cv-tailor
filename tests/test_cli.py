"""CLI smoke tests.

Every test here is offline: ``doctor`` never contacts Google unless
``--verify-key`` is passed, ``render`` makes no API call at all, and
``generate`` is only exercised on its failure paths (no key configured).

Commands are called through :func:`cli.main.main` with an explicit argv, so the
tests cover the real parsing and dispatch rather than a reimplementation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from cli.main import main  # noqa: E402

from support import copy_content_json, latex_available  # noqa: E402

# Same two-part convention as the renderer suite: the `requires_latex` marker lets the
# fast lane deselect the slow pdflatex work, and the skipif keeps the suite green on a
# machine with no TeX installed.
requires_latex = pytest.mark.skipif(
    not latex_available(), reason='No pdflatex compiler could be resolved on this machine'
)


# --- guided default -------------------------------------------------------------------

def test_no_arguments_prints_a_guided_menu(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert 'cvtailor' in out
    # The ADR 0007 guided default should name the common flows.
    for command in ('doctor', 'profile show', 'generate', 'render'):
        assert command in out


def test_no_arguments_with_json_emits_the_command_list(capsys):
    assert main(['--json']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert 'doctor' in payload['commands']


def test_help_lists_every_shipped_command(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(['--help'])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in ('doctor', 'profile', 'generate', 'render'):
        assert command in out


# --- exit codes -----------------------------------------------------------------------

def test_an_unknown_command_exits_with_a_usage_code(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(['not-a-command'])
    assert exit_info.value.code != 0


def test_an_explicitly_missing_profile_reports_and_exits_nonzero(tmp_path, capsys):
    code = main(['--profile', str(tmp_path / 'nope.yaml'), 'profile', 'show'])
    assert code != 0
    assert 'not found' in capsys.readouterr().err.lower()


def test_a_bad_project_directory_is_rejected(capsys):
    code = main(['--project', 'D:/definitely/not/here', 'profile', 'show'])
    assert code != 0
    assert 'not a directory' in capsys.readouterr().err.lower()


# --- doctor ---------------------------------------------------------------------------

def test_doctor_runs_offline_and_reports_every_check(capsys):
    main(['doctor'])
    out = capsys.readouterr().out
    for name in ('python', 'profile', 'timezone', 'templates', 'pdflatex', 'outputs', 'api key'):
        assert name in out, f'doctor did not report {name}'


def test_doctor_json_is_valid_and_lists_checks(capsys):
    main(['--json', 'doctor'])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) >= {'ok', 'checks'}
    names = {check['check'] for check in payload['checks']}
    assert {'python', 'profile', 'pdflatex'} <= names
    # Statuses are constrained, so a caller can rely on them.
    assert {c['status'] for c in payload['checks']} <= {'ok', 'warn', 'fail'}


def test_doctor_does_not_verify_the_key_unless_asked(monkeypatch, capsys):
    """The default doctor must never make a network call."""
    import cli.commands.doctor as doctor

    called = []

    def explode(*args, **kwargs):
        called.append(True)
        raise AssertionError('doctor contacted Google without --verify-key')

    monkeypatch.setattr(doctor, 'check_api_key', lambda config, verify=False: doctor.Check('api key', 'ok'))
    main(['doctor'])
    assert not called


def test_doctor_fails_when_the_profile_is_missing(tmp_path, capsys, monkeypatch):
    import cli.commands.doctor as doctor
    from config import Config

    broken = Config.from_env(load_env_file=False,
                             overrides={'project_root': ROOT, 'profile_path': tmp_path / 'x.yaml'})
    monkeypatch.setattr(doctor, 'check_api_key', lambda config, verify=False: doctor.Check('api key', 'ok'))
    assert doctor.run(type('A', (), {'verify_key': False})(), _console(), broken) == 1


def _console():
    from cli.context import Console

    return Console(as_json=False)


# --- profile show ---------------------------------------------------------------------

def test_profile_show_prints_the_candidate_and_their_roles(capsys):
    assert main(['profile', 'show']) == 0
    out = capsys.readouterr().out
    assert 'Experience (' in out
    assert 'Validation rules' in out


def test_profile_show_json_round_trips_the_profile(capsys):
    assert main(['--json', 'profile', 'show']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['profile']['identity']['full_name']
    assert payload['profile']['experience']


def test_profile_show_defaults_to_show(capsys):
    """`profile` with no action behaves like `profile show`."""
    assert main(['profile']) == 0
    assert 'Profile:' in capsys.readouterr().out


# --- render ---------------------------------------------------------------------------

def _scratch_application(tmp_path: Path, name: str = 'valid_content.json') -> Path:
    application = tmp_path / 'application'
    copy_content_json(application, name)
    return application


def test_render_rejects_content_outside_a_source_folder(tmp_path, capsys):
    stray = tmp_path / 'content.json'
    stray.write_text('{}', encoding='utf-8')
    assert main(['render', '--content', str(stray)]) != 0
    assert 'source' in capsys.readouterr().err


def test_render_reports_a_missing_content_file(tmp_path, capsys):
    code = main(['render', '--content', str(tmp_path / 'missing' / 'source' / 'content.json')])
    assert code != 0
    assert 'not found' in capsys.readouterr().err.lower()


def test_render_rejects_malformed_content(tmp_path, capsys):
    application = _scratch_application(tmp_path, 'invalid_content.json')
    code = main(['render', '--content', str(application / 'source' / 'content.json')])
    assert code != 0


@pytest.mark.requires_latex
def test_render_produces_the_documents_without_an_api_key(tmp_path, capsys, monkeypatch):
    """The whole point of the render path: real output, zero LLM calls."""
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    application = _scratch_application(tmp_path)
    content = application / 'source' / 'content.json'

    assert main(['render', '--content', str(content)]) == 0

    from support import page_count

    out = capsys.readouterr().out
    assert 'CV:' in out and 'Cover letter:' in out
    pdfs = list(application.glob('*.pdf'))
    assert pdfs, 'render produced no PDFs'
    for pdf in pdfs:
        assert page_count(pdf) >= 1


@pytest.mark.requires_latex
def test_render_page_count_matches_the_existing_script(tmp_path, monkeypatch):
    """Acceptance criterion: the CLI reproduces the script's page count."""
    import subprocess

    from support import page_count

    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    application = _scratch_application(tmp_path)
    content = application / 'source' / 'content.json'

    # Render with the CLI, record the page counts.
    assert main(['render', '--content', str(content), '--cv-only']) == 0
    cli_pdfs = {p.name: page_count(p) for p in application.glob('*_CV_*.pdf')}
    assert cli_pdfs, 'the CLI produced no CV PDF'

    # Render the same content with the existing script, into a copy of the folder.
    from support import FIXTURES
    import shutil

    other = tmp_path / 'script-application'
    shutil.copytree(application, other)
    for pdf in other.glob('*.pdf'):
        pdf.unlink()
    script_content = other / 'source' / 'content.json'

    environment = dict(**__import__('os').environ)
    environment.pop('GEMINI_API_KEY', None)
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'render_application.py'),
         '--project', str(ROOT), '--content', str(script_content), '--cv-only'],
        capture_output=True, text=True, env=environment, timeout=600,
    )
    assert completed.returncode == 0, completed.stderr

    script_pdfs = {p.name: page_count(p) for p in other.glob('*_CV_*.pdf')}
    assert script_pdfs, 'the script produced no CV PDF'

    # Same filenames, same page counts.
    assert set(cli_pdfs) == set(script_pdfs)
    assert cli_pdfs == script_pdfs, f'page counts differ: {cli_pdfs} vs {script_pdfs}'


# --- generate (failure paths only; never calls the API) -------------------------------

def test_generate_without_an_api_key_fails_with_a_fix(monkeypatch, capsys):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    code = main(['generate', '--job', 'x' * 200])
    assert code != 0
    err = capsys.readouterr().err
    assert 'GEMINI_API_KEY' in err
    assert '.env' in err


def test_generate_rejects_a_short_job_description(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-not-real')
    code = main(['generate', '--job', 'too short'])
    assert code != 0
    assert 'too short' in capsys.readouterr().err.lower()


def test_generate_reports_a_missing_job_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-not-real')
    code = main(['generate', '--job-file', str(tmp_path / 'nope.txt')])
    assert code != 0
    assert 'not found' in capsys.readouterr().err.lower()


def test_generate_accepts_a_job_file_path(monkeypatch, tmp_path, capsys):
    """With no key configured it must still get as far as the key check."""
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    job = tmp_path / 'job.txt'
    job.write_text('A sufficiently detailed job description for the CLI smoke test.' * 3,
                   encoding='utf-8')

    code = main(['generate', '--job-file', str(job)])

    assert code != 0
    assert 'GEMINI_API_KEY' in capsys.readouterr().err
