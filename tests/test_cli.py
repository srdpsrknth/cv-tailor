"""CLI smoke tests.

Every test here is offline: ``doctor`` only attempts provider access with
``--verify-key`` and a mocked client, ``render`` makes no API call at all, and
``generate`` uses a mocked service when a key is configured.

Commands are called through :func:`cli.main.main` with an explicit argv, so the
tests cover the real parsing and dispatch rather than a reimplementation.

**"No key configured" needs more than ``delenv``, and that was a real defect.**
``Config.from_env`` loads ``.env`` by default, so a developer whose ``.env`` holds a
*real* ``GEMINI_API_KEY`` defeats ``monkeypatch.delenv('GEMINI_API_KEY')``: the key is
re-supplied from the file and the two ``generate`` tests below stop failing at the key
check and start making **live, paid API calls**. They passed for months only because
this project's ``.env`` shipped a placeholder. ``no_api_key`` closes that hole by
patching the environment *and* the file-loading step, so "offline" is enforced rather
than assumed.
"""
from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from cli.main import main  # noqa: E402

from support import copy_content_json, latex_available  # noqa: E402


@pytest.fixture
def no_api_key(monkeypatch):
    """Make "no API key is configured" true, whatever this machine's ``.env`` holds.

    Both halves are needed. ``delenv`` alone is defeated by the ``.env`` file, and
    patching the loader alone is defeated by a key already exported into the process
    (``load_dotenv`` mutates ``os.environ`` process-wide, so a previous test's load
    persists). Together they cannot be worked around by the environment the tests
    happen to run in.
    """
    import config as config_module

    for name in ('GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'CVTAILOR_PROVIDER'):
        monkeypatch.delenv(name, raising=False)
    # `load_dotenv(candidate)` is the only step that reads the file; making it a no-op
    # leaves every other part of `from_env` under test.
    monkeypatch.setattr(config_module, 'load_dotenv', lambda *a, **k: False)
    return monkeypatch

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


def test_doctor_does_not_verify_the_key_unless_asked(no_api_key, monkeypatch, capsys):
    """The default doctor must never make a network call."""
    request = Mock(side_effect=AssertionError('unexpected network call'))
    monkeypatch.setattr('requests.get', request)
    monkeypatch.setattr('google.genai.Client', request)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-router-key')

    main(['--json', 'doctor'])

    check = _doctor_key_check(capsys)
    assert check['status'] == 'ok'
    assert 'not verified' in check['detail']
    assert 'test-router-key' not in str(check)
    request.assert_not_called()


def _doctor_key_check(capsys):
    result = json.loads(capsys.readouterr().out)
    return next(check for check in result['checks'] if check['check'] == 'api key')


def test_doctor_verifies_openrouter_via_metadata(no_api_key, monkeypatch, capsys):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-router-key')
    response = Mock()
    response.status_code = 200
    response.json.return_value = {'data': {'limit_remaining': 3.25, 'label': 'test-router-key'}}
    request = Mock(return_value=response)
    monkeypatch.setattr('requests.get', request)

    main(['--json', 'doctor', '--verify-key'])

    check = _doctor_key_check(capsys)
    assert check['status'] == 'ok'
    assert '$3.25' in check['detail']
    assert 'test-router-key' not in str(check)
    assert request.call_args.args == ('https://openrouter.ai/api/v1/key',)
    assert request.call_args.kwargs['headers'] == {'Authorization': 'Bearer test-router-key'}


def test_doctor_redacts_provider_exceptions(no_api_key, monkeypatch, capsys):
    from requests import RequestException

    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-router-key')
    request = Mock(side_effect=RequestException('test-router-key'))
    monkeypatch.setattr('requests.get', request)

    assert main(['--json', 'doctor', '--verify-key']) == 1

    check = _doctor_key_check(capsys)
    assert check['status'] == 'fail'
    assert 'test-router-key' not in str(check)
    assert 'OPENROUTER_API_KEY' in check['fix']
    request.assert_called_once()


def test_doctor_reports_openrouter_rejection_without_reading_the_body(no_api_key, monkeypatch, capsys):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-router-key')
    response = Mock(status_code=401)
    monkeypatch.setattr('requests.get', Mock(return_value=response))

    assert main(['--json', 'doctor', '--verify-key']) == 1

    check = _doctor_key_check(capsys)
    assert check['status'] == 'fail'
    assert 'HTTP 401' in check['detail']
    response.json.assert_not_called()


def test_doctor_verifies_native_gemini_without_generating(no_api_key, monkeypatch, capsys):
    monkeypatch.setenv('CVTAILOR_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-gemini-key')
    monkeypatch.setenv('CVTAILOR_MODEL', 'gemini-test-model')
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr('google.genai.Client', factory)

    main(['--json', 'doctor', '--verify-key'])

    check = _doctor_key_check(capsys)
    assert check['status'] == 'ok'
    assert 'gemini-test-model' in check['detail']
    assert 'test-gemini-key' not in str(check)
    factory.assert_called_once_with(api_key='test-gemini-key')
    client.models.get.assert_called_once_with(model='gemini-test-model')
    client.models.generate_content.assert_not_called()


def test_setup_script_forwards_verify_key(monkeypatch):
    call = Mock(return_value=0)
    monkeypatch.setattr('subprocess.call', call)
    monkeypatch.setattr(sys, 'argv', ['check_setup.py', '--verify-key'])

    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / 'scripts' / 'check_setup.py'), run_name='__main__')

    assert result.value.code == 0
    assert call.call_args.args[0][2:] == ['doctor', '--verify-key']


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


