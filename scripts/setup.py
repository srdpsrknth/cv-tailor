"""Create a local environment without replacing existing configuration."""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from python_floor import MIN_PYTHON, min_python_text  # noqa: E402

_ARCH_ALIASES = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x86_64', 'amd64': 'x86_64'}


def normalise_arch(machine: str) -> str:
    return _ARCH_ALIASES.get((machine or '').strip().lower(), (machine or '').strip().lower())


def host_arch() -> str:
    """The CPU the machine really has, even when this interpreter runs under Rosetta."""
    if sys.platform == 'darwin':
        try:
            result = subprocess.run(
                ['sysctl', '-n', 'hw.optional.arm64'],
                capture_output=True, text=True, encoding='utf-8', timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip() == '1':
                return 'arm64'
        except (OSError, subprocess.SubprocessError):
            pass
    return normalise_arch(platform.machine())


def venv_python_path(folder: Path) -> Path:
    return folder / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def probe_interpreter(python: Path):
    """Return ``((major, minor), machine)`` for ``python``, or ``None`` if it won't run."""
    code = 'import sys, platform; print(sys.version_info[0], sys.version_info[1], platform.machine())'
    try:
        result = subprocess.run(
            [str(python), '-c', code],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        major, minor, machine = result.stdout.split()
        return (int(major), int(minor)), normalise_arch(machine)
    except ValueError:
        return None


def venv_problems(python: Path, host: str, folder: Path) -> list:
    """Reasons an existing virtual environment cannot be reused; empty when it is fine."""
    probe = probe_interpreter(python)
    delete_hint = (
        f'Delete the {folder} folder (nothing is deleted automatically) and rerun '
        'scripts/setup.py with a native Python'
    )
    if probe is None:
        return [f'The existing environment at {folder} has an interpreter that will not run. {delete_hint}.']
    version, machine = probe
    problems = []
    if version < MIN_PYTHON:
        problems.append(
            f'The existing environment at {folder} uses Python {version[0]}.{version[1]}, '
            f'but {min_python_text()} or newer is required. {delete_hint} of Python {min_python_text()}.'
        )
    if machine and host and machine != host:
        problems.append(
            f'The existing environment at {folder} is {machine} but this machine is {host} '
            f'(for example an Intel/Rosetta Python on Apple Silicon). Some locked wheels, such as '
            f'cryptography 50.x, have no macOS x86_64 build. {delete_hint} that matches {host}.'
        )
    return problems


def main() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f'Python {min_python_text()} or newer is required.')
    folder = ROOT / '.venv'
    python = venv_python_path(folder)
    if folder.exists():
        problems = venv_problems(python, host_arch(), folder)
        if problems:
            raise SystemExit('\n'.join(problems))
    else:
        venv.EnvBuilder(with_pip=True).create(folder)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.lock.txt')], check=True)
    if not (ROOT / '.env').exists():
        shutil.copy2(ROOT / '.env.example', ROOT / '.env')
    print(
        'Environment ready.\n'
        '\n'
        'Next steps:\n'
        '  1. Put your OpenRouter key in .env (OPENROUTER_API_KEY=...).\n'
        '     The default provider and model are openrouter + openai/gpt-6-luna.\n'
        '     Get a key from https://openrouter.ai/settings/keys -- it needs credit.\n'
        '  2. Install a LaTeX distribution, then run scripts/check_setup.py:\n'
        '       macOS   MacTeX  https://www.tug.org/mactex/  (installs to /Library/TeX/texbin)\n'
        '       Windows MiKTeX  https://miktex.org/download  (or TeX Live)\n'
        '       Linux   TeX Live via your package manager\n'
        '  3. Point CVTAILOR_STORE at your private store and set CVTAILOR_PROFILE_ID.\n'
        '  4. Run: {python} scripts/check_setup.py\n'
        '\n'
        'See docs/MAC_SETUP.md (macOS) or docs/HOW_TO_GENERATE.md (day-to-day use).'.format(
            python=python.relative_to(ROOT)
        )
    )


if __name__ == '__main__':
    main()
