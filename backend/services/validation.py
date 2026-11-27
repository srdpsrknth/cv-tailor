"""Candidate-specific validation rules and the gates each document must pass.

These rules used to be hardcoded in the validator, which meant a second candidate was
checked against the first candidate's employers and tool list (A-1). They are now data,
resolved from the profile's optional ``rules`` block. Missing rules are neutral.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from models.profile import Profile
from models.job import normalise_country
from models.tailored_output import TailoredCV, TailoredCoverLetter
from services.cv_structure import validate_role_set, validate_standalone_projects
from services.fact_checks import validate_cv_numbers, validate_cv_skills

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileRules:
    """Candidate-specific validation rules.

    These used to be hardcoded in the validator, which meant a second candidate was
    checked against the first candidate's employers and tool list (A-1). They are
    now data, resolved from the profile's optional ``rules`` block.

    An undeclared rule never inherits another candidate's policy.
    """

    #: Employers needing bespoke project/ownership rules, keyed by a lowercase match.
    special_employers: dict = field(default_factory=dict)

    #: Technologies the profile does not evidence; claiming one is an error.
    banned_tools: tuple = ()

    #: Regex for third-person verbs and aspirations forbidden in the CV summary.
    summary_forbidden_verbs: Optional[str] = None

    #: Immigration label for the CV, applied outside the home countries.
    visa_label: Optional[str] = None
    home_countries: tuple = ()
    local_permit_countries: tuple = ()
    country_overrides: dict = field(default_factory=dict)

    def country_override(self, country: Optional[str]) -> Optional[dict]:
        if not country:
            return None
        key = normalise_country(country) or country.strip().casefold()
        return self.country_overrides.get(key)

    @classmethod
    def from_profile(cls, profile: Profile) -> "ProfileRules":
        """Resolve the selected profile's rules, or neutral defaults."""
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
            country_overrides={
                normalise_country(country) or country.strip().casefold(): rule.model_dump()
                for country, rule in declared.country_overrides.items()
            },
        )

def _employer_rules_to_dict(rules) -> dict:
    """Convert an EmployerRules model into the plain dict the validator reads."""
    return {
        key: value
        for key, value in rules.model_dump().items()
        if value is not None
    }

# Compatibility name for callers that explicitly request candidate-neutral rules.
DEFAULT_PROFILE_RULES = ProfileRules()

def validate_cv(cv: TailoredCV, profile: Profile, rules: ProfileRules) -> None:
    """Check a CV against the profile and the candidate-specific rules."""
    validate_standalone_projects(cv, profile)
    expected = {exp.company: exp for exp in profile.experience}
    validate_role_set(cv, profile)
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
    validate_cv_skills(cv, profile)
    validate_cv_numbers(cv, profile)
    _validate_cv_has_no_gap_statements(cv)
    _validate_cv_tense(cv, profile)

def _validate_employer_prose_rules(
    paragraphs: list[str],
    rules: ProfileRules,
    *,
    company_filter: Optional[str] = None,
) -> None:
    """Enforce ongoing-work and ownership rules against CV bullets or cover-letter prose."""
    joined = " ".join(paragraphs)
    for needle, employer_rules in rules.special_employers.items():
        if company_filter is not None:
            if needle not in company_filter.lower():
                continue
        elif needle not in joined.lower():
            continue
        ongoing_tool = employer_rules.get("ongoing_tool")
        if ongoing_tool:
            for index, text in enumerate(paragraphs, start=1):
                if re.search(rf"\b{re.escape(ongoing_tool)}\b", text) and not re.search(
                    r"developing|development|working on", text, re.I
                ):
                    target = company_filter or needle.capitalize()
                    unit = "bullet" if company_filter is not None else "paragraph"
                    raise ValueError(
                        f"Describe {target} {ongoing_tool} integration as ongoing "
                        f"development, not shipped work. Fix {unit} {index}: {text!r}. "
                        "Every mention must include 'developing', 'development', or "
                        f"'working on' in the same {unit}; correcting another {unit} "
                        "does not fix this one."
                    )
        ownership = employer_rules.get("ownership_pattern")
        if ownership and re.search(ownership, joined, re.I):
            raise ValueError(employer_rules.get("ownership_message", "Ownership is limited."))


def _apply_employer_rules(exp, rules: ProfileRules) -> None:
    """Apply any bespoke rule set configured for this employer."""
    for needle, employer_rules in rules.special_employers.items():
        if needle not in exp.company.lower():
            continue
        expected_projects = employer_rules.get("project_count")
        bullets_each = employer_rules.get("bullets_per_project")
        if expected_projects is not None and len(exp.projects) != expected_projects:
            raise ValueError(f"{exp.company} must have exactly {expected_projects} project(s).")
        if bullets_each is not None and any(len(p.bullets) != bullets_each for p in exp.projects):
            raise ValueError(f"{exp.company} projects must have exactly {bullets_each} bullets each.")
        if exp.projects:
            forbidden = employer_rules.get("forbidden_project_name")
            if forbidden and any(re.search(forbidden, project.name, re.I) for project in exp.projects):
                raise ValueError("Use a project name that follows the profile's naming rules.")
    _validate_employer_prose_rules(exp.bullets, rules, company_filter=exp.company)

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
    data = profile.model_dump(exclude={"rules", "job_search", "cv_section_order", "cv_hidden_sections"})
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

