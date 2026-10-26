"""LLM orchestration and document validation.

Extracted from ``tailor_service.tailor_documents`` (A-3). This module knows how to
turn a job description plus a profile into a validated CV and cover letter: it
builds the prompts, calls the model, validates each response, corrects failures,
and drives the layout-retry loop.

It deliberately knows **nothing** about the filesystem. ``tailor_service`` owns
persistence and calls into here, which is what makes the flow testable in parts.

Validation rules that are candidate-specific (employers, banned tools, visa
handling) are supplied by a ``ProfileRules`` object rather than hardcoded
(A-1).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from models.profile import Profile
from models.tailored_output import TailoredCV, TailoredCoverLetter

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_CV_PATH = PROJECT_ROOT / "backend/prompts/tailor_cv_prompt.md"
PROMPT_CL_PATH = PROJECT_ROOT / "backend/prompts/tailor_cl_prompt.md"

#: Attempts per document before giving up and reporting the last validation error.
MAX_VALIDATION_ATTEMPTS = 3

#: Layout attempts before the two-page target is declared unreachable.
MAX_LAYOUT_ATTEMPTS = 4

#: Target CV body length after each failed layout attempt, in words.
LAYOUT_BUDGET_START = 650
LAYOUT_BUDGET_STEP = 100
LAYOUT_BUDGET_FLOOR = 400

#: Private attribute that carries the serialized facts on the profile object.
#: It is deliberately in this module's namespace, so it is neither a declared field
#: of the ``Profile`` model nor something a serialized profile can contain. That
#: matters twice over: the cached text can never leak into a prompt, and
#: :func:`_profile_facts_json` -- which *does* serialize the model -- cannot see it
#: and recurse into itself.
_FACTS_CACHE_FIELD = "_cvtailor_facts_json"


def parse_json_response(text: str, accept_delta: bool = False) -> dict:
    """Use the same parser for first drafts, reviews, and length retries.

    Accept wrappers around complete JSON; never repair truncated document data.

    ``accept_delta`` additionally accepts the *targeted* retry shape: an object of unit
    ids such as ``{"experience[0].bullets[1]": "..."}``, which has no document key and
    would otherwise be rejected as "not a document". It is off by default and is only
    switched on for layout retries, so a draft that returns a stray object still fails
    loudly rather than being treated as a partial document. Whether the object really
    is a delta -- rather than an arbitrary JSON blob -- is then decided by
    :func:`looks_like_cv_delta`, and every key is validated by
    :func:`apply_cv_delta` before anything is merged.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned an empty document.")
    decoder = json.JSONDecoder()
    for start in [0] + [match.start() for match in re.finditer(r"\{", text)]:
        try:
            value, _ = decoder.raw_decode(text[start:].lstrip())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if any(key in value for key in ("cv", "cover_letter", "experience", "paragraphs")):
            return value
        if accept_delta and looks_like_cv_delta(value):
            return value
    raise ValueError("The model response did not contain a complete document JSON object.")


def extract_explanation(data: dict) -> Optional[dict]:
    """Find the tailoring explanation wherever the model put it.

    The prompt asks for it at the top level, but the more natural document shape nests it
    inside ``cv``. Reading only the top level silently yields ``None`` for a nested
    response: the UI then shows no explanation, with no error. Accept both, preferring
    the documented top-level key.
    """
    if not isinstance(data, dict):
        return None
    top_level = data.get("tailoring_explanation")
    if isinstance(top_level, dict):
        return top_level
    cv = data.get("cv")
    if isinstance(cv, dict):
        nested = cv.get("tailoring_explanation")
        if isinstance(nested, dict):
            return nested
    return None


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


# --- prompt construction --------------------------------------------------------------

