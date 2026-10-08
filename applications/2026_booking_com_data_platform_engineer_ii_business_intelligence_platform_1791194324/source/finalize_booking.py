import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from services.profile_loader import load_profile
from models.tailored_output import TailoredCV, TailoredCoverLetter
from renderers import create_latex_renderer, create_docx_renderer
from pypdf import PdfReader

result_path = Path(__file__).resolve().parent / 'generation_result.json'
result = json.loads(result_path.read_text())
folder = Path(__file__).resolve().parents[1]
profile = load_profile()
role = 'Data Platform Engineer II - Business Intelligence Platform'
content = [
    ([
        'Own end-to-end Snowflake ETL pipelines and reusable SQL models across landing, business-logic, and aggregation layers.',
        'Maintain Airflow DAGs and GitLab workflows; deliver models to GoodData for business reporting.',
        'Contribute to automated data quality checks across approximately 80 tables, owning funnel and sales-channel checks.',
        'Maintain YAML/SQL checks for freshness, uniqueness, reconciliation, taxonomy values, and tracking contracts across 20 channel/CTA combinations.',
        'Maintain model documentation with custom Cursor skills that support business context and calculation logic.',
        'Developing MCP access for Claude/Cursor SQL execution incl. table context and reusable skills for business definitions and calculations.',
        'Developing a Claude-based analytics interface using MCP and semantic context, with the aim of replacing existing BI tooling.',
    ], [
        ('Traffic Source & Customer Journey Attribution', [
            'Led incremental event and customer-journey pipelines to identify traffic sources and attribute journeys to their first interaction.',
            'Validated pipelines against production and introduced the new attribution model alongside existing reporting, with controlled historical backfills and no breaking changes.',
            'Updated GoodData models and dashboards and analyzed 72 customer brands, enabling all customer success managers to recommend improvements to clients\' acquisition channels.',
        ]),
    ]),
    ([
        'As lead marketing analyst, owned Snowflake/dbt models for a subscription app across 51 cities and EUR 200k-500k monthly spend.',
        'Partnered with marketing leadership on budget scenarios, ROAS, CAC, and subscriber growth forecasts.',
        'Evaluated new-city launches by forecasting demand saturation, payback timelines, and growth potential.',
    ], [('Marketing Demand Forecasting & Scenario Dashboard', [
        'Replaced spreadsheet planning with dbt/Snowflake models, improving accuracy by approximately 20% and contributing to 8-10% ROAS uplift.',
        'Linked city-level spend to user and subscription growth, supporting scenario planning and 3-5% monthly CAC reductions since Q2 2025.',
    ])]),
    ([
        'Built data pipelines in a two-person team, combining behavioral, marketing, and investment data using BigQuery and dbt.',
        'Developed Markov-chain attribution that informed a 30% shift in channel spend and reduced blended CAC by 8% in one quarter.',
        'Unified investor, revenue, and marketing reporting for a platform with 50k-70k monthly users and multi-million-euro annual investment volume.',
    ], [
        ('Conversational LLM Chatbot for Database Querying', [
            'Built a GPT-powered BigQuery SQL assistant for business users, contributing to approximately 10 hours of weekly reporting savings.',
            'Enabled non-technical stakeholders to self-serve investor, marketing, and revenue insights through conversational queries.',
        ]),
        ('Cashback & Bonus Payment Automation', [
            'Automated payout calculations and SEPA file generation using Python, dbt, and Y42 workflows.',
        ]),
        ('Investor Segmentation & Retention Analytics', [
            'Built K-means segmentation and cohort analysis supporting a 7% increase in repeat investment and approximately 4% lower monthly churn.',
        ]),
    ]),
    ([
        'Delivered cross-functional marketing, product, and sales analytics supporting growth in an automotive marketplace.',
        'Maintained executive KPI dashboards across Paid, Organic, and Brand channels to help detect performance trends.',
        'Supported experimentation on product and search features to improve funnel performance and conversion rates.',
    ], [('Performance Marketing Channel Attribution', [
        'Built multi-touch attribution and Matillion ETL supporting six-figure budget reallocation and a 6-8% increase in qualified leads.',
        'Redistributed untracked sessions and leads using session-level behavior and U-shaped logic, contributing to approximately 4% higher downstream conversion.',
    ])]),
    ([], []),
    ([], []),
]
experiences = []
for base, (bullets, projects) in zip(profile.experience, content):
    experiences.append(dict(company=base.company, role=base.role,
                            start_date=base.start_date, end_date=base.end_date,
                            bullets=bullets,
                            projects=[dict(name=name, bullets=items) for name, items in projects]))