def _check_banned_tools_in_text(text: str, profile: Profile, rules: ProfileRules) -> None:
    """Catch keyword stuffing for technologies absent from this profile."""
    source = profile_facts_json(profile).lower()
    lowered = text.lower()
    for tool in rules.banned_tools:
        if re.search(r"\b" + re.escape(tool.lower()) + r"\b", lowered) and not re.search(
            r"\b" + re.escape(tool.lower()) + r"\b", source
        ):
            raise ValueError(f"Do not claim {tool} experience: it is not in the profile.")


def _validate_no_banned_tools(cv: TailoredCV, profile: Profile, rules: ProfileRules) -> None:
    """Catch keyword stuffing for technologies absent from this profile."""
    _check_banned_tools_in_text(cv.model_dump_json(), profile, rules)


def validate_cover_letter(
    cl: TailoredCoverLetter,
    profile: Profile,
    rules: Optional[ProfileRules] = None,
) -> None:
    """Validate cover-letter structure, grounded claims, and employer prose rules."""
    words = sum(len(paragraph.split()) for paragraph in cl.paragraphs)
    if len(cl.paragraphs) != 4 or not 290 <= words <= 310:
        raise ValueError(
            f"Cover letter has {len(cl.paragraphs)} paragraphs and {words} words; "
            "return exactly four body paragraphs totaling 290-310 words."
        )
    if cl.signature_name != profile.identity.full_name:
        raise ValueError("Use the exact candidate name from the profile.")
    if any(
        re.search(
            r"(?:^|\n)\s*(Dear\s+\S|Sincerely|Best regards|Kind regards|Warm regards)",
            paragraph,
            re.I,
        )
        for paragraph in cl.paragraphs
    ):
        raise ValueError("Body paragraphs must not contain a salutation or signature.")
    if any(re.search(r"(?<!\d)[:;](?!\d)", paragraph) for paragraph in cl.paragraphs):
        raise ValueError(
            "Do not use colons or semicolons in cover-letter paragraphs; write smooth, natural sentences."
        )
    if any("—" in paragraph for paragraph in cl.paragraphs):
        raise ValueError(
            "Do not use em dashes in cover-letter paragraphs; use a conjunction or a full stop."
        )
    closing_line = (cl.closing_line or "").strip()
    if closing_line and any(
        re.search(r"(?:^|\n)\s*" + re.escape(closing_line), paragraph, re.I)
        for paragraph in cl.paragraphs
    ):
        raise ValueError("Do not repeat the configured closing line in the body paragraphs.")
    active_rules = rules or ProfileRules.from_profile(profile)
    _check_banned_tools_in_text(" ".join(cl.paragraphs), profile, active_rules)
    _validate_employer_prose_rules(cl.paragraphs, active_rules)
    _validate_no_gap_statements(cl.paragraphs, "cover-letter paragraph")
    _validate_letter_tense(cl.paragraphs, profile)


# ---------------------------------------------------------------------------
# Gap statements and tense
# ---------------------------------------------------------------------------

_QUAL_NOUN = (
    r"(?:experience|exposure|knowledge|background|qualifications?|fluency|"
    r"proficiency|certifications?|credentials?|command)"
)
_QUALIFIER = r"(?:direct|prior|previous|formal|hands-on|professional|relevant|practical|specific)"

#: Phrases that state, imply or apologise for something the candidate lacks.
#: ``lack`` is only a gap statement before a qualification noun, so ordinary
#: engineering prose such as "reduced lack of data" is deliberately not matched.
_GAP_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        rf"\bno\s+{_QUALIFIER}\b(?:\s+[\w/&-]+){{0,6}}?\s+(?:experience|exposure)\b",
        r"\blimited\s+(?:[\w-]+\s+)?(?:experience|exposure|proficiency|fluency|knowledge)\b",
        rf"\black(?:s|ed|ing)?\s+(?:of\s+)?(?:(?:{_QUALIFIER}|the|any)\s+)*{_QUAL_NOUN}\b",
        r"\bI\s+lack\b",
        r"\bnot\s+listed\b",
        rf"\b(?:I|candidate|he|she|they)\s+(?:do|does|did)(?:\s+not|n't)\s+(?:yet\s+)?(?:have|hold|possess)\b",
        rf"\b(?:do|does)\s+not\s+(?:yet\s+)?(?:have|hold|possess)\s+(?:(?:{_QUALIFIER}|the|any|a|an)\s+)*{_QUAL_NOUN}\b",
        rf"\bwithout\s+{_QUALIFIER}\b(?:\s+[\w/&-]+){{0,4}}?\s+(?:experience|exposure)\b",
        r"\b(?:although|while|though)\s+I\s+(?:have\s+not|haven't|do\s+not|don't)\b",
        r"\bI\s+(?:have\s+not|haven't)\s+(?:yet|had)\b",
        r"\bdespite\s+(?:not\s+(?:having|holding|possessing|yet)|lacking)\b",
    )
)