def build_context(
    job_description: str,
    profile: Profile,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    work_country: Optional[str] = None,
    profile_json: Optional[str] = None,
    profile_bytes: Optional[str] = None,
) -> str:
    """The shared COMPANY/ROLE/country/posting/profile block both prompts append.

    ``profile_bytes`` (equivalently its older spelling ``profile_json``) lets a caller
    that already serialized the profile reuse those exact bytes: the pipeline
    serializes once per application and every prompt -- CV, cover letter and each
    layout retry -- appends this same block. Serializing the profile is pure cost, so
    it is done once rather than once per call.

    Since Phase 3 item 5 the **same string** is also the profile half of the cache
    key, which is why the parameter is named for what it is: the bytes the model was
    shown. Hashing anything else -- a re-serialization, a digest of the profile model
    -- would let the key and the prompt drift apart, and a prompt change would be
    served from cache without anyone noticing.

    The default reproduces the previous behaviour byte for byte, so a caller that
    passes nothing gets exactly what it got before. This parameter carries **no**
    prompt-wording change: it selects between two identical strings.
    """
    work_country = (work_country or "").strip() or None
    if profile_bytes is None:
        profile_bytes = profile_json
    if profile_bytes is None:
        profile_bytes = profile.model_dump_json(indent=2)
    country_context = (
        f"\nWORK COUNTRY (explicit user selection; overrides country inference): {work_country}. "
        "Apply the work-authorization rules for this country. Company headquarters and past job locations are irrelevant.\n"
        if work_country
        else "\nWORK COUNTRY: infer only from a clear actual job location; do not guess from company headquarters.\n"
    )
    return (
        f"\nCOMPANY: {company_name or 'Infer from job description'}\n"
        f"ROLE: {role_title or 'Infer from job description'}\n"
        + country_context
        + f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"BASE PROFILE (authoritative JSON):\n{profile_bytes}"
    )


#: The editorial requirements that used to be a second, whole-CV pass.
#:
#: Phase 3, increment 2 removed that pass and folded its requirements into the draft
#: prompt instead. The pass re-sent the entire context *plus* the finished draft
#: (~7,730 tokens) to ask for a complete revision -- one whole call and ~25% of total
#: input tokens (ASSESSMENT.md §5) for instructions that were already implicit in the
#: draft prompt's WRITING AND FACTUAL RULES. The revision it returned was also
#: re-validated from scratch, so the pass bought a second draft, not a stronger gate.
#:
#: The text below is tested against the real validators before it is shipped
#: (``tests/test_editorial_instructions.py``): every clause here is one the pipeline
#: already enforces downstream, so stating it up front is what makes a single draft
#: sufficient. It is injected by :func:`build_cv_prompt`, never as a suffix to the
#: finished document.
EDITORIAL_REQUIREMENTS = (
    "\nEDITORIAL AND FACTUAL REQUIREMENTS (check the draft against these before returning it)\n"
    "- Remove invented outcomes, tools, claims of sole ownership, and any implication that "
    "developing work is complete.\n"
    "- Use plain language and remove repeated responsibilities or project bullets.\n"
    "- Check alignment with the supplied role and job description: preserve natural supported "
    "keywords, prioritize relevant examples, and retain profile-backed foundational skills "
    "expected for the role.\n"
    "- Treat the approved summary as a style reference, not mandatory identical wording.\n"
    "- Preserve work history and factual metrics exactly.\n"
)


def build_cv_prompt(prompt_text: str, context: str) -> str:
    """The CV prompt: the prompt file, the editorial requirements, then the context.

    The requirements sit **before** the job description and profile so the model reads
    them as part of the brief it is drafting against, rather than as an afterthought
    appended to a document it has already written. That ordering is the whole point of
    merging the pass: the model is asked to satisfy these checks while drafting, not to
    re-read its own output afterwards and revise it.

    They are deliberately *not* part of ``tailor_cv_prompt.md``: that file is the
    candidate-facing writing brief, and these are checks the pipeline enforces anyway.
    Keeping them in code lets a test assert they are injected exactly once, and lets the
    layout-retry path (which reuses the same prompt) inherit them unchanged.
    """
    return prompt_text + EDITORIAL_REQUIREMENTS + context


def layout_correction_instruction(page_count: int, budget: int, rules: ProfileRules) -> str:
    """The shortening rules for one layout retry, without a heading.

    The rules are byte-identical to what the whole-document instruction always said --
    Phase 3, item 1 changed what the retry *sends* and what it *asks for*, not whether
    these constraints still apply. The heading comes from
    :func:`layout_retry_instruction`, which is the only caller: a retry is no longer a
    ``LAYOUT CORRECTION`` (that string identified the old, whole-document contract), and
    keeping it here would put two different labels on the same brief.
    """
    return (
        f"The current CV rendered to {page_count} pages. "
        f"Reduce its body text to approximately {budget} words or fewer. "
        "Prioritize concise responsibilities; reduce repetitive bullets and less relevant project detail. "
        "Keep all employers and exact dates, education and core skills."
        + pinned_project_clause(rules) +
        " Do not change facts, shrink the font, or turn ongoing work into completed work."
    )


