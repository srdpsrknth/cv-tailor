"""Structural checks on a tailored CV: which roles and standalone projects it contains.

Kept apart from ``validation`` so that module stays within its size ceiling. The
factual checks that apply to the prose (banned tools, gap statements) stay there and
see standalone-project bullets through ``_cv_texts``.
"""
from __future__ import annotations

import re

from models.profile import Profile
from models.tailored_output import TailoredCV


def validate_role_set(cv: TailoredCV, profile: Profile) -> None:
    """Every non-optional profile role exactly once; optional roles may be omitted."""
    expected = {exp.company: exp for exp in profile.experience}
    companies = [exp.company for exp in cv.experience]
    required = {company for company, exp in expected.items() if not exp.optional}
    if (len(companies) != len(set(companies)) or not set(companies) <= set(expected)
            or not required <= set(companies)):
        raise ValueError(
            "Include each profile employer exactly once, including older roles; "
            "only roles the profile marks optional may be left out."
        )


_NUMBER = re.compile(r"\d[\d.,]*\d|\d")


def _numbers(text: str) -> set[str]:
    return {match.rstrip(".,") for match in _NUMBER.findall(text)}


def validate_standalone_projects(cv: TailoredCV, profile: Profile) -> None:
    """The standalone-project selection, policy and reworded bullets.

    Names and bullet counts are checked while resolving. Reworded bullets must also not
    introduce a number the project's own profile bullets do not contain. Banned tools and
    gap statements are checked with the rest of the CV (``validation._cv_texts``).
    """
    cv.resolve_standalone_projects(profile)
    sources = {project.name: project for project in profile.standalone_projects}
    # A hidden Projects section shows nothing, so there is nothing to require.
    if profile.standalone_projects_policy == "all" and "projects" in profile.visible_cv_sections():
        expected = [project.name for project in profile.standalone_projects]
        if cv.standalone_project_names() != expected:
            raise ValueError(
                "This profile's standalone_projects_policy is 'all': list every standalone "
                "project, in profile order: " + ", ".join(repr(name) for name in expected) + "."
            )
    for item in cv.standalone_projects:
        if isinstance(item, str):
            continue
        allowed = _numbers(" ".join(sources[item.name].bullets))
        for bullet in item.bullets:
            invented = sorted(_numbers(bullet) - allowed)
            if invented:
                raise ValueError(
                    f"Standalone project {item.name!r}: do not add metrics or numbers the "
                    f"profile does not state ({', '.join(invented)}). Reword using only the "
                    f"facts in its profile bullets. Bullet: {bullet!r}"
                )
