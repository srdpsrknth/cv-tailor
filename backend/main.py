# cv-tailor/backend/main.py

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from models.requests import TailorRequest, TailorResponse
from services.profile_loader import load_profile
from services.tailor_service import tailor_documents


load_dotenv(override=True)

app = FastAPI(title="cv-tailor-backend", version="0.1.0")

# Base outputs directory
OUTPUTS_DIR = Path(__file__).resolve().parents[1] / "outputs"


def _slugify(text: str) -> str:
    """Filesystem-safe slug (match renderer behavior)."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "role"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/tailor", response_model=TailorResponse)
def tailor(req: TailorRequest):
    try:
        profile = load_profile()
        result = tailor_documents(
            job_description=req.job_description,
            profile=profile,
            company_name=req.company_name,
            role_title=req.role_title,
        )
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@app.get("/api/download/cv/{job_id}")
def download_cv(job_id: str):
    """Download the generated CV PDF by job_id (filename stem)."""
    pdf_path = OUTPUTS_DIR / f"{job_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"CV PDF not found for job_id: {job_id}")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@app.get("/api/preview/{job_id}")
def preview_cv(job_id: str):
    """Return the CV PDF for inline preview embedding."""
    pdf_path = OUTPUTS_DIR / f"{job_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"CV PDF not found for job_id: {job_id}")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@app.get("/api/download/cover-letter/{job_id}")
def download_cover_letter(job_id: str):
    """
    Download the generated cover letter DOCX inferred from the CV job_id.

    job_id format from renderer: {year}_CV_{full_name_slug}_{job_slug}
    We map to DOCX: {year}_cover_letter_{company_slug}_{job_slug}.docx
    """
    # Extract year and job slug from job_id
    try:
        parts = job_id.split("_")
        year = parts[0]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    profile = load_profile()
    full_name_slug = _slugify(profile.identity.full_name)

    prefix = f"{year}_CV_{full_name_slug}_"
    if job_id.startswith(prefix):
        job_slug = job_id[len(prefix):]
    else:
        # Fallback: use trailing part as job slug
        job_slug = parts[-1]

    # Find a matching DOCX: {year}_cover_letter_*_{job_slug}.docx
    matches = list(OUTPUTS_DIR.glob(f"{year}_cover_letter_*_{job_slug}.docx"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Cover letter not found for job_id: {job_id}")

    docx_path = matches[0]
    return FileResponse(
        path=str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=docx_path.name,
    )
