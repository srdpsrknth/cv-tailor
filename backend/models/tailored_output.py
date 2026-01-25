from __future__ import annotations

from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field, ConfigDict


# -------------------------
# CV output (structured)
# -------------------------

class TailoredProject(BaseModel):
    """Individual project with its own bullets."""
    model_config = ConfigDict(extra="ignore")
    
    name: str
    bullets: List[str] = Field(default_factory=list)


class TailoredExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company: str
    role: str
    start_date: str
    end_date: str
    bullets: List[str] = Field(default_factory=list)
    # Legacy fields for backward compatibility
    selected_project_names: List[str] = Field(default_factory=list)
    project_bullets: List[str] = Field(default_factory=list)
    # New field for proper project structure
    projects: List[TailoredProject] = Field(default_factory=list)


class TailoredCV(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    summary: List[str] = Field(default_factory=list)
    skills: Dict[str, List[str]] = Field(default_factory=dict)
    experience: List[TailoredExperience] = Field(default_factory=list)
    include_education: bool = True
    include_certifications: bool = True


# -------------------------
# Cover letter output (structured)
# -------------------------

class TailoredCoverLetter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role_title: str
    company_name: str
    paragraphs: List[str] = Field(default_factory=list)
    highlight_bullets: List[str] = Field(default_factory=list)
    closing_line: str = "Sincerely,"
    signature_name: str = ""


class TailoredOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cv: TailoredCV
    cover_letter: TailoredCoverLetter
    confidence: Literal["low", "medium", "high"] = "medium"
    notes: List[str] = Field(default_factory=list)
    tailoring_explanation: Optional[str] = None
