"""Render this application with its compact, role-specific technology lists."""
from pathlib import Path
import json,sys,runpy
content=Path(__file__).with_name('content.json')
root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'backend'))
from renderers.latex_renderer import LaTeXRenderer
original=LaTeXRenderer._get_technologies_for_company
overrides=json.loads(content.read_text(encoding='utf-8')).get('experience_technologies',{})
LaTeXRenderer._get_technologies_for_company=lambda self,company,profile: overrides.get(company,original(self,company,profile))
sys.argv=['render_application.py','--project',str(root),'--content',str(content),'--mirror-configured']
runpy.run_path(str(root/'scripts/render_application.py'),run_name='__main__')
