# Project: cv-tailor

## Goal
A tool that takes a job description and produces:
1) Tailored CV in LaTeX → compiled to PDF
2) Tailored cover letter as DOCX
UI must preview and allow download of both, with token usage and cost tracking.

## Architecture Overview
```
cv-tailor/
├── backend/              # FastAPI backend
│   ├── main.py           # REST API endpoints
│   ├── models/           # Pydantic data models
│   │   ├── profile.py    # BaseProfile (from YAML)
│   │   └── tailored_output.py  # TailoredCV, TailoredCoverLetter
│   ├── services/         # Business logic
│   │   ├── gemini_service.py    # Google Gemini API integration
│   │   ├── tailor_service.py    # CV/CL tailoring orchestration
│   │   └── profile_loader.py    # Load/validate YAML profile
│   ├── renderers/        # Document generation
│   │   ├── latex_renderer.py    # Jinja2 → LaTeX → tectonic → PDF
│   │   └── docx_renderer.py     # docxtpl → DOCX
│   └── prompts/          # Versioned AI prompts
│       ├── tailor_cv_prompt.md
│       └── tailor_cl_prompt.md
├── ui/                   # Streamlit frontend
│   └── app.py            # UI with preview, download, cost tracking
├── templates/            # Document templates
│   ├── cv/               # LaTeX templates
│   │   ├── main.tex.jinja2
│   │   └── altacv.cls
│   └── cover_letter/     # DOCX templates
│       └── cover_letter.docx
├── storage/profile/      # Ground truth CV data
│   └── profile.yaml
├── outputs/              # Generated files (gitignored except .gitkeep)
└── cover_letter_examples/  # 87 sample cover letters for reference
```

## Core Technologies
- **LLM**: Google Gemini API (gemini-1.5-flash recommended)
- **Backend**: FastAPI + Pydantic + python-dotenv
- **Frontend**: Streamlit
- **LaTeX Compiler**: Tectonic CLI
- **Document Templating**: Jinja2 (LaTeX), docxtpl (DOCX)
- **Data Format**: YAML (base profile)
- **Python**: 3.10+

---

## Base Profile Structure (YAML)

File: `storage/profile/profile.yaml`

### Schema
```yaml
version: "1.0"

identity:
  full_name: str
  tagline: str
  email: str
  phone: str
  linkedin: str (URL)
  github: str (URL)
  location: str
  visa_status: str (optional)

summary_base:
  - str  # Professional summary (1-2 paragraphs)

experience:
  - company: str
    location: str
    role: str
    start_date: str (YYYY-MM format)
    end_date: str ("present" or YYYY-MM)
    bullets:
      - str  # Achievement/responsibility bullets
    selected_projects:  # Optional nested projects
      - name: str
        bullets:
          - str
    technologies:
      - str  # Technology stack

education:
  - degree: str
    institution: str
    location: str
    start_year: int
    end_year: int

certifications:
  - str

skills:
  # Organized into semantic categories
  core_analytics_quant_methods:
    - str
  product_growth_gtm:
    - str
  data_engineering_modeling_bi:
    - str
  tracking_marketing_tech_product_analytics:
    - str
  automation_llms_advanced_tooling:
    - str
  collaboration_communication:
    - str

languages:
  - name: str
    proficiency: str
```

### Key Rules
- **Chronological order**: Experiences in reverse chronological (most recent first)
- **Present tense**: Use "present" for current roles
- **Quantification**: Bullets include metrics where possible (e.g., "51 cities", "10k records")
- **No fabrication**: AI must ONLY reword/reorder existing content, never invent new facts
- **Technologies**: Track separately per experience for intelligent skill matching

---

## Security & API Configuration

### Environment Variables (.env)
```bash
# Google Gemini API
GEMINI_API_KEY=xxx           # From https://aistudio.google.com/app/apikey
GEMINI_MODEL=gemini-1.5-flash  # or gemini-2.0-flash
GEMINI_TEMPERATURE=0.3       # Low temp for consistency
GEMINI_MAX_OUTPUT_TOKENS=8000

# Backend
BACKEND_HOST=localhost
BACKEND_PORT=8000

# UI
UI_HOST=localhost
UI_PORT=8501

# Paths
OUTPUTS_DIR=outputs
TEMPLATES_DIR=templates
PROFILE_PATH=storage/profile/profile.yaml
```

### Security Rules
- ✅ **CRITICAL**: NEVER expose `GEMINI_API_KEY` in Streamlit/frontend
- ✅ Backend reads `.env` using `python-dotenv`
- ✅ UI calls backend via REST API at `http://localhost:8000`
- ✅ `.gitignore` includes `.env` (use `.env.example` for templates)

