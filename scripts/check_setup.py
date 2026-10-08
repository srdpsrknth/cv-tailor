"""Check local prerequisites without sending data to Gemini."""
from pathlib import Path
import os, sys
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from services.profile_loader import load_profile
from renderers.latex_renderer import LaTeXRenderer
from renderers.docx_renderer import DocxRenderer
load_profile()
ZoneInfo('Europe/Berlin')
print('Profile and timezone: OK')
print('LaTeX compiler:', LaTeXRenderer()._resolve_pdflatex_path())
DocxRenderer()
print('CV and cover-letter templates: OK')
key = os.getenv('GEMINI_API_KEY', '')
if not key or key == 'your_gemini_api_key_here':
    raise SystemExit('Set GEMINI_API_KEY in .env before AI generation.')
print('API key configured (not verified with Google); model:', os.getenv('GEMINI_MODEL'))
