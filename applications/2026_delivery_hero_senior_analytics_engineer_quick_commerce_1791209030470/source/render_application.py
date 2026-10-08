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
original_init=LaTeXRenderer.__init__
def application_init(self,*args,**kwargs):
    original_init(self,*args,**kwargs)
    original_get=self.jinja_env.get_template
    def get_template(name,*args,**kwargs):
        if name!='main.tex.jinja2':return original_get(name,*args,**kwargs)
        template=(root/'templates/cv/main.tex.jinja2').read_text(encoding='utf-8')
        template=template.replace(r'\begin{samepage}',r'{% if exp.company != "ecoligo GmbH" %}\begin{samepage}{% endif %}')
        template=template.replace(r'\end{samepage}',r'{% if exp.company != "ecoligo GmbH" %}\end{samepage}{% endif %}')
        marker=r'\item {{ bullet }}'
        continuation='''\\item {{ bullet }}
{% if exp.company == "ecoligo GmbH" and loop.index == 3 %}
\\end{itemize}
\\newpage
\\cveventsmall{ecoligo GmbH (continued)}{Business Intelligence Analyst}{}{Berlin, Germany}
\\begin{itemize}
{% endif %}'''
        template=template.replace(marker,continuation,1)
        return self.jinja_env.from_string(template)
    self.jinja_env.get_template=get_template
LaTeXRenderer.__init__=application_init
sys.argv=['render_application.py','--project',str(root),'--content',str(content),'--mirror-configured']
runpy.run_path(str(root/'scripts/render_application.py'),run_name='__main__')
