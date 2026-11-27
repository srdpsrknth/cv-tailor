"""Grounding checks on a tailored CV: skills and numbers must come from the profile.

Kept apart from ``validation`` (which has a line ceiling) and free of any import from it,
so ``validation.validate_cv`` can call these without a cycle.

Every retry costs money, so each rule rejects **clear inventions only**:

* A skill is accepted when it matches a profile skill/technology/language exactly (after
  normalisation) *or* when every significant word of it appears somewhere in the profile's
  facts. That lets "Python (pandas)" through when the profile says "Python" and "pandas",
  and "Advanced SQL" when it says "SQL", but not "Kubernetes" when the profile has no such
  word anywhere.
* A number is accepted when the profile states it anywhere (a metric, a date, a count).
  Numbers that are not metrics -- ordinals, tool names such as "GA4", release labels such
  as "Phase 2", durations that fit the candidate's career span, years inside the profile's
  dated range -- are not examined. Metrics are never *required*; only invented ones fail.
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from typing import Iterable

from models.profile import Profile
from models.tailored_output import TailoredCV

__all__ = ["validate_cv_skills", "validate_cv_numbers", "unsupported_skills"]

#: Where the per-profile index is memoised. Private and underscore-prefixed for the same
#: reason as ``validation._FACTS_CACHE_FIELD``: ``Profile`` forbids undeclared fields.
_INDEX_FIELD = "_cvtailor_fact_index"

_EXCLUDED_FROM_FACTS = {"rules", "job_search", "cv_section_order", "cv_hidden_sections"}
_CONTACT_KEYS = {"email", "phone", "linkedin", "github"}

# --------------------------------------------------------------------------- tokens

_TOKEN = re.compile(r"[^\W_]+(?:[+#]+)?(?:\.[^\W_]+(?:[+#]+)?)*")

#: Words that describe a level or frame a skill without being the skill.
_FILLER = frozenset({
    "a", "an", "and", "or", "of", "the", "for", "with", "in", "on", "to", "via", "using",
    "basic", "intermediate", "advanced", "proficient", "proficiency", "strong", "working",
    "expert", "familiar", "familiarity", "knowledge", "experience", "skills", "skill",
    "level", "hands", "on", "fluent", "good", "solid", "applied", "general", "core",
})


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


def _tokens(text: str) -> list[str]:
    return [_stem(token) for token in _TOKEN.findall(text.casefold())]


def _norm(text: str) -> str:
    """Spelling-insensitive form of a skill: case, punctuation and '&' vs 'and' ignored."""
    cleaned = text.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w+#.]+", " ", cleaned).replace("_", " ").split()).strip(".")


# --------------------------------------------------------------------------- numbers

#: ``(1,200.5)(suffix)`` not glued to a preceding letter or digit, so ``GA4``, ``S3`` and
#: ``Q3`` are names, not numbers.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)([A-Za-z×]*%?)")
_SCALE = {"k": 1e3, "m": 1e6, "mn": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}
#: Suffixes that make the number a quantity rather than part of a name.
_UNIT_SUFFIXES = frozenset({
    "", "%", "x", "×", "pp", "ms", "s", "kb", "mb", "gb", "tb", "h", "hr", "hrs", "min",
    "mins", "sec", "px",
})
_ORDINAL = frozenset({"st", "nd", "rd", "th"})
#: Words after which a bare number is a label ("Phase 2", "Tier 1"), not a metric.
_LABELS = frozenset({
    "phase", "tier", "level", "stage", "step", "part", "version", "v", "release", "sprint",
    "wave", "grade", "class", "type", "group", "cohort", "module", "track", "zone", "lot",
    "table", "figure", "section", "chapter", "annex", "appendix", "no", "iteration", "round",
    "batch", "page", "week", "day", "quarter", "fy", "h", "q", "area", "pillar", "layer",
})
_IDIOMS = re.compile(
    r"\b24\s*[/x]\s*7\b|\b360(?=[- ]?(?:degree|view|feedback))|\b1[:-]1\b|\b1\s*-\s*to\s*-\s*1\b",
    re.I,
)
_DURATION = re.compile(r"\s*\+?\s*(?:-\s*)?(?:years?|yrs?|months?)\b", re.I)
_MONTH_OF_DATE = re.compile(r"\b(\d{4})-\d{2}(?:-\d{2})?\b")


def _value(number: str, suffix: str) -> float | None:
    """Numeric value of a metric token, or ``None`` if it is a name/ordinal."""
    suffix = suffix.casefold()
    if suffix in _ORDINAL:
        return None
    if suffix not in _UNIT_SUFFIXES and suffix not in _SCALE:
        return None
    try:
        value = float(number.rstrip(",").replace(",", ""))
    except ValueError:
        return None
    return round(value * _SCALE.get(suffix, 1), 6)


def _fixed_values(text: str) -> set[float]:
    """Every number a text states, with unit scaling, for the profile's side."""
    values: set[float] = set()
    for number, suffix in _NUMBER.findall(_MONTH_OF_DATE.sub(r"\1", text)):
        try:
            raw = round(float(number.rstrip(",").replace(",", "")), 6)
        except ValueError:
            continue
        values.add(raw)
        scaled = _value(number, suffix)
        if scaled is not None:
            values.add(scaled)
    return values


