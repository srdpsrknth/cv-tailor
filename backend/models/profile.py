from __future__ import annotations

from typing import Annotated, Any, ClassVar, List, Dict, Literal, Optional, Union
from pydantic import (
    BaseModel, Field, ConfigDict, StringConstraints, field_validator, model_serializer,
    model_validator,
)


CVSection = Literal["experience", "projects", "education", "certifications", "skills", "languages",
                    "publications", "activities"]
DEFAULT_CV_SECTION_ORDER = ("experience", "projects", "education", "certifications", "skills", "languages",
                            "publications", "activities")
CVEntry = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^\r\n]+$")]


class _OmitDefaultsWhenNew(BaseModel):
    """Serialise newer optional fields only when they carry a value.

    Fields added after profiles already existed (dates, highlights, ``optional`` ...)
    are dropped from ``model_dump`` while they hold their default. That keeps the
    profile bytes shown to the model, and therefore the generation cache key and the
    saved profile snapshot, identical for every profile that does not use them, and
    changes them as soon as one is set.
    """

    _omit_when_default: ClassVar[tuple] = ()

    @model_serializer(mode="wrap")
    def _serialise_without_unused_new_fields(self, handler) -> Any:
        data = handler(self)
        if isinstance(data, dict):
            for name in self._omit_when_default:
                if name in data and data[name] == self.__class__.model_fields[name].get_default(
                    call_default_factory=True
                ):
                    del data[name]
        return data


def resolve_cv_section_order(preferred, hidden=()):
    """Put listed sections first and append the remainder in their default order."""
    preferred = preferred if isinstance(preferred, list) else []
    known = (section for section in preferred if section in DEFAULT_CV_SECTION_ORDER)
    return tuple(section for section in dict.fromkeys((*known, *DEFAULT_CV_SECTION_ORDER))
                 if section not in hidden)


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

class Project(_OmitDefaultsWhenNew):
    model_config = ConfigDict(extra="forbid")
    _omit_when_default = ("dates", "technologies", "context")

    name: str
    bullets: List[str] = Field(default_factory=list)
    #: Free-text period, e.g. "2024" or "Mar 2024 - Jun 2024". Shown, never parsed.
    dates: Optional[str] = None
    technologies: List[str] = Field(default_factory=list)
    #: What kind of work this was, e.g. "University team project".
    context: Optional[str] = None


class Experience(_OmitDefaultsWhenNew):
    model_config = ConfigDict(extra="forbid")
    _omit_when_default = ("optional", "display_name")

    company: str
    #: Short company name for compact places (the project parenthetical).
    display_name: Optional[str] = None
    #: An optional role may be left out of a tailored CV when irrelevant or for space.
    optional: bool = False
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

class Education(_OmitDefaultsWhenNew):
    model_config = ConfigDict(extra="forbid")
    _omit_when_default = ("highlights",)

    degree: str
    institution: str
    location: Optional[str] = None
    start_year: int
    end_year: Optional[int] = None
    ongoing: bool = False
    #: Coursework, thesis title, focus. Rendered as one compact line under the degree.
    highlights: List[str] = Field(default_factory=list)

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


class Certification(BaseModel):
    """A certification with provenance; a bare string stays valid."""
    model_config = ConfigDict(extra="forbid")

    name: CVEntry
    issuer: Optional[str] = None
    year: Optional[str] = None

    @field_validator("year", mode="before")
    @classmethod
    def _year_may_be_a_number(cls, value):
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else value

    def label(self) -> str:
        details = ", ".join(part.strip() for part in (self.issuer, self.year) if part and part.strip())
        return f"{self.name} ({details})" if details else self.name


class CVEntryWithBullets(BaseModel):
    """A publication or activity with supporting bullets.

    ``text`` is the citation or headline and is always rendered verbatim.
    """
    model_config = ConfigDict(extra="forbid")

    text: CVEntry
    bullets: List[str] = Field(default_factory=list)


def entry_text(entry) -> str:
    """The headline text of a publication/activity, whichever spelling it uses."""
    return entry if isinstance(entry, str) else entry.text


def entry_bullets(entry) -> List[str]:
    return [] if isinstance(entry, str) else list(entry.bullets)


def certification_label(entry) -> str:
    """``name (issuer, year)`` for a structured certification; a string verbatim."""
    return entry if isinstance(entry, str) else entry.label()


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


class Profile(_OmitDefaultsWhenNew):
    model_config = ConfigDict(extra="forbid")
    _omit_when_default = ("standalone_projects_policy",)

    version: str
    identity: Identity
    summary_base: List[str] = Field(default_factory=list)
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    certifications: List[Union[str, Certification]] = Field(default_factory=list)
    skills: Dict[str, List[str]] = Field(default_factory=dict)
    languages: List[Language] = Field(default_factory=list)
    rules: Optional[ProfileRules] = None
    job_search: Optional[JobSearchDefaults] = None
    standalone_projects: List[Project] = Field(default_factory=list)
    publications: List[Union[CVEntry, CVEntryWithBullets]] = Field(default_factory=list)
    activities: List[Union[CVEntry, CVEntryWithBullets]] = Field(default_factory=list)
    #: "select": the model chooses which standalone projects to show.
    #: "all": every one appears, in profile order.
    standalone_projects_policy: Literal["select", "all"] = "select"
    cv_section_order: List[CVSection] = Field(default_factory=list)
    cv_hidden_sections: List[CVSection | Literal["summary", "employer_projects"]] = Field(default_factory=list)

    @field_validator("cv_section_order", "cv_hidden_sections")
    @classmethod
    def validate_cv_section_order(cls, order):
        if len(order) != len(set(order)):
            raise ValueError("CV section preferences must not repeat a section.")
        return order

    def visible_cv_sections(self):
        return resolve_cv_section_order(self.cv_section_order, self.cv_hidden_sections)

    @model_validator(mode="after")
    def validate_standalone_projects(self):
        names = [project.name.strip().casefold() for project in self.standalone_projects]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Standalone project names must be nonempty and unique.")
        return self
