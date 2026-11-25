from __future__ import annotations

from typing import List, Optional, Dict, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator

from models.profile import Profile, Project


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
    #: Either a profile project name (rendered with the profile's bullets verbatim) or
    #: ``{name, bullets}`` with bullets reworded toward the posting.
    standalone_projects: List[Union[str, TailoredProject]] = Field(default_factory=list)

    def standalone_project_names(self) -> List[str]:
        return [item if isinstance(item, str) else item.name for item in self.standalone_projects]

    def resolve_standalone_projects(self, profile: Profile) -> List[Project]:
        """Resolve the selection against the profile used for this CV.

        A name yields the profile's project unchanged. An object keeps the profile's
        name, dates, context and technologies and takes the tailored bullets, after the
        structural checks below. Whether those bullets are *factual* is
        ``validate_cv``'s job; this only guarantees the shape the renderers rely on.
        """
        available = {project.name: project for project in profile.standalone_projects}
        names = self.standalone_project_names()
        if len(names) != len(set(names)) or any(name not in available for name in names):
            raise ValueError("Select distinct standalone project names exactly as written in the profile.")
        resolved: List[Project] = []
        for item in self.standalone_projects:
            if isinstance(item, str):
                resolved.append(available[item])
                continue
            source = available[item.name]
            bullets = [bullet.strip() for bullet in item.bullets]
            if not source.bullets:
                raise ValueError(
                    f"Standalone project {item.name!r} has no profile bullets to reword; "
                    "select it by name only."
                )
            if not bullets or any(not bullet for bullet in bullets) or len(bullets) > len(source.bullets) + 1:
                raise ValueError(
                    f"Standalone project {item.name!r} needs between 1 and "
                    f"{len(source.bullets) + 1} non-empty bullets (the profile has {len(source.bullets)})."
                )
            resolved.append(source.model_copy(update={"bullets": bullets}))
        return resolved

    @field_validator("skills", mode="before")
    @classmethod
    def _accept_skills_as_a_list(cls, value):
        """Accept ``[{category, items}, ...]`` as well as ``{category: [items]}``.

        **A free-form map cannot be expressed in a strict schema dialect**, so a model
        asked with ``additionalProperties: false`` must be asked for the array spelling
        instead -- ``{category, items}`` entries carry exactly the same document. The
        request differs; the *document* must not.

        So both spellings normalise here into the dict the renderers and every existing
        consumer already expect. Without this the reshape would be a request the
        validator then rejects, which is what happened on the first live attempt: both
        models returned the array correctly and were refused for it.

        Anything else is passed through untouched, so a genuinely malformed ``skills``
        still fails validation rather than being coerced into something plausible.
        """
        if not isinstance(value, list):
            return value
        normalised: Dict[str, List[str]] = {}
        for entry in value:
            if not isinstance(entry, dict):
                return value
            category = entry.get("category")
            items = entry.get("items")
            if not isinstance(category, str) or not isinstance(items, list):
                return value
            normalised[category] = [str(item) for item in items]
        return normalised


# -------------------------
# Cover letter output (structured)
# -------------------------

class TailoredCoverLetter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role_title: str
    company_name: str
    paragraphs: List[str] = Field(default_factory=list)
    closing_line: str = "Warm regards,"
    signature_name: str = ""