---

## Google Gemini API Integration

### Model Selection
- **Recommended**: `gemini-1.5-flash` (fast, cheap, free tier: 15 req/min, 1.5M tokens/day)
- **Alternative**: `gemini-2.0-flash` (latest, better performance)
- **Not recommended**: `gemini-1.5-pro` (expensive, unnecessary for this task)

### Cost Tracking
- Track **input tokens** (job description + base profile)
- Track **output tokens** (tailored CV + cover letter JSON)
- Estimate cost: Free tier is sufficient (~$0.002 per application within paid tier)
- Display token counts and costs in Streamlit UI

### Structured Output Requirements
- Use `response_mime_type="application/json"` for JSON mode
- Define Pydantic models matching expected output
- Gemini returns JSON matching Pydantic schema
- **Validation**: Use Pydantic to parse/validate responses
- **Error handling**: Retry on invalid JSON, fallback to base profile on failure

### Example API Call Pattern
```python
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config={
        "temperature": 0.3,
        "max_output_tokens": 8000,
        "response_mime_type": "application/json"
    }
)

response = model.generate_content([
    {"role": "user", "parts": [prompt]}
])
```

---

## AI Tailoring Logic (Critical Rules)

### CV Tailoring Principles
1. **Extract relevant experiences**: Prioritize bullets matching job description keywords
2. **Reword achievements**: Use job description terminology while preserving facts
3. **Adjust skills**: Move relevant skills to top of each category, keep related ones
4. **Maintain chronological order**: ALWAYS keep experiences in reverse chronological order
5. **No fabrication**: Never invent skills, experiences, or achievements not in base profile
6. **Quantification**: Preserve all numbers/metrics from base profile
7. **Alternative tools**: If job asks for Tool X but profile has Tool Y (alternative), use Tool Y with context
   - Example: Job wants "Tableau" → Base has "Looker" → Keep "Looker", don't invent "Tableau"

### Cover Letter Principles
1. **Structure**: 
   - Salutation: "Dear Hiring Manager,"
   - Opening: Express interest in specific role/company
   - Body (2-3 paragraphs): Highlight relevant experiences with specifics
   - Closing: Thank + call to action
   - Signature: Name, phone, email
2. **Tone**: Professional but warm (see examples in `cover_letter_examples/`)
3. **Length**: 250-350 words
4. **Personalization**: Reference company name, role title, key requirements
5. **No generic claims**: Be specific with technologies, metrics, outcomes
6. **Reference base profile**: Pull from actual experiences, not invented

### Prompt Engineering
- **Context**: Provide full base profile + job description
- **Instructions**: Clear rules (no fabrication, chronological, etc.)
- **Format**: Specify exact JSON structure needed
- **Examples**: Few-shot examples in prompts for consistency
- **Constraints**: Max output tokens, temperature settings

---

## LaTeX CV Template (ATS Compliance)

### Requirements
- **ATS-friendly**: Simple formatting, proper text extraction, no complex graphics
- **Template engine**: Jinja2 for variable substitution
- **Base class**: Use `altacv.cls` (modified for simplicity)
- **Sections to include**:
  - Personal info (name, tagline, email, phone, LinkedIn, GitHub)
  - Professional summary
  - Professional experience (with projects nested)
  - Education
  - Certifications
  - Skills (6 categories)
  - Languages (NEW: add this section)
  - Collaboration tools (NEW: add this section under skills or separate)

### Template Location
`templates/cv/main.tex.jinja2`

### Compilation Pipeline
```python
# 1. Load template
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates/cv'))
template = env.get_template('main.tex.jinja2')

# 2. Render with data
latex_content = template.render(
    name=profile.identity.full_name,
    email=profile.identity.email,
    experiences=tailored_experiences,
    skills=tailored_skills,
    # ... etc
)

# 3. Save to temp file
temp_tex = f"outputs/{job_id}.tex"
with open(temp_tex, 'w', encoding='utf-8') as f:
    f.write(latex_content)

# 4. Compile with tectonic
subprocess.run([
    "tectonic",
    temp_tex,
    "-o", "outputs",
    "--keep-intermediates"  # Optional: for debugging
], check=True)

# 5. Return PDF path
return f"outputs/{job_id}.pdf"
```

### Error Handling
- Check tectonic installed: `tectonic --version`
- Handle LaTeX errors (syntax, missing packages)
- Validate PDF generation
- Clean up temp files (or keep for debugging)

---

## DOCX Cover Letter Template

