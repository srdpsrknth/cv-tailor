"""Plain-text wording for the richer CV sections, shared by every output.

The PDF, the DOCX/TXT upload export, the extraction contract and the saved-application
review must all show exactly the same words for project metadata, education highlights
and structured certifications, so the wording is decided once, here, as text. Callers
escape or style it for their own medium.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from models.profile import Education, Experience, Profile, Project
from models.tailored_output import TailoredExperience

#: Section titles, decided once. The PDF upper-cases them; DOCX/TXT show them as written.
#: ``summary`` is deliberately DOCX/TXT only: the PDF shows the summary as an unlabelled
#: paragraph under the headline, but the upload copy keeps an explicit "Summary" heading
#: because ATS resume parsers use headings to find the section.
SECTION_TITLES = {
    "summary": "Summary",
    "experience": "Professional Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
    "skills": "Skills",
    "languages": "Languages",
    "publications": "Publications",
    "activities": "Activities",
}

#: Every fixed English label of the CV, kept together so a later localisation has a
#: single place to change. (No localisation exists yet; these are today's words.)
LABELS = {
    "technologies": "Technologies:",
    "selected_projects": "Selected Projects:",
    "project": "Project:",
    "continued": "continued",
    "work_authorization": "Work authorization:",
}

#: Word shown for an ongoing role or study, in every output.
PRESENT = "Present"

#: Between the two ends of a date range, in every output (an en dash, not a hyphen).
DATE_RANGE_SEPARATOR = " – "
#: The same separator in LaTeX source, where ``--`` typesets an en dash.
DATE_RANGE_SEPARATOR_LATEX = " -- "

#: Fixed English month names. ``strftime`` follows the OS locale, which would change a
#: CV's words between two machines; this table does not.
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
MONTHS_SHORT = tuple(name[:3] for name in MONTHS)

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
    return f"{LABELS['technologies']} " + ", ".join(items) if items else None


def format_month_year(value: str, *, short: bool = True) -> str:
    """``2025-08`` -> ``Aug 2025`` (or ``August 2025``); ``present``/blank -> ``Present``.

    Locale independent. Any other text (a bare year, free wording) is returned as is.
    """
    text = (value or "").strip()
    if not text or text.lower() == "present":
        return PRESENT
    match = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if match and 1 <= int(match.group(2)) <= 12:
        names = MONTHS_SHORT if short else MONTHS
        return f"{names[int(match.group(2)) - 1]} {match.group(1)}"
    return text


def education_highlights_line(education: Education) -> Optional[str]:
    items = [item.strip() for item in education.highlights if item.strip()]
    return HIGHLIGHT_SEPARATOR.join(items) if items else None


def role_company_label(role: Optional[Experience], company: str) -> str:
    """The short company name for compact places, else the full employer name."""
    short = (getattr(role, "display_name", None) or "").strip()
    return short or company


def find_role(profile: Profile, experience: TailoredExperience) -> Optional[Experience]:
    """Find the profile role without borrowing metadata from another role."""
    matches = [row for row in profile.experience if row.company == experience.company]
    if len(matches) <= 1:
        return matches[0] if matches else None
    identity = (experience.role, experience.start_date, experience.end_date)
    matches = [row for row in matches if (row.role, row.start_date, row.end_date) == identity]
    return matches[0] if len(matches) == 1 else None


def find_profile_project(role: Optional[Experience], name: str) -> Optional[Project]:
    """The profile's selected project of ``role`` with this name, if any."""
    if role is None:
        return None
    wanted = name.strip().casefold()
    return next((p for p in role.selected_projects if p.name.strip().casefold() == wanted), None)


def experience_technologies(
    role: Optional[Experience], visible_projects: Iterable[Optional[Project]],
) -> list[str]:
    """Combine role tools with tools from the employer projects shown in the CV."""
    technology_lists = [role.technologies] if role is not None else []
    technology_lists.extend(project.technologies for project in visible_projects if project is not None)
    unique = {}
    for items in technology_lists:
        for item in items:
            label = " ".join(item.split())
            if label:
                unique.setdefault(label.casefold(), label)
    return list(unique.values())


def project_as_subheading(exp, show_projects: bool = True) -> bool:
    """A role with no regular bullets and exactly one project drops the label.

    ``Selected Projects:`` and the company parenthetical say nothing when the project
    *is* the role's content, so the project name stands alone as an italic subheading.
    """
    return bool(show_projects and not exp.bullets and len(exp.projects) == 1)
