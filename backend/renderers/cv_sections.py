"""Plain-text wording for the richer CV sections, shared by every output.

The PDF, the DOCX/TXT upload export, the extraction contract and the saved-application
review must all show exactly the same words for project metadata, education highlights
and structured certifications, so the wording is decided once, here, as text. Callers
escape or style it for their own medium.
"""
from __future__ import annotations

from typing import Optional

from models.profile import Education, Experience, Project

#: Separator for education highlights. One compact metadata line under the degree.
HIGHLIGHT_SEPARATOR = " · "


def project_meta(project: Project) -> str:
    """``— context | dates`` (either part optional), shown after the project name."""
    context = (project.context or "").strip()
    dates = (project.dates or "").strip()
    meta = f"— {context}" if context else ""
    if dates:
        meta = f"{meta} | {dates}" if meta else f"| {dates}"
    return meta


def project_heading(project: Project) -> str:
    """``Name — context | dates``: the project's name plus whatever metadata is set."""
    meta = project_meta(project)
    return f"{project.name} {meta}" if meta else project.name


def project_technologies_line(project: Project) -> Optional[str]:
    """``Technologies: a, b``, laid out like an employer role's line."""
    items = [item.strip() for item in project.technologies if item.strip()]
    return "Technologies: " + ", ".join(items) if items else None


def education_highlights_line(education: Education) -> Optional[str]:
    items = [item.strip() for item in education.highlights if item.strip()]
    return HIGHLIGHT_SEPARATOR.join(items) if items else None


def role_company_label(role: Optional[Experience], company: str) -> str:
    """The short company name for compact places, else the full employer name."""
    short = (getattr(role, "display_name", None) or "").strip()
    return short or company


def find_role(profile, company: str) -> Optional[Experience]:
    """The profile role for ``company`` when it is unambiguous."""
    matches = [row for row in profile.experience if row.company == company]
    return matches[0] if len(matches) == 1 else None


def find_profile_project(role: Optional[Experience], name: str) -> Optional[Project]:
    """The profile's selected project of ``role`` with this name, if any."""
    if role is None:
        return None
    wanted = name.strip().casefold()
    return next((p for p in role.selected_projects if p.name.strip().casefold() == wanted), None)


def project_as_subheading(exp, show_projects: bool = True) -> bool:
    """A role with no regular bullets and exactly one project drops the label.

    ``Selected Projects:`` and the company parenthetical say nothing when the project
    *is* the role's content, so the project name stands alone as an italic subheading.
    """
    return bool(show_projects and not exp.bullets and len(exp.projects) == 1)
