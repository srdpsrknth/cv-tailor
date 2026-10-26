# cv-tailor/backend/main.py

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from config import Config
from models.requests import TailorRequest, TailorResponse
from services.profile_store import ProfileStoreError
from services.tailor_service import tailor_documents


app = FastAPI(title="cv-tailor-backend", version="0.1.0")

#: A job folder name, as produced by ``make_job_id``. Validated on every download
#: route: FastAPI's default ``str`` converter is ``[^/]+``, which already rejects
#: ``../../etc/x``, but this closes the encoded and backslash variants too
#: (ASSESSMENT.md §6).
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def get_config() -> Config:
    """Resolve configuration per request rather than at import time.

    Rebuilding it here means editing ``.env`` (or changing ``CVTAILOR_STORE``)
    takes effect without restarting the process, and no environment read happens
    merely by importing this module.
    """
    return Config.from_env()


def resolve_profile_id(config: Config, explicit: Optional[str]) -> str:
    """Resolve the candidate for a request, or fail closed (ADR 0003).

    The API is an adapter over the same service the CLI uses, so it resolves
    identity the same way: an explicit value wins, otherwise the configured id.
    There is deliberately no third step that picks "the only profile" in the store.
    """
    from services.profile_store import resolve_profile_id as _resolve

    return _resolve(config, explicit)


def job_folder(config: Config, profile_id: str, job_id: str) -> Path:
    """The folder a download resolves against: ``<store>/outputs/<id>/<job_id>``.

    The candidate segment is part of the path (ADR 0003, A-9), so this cannot use
    ``config.outputs_dir`` -- that is the optional *mirror*, which is a different
    thing and may not be set at all.
    """
    if not JOB_ID_PATTERN.match(job_id):
        raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id!r}")
    return config.store.outputs_dir(profile_id) / job_id


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/tailor", response_model=TailorResponse)
def tailor(req: TailorRequest):
    config = get_config()
    try:
        # Resolve the candidate through the store, exactly as the CLI does. The
        # old `load_profile()` call read the pre-Phase-2 default path and would
        # happily tailor a stale duplicate profile (ADR 0003 forbids that).
        profile_id = resolve_profile_id(config, req.profile_id)
        profile = config.store.load(profile_id)
    except ProfileStoreError as e:
        # A missing, malformed or unknown id is the caller's mistake, not a server
        # fault, so it is a 400. `ProfileStoreError` is deliberately not a
        # ValueError, so it must be named explicitly here.
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = tailor_documents(
            job_description=req.job_description,
            profile=profile,
            company_name=req.company_name,
            role_title=req.role_title,
            work_country=req.work_country,
            config=config,
            profile_id=profile_id,
        )
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@app.get("/api/download/cv/{job_id}")
def download_cv(job_id: str, profile_id: Optional[str] = None):
    """Download the generated CV PDF by job_id (in job-specific folder)."""
    config = get_config()
    folder = job_folder(config, resolve_profile_id(config, profile_id), job_id)
    pdf_path = folder / f"{job_id}.pdf"

    # Generated CV filenames differ from job_id; exclude cover-letter PDFs.
    if not pdf_path.exists():
        if folder.exists():
            pdfs = [p for p in folder.glob("*.pdf") if "cover_letter" not in p.name.lower()]
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
def download_cover_letter(job_id: str, profile_id: Optional[str] = None):
    """
    Download the generated cover letter DOCX from job-specific folder.
    """
    config = get_config()
    folder = job_folder(config, resolve_profile_id(config, profile_id), job_id)

    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Job folder not found: {job_id}")

    # Find DOCX file in job folder
    docx_files = list(folder.glob("*.docx"))
    if not docx_files:
        raise HTTPException(status_code=404, detail=f"Cover letter DOCX not found for job_id: {job_id}")

    docx_path = docx_files[0]
    return FileResponse(
        path=str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=docx_path.name,
    )


@app.get("/api/download/cover-letter-pdf/{job_id}")
def download_cover_letter_pdf(job_id: str, profile_id: Optional[str] = None):
    """
    Download the generated cover letter PDF from job-specific folder.
    """
    config = get_config()
    folder = job_folder(config, resolve_profile_id(config, profile_id), job_id)

    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Job folder not found: {job_id}")

    # Find PDF file in job folder (exclude CV PDF by looking for cover_letter pattern)
    pdf_files = [p for p in folder.glob("*.pdf") if "cover_letter" in p.name or p.stem.endswith("cover_letter")]
    if not pdf_files:
        # Fallback: any PDF that isn't the CV
        all_pdfs = list(folder.glob("*.pdf"))
        pdf_files = [p for p in all_pdfs if p.stem != job_id]

    if not pdf_files:
        raise HTTPException(status_code=404, detail=f"Cover letter PDF not found for job_id: {job_id}")

    pdf_path = pdf_files[0]
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