def pinned_project_clause(rules: ProfileRules) -> str:
    """The project constraint implied by the candidate's own rules, if any.

    Derived from ``rules`` rather than hardcoded, so a second candidate is not told
    to keep an employer's project shape it does not have.
    """
    for needle, employer_rules in rules.special_employers.items():
        expected_projects = employer_rules.get("project_count")
        if expected_projects:
            return (
                f" Keep one {needle.capitalize()} attribution project with three concise "
                "bullets; other projects can be summarized in role bullets."
            )
    return ""


#: Marks a retry prompt. Deliberately not ``LAYOUT CORRECTION``: that string identified
#: the old, whole-document contract, and a test must be able to tell the two apart.
LAYOUT_RETRY_MARKER = "LAYOUT RETRY"


def cv_body_words(cv: TailoredCV) -> int:
    """Words of body text in the document, measured the way the brief talks about it.

    Summary and responsibilities only. Bullets inside a *project* and the skills list
    are deliberately excluded: they are the units the model consolidates and reorders
    to make room, so counting them would make the number go up while the document got
    shorter. Anchoring the budget to text the model may only shorten keeps the two
    moving in the same direction.
    """
    return sum(len(line.split()) for line in cv.summary) + sum(
        len(bullet.split()) for exp in cv.experience for bullet in exp.bullets
    )


def layout_inventory(cv: TailoredCV, attempt: int = 1) -> str:
    """The current CV's shape in one line: body length, summary and employer sizes.

    The old brief told the model to hit "approximately 650 words" without ever saying
    how long the document was -- the recorded fixtures are ~80-100 real words, so the
    target described a document three to eight times the size of the one being
    shortened. This line makes the target readable against reality, and it is measured
    from the CV that was actually rendered.

    The attempt number is included so that a correction loop, which re-sends the same
    CV after an invalid retry, does not present a stale "shortening attempt 1" label.

    It deliberately does **not** quote the CV's text back: the model wrote it, and
    echoing it would restore the repetition this increment removes.
    """
    summary_words = sum(len(line.split()) for line in cv.summary)
    bullet_words = sum(len(bullet.split()) for exp in cv.experience for bullet in exp.bullets)
    employers = "; ".join(
        f"{exp.company}: {len(exp.bullets)} bullets"
        + (f", {len(exp.projects)} project(s)" if exp.projects else "")
        for exp in cv.experience
    )
    return (
        f"Shortening attempt {attempt}. Current body: {cv_body_words(cv)} words "
        f"({summary_words} summary + {bullet_words} responsibility)."
        + (f" Employers: {employers}." if employers else "")
    )


def layout_retry_instruction(
    cv: TailoredCV, page_count: int, budget: int, attempt: int, rules: ProfileRules
) -> str:
    """The targeted brief for one layout retry.

    Replaces the old "here is the whole context again, return the complete shorter CV"
    instruction. Everything the retry needs to know about the *document* is measured
    here, and the response may be a delta instead of a copy:

    * the response may be a delta object of replacement values, merged onto the CV
      that was just rendered (:func:`apply_cv_delta`);
    * the complete-CV shape is still accepted, so a model that ignores the delta is not
      a failure -- it is simply as expensive as before.

    The context (profile, job description, prompt file) is deliberately absent: it was
    sent on the draft call, and repeating it is what this increment removes.

    The ``LAYOUT RETRY`` marker leads the brief so a retry is identifiable on its own,
    and so a test can tell it apart from the old ``LAYOUT CORRECTION`` contract.
    """
    retry = layout_correction_instruction(page_count, budget, rules)
    if attempt:
        retry += (
            f" This is shortening attempt {attempt + 1} and the CV still renders to "
            f"{page_count} pages; cut deeper than last time, starting with the longest "
            "units and the least relevant project detail."
        )
    return (
        f"\n{LAYOUT_RETRY_MARKER}\n"
        + retry
        + "\nKeep the summary and every responsibility bullet; merge or shorten them "
        "rather than removing a field. Do not rename, re-employer, re-date, remove an "
        "achievement or a metric, or drop a supporting claim.\n"
        + layout_inventory(cv, attempt + 1)
        + '\nReturn either the complete shorter CV JSON, or a delta object of only the '
        'units that change, e.g. {"summary": [...], "experience[0].bullets[1]": '
        '"shorter text"}. Units not returned are kept unchanged.\nCURRENT CV:\n'
    )


def layout_budget(attempt: int) -> int:
    """Body-word budget for a given failed layout attempt."""
    return max(LAYOUT_BUDGET_FLOOR, LAYOUT_BUDGET_START - attempt * LAYOUT_BUDGET_STEP)


