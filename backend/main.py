# cv-tailor/backend/main.py

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from config import Config
from models.requests import TailorRequest, TailorResponse
from services.profile_loader import load_profile
from services.tailor_service import tailor_documents


app = FastAPI(title="cv-tailor-backend", version="0.1.0")


def get_config() -> Config:
    """Resolve configuration per request rather than at import time.

    Rebuilding it here means editing ``.env`` (or changing ``OUTPUTS_DIR``) takes
    effect without restarting the process, and no environment read happens merely
    by importing this module.
    """
    return Config.from_env()


def outputs_dir() -> Path:
    """The directory download endpoints resolve ``job_id`` against."""
    return get_config().outputs_dir


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
            work_country=req.work_country,
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
    """Download the generated CV PDF by job_id (in job-specific folder)."""
    pdf_path = outputs_dir() / job_id / f"{job_id}.pdf"

    # Generated CV filenames differ from job_id; exclude cover-letter PDFs.
    if not pdf_path.exists():
        job_folder = outputs_dir() / job_id
        if job_folder.exists():
            pdfs = [p for p in job_folder.glob("*.pdf") if "cover_letter" not in p.name.lower()]
            if pdfs:
                pdf_path = pdfs[0]

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
    Download the generated cover letter DOCX from job-specific folder.
    """
    job_folder = outputs_dir() / job_id

    if not job_folder.exists():
        raise HTTPException(status_code=404, detail=f"Job folder not found: {job_id}")

    # Find DOCX file in job folder
    docx_files = list(job_folder.glob("*.docx"))
    if not docx_files:
        raise HTTPException(status_code=404, detail=f"Cover letter DOCX not found for job_id: {job_id}")

    docx_path = docx_files[0]
    return FileResponse(
        path=str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=docx_path.name,
    )


@app.get("/api/download/cover-letter-pdf/{job_id}")
def download_cover_letter_pdf(job_id: str):
    """
    Download the generated cover letter PDF from job-specific folder.
    """
    job_folder = outputs_dir() / job_id

    if not job_folder.exists():
        raise HTTPException(status_code=404, detail=f"Job folder not found: {job_id}")

    # Find PDF file in job folder (exclude CV PDF by looking for cover_letter pattern)
    pdf_files = [p for p in job_folder.glob("*.pdf") if "cover_letter" in p.name or p.stem.endswith("cover_letter")]
    if not pdf_files:
        # Fallback: any PDF that isn't the CV
        all_pdfs = list(job_folder.glob("*.pdf"))
        pdf_files = [p for p in all_pdfs if p.stem != job_id]

    if not pdf_files:
        raise HTTPException(status_code=404, detail=f"Cover letter PDF not found for job_id: {job_id}")

    pdf_path = pdf_files[0]
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