def test_render_manifest_merge_preserves_provenance_for_untouched_artifacts(tmp_path):
    from cli.commands.render import _update_manifest

    path = tmp_path / "source" / "generation_result.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"provider": "historical", "artifact_provenance": {"letter.pdf": {"artifact_sha256": "letter"}}}),
        encoding="utf-8",
    )
    _update_manifest(
        path,
        {"cv_path": "cv.pdf"},
        tmp_path,
        artifact_provenance={"cv.pdf": {"artifact_sha256": "cv"}},
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["provider"] == "historical"
    assert manifest["artifact_provenance"] == {
        "letter.pdf": {"artifact_sha256": "letter"},
        "cv.pdf": {"artifact_sha256": "cv"},
    }


@pytest.mark.requires_latex
def test_render_produces_the_documents_without_an_api_key(tmp_path, capsys, no_api_key):
    """The whole point of the render path: real output, zero LLM calls."""
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
def test_render_page_count_matches_the_existing_script(tmp_path, monkeypatch, no_api_key):
    """Acceptance criterion: the CLI reproduces the script's page count."""
    import subprocess

    from support import page_count

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


# --- generate (offline) ---------------------------------------------------------------

@pytest.mark.parametrize('provider', ['openrouter', 'gemini'])
def test_generate_accepts_only_the_selected_key(no_api_key, monkeypatch, capsys, provider):
    from services import tailor_service

    monkeypatch.setenv('CVTAILOR_PROVIDER', provider)
    monkeypatch.setenv(f'{provider.upper()}_API_KEY', 'selected-test-key')
    generate = Mock()
    generate.return_value.model_dump.return_value = {'job_id': 'offline'}
    monkeypatch.setattr(tailor_service, 'tailor_documents', generate)

    assert main(['--json', 'generate', '--job', 'x' * 200]) == 0

    generate.assert_called_once()
    assert generate.call_args.kwargs['config'].require_provider_key() == 'selected-test-key'
    assert json.loads(capsys.readouterr().out) == {'job_id': 'offline'}


@pytest.mark.parametrize('provider', ['openrouter', 'gemini'])
def test_cli_ignores_the_other_providers_key(no_api_key, monkeypatch, capsys, provider):
    selected = f'{provider.upper()}_API_KEY'
    other = 'GEMINI_API_KEY' if provider == 'openrouter' else 'OPENROUTER_API_KEY'
    monkeypatch.setenv('CVTAILOR_PROVIDER', provider)
    monkeypatch.setenv(other, 'other-provider-test-key')
    generate = Mock(side_effect=AssertionError('unexpected paid generation'))
    monkeypatch.setattr('services.tailor_service.tailor_documents', generate)

    assert main(['generate', '--job', 'x' * 200]) == 3
    error = capsys.readouterr().err
    assert selected in error and other not in error
    generate.assert_not_called()

    assert main(['--json', 'doctor']) == 1
    check = _doctor_key_check(capsys)
    assert check['status'] == 'fail'
    assert selected in check['detail'] and other not in check['detail']

def test_generate_without_an_api_key_fails_with_a_fix(no_api_key, capsys):
    code = main(['generate', '--job', 'x' * 200])
    assert code != 0
    err = capsys.readouterr().err
    assert 'OPENROUTER_API_KEY' in err
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


def test_generate_accepts_a_job_file_path(no_api_key, tmp_path, capsys):
    """With no key configured it must still get as far as the key check."""
    job = tmp_path / 'job.txt'
    job.write_text('A sufficiently detailed job description for the CLI smoke test.' * 3,
                   encoding='utf-8')

    code = main(['generate', '--job-file', str(job)])

    assert code != 0
    assert 'OPENROUTER_API_KEY' in capsys.readouterr().err


@pytest.mark.parametrize('source', ['inline', 'file', 'stdin'])
@pytest.mark.parametrize('command', [
    '.venv/bin/python cvtailor.py \\\n  --profile-id analyst_a \\\n  generate --job "$(pbpaste)" --country Germany',
    'cvtailor --profile-id analyst_a generate --job-file posting.txt',
])
def test_generate_rejects_a_command_as_the_posting(
    no_api_key, monkeypatch, tmp_path, capsys, source, command,
):
    """A clipboard mistake must stop before the API-key check or any paid call."""
    import io
    from services import tailor_service

    def unexpected_call(**kwargs):
        pytest.fail('A shell command reached paid generation')

    monkeypatch.setattr(tailor_service, 'tailor_documents', unexpected_call)
    argv = ['generate']
    if source == 'inline':
        argv += ['--job', command]
    elif source == 'file':
        job = tmp_path / 'posting.txt'
        job.write_text(command, encoding='utf-8')
        argv += ['--job-file', str(job)]
    else:
        monkeypatch.setattr(sys, 'stdin', io.StringIO(command))

    assert main(argv) == 2
    error = capsys.readouterr().err
    assert 'command' in error.lower() and 'clipboard' in error.lower()
    assert 'OPENROUTER_API_KEY' not in error


def test_a_posting_can_mention_the_cli_below_its_title(no_api_key, capsys):
    posting = ('Python Engineer\nMaintain our internal application tooling.\n'
               'Example: python cvtailor.py generate --job-file posting.txt')
    assert main(['generate', '--job', posting]) == 3
    assert 'OPENROUTER_API_KEY' in capsys.readouterr().err
