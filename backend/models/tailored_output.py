from __future__ import annotations

from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict, field_validator, field_validator


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
    closing_line: str = "Sincerely,"
    signature_name: str = ""
