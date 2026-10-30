"""Candidate-specific validation rules and the gates each document must pass.

These rules used to be hardcoded in the validator, which meant a second candidate was
checked against the first candidate's employers and tool list (A-1). They are now data,
resolved from the profile's optional ``rules`` block, with `DEFAULT_PROFILE_RULES`
reproducing the original single-candidate behaviour exactly.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from models.profile import Profile
from models.tailored_output import TailoredCV, TailoredCoverLetter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileRules:
    """Candidate-specific validation rules.

    These used to be hardcoded in the validator, which meant a second candidate was
    checked against the first candidate's employers and tool list (A-1). They are
    now data, resolved from the profile's optional ``rules`` block.

    The defaults below reproduce the original single-candidate behaviour exactly, so
    a profile that declares no rules validates as it always did.
    """

    #: Employers needing bespoke project/ownership rules, keyed by a lowercase match.
    special_employers: dict = field(default_factory=dict)

    #: Technologies the profile does not evidence; claiming one is an error.
    banned_tools: tuple = ()

    #: Regex for third-person verbs and aspirations forbidden in the CV summary.
    summary_forbidden_verbs: Optional[str] = None

    #: Immigration label for the CV, applied outside the home countries.
    visa_label: Optional[str] = None
    home_countries: tuple = ("germany", "deutschland", "de")
    local_permit_countries: tuple = ("ireland", "denmark")

    @classmethod
    def from_profile(cls, profile: Profile) -> "ProfileRules":
        """Resolve rules for a profile, falling back to the original defaults.

        A profile with no ``rules`` block gets :data:`DEFAULT_PROFILE_RULES`, which
        keeps every previously-working profile and fixture behaving identically.
        """
        declared = getattr(profile, "rules", None)
        if declared is None:
            return DEFAULT_PROFILE_RULES
        return cls(
            special_employers={
                key.lower(): _employer_rules_to_dict(value)
                for key, value in (declared.employers or {}).items()
            },
            banned_tools=tuple(declared.banned_tools or ()),
            summary_forbidden_verbs=declared.summary_forbidden_verbs,
            visa_label=declared.visa_label,
            home_countries=tuple(declared.home_countries or ()),
            local_permit_countries=tuple(declared.local_permit_countries or ()),
        )

def _employer_rules_to_dict(rules) -> dict:
    """Convert an EmployerRules model into the plain dict the validator reads."""
    return {
        key: value
        for key, value in rules.model_dump().items()
        if value is not None
    }

#: The original candidate's rules, preserved as the default so behaviour is unchanged.
#: A profile may override any part of this by declaring its own ``rules`` block.
DEFAULT_PROFILE_RULES = ProfileRules(
    special_employers={
        "aklamio": {
            "project_count": 1,
            "bullets_per_project": 3,
            "forbidden_project_name": r"entrypoints|in progress|20\d{2}",
            "ongoing_tool": "MCP",
            "ownership_pattern": r"\b(lead|led|own|owned)\b[^.]{0,50}(framework|80)",
            "ownership_message": (
                "Aklamio DQ framework is a contribution; ownership is limited to "
                "funnel/sales-channel checks."
            ),
        },
    },
    banned_tools=("Fivetran", "Databricks", "Tableau", "ThoughtSpot", "DealCloud",
                  "Cortex", "AWS"),
    summary_forbidden_verbs=r"\b(combines|builds|aims|passionate|dedicated to)\b",
    visa_label="German EU Blue Card holder",
)

def validate_cv(cv: TailoredCV, profile: Profile, rules: ProfileRules) -> None:
    """Check a CV against the profile and the candidate-specific rules."""
    expected = {exp.company: exp for exp in profile.experience}
    companies = [exp.company for exp in cv.experience]
    if len(companies) != len(set(companies)) or set(companies) != set(expected):
        raise ValueError("Include each profile employer exactly once, including older roles.")
    cv.experience.sort(key=lambda exp: list(expected).index(exp.company))
    for exp in cv.experience:
        base = expected[exp.company]
        if (exp.role, exp.start_date, exp.end_date) != (base.role, base.start_date, base.end_date):
            raise ValueError(f"Keep the exact profile title and dates for {exp.company}.")
        if not base.bullets and not base.selected_projects and (exp.bullets or exp.projects):
            raise ValueError(f"Do not invent responsibilities for {exp.company}.")
        _apply_employer_rules(exp, rules)
    _validate_summary(cv, rules)
    _validate_no_banned_tools(cv, profile, rules)

def _apply_employer_rules(exp, rules: ProfileRules) -> None:
    """Apply any bespoke rule set configured for this employer."""
    for needle, employer_rules in rules.special_employers.items():
        if needle not in exp.company.lower():
            continue
        expected_projects = employer_rules.get("project_count")
        bullets_each = employer_rules.get("bullets_per_project")
        if expected_projects is not None:
            if len(exp.projects) != expected_projects or any(
                len(p.bullets) != bullets_each for p in exp.projects
            ):
                raise ValueError(
                    f"{exp.company} must have {expected_projects} attribution project(s) "
                    f"with exactly {bullets_each} bullets each; fold other projects into "
                    "role bullets."
                )
        if exp.projects:
            forbidden = employer_rules.get("forbidden_project_name")
            if forbidden and re.search(forbidden, exp.projects[0].name, re.I):
                raise ValueError(
                    "Use a clear external attribution project name without dates or "
                    "status labels."
                )
        ongoing_tool = employer_rules.get("ongoing_tool")
        if ongoing_tool:
            for bullet in exp.bullets:
                if re.search(rf"\b{re.escape(ongoing_tool)}\b", bullet) and not re.search(
                    r"developing|development|working on", bullet, re.I
                ):
                    raise ValueError(
                        f"Describe {exp.company} {ongoing_tool} integration as ongoing "
                        "development, not shipped work."
                    )
        ownership = employer_rules.get("ownership_pattern")
        if ownership and re.search(ownership, " ".join(exp.bullets), re.I):
            raise ValueError(employer_rules.get("ownership_message", "Ownership is limited."))

def _validate_summary(cv: TailoredCV, rules: ProfileRules) -> None:
    summary = " ".join(cv.summary)
    if rules.summary_forbidden_verbs and re.search(rules.summary_forbidden_verbs, summary, re.I):
        raise ValueError(
            "Use a factual career summary with 'experience across' or 'background in', "
            "not third-person verbs or aspirations."
        )

#: Private attribute that carries the serialized facts on the profile object.
#: It is deliberately in this module's namespace, so it is neither a declared field
#: of the ``Profile`` model nor something a serialized profile can contain. That
#: matters twice over: the cached text can never leak into a prompt, and
#: :func:`_profile_facts_json` -- which *does* serialize the model -- cannot see it
#: and recurse into itself.
_FACTS_CACHE_FIELD = "_cvtailor_facts_json"

def _profile_facts_json(profile: Profile) -> str:
    """Serialize only the profile's evidence, excluding the rules block.

    A tool named in ``rules.banned_tools`` must not count as evidence that the
    candidate has used it -- otherwise declaring a tool banned would silently
    un-ban it.
    """
    data = profile.model_dump()
    data.pop("rules", None)
    return json.dumps(data, ensure_ascii=False)

def profile_facts_json(profile: Profile) -> str:
    """The profile's evidence as one JSON string, computed and cached per process.

    ``_validate_no_banned_tools`` scans this text for **every** banned tool, and a
    profile with the original candidate's rules has seven of them, so the same
    ~15,000-character document used to be rebuilt up to seven times per validated
    CV -- on every draft, review and layout retry. The value is a pure function of
    the profile, so it is computed once and memoized on the object.

    The cache is a *private* attribute on the ``Profile`` object, not a module-level
    map: no process-global state, no key to collide, and the entry is collected with
    its profile. The name must stay underscore-prefixed -- ``Profile`` sets
    ``extra='forbid'``, and pydantic allows an undeclared attribute only while its
    name is private. Declaring it as a field instead would put the cached text into
    ``model_dump()``, which is both sent to the model and the input to this very
    function.

    Writing to a caller's profile is harmless for the same reason
    ``docx_renderer``'s mutation is bounded: it is derived data, never a fact, and
    nothing validates against the attribute. The cache never changes what is
    returned -- only the *first* call does the work.
    """
    cached = getattr(profile, _FACTS_CACHE_FIELD, None)
    if isinstance(cached, str):
        return cached
    facts = _profile_facts_json(profile)
    try:
        object.__setattr__(profile, _FACTS_CACHE_FIELD, facts)
    except (AttributeError, TypeError, ValueError):
        # ``object.__setattr__`` bypasses pydantic's ``__setattr__``, so this is
        # belt-and-braces rather than an expected path: a profile-like object with
        # ``__slots__`` that excludes ``__dict__`` simply recomputes, which is the
        # pre-existing behaviour. Caching is an optimization, never a requirement.
        logger.debug("Could not cache profile facts on %r; recomputing.", type(profile))
    return facts

def _validate_no_banned_tools(cv: TailoredCV, profile: Profile, rules: ProfileRules) -> None:
    """Catch keyword stuffing for technologies absent from this profile."""
    source = profile_facts_json(profile).lower()
    text = cv.model_dump_json().lower()
    for tool in rules.banned_tools:
        if re.search(r"\b" + re.escape(tool.lower()) + r"\b", text) and not re.search(
            r"\b" + re.escape(tool.lower()) + r"\b", source
        ):
            raise ValueError(f"Do not claim {tool} experience: it is not in the profile.")

def validate_cover_letter(cl: TailoredCoverLetter, profile: Profile) -> None:
    words = sum(len(paragraph.split()) for paragraph in cl.paragraphs)
    if len(cl.paragraphs) != 4 or not 290 <= words <= 310:
        raise ValueError(
            f"Cover letter has {len(cl.paragraphs)} paragraphs and {words} words; "
            "return exactly four body paragraphs totaling 290-310 words."
        )
    if cl.signature_name != profile.identity.full_name:
        raise ValueError("Use the exact candidate name from the profile.")
    if any(
        re.search(r"(?:^|\n)\s*(Dear Hiring|Sincerely|Best regards|Kind regards)", paragraph, re.I)
        for paragraph in cl.paragraphs
    ):
        raise ValueError("Body paragraphs must not contain a salutation or signature.")