### Template Engine: `docxtpl`
- Uses Jinja2 syntax within Word documents
- Placeholders: `{{ variable_name }}`
- Loops: `{% for item in items %} ... {% endfor %}`

### Template Location
`templates/cover_letter/cover_letter.docx`

### Required Placeholders
```
{{ company_name }}
{{ role_title }}
{{ current_date }}
{{ hiring_manager }}  # "Hiring Manager" as default
{{ opening_paragraph }}
{{ body_paragraph_1 }}
{{ body_paragraph_2 }}
{{ closing_paragraph }}
{{ candidate_name }}
{{ candidate_phone }}
{{ candidate_email }}
```

### Rendering Pipeline
```python
from docxtpl import DocxTemplate

template = DocxTemplate('templates/cover_letter/cover_letter.docx')
template.render({
    'company_name': 'Acme Corp',
    'role_title': 'Senior Data Analyst',
    'current_date': '2026-01-23',
    # ... etc
})
template.save(f'outputs/{job_id}_cover_letter.docx')
```

### Style Guidelines (from examples)
- Font: Professional (Calibri, Arial, Times New Roman)
- Spacing: 1.15 or 1.5 line spacing
- Length: 1 page maximum
- Margins: 1 inch all sides

---

## FastAPI Backend Endpoints

### Endpoint Design

#### `POST /api/tailor`
**Input**:
```json
{
  "job_description": "string",
  "company_name": "string (optional)",
  "role_title": "string (optional)"
}
```

**Process**:
1. Load base profile from YAML
2. Call Gemini to tailor CV (track tokens)
3. Call Gemini to generate cover letter (track tokens)
4. Render LaTeX → PDF
5. Render DOCX
6. Return job ID + metadata

**Output**:
```json
{
  "job_id": "uuid",
  "status": "success",
  "cv_path": "outputs/{job_id}.pdf",
  "cover_letter_path": "outputs/{job_id}_cover_letter.docx",
  "token_usage": {
    "cv_input_tokens": 1500,
    "cv_output_tokens": 2000,
    "cl_input_tokens": 1200,
    "cl_output_tokens": 800,
    "total_tokens": 5500,
    "estimated_cost_usd": 0.0022
  }
}
```

#### `GET /api/preview/{job_id}`
Returns PDF file for embedding in Streamlit

#### `GET /api/download/cv/{job_id}`
Downloads PDF

#### `GET /api/download/cover-letter/{job_id}`
Downloads DOCX

#### `GET /api/health`
Health check endpoint

### Error Responses
```json
{
  "error": "string",
  "detail": "string",
  "status_code": 400/500
}
```

---

## Streamlit UI Requirements

### Layout
```
Title: CV & Cover Letter Tailor

[Job Description]
┌─────────────────────────────────┐
│ Paste job description here...   │
│                                  │
│                                  │
└─────────────────────────────────┘

[Optional: Company Name] [Optional: Role Title]

[Generate Button] ← Primary action

---

[Preview Section]
┌─────────────────┬─────────────────┐
│ CV Preview      │ Cover Letter    │
│ (PDF embedded)  │ (Text preview)  │
│                 │                 │
│ [Download PDF]  │ [Download DOCX] │
└─────────────────┴─────────────────┘

[Token Usage & Cost]
Input Tokens: 1500 | Output Tokens: 2800 | Total: 4300
Estimated Cost: $0.0022 (within free tier)
```

### Features
- ✅ Text area for job description (required)
- ✅ Optional fields: company name, role title
- ✅ Generate button (disabled until job description entered)
- ✅ Loading spinner during generation
- ✅ PDF preview using `st.iframe()` or `st.download_button()`
- ✅ Cover letter text preview (first 500 chars)
- ✅ Download buttons for both files
- ✅ Token usage and cost display
- ✅ Error messages (friendly, actionable)

### Code Structure
```python
import streamlit as st
import requests

st.title("CV & Cover Letter Tailor")

job_desc = st.text_area("Job Description", height=300)
company = st.text_input("Company Name (optional)")
role = st.text_input("Role Title (optional)")

if st.button("Generate", disabled=not job_desc):
    with st.spinner("Generating tailored documents..."):
        response = requests.post("http://localhost:8000/api/tailor", json={
            "job_description": job_desc,
            "company_name": company,
            "role_title": role
        })
        
        if response.ok:
            data = response.json()
            # Display previews, downloads, costs
        else:
            st.error(f"Error: {response.json()['error']}")
```

---

## Error Handling Best Practices

### Gemini API Errors
- Rate limit exceeded → Wait and retry with exponential backoff
- Invalid API key → Clear error message to check `.env`
- JSON parsing failure → Retry up to 3 times, fallback to base profile
- Timeout → Increase timeout, show loading indicator

