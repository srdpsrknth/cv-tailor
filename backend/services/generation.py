"""LLM orchestration and document validation.

Extracted from ``tailor_service.tailor_documents`` (A-3). This module knows how to
turn a job description plus a profile into a validated CV and cover letter: it
builds the prompts, calls the model, validates each response, corrects failures,
runs the editorial review, and drives the layout-retry loop.

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


def parse_json_response(text: str) -> dict:
    """Use the same parser for first drafts, reviews, and length retries.

    Accept wrappers around complete JSON; never repair truncated document data.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned an empty document.")
    decoder = json.JSONDecoder()
    for start in [0] + [match.start() for match in re.finditer(r"\{", text)]:
        try:
            value, _ = decoder.raw_decode(text[start:].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and any(
            key in value for key in ("cv", "cover_letter", "experience", "paragraphs")
        ):
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
) -> str:
    """The shared COMPANY/ROLE/country/posting/profile block both prompts append.

    ``profile_json`` lets a caller that already serialized the profile reuse those
    exact bytes: the pipeline serializes once per application and every prompt --
    CV, cover letter and each layout retry -- appends this same block. Serializing
    the profile is pure cost, so it is done once rather than once per call.

    The default reproduces the previous behaviour byte for byte, so a caller that
    passes nothing gets exactly what it got before. This parameter carries **no**
    prompt-wording change: it selects between two identical strings.
    """
    work_country = (work_country or "").strip() or None
    if profile_json is None:
        profile_json = profile.model_dump_json(indent=2)
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
        f"BASE PROFILE (authoritative JSON):\n{profile_json}"
    )


EDITORIAL_REVIEW_INSTRUCTION = (
    "\nEDITORIAL AND FACTUAL REVIEW: Review the following draft against the profile. "
    "Remove invented outcomes, tools, claims of sole ownership, and claims that developing projects are complete. "
    "Improve plain-language writing and remove repeated responsibilities/project bullets. "
    "Check alignment with the supplied role and job description: preserve natural supported keywords, "
    "prioritize relevant examples, and retain profile-backed foundational skills expected for the role. "
    "Treat the approved summary as a style reference, not mandatory identical wording. "
    "Preserve work history and factual metrics. Return a complete revised CV JSON.\nDRAFT:\n"
)


def layout_correction_instruction(page_count: int, budget: int, rules: ProfileRules) -> str:
    """The shortening instruction for one layout retry."""
    project_clause = ""
    for needle, employer_rules in rules.special_employers.items():
        expected_projects = employer_rules.get("project_count")
        if expected_projects:
            project_clause = (
                f" Keep one {needle.capitalize()} attribution project with three concise "
                "bullets; other projects can be summarized in role bullets."
            )
            break
    return (
        f"\nLAYOUT CORRECTION: The current CV rendered to {page_count} pages. "
        f"Reduce its body text to approximately {budget} words or fewer. "
        "Prioritize concise responsibilities; reduce repetitive bullets and less relevant project detail. "
        "Keep all employers and exact dates, education and core skills."
        + project_clause +
        " Do not change facts, shrink the font, or turn ongoing work into completed work. "
        "Return the complete shorter CV JSON, not just changes.\nCURRENT CV:\n"
    )


def layout_budget(attempt: int) -> int:
    """Body-word budget for a given failed layout attempt."""
    return max(LAYOUT_BUDGET_FLOOR, LAYOUT_BUDGET_START - attempt * LAYOUT_BUDGET_STEP)


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
    ):
        """Call the model until its response validates, or raise after three attempts."""
        last_error = ""
        previous = ""
        for _ in range(MAX_VALIDATION_ATTEMPTS):
            feedback = (
                f"\nCORRECTION REQUIRED: {last_error}\nPREVIOUS RESPONSE:\n{previous}\n"
                "Return the corrected complete JSON document."
                if last_error
                else ""
            )
            response, inputs, outputs = self.service._call_gemini(prompt + feedback)
            self.counts[kind].add(inputs, outputs)
            self.drafts.append({"component": kind, "response": response})
            try:
                data = parse_json_response(response)
                model = self._build_model(data, kind, work_country, company_name, role_title)
                return model, data
            except ValueError as error:
                last_error = str(error)
                previous = response
                logger.warning("%s document validation failed: %s", kind, last_error)
        raise ValueError(
            f"Could not produce a valid {kind} document after three attempts: {last_error}"
        )

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
        """Draft, review, and generate the letter. Returns (cv, cl, explanation)."""
        self._status("Drafting CV...")
        cv, _ = self.generate(cv_prompt, "cv", work_country, company_name, role_title)
        # The Booking workflow included editorial review. Apply it to UI generation too.
        cv, data = self.generate(
            cv_prompt + EDITORIAL_REVIEW_INSTRUCTION + cv.model_dump_json(indent=2),
            "cv", work_country, company_name, role_title,
        )
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
        """One layout retry: revise the *current* candidate with a tighter budget.

        Uses the identical complete-JSON parser and validation as every other call.
        """
        self._status(f"CV is {page_count} pages; shortening content...")
        budget = layout_budget(attempt)
        cv, data = self.generate(
            cv_prompt
            + layout_correction_instruction(page_count, budget, self.rules)
            + cv.model_dump_json(indent=2),
            "cv", work_country, company_name, role_title,
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
