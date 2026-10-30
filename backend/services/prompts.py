"""Prompt construction: the context block, the draft briefs and the retry briefs.

Every prompt the pipeline sends is assembled here from the profile and the posting.
`build_context` builds the block that is shared by the CV prompt, the letter prompt and
every layout retry, so the profile is serialized once per application rather than once
per call.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models.profile import Profile
from models.tailored_output import TailoredCV

from services.validation import ProfileRules

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The two prompt files, read and hashed per call rather than tracked by a version
#: constant: a hand-maintained constant is one more thing a prompt edit can forget to
#: bump, and the failure is silent (ADR 0015).
PROMPT_CV_PATH = PROJECT_ROOT / "backend/prompts/tailor_cv_prompt.md"
PROMPT_CL_PATH = PROJECT_ROOT / "backend/prompts/tailor_cl_prompt.md"

#: Target CV body length after each failed layout attempt, in words.
LAYOUT_BUDGET_START = 650
LAYOUT_BUDGET_STEP = 100
LAYOUT_BUDGET_FLOOR = 400


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