# --------------------------------------------------------------------------- index

@dataclass(frozen=True)
class _FactIndex:
    tokens: frozenset
    numbers: frozenset
    skill_norms: frozenset
    tech_tokens: frozenset
    language_names: tuple
    first_year: int
    last_year: int

    @property
    def career_years(self) -> int:
        return max(self.last_year - self.first_year, 0) + 1


def _years(profile: Profile) -> tuple[int, int]:
    this_year = datetime.date.today().year
    found: list[int] = []
    for exp in profile.experience:
        for value in (exp.start_date, exp.end_date):
            match = re.match(r"\s*(\d{4})", value or "")
            if match:
                found.append(int(match.group(1)))
            elif (value or "").strip().lower() in {"present", "current", "ongoing"}:
                found.append(this_year)
    for edu in profile.education:
        found.extend(year for year in (edu.start_year, edu.end_year) if year)
        if edu.ongoing:
            found.append(this_year)
    return (min(found), max(found)) if found else (this_year, this_year)


def _index(profile: Profile) -> _FactIndex:
    cached = getattr(profile, _INDEX_FIELD, None)
    if isinstance(cached, _FactIndex):
        return cached
    data = profile.model_dump(exclude=_EXCLUDED_FROM_FACTS)
    text = json.dumps(data, ensure_ascii=False)
    identity = {k: v for k, v in data.get("identity", {}).items() if k not in _CONTACT_KEYS}
    number_text = json.dumps({**data, "identity": identity}, ensure_ascii=False)

    skills: set[str] = set()
    tech: list[str] = []
    for items in profile.skills.values():
        tech.extend(items)
    for exp in profile.experience:
        tech.extend(exp.technologies)
        for project in exp.selected_projects:
            tech.extend(project.technologies)
    for project in profile.standalone_projects:
        tech.extend(project.technologies)
    skills.update(_norm(item) for item in tech)
    skills.update(_norm(language.name) for language in profile.languages)
    first, last = _years(profile)
    index = _FactIndex(
        tokens=frozenset(_tokens(text)),
        numbers=frozenset(_fixed_values(number_text)),
        skill_norms=frozenset(skills),
        tech_tokens=frozenset(t for item in tech for t in _tokens(item)),
        language_names=tuple(_norm(language.name) for language in profile.languages),
        first_year=first,
        last_year=last,
    )
    try:
        object.__setattr__(profile, _INDEX_FIELD, index)
    except (AttributeError, TypeError, ValueError):
        pass  # memoising is an optimisation, never a requirement
    return index


# --------------------------------------------------------------------------- skills

#: What may follow a spoken-language name in a skills entry: a proficiency, not a topic.
_LEVEL_WORDS = frozenset({
    "native", "fluent", "bilingual", "mother", "tongue", "proficient", "proficiency",
    "professional", "basic", "intermediate", "advanced", "conversational", "beginner",
    "elementary", "working", "limited", "full", "business", "fluency", "level", "speaker",
    "speaking", "written", "spoken", "and", "or", "c1", "c2", "b1", "b2", "a1", "a2",
    "upper", "lower", "good", "excellent", "mothertongue", "first", "language",
    "c1+", "c2+", "b2+",
})