### LaTeX Compilation Errors
- Tectonic not found → Check installation, provide instructions
- Syntax errors → Log LaTeX errors, return friendly message
- Missing packages → Auto-install or document required packages
- Encoding issues → Always use UTF-8

### DOCX Template Errors
- Template not found → Check path, create default template
- Missing placeholders → Log warning, use defaults
- Rendering failures → Validate data types match placeholders

### File System Errors
- Outputs directory missing → Auto-create with `os.makedirs(exist_ok=True)`
- Permission denied → Check write permissions
- Disk space → Handle gracefully

### General
- Log all errors with context (job ID, timestamp, stack trace)
- Return user-friendly messages (not stack traces)
- Provide actionable next steps in error messages
- Validate inputs early (job description not empty, valid YAML, etc.)

---

## Testing & Validation

### Profile Validation Script
`backend/validate_profile.py`
```python
import yaml
from pydantic import ValidationError
from models.profile import BaseProfile

with open('storage/profile/profile.yaml') as f:
    data = yaml.safe_load(f)

try:
    profile = BaseProfile(**data)
    print("✅ Profile valid")
except ValidationError as e:
    print("❌ Validation errors:")
    print(e)
```

### Test Cases
1. ✅ Valid job description → Successful generation
2. ✅ Empty job description → Error message
3. ✅ Invalid YAML → Validation error
4. ✅ Gemini API failure → Fallback to base profile
5. ✅ LaTeX compilation error → Clear error message
6. ✅ Missing templates → Auto-create or error
7. ✅ Token limit exceeded → Rate limit handling

---

## Development Workflow with GitHub Copilot

### When to Use Copilot
- ✅ Implementing Pydantic models from YAML schema
- ✅ Writing Gemini API integration code
- ✅ Creating Jinja2 templates with proper escaping
- ✅ Building FastAPI routes with proper typing
- ✅ Streamlit UI components and layouts
- ✅ Error handling patterns
- ✅ Docstring generation

### Copilot Chat Prompts (Examples)
```
"Create a Pydantic model for the profile.yaml schema with nested experience and projects"

"Write a Gemini API call that returns structured JSON for CV tailoring with error handling"

"Generate a Jinja2 LaTeX template for the altacv class with these sections: {sections}"

"Create a FastAPI endpoint that accepts job description, calls tailor service, and returns job ID with token usage"

"Build a Streamlit UI with job description input, preview, and download buttons"
```

### Best Practices
- Reference this file in Copilot chat: "@workspace follow instructions in .github/copilot-instructions.md"
- Use type hints for better Copilot suggestions
- Write clear function/class names
- Add docstrings for complex logic
- Test incrementally

---

## Deployment Considerations (Future)

### Local Development (Current)
- Backend: `uvicorn main:app --reload`
- UI: `streamlit run app.py`
- No authentication needed

### Future Enhancements
- 🔜 Docker containerization
- 🔜 Cloud deployment (Railway, Render, Fly.io)
- 🔜 User authentication
- 🔜 Job history storage
- 🔜 Batch processing multiple jobs
- 🔜 Email delivery of documents
- 🔜 Alternative LLMs (Claude, GPT-4)

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `.env` | Gemini API key and config (gitignored) |
| `requirements.txt` | Python dependencies |
| `storage/profile/profile.yaml` | Base CV content (ground truth) |
| `templates/cv/main.tex.jinja2` | LaTeX CV template |
| `templates/cv/altacv.cls` | LaTeX document class |
| `templates/cover_letter/cover_letter.docx` | DOCX template |
| `backend/main.py` | FastAPI app entry point |
| `backend/services/gemini_service.py` | Gemini API integration |
| `backend/renderers/latex_renderer.py` | LaTeX → PDF pipeline |
| `backend/renderers/docx_renderer.py` | DOCX generation |
| `ui/app.py` | Streamlit UI |
| `cover_letter_examples/` | 87 sample cover letters for reference |

---

## Quick Commands

### Setup
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env with GEMINI_API_KEY
```

### Run
```bash
# Terminal 1: Backend
cd backend
uvicorn main:app --reload

# Terminal 2: UI
cd ui
streamlit run app.py
```

### Test
```bash
python backend/validate_profile.py
pytest
```

### LaTeX Debug
```bash
tectonic outputs/test.tex -o outputs --keep-intermediates
```

---

**Last Updated**: 2026-01-23
**Python Version**: 3.14+
**LLM**: Google Gemini 1.5 Flash
**Maintainer**: Sreedeep Sreekanth
