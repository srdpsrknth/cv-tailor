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
print('Environment ready. Set GEMINI_API_KEY in .env, install MiKTeX/TeX Live, then run scripts/check_setup.py.')
