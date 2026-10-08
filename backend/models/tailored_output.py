from __future__ import annotations

from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict


# -------------------------
# Tailoring explanation (structured)
# -------------------------

class TailoringExplanation(BaseModel):
    """Structured explanation of CV tailoring decisions."""
    model_config = ConfigDict(extra="ignore")

    summary_changes: str = Field(default="", description="How the summary was crafted")
    bullet_modifications: str = Field(default="", description="Key rewording decisions for bullets")
    skill_reordering: str = Field(default="", description="How skills were prioritized")
    project_selection: str = Field(default="", description="Which projects included and why")
    overall_strategy: str = Field(default="", description="High-level tailoring approach")


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
    projects: List[TailoredProject] = Field(default_factory=list)


class TailoredCV(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    work_authorization: Optional[str] = Field(default=None, description="Application-specific immigration label; None preserves profile status")
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
    closing_line: str = "Sincerely,"
    signature_name: str = ""


class TailoredOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cv: TailoredCV
    cover_letter: TailoredCoverLetter
    tailoring_explanation: Optional[TailoringExplanation] = None
