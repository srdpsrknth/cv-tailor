from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CVExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    start_date: str
    end_date: str
    bullets: List[str] = Field(default_factory=list)
    selected_project_names: List[str] = Field(default_factory=list)
    project_bullets: List[str] = Field(default_factory=list)


class CV(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    summary: List[str] = Field(default_factory=list)
    skills: Dict[str, List[str]] = Field(default_factory=dict)
    experience: List[CVExperience] = Field(default_factory=list)
    include_education: bool
    include_certifications: bool


class CoverLetter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_title: str
    company_name: str
    paragraphs: List[str] = Field(default_factory=list)
    highlight_bullets: List[str] = Field(default_factory=list)
    closing_line: str
    signature_name: str


class TailoredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cv: CV
    cover_letter: CoverLetter
    confidence: Literal["low", "medium", "high"]
    notes: List[str] = Field(default_factory=list)