# --- the targeted delta -----------------------------------------------------------------

#: Units a delta may replace. Everything it cannot address is a fact the CV was
#: already validated on: employers, titles, dates, education, certifications, the
#: work-authorization label, and the skills categories themselves.
_DELTA_KEY_PATTERN = re.compile(
    r"^(?:"
    r"summary"
    r"|experience\[\d+\]\.bullets"
    r"|experience\[\d+\]\.bullets\[\d+\]"
    r"|experience\[\d+\]\.projects\[\d+\]\.name"
    r"|experience\[\d+\]\.projects\[\d+\]\.bullets"
    r"|experience\[\d+\]\.projects\[\d+\]\.bullets\[\d+\]"
    r"|skills\.[^.\[\]]+"
    r")$"
)


def looks_like_cv_delta(data: dict) -> bool:
    """True when a parsed retry response replaces units instead of returning the document.

    A response containing ``cv`` or ``experience`` is a complete document, which is what
    ``parse_json_response`` guarantees and what both fixture transcripts use. Anything
    else with at least one recognisable delta key is a delta. A response that is
    neither fails loudly rather than being guessed at.
    """
    if not isinstance(data, dict):
        return False
    if any(key in data for key in ("cv", "experience")):
        return False
    return bool(data) and all(isinstance(key, str) for key in data) and any(
        _DELTA_KEY_PATTERN.match(key) for key in data
    )


def _require_strings(value, key: str) -> list:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"unknown unit {key!r}: expected a string or a list of strings")
    if not any(item.strip() for item in value):
        raise ValueError(f"unknown unit {key!r}: an empty replacement would delete text")
    return value


def apply_cv_delta(cv: TailoredCV, delta: dict) -> TailoredCV:
    """Merge a delta of replacement values onto a CV, returning a new CV.

    This is why a targeted retry cannot break the promises ``validate_cv`` makes. The
    input was already accepted by the gate, and the only units a delta may address are
    prose the gate does not anchor a fact to: the summary, bullets, project names and
    the skills list. Employers, titles, dates, education, certifications and the
    work-authorization label are simply **not addressable**, so no delta can invent an
    employer, change a date, or turn ongoing work into completed work.

    A key that is not addressable, names a unit that does not exist, or carries a value
    of the wrong type raises ``ValueError``. It is never ignored: silently dropping part
    of a delta would produce a document the model did not ask for.

    The result is a *copy*; the caller's CV is left untouched, so a rejected retry
    cannot leave the accepted document half-edited.
    """
    merged = cv.model_copy(deep=True)
    unknown: list[str] = []
    for key, value in delta.items():
        if not isinstance(key, str) or not _DELTA_KEY_PATTERN.match(key):
            unknown.append(str(key))
            continue
        if key == "summary":
            merged.summary = _require_strings(value, key)
        elif key.startswith("skills."):
            merged.skills[key[len("skills."):]] = _require_strings(value, key)
        else:
            _merge_experience_unit(merged, key, value)
    if unknown:
        raise ValueError(
            "unknown unit(s) " + ", ".join(repr(item) for item in unknown)
            + ": a delta may only replace the summary, bullets, project names/bullets "
            "or an existing skills category"
        )
    return merged


def _merge_experience_unit(cv: TailoredCV, key: str, value) -> None:
    """Apply one ``experience[...]`` key, rejecting anything that does not exist."""
    failure = ValueError(f"unknown unit {key!r}: no such unit in the current CV")
    match = re.match(
        r"^experience\[(\d+)\](?:\.bullets(?:\[(\d+)\])?|\.projects\[(\d+)\]"
        r"\.(?:name|bullets(?:\[(\d+)\])?))$",
        key,
    )
    if match is None:
        raise failure
    exp_index, bullet_index, project_index, project_bullet_index = match.groups()
    if int(exp_index) >= len(cv.experience):
        raise failure
    exp = cv.experience[int(exp_index)]

    if bullet_index is not None:
        if int(bullet_index) >= len(exp.bullets):
            raise failure
        exp.bullets[int(bullet_index)] = _require_strings(value, key)[0]
        return
    if project_index is None:
        exp.bullets = _require_strings(value, key)
        return

    if int(project_index) >= len(exp.projects):
        raise failure
    project = exp.projects[int(project_index)]
    if project_bullet_index is not None:
        if int(project_bullet_index) >= len(project.bullets):
            raise failure
        project.bullets[int(project_bullet_index)] = _require_strings(value, key)[0]
    elif key.endswith(".name"):
        project.name = _require_strings(value, key)[0]
    else:
        project.bullets = _require_strings(value, key)



