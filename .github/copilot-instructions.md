# Project: cv-tailor

## Goal
A tool that takes a job description and produces:
1) Tailored CV in LaTeX -> compiled to PDF
2) Tailored cover letter as DOCX
UI must preview and allow download of both.

## Architecture
- ui/: Streamlit UI (ui/app.py). Calls backend via REST.
- backend/: FastAPI backend. Owns OpenAI calls and document rendering.
- templates/cv/: LaTeX template (.tex)
- templates/cover_letter/: DOCX template with placeholders
- storage/profile/: base profile content (YAML/JSON) used as ground truth
- outputs/: generated files (PDF/DOCX)

## Security rules
- NEVER put OPENAI_API_KEY in Streamlit or any frontend.
- Only backend reads OPENAI_API_KEY from backend/.env.

## Engineering rules
- OpenAI outputs MUST be structured JSON matching Pydantic models.
- Keep prompts in backend/prompts/ as versioned files.
- Rendering:
  - use `tectonic` CLI for LaTeX->PDF
  - use `docxtpl` for DOCX templating
- Add robust error handling for: missing templates, invalid JSON, OpenAI failures, render failures.

## UX requirements (Streamlit)
- Text area for job description
- Button to generate
- Preview PDF (embedded)
- Show cover letter text preview (and DOCX download)
- Download buttons for PDF and DOCX
