import runpy
from pathlib import Path
import sys
project = Path(__file__).resolve().parents[3]
sys.argv = [str(Path.home() / '.codex/skills/cv-tailor-application/scripts/render_application.py'), '--project', str(project), '--content', str(Path(__file__).with_name('content.json')), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name='__main__')