# --- structured output ------------------------------------------------------------------
#
# Where a schema is sent, and where it deliberately is not.
#
# Gemini's structured output constrains a response to a declared shape. It is a real gain --
# the brace-scan in :func:`parse_json_response` stops being the failure path -- but the
# original implementation was **deleted as dead code in Phase 1 (D-1)**, because
# ``response_mime_type="application/json"`` *caused premature truncation of long document
# responses*. That reason is still load-bearing, so this increment scopes structured output
# instead of enabling it everywhere:
#
# * the **CV draft** and the **cover letter** always return one complete document, so they
#   get a schema, and the schema is required;
# * the **layout retry** is the one call whose response may be a *delta* -- an object of unit
#   ids such as ``{"experience[0].bullets[1]": "..."}`` with no document key. A schema that
#   requires ``cv`` cannot express that shape, so sending one there would break
#   :func:`apply_cv_delta` or make the provider silently substitute a whole-document answer
#   for the cheaper delta. That call therefore sends **no** schema.
#
# Why this is not merely a compromise: the anti-truncation property is designed into the
# schema, not hoped for. Descriptions are deliberate -- they are what the provider shows the
# model -- but ``additionalProperties`` is left unset and no field inside a document is
# ``required``. Enumerating and requiring a ~1,350-token document's every field is what makes
# a constrained response long and cut-off-prone, and a cut-off response is invalid JSON.
# Constraining the *envelope* buys the parse guarantee this increment wants (the response is
# an object carrying ``cv``/``cover_letter``, never prose or a bare array) while leaving the
# document's own length and shape to the model.


def _tailoring_explanation_schema():
    """The explanation object, accepted in either position by :func:`extract_explanation`."""
    from google.genai import types

    return types.Schema(
        type="OBJECT",
        description="How the document was tailored. Optional; omit it if there is nothing to say.",
        properties={
            key: types.Schema(type="STRING")
            for key in (
                "summary_changes",
                "bullet_modifications",
                "skill_reordering",
                "project_selection",
                "overall_strategy",
            )
        },
    )


def _cv_document_schema():
    """The CV body: properties described, nothing required.

    ``summary`` is an array of strings, ``skills`` a map of category to skills, and
    ``experience`` a list of roles with their own bullets and projects -- the shape
    ``TailoredCV`` validates. Listing them keeps the contract meaningful; *not*
    requiring them keeps the response short enough to finish.
    """
    from google.genai import types

    return types.Schema(
        type="OBJECT",
        description="The tailored CV. Keep every employer, title and date from the profile.",
        properties={
            "title": types.Schema(type="STRING"),
            "work_authorization": types.Schema(type="STRING", nullable=True),
            "summary": types.Schema(type="ARRAY", items=types.Schema(type="STRING")),
            "skills": types.Schema(
                type="OBJECT",
                # ``additional_properties`` is deliberately **not** set here, and this
                # is a fix rather than a simplification: the Gemini API rejects the
                # keyword outright -- "additionalProperties is not supported in the
                # Gemini API" -- so every schema-bearing draft call failed after three
                # attempts on the default provider. Verified against the live API on
                # 2026-10-26: an otherwise identical schema succeeds without it and
                # fails with it.
                #
                # Nothing is lost. The comment above already claimed this keyword was
                # unset; the code disagreed with its own comment. A map of category to
                # skills needs no declaration for the *response* to be valid -- it is
                # ``validate_cv`` that checks the contents, and it always was.
            ),
            "experience": types.Schema(
                type="ARRAY",
                items=types.Schema(
                    type="OBJECT",
                    properties={
                        "company": types.Schema(type="STRING"),
                        "role": types.Schema(type="STRING"),
                        "start_date": types.Schema(type="STRING"),
                        "end_date": types.Schema(type="STRING"),
                        "bullets": types.Schema(
                            type="ARRAY", items=types.Schema(type="STRING")
                        ),
                        "projects": types.Schema(
                            type="ARRAY",
                            items=types.Schema(
                                type="OBJECT",
                                properties={
                                    "name": types.Schema(type="STRING"),
                                    "bullets": types.Schema(
                                        type="ARRAY", items=types.Schema(type="STRING")
                                    ),
                                },
                            ),
                        ),
                    },
                ),
            ),
            "include_education": types.Schema(type="BOOLEAN"),
            "include_certifications": types.Schema(type="BOOLEAN"),
            # extract_explanation reads a nested explanation too, so it must stay legal
            # here. Forbidding it would decide, on the model's behalf, which of the two
            # shapes it may return -- the thing `extract_explanation` exists not to do.
            "tailoring_explanation": _tailoring_explanation_schema(),
        },
    )


