from __future__ import annotations

from typing import List, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict


# -------------------------
# Core identity information
# -------------------------

class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    tagline: Optional[str] = None
    email: str
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    location: Optional[str] = None
    visa_status: Optional[str] = None


# -------------------------
# Experience sub-structures
# -------------------------

class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    bullets: List[str] = Field(default_factory=list)


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    location: Optional[str] = None
    role: str
    start_date: str          # YYYY-MM
    end_date: str            # YYYY-MM or "present"
    bullets: List[str] = Field(default_factory=list)
    selected_projects: List[Project] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)


# -------------------------
# Education & languages
# -------------------------

class Education(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degree: str
    institution: str
    location: Optional[str] = None
    start_year: int
    end_year: int


class Language(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    proficiency: str


# -------------------------
# Root profile model
# -------------------------

class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    identity: Identity
    summary_base: List[str] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    skills: Dict[str, List[str]] = Field(default_factory=dict)
    languages: List[Language] = Field(default_factory=list)