def _is_spoken_language(item: str, index: _FactIndex) -> bool:
    """True for "English", "German (A2)", "Malayalam - Native" when the profile lists them."""
    norm = _norm(item)
    for name in index.language_names:
        if name and (norm == name or norm.startswith(name + " ")):
            rest = norm[len(name):].split()
            if all(word in _LEVEL_WORDS or re.fullmatch(r"[abc][12]\+?", word) for word in rest):
                return True
    return False


def _parts(item: str) -> list[str]:
    """A skill entry may bundle several skills; check each separately."""
    return [part.strip() for part in re.split(r"[;,\n]", item) if part.strip()]


def _skill_supported(skill: str, index: _FactIndex) -> bool:
    if _norm(skill) in index.skill_norms:
        return True
    tokens = [t for t in _tokens(skill) if t not in _FILLER]
    significant = [t for t in tokens if len(t) > 1] or tokens
    return all(token in index.tokens for token in significant)


def unsupported_skills(cv: TailoredCV, profile: Profile) -> list[tuple[str, str]]:
    """``(category, skill)`` pairs the profile gives no basis for."""
    index = _index(profile)
    return [
        (category, item)
        for category, items in cv.skills.items()
        for item in items
        if isinstance(item, str) and not all(_skill_supported(p, index) for p in _parts(item))
    ]


def validate_cv_skills(cv: TailoredCV, profile: Profile) -> None:
    """Every tailored skill must come from the profile; spoken languages stay in Languages."""
    index = _index(profile)
    if index.language_names:
        spoken = [i for items in cv.skills.values() for i in items if _is_spoken_language(i, index)]
        if spoken:
            raise ValueError(
                "Do not list spoken languages in the skills section ("
                + ", ".join(repr(item) for item in spoken[:4])
                + "): the CV already has a Languages section. Keep skills to tools, "
                "methods and domain skills."
            )
    bad = unsupported_skills(cv, profile)
    if bad:
        named = ", ".join(f"{item!r} (in {category!r})" for category, item in bad[:5])
        raise ValueError(
            f"Unsupported skill(s): {named}. Skills must come from the profile's skills, "
            "technologies or project tools; remove them or reword using only profile "
            "terms. A job posting is not evidence that the candidate has a skill."
        )


# --------------------------------------------------------------------------- numbers

def _invented_numbers(text: str, index: _FactIndex) -> list[str]:
    text = _IDIOMS.sub(" ", text)
    found: list[str] = []
    for match in _NUMBER.finditer(text):
        number, suffix = match.groups()
        value = _value(number, suffix)
        if value is None:
            continue
        raw = round(float(number.rstrip(",").replace(",", "")), 6)
        if value in index.numbers or raw in index.numbers:
            continue
        before = _tokens(text[: match.start()])
        if before and (before[-1] in _LABELS or before[-1] in index.tech_tokens):
            continue
        if _DURATION.match(text, match.end()) and value <= index.career_years + 1:
            continue
        if suffix == "" and 1900 <= value <= 2100 and index.first_year <= value <= index.last_year:
            continue
        found.append(match.group(0).strip())
    return found


def _prose(cv: TailoredCV) -> Iterable[tuple[str, str]]:
    for line in cv.summary:
        yield "the summary", line
    for exp in cv.experience:
        for bullet in exp.bullets:
            yield f"a {exp.company} bullet", bullet
        for project in exp.projects:
            for bullet in project.bullets:
                yield f"a {exp.company} project bullet", bullet


def validate_cv_numbers(cv: TailoredCV, profile: Profile) -> None:
    """The summary and experience bullets must not introduce numbers the profile lacks."""
    index = _index(profile)
    problems = []
    for where, text in _prose(cv):
        invented = _invented_numbers(text, index)
        if invented:
            problems.append(f"{', '.join(dict.fromkeys(invented))} in {where}: {text!r}")
    if problems:
        raise ValueError(
            "Do not add metrics or numbers the profile does not state. "
            + " | ".join(problems[:3])
            + ". Reword using only figures that appear in the profile, or drop the figure."
        )