def _cover_letter_document_schema():
    from google.genai import types

    return types.Schema(
        type="OBJECT",
        description="The tailored cover letter: four paragraphs, 290-310 body words.",
        properties={
            "role_title": types.Schema(type="STRING"),
            "company_name": types.Schema(type="STRING"),
            "paragraphs": types.Schema(type="ARRAY", items=types.Schema(type="STRING")),
            "closing_line": types.Schema(type="STRING"),
            "signature_name": types.Schema(type="STRING"),
        },
    )


def _document_response_schema(envelope_key: str, document):
    """Wrap one document in its envelope, requiring exactly that envelope key.

    ``cv``/``cover_letter`` is the only required property. The prompt asks for
    ``tailoring_explanation`` beside it, but the recorded fixtures show it is genuinely
    optional in practice and :func:`extract_explanation` reads it defensively -- so
    requiring it would turn a harmless omission into a failed run and a wasted call.
    """
    from google.genai import types

    properties = {envelope_key: document}
    if envelope_key == "cv":
        properties["tailoring_explanation"] = _tailoring_explanation_schema()
    return types.Schema(
        type="OBJECT",
        description=(
            "A JSON object carrying the tailored document under "
            f"{envelope_key!r}. No markdown, commentary or LaTeX."
        ),
        properties=properties,
        required=[envelope_key],
    )


def _build_response_schemas() -> dict:
    """Build the per-document schemas once, at import.

    Building them here rather than per call keeps the cost off the generation path.
    They are plain data describing a contract, not per-run state, so a module-level
    mapping is correct -- this is deliberately *not* an environment read (ADR 0010).
    """
    return {
        "cv": _document_response_schema("cv", _cv_document_schema()),
        "cover_letter": _document_response_schema(
            "cover_letter", _cover_letter_document_schema()
        ),
    }


#: Response contract per document kind. A kind absent from this mapping is sent **no**
#: schema: an unknown document type must not inherit the CV's constraints by accident.
RESPONSE_SCHEMAS = _build_response_schemas()


def response_schema_for(kind: Optional[str], allow_delta: bool = False):
    """The schema for one call, or ``None`` to leave the response unconstrained.

    ``allow_delta`` marks the layout retry, whose response may be a delta rather than a
    document. That path is deliberately schema-free: see the module comment above
    :data:`RESPONSE_SCHEMAS`.

    Returning ``None`` means "no schema", and the caller must then also leave
    ``response_mime_type`` unset -- JSON mode without a schema still changes the
    response envelope, and this function's contract is about the whole config.
    """
    if allow_delta:
        return None
    return RESPONSE_SCHEMAS.get(kind or "")


# --- the generation pipeline ----------------------------------------------------------

