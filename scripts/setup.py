"""Create a local environment without replacing existing configuration."""
from pathlib import Path
import shutil, subprocess, sys, venv

ROOT = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11 or newer is required; Python 3.12 is recommended.')
folder = ROOT / '.venv'
if not folder.exists():
    venv.EnvBuilder(with_pip=True).create(folder)
python = folder / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
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
    '       Windows MiKTeX  https://miktex.org/download\n'
    '       Linux   TeX Live via your package manager\n'
    '  3. Point CVTAILOR_STORE at your private store and set CVTAILOR_PROFILE_ID.\n'
    '  4. Run: {python} scripts/check_setup.py\n'
    '\n'
    'See docs/MAC_SETUP.md (macOS) or docs/HOW_TO_GENERATE.md (day-to-day use).'.format(
        python=python.relative_to(ROOT).as_posix()
    )
)
