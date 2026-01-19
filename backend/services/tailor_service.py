# cv-tailor/backend/services/tailor_service.py

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from openai import APIError, RateLimitError, AuthenticationError

from backend.models.tailored_output import TailoredOutput
from backend.models.profile import Profile


# Force-load backend/.env no matter where uvicorn is started from
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

# Safe debug log (prints only prefix + length)
_loaded = os.getenv("OPENAI_API_KEY", "")
print(f"[cv-tailor] Loaded OPENAI_API_KEY prefix: {_loaded[:7]} (len={len(_loaded)}) from {ENV_PATH}")

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tailor_prompt.md"


def tailor_documents(job_description: str, profile: Profile) -> TailoredOutput:
    """
    Calls OpenAI and returns strictly validated structured output.
    """
    if not job_description.strip():
        raise ValueError("Job description is empty.")

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    client = OpenAI()

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "JOB DESCRIPTION:\n"
                        f"{job_description}\n\n"
                        "BASE PROFILE (JSON):\n"
                        f"{profile.model_dump_json(indent=2)}"
                    ),
                },
            ],
            temperature=0.2,
        )
    except AuthenticationError as e:
        raise ValueError("OpenAI authentication failed. Check OPENAI_API_KEY.") from e
    except RateLimitError as e:
        raise ValueError(
            "OpenAI rate limit / quota exceeded (HTTP 429). "
            "Check your OpenAI plan/billing and try again."
        ) from e
    except APIError as e:
        raise ValueError(f"OpenAI API error: {e}") from e

    text = resp.choices[0].message.content or ""
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON. Raw output:\n{text}") from e

    return TailoredOutput.model_validate(data)
