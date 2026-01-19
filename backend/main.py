# cv-tailor/backend/main.py

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from dotenv import load_dotenv
from openai import OpenAI

from backend.models.tailored_output import TailoredOutput
from backend.services.profile_loader import load_profile
from backend.services.tailor_service import tailor_documents


# Force-load backend/.env for the API process as well (safe even if already loaded)
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

app = FastAPI(title="cv-tailor-backend", version="0.1.0")


class TailorRequest(BaseModel):
    job_description: str = Field(..., min_length=10)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/openai")
def health_openai():
    """
    Lightweight check: verifies the backend can talk to OpenAI with the configured key.
    Note: If your account has no quota/billing, this may still fail with 429.
    """
    client = OpenAI()
    try:
        client.models.list()
        return {"openai": "ok"}
    except Exception as e:
        return {"openai": "error", "detail": str(e)}


@app.post("/tailor", response_model=TailoredOutput)
def tailor(req: TailorRequest):
    try:
        profile = load_profile()
        result = tailor_documents(job_description=req.job_description, profile=profile)
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    except ValueError as e:
        # Includes: empty JD, OpenAI auth/quota errors (mapped in tailor_service),
        # JSON decode failures, and Pydantic validation errors
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
