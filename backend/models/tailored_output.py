from __future__ import annotations

from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field, ConfigDict


# -------------------------
# CV output (structured)
# -------------------------

class TailoredExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    start_date: str
    end_date: str
    # IMPORTANT: bullets must be rewritten versions of existing bullets from profile.yaml
    bullets: List[str] = Field(default_factory=list)

    # Optional: if we include 0-1 projects per role
    selected_project_names: List[str] = Field(default_factory=list)
    project_bullets: List[str] = Field(default_factory=list)


class TailoredCV(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Tailored headline / summary
    title: Optional[str] = None
    summary: List[str] = Field(default_factory=list)

    # Skills are reordered and optionally subsetted, but must come from profile.yaml categories/items
    skills: Dict[str, List[str]] = Field(default_factory=dict)

    # Experiences can be subset/reordered
    experience: List[TailoredExperience] = Field(default_factory=list)

    # Education & certifications usually unchanged; we include them to render deterministically
    include_education: bool = True
    include_certifications: bool = True


# -------------------------
# Cover letter output (structured)
# -------------------------

class TailoredCoverLetter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # We will map these into a DOCX template
    role_title: str
    company_name: str

    # Body split into paragraphs for safe templating
    paragraphs: List[str] = Field(default_factory=list)

    # Optional: bullets (sometimes cover letters have a small achievement list)
    highlight_bullets: List[str] = Field(default_factory=list)

    closing_line: str = "Sincerely,"
    signature_name: str = ""


class TailoredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cv: TailoredCV
    cover_letter: TailoredCoverLetter

    # Safety/debug fields
    confidence: Literal["low", "medium", "high"] = "medium"
    notes: List[str] = Field(default_factory=list)
