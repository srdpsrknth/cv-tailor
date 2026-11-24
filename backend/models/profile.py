from __future__ import annotations

from typing import List, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator


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
    end_year: Optional[int] = None
    ongoing: bool = False

    @model_validator(mode="after")
    def validate_completion(self):
        if not self.ongoing and self.end_year is None:
            raise ValueError("completed education requires an end_year")
        return self

    def end_date_label(self) -> str:
        if self.ongoing:
            return "Present" if self.end_year is None else f"Present (expected {self.end_year})"
        return str(self.end_year)

    def date_range(self, separator: str = " - ") -> str:
        return f"{self.start_year}{separator}{self.end_date_label()}"


class Language(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    proficiency: str


# -------------------------
# Candidate-specific validation rules
# -------------------------

class EmployerRules(BaseModel):
    """Bespoke rules for one employer, e.g. how its projects may be described."""
    model_config = ConfigDict(extra="forbid")

    project_count: Optional[int] = None
    bullets_per_project: Optional[int] = None
    forbidden_project_name: Optional[str] = None
    ongoing_tool: Optional[str] = None
    ownership_pattern: Optional[str] = None
    ownership_message: Optional[str] = None


class CountryApplicationRules(BaseModel):
    """Confirmed candidate-specific authorization and tailoring for one country."""
    model_config = ConfigDict(extra="forbid")

    # An empty label explicitly suppresses the profile's default immigration status.
    work_authorization: str = ""
    requires_employer_support: bool = True
    authorization_basis: Optional[str] = None
    tailoring_guidance: Optional[str] = None


class ProfileRules(BaseModel):
    """Validation rules scoped to one candidate.

    These used to be hardcoded in the validator, so a second candidate was checked
    against the first candidate's employers, banned tools and immigration wording
    (A-1). Declaring them in the profile keeps validation honest per candidate.

    Everything is optional: a profile with no ``rules`` block is validated by the
    generic rules alone, which is correct for a candidate with no special cases.
    """
    model_config = ConfigDict(extra="forbid")

    #: Employer-specific rules, keyed by a lowercase substring of the company name.
    employers: Dict[str, EmployerRules] = Field(default_factory=dict)

    #: Technologies this candidate cannot evidence; claiming one is an error.
    banned_tools: List[str] = Field(default_factory=list)

    #: Regex for third-person verbs and aspirations forbidden in the CV summary.
    summary_forbidden_verbs: Optional[str] = None

    #: Immigration label substituted into the CV for non-home work countries.
    visa_label: Optional[str] = None
    #: Countries considered home, where no visa label is added.
    home_countries: List[str] = Field(default_factory=list)
    #: Countries that issue their own permit, so an EU Blue Card must not be claimed.
    local_permit_countries: List[str] = Field(default_factory=list)
    country_overrides: Dict[str, CountryApplicationRules] = Field(default_factory=dict)


# -------------------------
# Root profile model
# -------------------------

class JobSearchDefaults(BaseModel):
    """Optional starting filters for this candidate's job searches."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    keywords: str = ""
    country: str = ""
    city: str = ""
    remote_only: bool = False


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
    rules: Optional[ProfileRules] = None
    job_search: Optional[JobSearchDefaults] = None