cv = TailoredCV(
    title='Analytics Engineering | Data Platforms & AI Analytics',
    summary=['Senior analytics professional with experience across analytics engineering, business intelligence, and growth analytics. Strong technical background in data modeling, automation, and statistical analysis, supported by hands-on delivery of reliable reporting, forecasting, and tools for business decision-making.'],
    skills={
        'Data Platforms & Modeling': ['SQL', 'Snowflake', 'dbt', 'BigQuery', 'Data Modeling & Semantic Layers', 'Apache Airflow'],
        'Quality & Delivery': ['Automated Data Quality', 'Data Contracts', 'GitLab CI', 'Docker', 'Git'],
        'BI & AI Analytics': ['GoodData', 'Looker', 'Power BI', 'Python', 'Claude', 'Cursor', 'MCP', 'LLM SQL Generation'],
        'Business Analytics': ['Attribution Modeling', 'Forecasting', 'A/B Testing', 'Stakeholder Management'],
    }, experience=experiences,
)
paragraphs = [
    'I am applying for the Data Platform Engineer II - Business Intelligence Platform role at Booking.com. Your focus on shared semantic foundations for BI and AI analytics closely matches my current work: building reusable warehouse models, validating business logic, and developing the context that helps language models interpret analytical questions. I bring experience connecting data engineering delivery with practical business use.',
    'As Senior Analytical Engineer at Aklamio, I own ETL pipelines from ingestion through Snowflake transformations to GoodData consumption. I develop SQL models across landing, intermediate, and aggregated layers, maintain Airflow DAGs and GitLab workflows, and contribute to a YAML-driven quality framework covering approximately 80 tables. My responsibilities include funnel and sales-channel checks, source reconciliation, taxonomy validation, and tracking contracts across 20 channel and CTA combinations. These checks connect technical validation to the business meaning of the data.',
    'I also led the released Entrypoints v2 attribution initiative, combining incremental enrichment pipelines with GoodData models and dashboards. The rollout preserved existing reporting, and analysis across 72 customer brands now supports recommendations from all CSMs. Alongside this production work, I am developing Snowflake MCP integration for Claude and Cursor, with table-level semantic context and reusable business-logic skills; a Claude-based dashboarding solution is also in progress. Earlier roles added hands-on dbt experience in Snowflake and BigQuery, plus a GPT-powered SQL assistant for business users.',
    'I would bring this combination of warehouse modeling, data quality ownership, BI delivery, and developing conversational analytics to your Central Tech team. My prior work also spans automated reporting, financial data workflows, and translating stakeholder needs into practical analytical tools. I am particularly interested in extending these foundations to the semantic and AI analytics capabilities described in the opening. I welcome the opportunity to discuss how my experience can support reliable, reusable analytical services at Booking.com.',
]
cl = TailoredCoverLetter(role_title=role, company_name='Booking.com', paragraphs=paragraphs,
                        closing_line='Sincerely,', signature_name=profile.identity.full_name)
(folder / 'source/content.json').write_text(json.dumps(dict(company_name=cl.company_name, role_title=role, cv=cv.model_dump(), cover_letter=cl.model_dump()), indent=2),encoding='utf-8')
latex = create_latex_renderer(outputs_dir=str(folder))
result['cv_path'] = latex.render_cv(cv, profile, job_position=role)
tex_path = Path(result['cv_path']).with_suffix('.tex')
tex = latex.jinja_env.get_template('main.tex.jinja2').render(**latex._prepare_template_data(cv, profile))
tex = tex.replace(r'{\small\textbf{\textcolor{accent}{Selected Projects:}}}',
                  r'\needspace{1.8cm}' + '\n' + r'{\small\textbf{\textcolor{accent}{Selected Projects:}}}')
tex_path.write_text(tex, encoding='utf-8')
result['cv_path'] = str(latex._compile_pdf(tex_path, tex_path.stem))
if '--cv-only' not in sys.argv:
    result['cover_letter_path'], result['cl_pdf_path'] = create_docx_renderer(outputs_dir=str(folder)).render_cover_letter(cl, profile, job_position=role)
for key, filename in result.get('artifact_filenames', {}).items():
    if '--cv-only' in sys.argv and key != 'cv_path':
        continue
    artifact = Path(result[key])
    preferred = folder / filename
    if artifact != preferred:
        import shutil
        shutil.copy2(artifact, preferred)
        artifact.unlink()
        result[key] = str(preferred)
result_path.write_text(json.dumps(result,indent=2),encoding='utf-8')
print('CV pages:',len(PdfReader(result['cv_path']).pages))
print('Cover letter PDF pages:',len(PdfReader(result['cl_pdf_path']).pages))
print('Cover letter body words:',sum(len(p.split()) for p in paragraphs))