@dataclass
class TokenCounts:
    """Input tokens, output tokens and call count, tracked per component."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, inputs: int, outputs: int) -> None:
        self.input_tokens += inputs
        self.output_tokens += outputs
        self.calls += 1

    def as_list(self) -> list:
        return [self.input_tokens, self.output_tokens, self.calls]


class DocumentGenerator:
    """Produces a validated CV and cover letter from a profile and a posting.

    Holds no filesystem state; ``tailor_service`` persists whatever comes back.
    """

    def __init__(
        self,
        service,
        profile: Profile,
        rules: Optional[ProfileRules] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        self.service = service
        self.profile = profile
        # Resolve rules from the profile unless the caller supplied an explicit set,
        # so a multi-profile setup validates each candidate against its own facts.
        self.rules = rules or ProfileRules.from_profile(profile)
        self.status_callback = status_callback
        self.counts = {"cv": TokenCounts(), "cover_letter": TokenCounts()}
        self.drafts: list = []

    # --- one document ------------------------------------------------------------------

    def _status(self, message: str) -> None:
        if self.status_callback:
            self.status_callback(message)

    def generate(
        self,
        prompt: str,
        kind: str,
        work_country: Optional[str] = None,
        company_name: Optional[str] = None,
        role_title: Optional[str] = None,
        base_cv: Optional[TailoredCV] = None,
    ):
        """Call the model until its response validates, or raise after three attempts.

        ``base_cv`` names the document a CV retry is shortening. When it is supplied, a
        response may be a *delta* (:func:`apply_cv_delta`) as well as a complete CV, and
        either way the result re-enters :meth:`_build_model`, so ``validate_cv`` gates it
        exactly as it gates a draft. There is no branch that returns a document the gate
        has not seen, and no branch that quietly keeps ``base_cv`` when the model fails:
        a retry that cannot be applied is retried and then raises.

        ``kind`` is also forwarded to the provider as the *response contract*: it selects
        the structured-output schema. ``base_cv`` is what marks the one call that may
        return a delta, and that call is sent no schema -- see
        :func:`response_schema_for`.
        """
        last_error = ""
        previous = ""
        for _ in range(MAX_VALIDATION_ATTEMPTS):
            feedback = (
                f"\nCORRECTION REQUIRED: {last_error}\nPREVIOUS RESPONSE:\n{previous}\n"
                "Return the corrected complete JSON document."
                if last_error
                else ""
            )
            response, inputs, outputs = self.service._call_gemini(
                prompt + feedback, kind=kind, allow_delta=base_cv is not None,
            )
            self.counts[kind].add(inputs, outputs)
            self.drafts.append({"component": kind, "response": response})
            try:
                data = parse_json_response(response, accept_delta=base_cv is not None)
                if base_cv is not None and looks_like_cv_delta(data):
                    # A delta is merged onto the *validated* CV, then gated again. The
                    # two checks are complementary: the merge guarantees employers,
                    # titles and dates are unchanged; the gate guarantees the new prose
                    # does not claim a banned tool, a forbidden summary verb, or
                    # sponsorship.
                    model = self._build_model(
                        {"cv": apply_cv_delta(base_cv, data).model_dump()},
                        kind, work_country, company_name, role_title,
                    )
                else:
                    model = self._build_model(data, kind, work_country, company_name, role_title)
                return model, data
            except ValueError as error:
                last_error = str(error)
                previous = response
                logger.warning("%s document validation failed: %s", kind, last_error)
        raise ValueError(
            f"Could not produce a valid {kind} document after three attempts: {last_error}"
        )

    def restore(
        self,
        cv_data: dict,
        cl_data: dict,
        work_country: Optional[str] = None,
        company_name: Optional[str] = None,
        role_title: Optional[str] = None,
    ):
        """Re-admit a **stored** CV and cover letter through the same gate.

        Phase 3 item 5 serves an identical generation from the cache instead of
        paying for it twice. The one thing that must not happen is a stored document
        reaching the renderer without being validated again: the cache is a file on
        disk that a person can edit, truncate or hand-craft, so "it was validated
        when it was stored" is a claim about the past, not about these bytes.

        Re-validating is free -- no API call -- so a cache hit runs exactly the same
        gate a fresh generation runs, through exactly the same method. A stored
        document that no longer validates (because the profile changed, or the file
        was edited) raises here, and the caller turns that into a miss and generates
        the document instead.

        The question this answers honestly: a cache entry that *fails* the gate
        cannot be served. It is not deleted -- the read path never writes -- and the
        next identical request re-generates, overwriting the entry.
        """
        cv = self._build_model(
            {"cv": cv_data}, "cv", work_country, company_name, role_title
        )
        cl = self._build_model(
            {"cover_letter": cl_data}, "cover_letter", work_country, company_name, role_title
        )
        return cv, cl

    def _build_model(
        self,
        data: dict,
        kind: str,
        work_country: Optional[str],
        company_name: Optional[str],
        role_title: Optional[str],
    ):
        """Validate one parsed response and apply country/company/role adjustments."""
        if kind == "cv":
            model = TailoredCV.model_validate(data.get("cv", data))
            self._apply_visa_label(model, work_country)
            if re.search(r"sponsorship|employer support|work permit support",
                         model.model_dump_json(), re.I):
                raise ValueError(
                    "Sponsorship and work permit support requirements belong only in the "
                    "cover letter, never in the CV."
                )
            validate_cv(model, self.profile, self.rules)
        else:
            model = TailoredCoverLetter.model_validate(data.get("cover_letter", data))
            validate_cover_letter(model, self.profile)
            self._check_sponsorship_sentence(model, work_country)
            if company_name:
                model.company_name = company_name
            if role_title:
                model.role_title = role_title
        return model

    def _apply_visa_label(self, cv: TailoredCV, work_country: Optional[str]) -> None:
        """Keep immigration status separate from sponsorship wording."""
        visa = (self.profile.identity.visa_status or "").lower()
        if not work_country or "blue card" not in visa:
            return
        cv.work_authorization = (
            None if work_country.lower() in self.rules.home_countries
            else self.rules.visa_label
        )

    def _check_sponsorship_sentence(self, cl: TailoredCoverLetter, work_country: Optional[str]) -> None:
        """Overseas letters must address permit support, without inventing a local card."""
        visa = (self.profile.identity.visa_status or "").lower()
        if not work_country or work_country.lower() in self.rules.home_countries:
            return
        if "blue card" not in visa:
            return
        closing = cl.paragraphs[-1]
        if not re.search(r"Blue Card", closing, re.I) or not re.search(
            r"employer support|sponsor", closing, re.I
        ):
            raise ValueError(
                f"Include the German-issued EU Blue Card and employer permit support "
                f"needed for {work_country} in the final cover-letter paragraph."
            )
        if work_country.lower() in self.rules.local_permit_countries and re.search(
            r"Irish (?:EU )?Blue Card|Danish (?:EU )?Blue Card", closing, re.I
        ):
            raise ValueError(
                "Ireland and Denmark do not issue EU Blue Cards; refer to the appropriate "
                "local employment permit."
            )

    # --- the full sequence -------------------------------------------------------------

    def generate_pair(
        self,
        cv_prompt: str,
        cl_prompt: str,
        work_country: Optional[str] = None,
        company_name: Optional[str] = None,
        role_title: Optional[str] = None,
    ):
        """Draft the CV, then generate the letter. Returns (cv, cl, explanation).

        The CV is produced by **one** call. Until Phase 3 increment 2 the draft was
        followed by a second, whole-CV editorial pass; its requirements now ship inside
        the draft prompt (:data:`EDITORIAL_REQUIREMENTS`), which removes a call and
        ~25% of input tokens without lowering the bar -- the returned draft is still the
        only document that reaches validation, and the ``tailoring_explanation`` now
        comes from the draft response rather than the review's.
        """
        self._status("Drafting CV...")
        cv, data = self.generate(cv_prompt, "cv", work_country, company_name, role_title)
        explanation = extract_explanation(data)

        # Generate the letter only once the CV's wording has passed validation.
        cl, _ = self.generate(cl_prompt, "cover_letter", work_country, company_name, role_title)
        return cv, cl, explanation

    def shorten_cv(
        self,
        cv: TailoredCV,
        page_count: int,
        attempt: int,
        cv_prompt: str,
        work_country: Optional[str],
        company_name: Optional[str],
        role_title: Optional[str],
        explanation: Optional[dict],
    ):
        """One layout retry: shorten the *current* candidate with a tighter budget.

        Until Phase 3 item 1 this re-sent ``cv_prompt`` -- prompt file, editorial
        requirements, job description and the whole profile -- plus the complete CV, and
        asked for a complete shorter CV. Measured on the recorded Nordwind run with a
        real tokenizer, that retry sent more input (3,488 tokens) than the draft itself
        (2,886) and asked for ~480 output tokens of JSON that were mostly a copy of the
        previous response.

        What is sent now is the retry brief and the current CV: the context was already
        sent on the draft call, and a delta response can replace only the units that
        actually need shortening. ``cv_prompt`` stays in the signature so callers are
        unchanged, but it is deliberately no longer re-sent.

        The gate is unchanged: see :meth:`generate`. ``extract_explanation`` is still
        read first from the retry's own response, so a retry that returns its own
        explanation supersedes the draft's.
        """
        self._status(f"CV is {page_count} pages; shortening content...")
        budget = layout_budget(attempt)
        cv, data = self.generate(
            layout_retry_instruction(cv, page_count, budget, attempt, self.rules)
            + cv.model_dump_json(indent=2),
            "cv", work_country, company_name, role_title,
            base_cv=cv,
        )
        return cv, extract_explanation(data) or explanation

    def usage_kwargs(self) -> dict:
        """Token counts in the shape ``calculate_token_usage`` expects."""
        cv, cl = self.counts["cv"], self.counts["cover_letter"]
        return {
            "cv_input_tokens": cv.input_tokens,
            "cv_output_tokens": cv.output_tokens,
            "cl_input_tokens": cl.input_tokens,
            "cl_output_tokens": cl.output_tokens,
            "cv_attempts": cv.calls,
            "cl_attempts": cl.calls,
        }