_GAP_MESSAGE = (
    "Remove the gap statement (%r) in %s %d. Never state, imply, summarise or apologise "
    "for missing qualifications, experience, languages or requirements; omit unmatched "
    "requirements silently and present the candidate's supported strengths instead."
)


def find_gap_statement(text: str) -> Optional[str]:
    """Return the first phrase in ``text`` that states a missing qualification."""
    for pattern in _GAP_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _validate_no_gap_statements(texts: list[str], where: str) -> None:
    for index, text in enumerate(texts, start=1):
        phrase = find_gap_statement(text)
        if phrase:
            raise ValueError(_GAP_MESSAGE % (phrase, where, index))


def _cv_texts(cv: TailoredCV) -> list[tuple[str, list[str]]]:
    """Every free-prose block of the CV, labelled for error messages."""
    blocks = [("CV summary line", list(cv.summary))]
    for exp in cv.experience:
        blocks.append((f"CV bullet for {exp.company},", list(exp.bullets)))
        for project in exp.projects:
            blocks.append((f"CV project bullet for {exp.company},", list(project.bullets)))
    for item in cv.standalone_projects:
        if not isinstance(item, str):
            blocks.append((f"CV standalone project bullet for {item.name},", list(item.bullets)))
    return blocks


def _validate_cv_has_no_gap_statements(cv: TailoredCV) -> None:
    for where, texts in _cv_texts(cv):
        _validate_no_gap_statements(texts, where)


#: Wording that places a role in the present. ``current`` alone is an ordinary
#: adjective ("the current process"), so it only counts before a role-like noun or
#: after "my"/"our".
_PRESENT_TENSE = re.compile(
    r"\b(?:currently|presently|at\s+present|to\s+present)\b"
    r"|\b(?:my|our)\s+current\b"
    r"|\bcurrent\s+(?:role|position|job|employer|internship|studies|thesis|project|"
    r"research|work|team|company)\b",
    re.I,
)

_COMPANY_STOPWORDS = frozenset({
    "gmbh", "ltd", "inc", "llc", "corp", "group", "company", "the", "and", "for",
    "university", "institute", "internship", "labs", "lab", "research", "analytics",
    "services", "solutions", "systems", "technologies", "limited", "centre", "center",
})


def _ended_experiences(profile: Profile):
    return [
        exp for exp in profile.experience
        if (exp.end_date or "").strip().lower() not in {"present", "current", "ongoing", ""}
    ]


def _company_needles(company: str) -> list[str]:
    """The full employer name plus its distinctive tokens, lowercased."""
    needles = {company.lower()}
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9&'-]+", company):
        if len(token) >= 4 and token.lower() not in _COMPANY_STOPWORDS:
            needles.add(token.lower())
    return sorted(needles)


def _validate_cv_tense(cv: TailoredCV, profile: Profile) -> None:
    """A role whose end date has passed must not read as current in its bullets."""
    ended = {exp.company for exp in _ended_experiences(profile)}
    for exp in cv.experience:
        if exp.company not in ended:
            continue
        bullets = list(exp.bullets) + [b for project in exp.projects for b in project.bullets]
        for bullet in bullets:
            match = _PRESENT_TENSE.search(bullet)
            if match:
                raise ValueError(
                    f"The {exp.company} role ended ({exp.end_date}); remove {match.group(0)!r} "
                    f"from its bullet {bullet!r} and describe it in the past tense."
                )


def _validate_letter_tense(paragraphs: list[str], profile: Profile) -> None:
    """A cover-letter sentence naming an ended employer must not call it current."""
    ended = _ended_experiences(profile)
    if not ended:
        return
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            match = _PRESENT_TENSE.search(sentence)
            if not match:
                continue
            lowered = sentence.lower()
            for exp in ended:
                if any(re.search(rf"\b{re.escape(n)}\b", lowered) for n in _company_needles(exp.company)):
                    raise ValueError(
                        f"The {exp.company} role ended ({exp.end_date}); do not describe it with "
                        f"{match.group(0)!r}. Use the past tense for it, and reserve current "
                        f"wording for roles marked present. Fix: {sentence!r}"
                    )
