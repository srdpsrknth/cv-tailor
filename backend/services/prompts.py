"""Prompt construction: the context block, the draft briefs and the retry briefs.

Every prompt the pipeline sends is assembled here from the profile and the posting.
`build_context` builds the block that is shared by the CV prompt, the letter prompt and
every layout retry, so the profile is serialized once per application rather than once
per call.
"""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Optional

from models.profile import Profile
from models.tailored_output import TailoredCV

from services.cache_store import serialize_profile_bytes
from services.validation import ProfileRules

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The two prompt files, read and hashed per call rather than tracked by a version
#: constant: a hand-maintained constant is one more thing a prompt edit can forget to
#: bump, and the failure is silent (ADR 0015).
PROMPT_CV_PATH = PROJECT_ROOT / "backend/prompts/tailor_cv_prompt.md"
PROMPT_CL_PATH = PROJECT_ROOT / "backend/prompts/tailor_cl_prompt.md"

#: Suggested reduction in visible, editable CV prose each time the PDF overflows.
LAYOUT_REDUCTION_PERCENT = 10


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
        profile_bytes = serialize_profile_bytes(profile)
    country_context = (
        f"\nWORK COUNTRY (explicit user selection; overrides country inference): {work_country}. "
        "Apply the work-authorization rules for this country. Company headquarters and past job locations are irrelevant.\n"
        if work_country
        else "\nWORK COUNTRY: infer only from a clear actual job location; do not guess from company headquarters.\n"
    )
    rules = ProfileRules.from_profile(profile)
    if rules.country_overrides:
        country_context += (
            "\nCOUNTRY-SPECIFIC APPLICATION RULES (take precedence over generic visa instructions):\n"
            + json.dumps(rules.country_overrides, ensure_ascii=False, sort_keys=True)
            + "\nApply only the actual employment country's override (ISO country keys). "
            "An empty work_authorization means suppress the CV immigration label, "
            "not fall back to the profile status. If requires_employer_support is false, "
            "omit immigration status and sponsorship wording from both documents. "
            "Follow tailoring_guidance using only profile-backed experience; do not invent "
            "international clients, leadership, outcomes, or relocation availability.\n"
        )
    if profile.standalone_projects and profile.standalone_projects_policy == "all":
        country_context += (
            "\nSTANDALONE PROJECTS POLICY: all. Include every standalone project from the "
            "profile in standalone_projects, in profile order, even if it is only loosely "
            "relevant. Reword their bullets toward the posting where useful, but never "
            "omit a project.\n"
        )
    return (
        f"\nCOMPANY: {company_name or 'Infer from job description'}\n"
        f"ROLE: {role_title or 'Infer from job description'}\n"
        + country_context
        + f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"BASE PROFILE (authoritative JSON):\n{profile_bytes}"
    )

#: The editorial requirements that replaced a second, whole-CV pass (ASSESSMENT.md §5).
#:
#: Every clause here is one the pipeline already enforces downstream, and that is what
#: makes a single draft sufficient: stating the checks up front is what removes the need
#: to re-read a finished document and revise it. The text is tested against the real
#: validators (``tests/test_editorial_instructions.py``), and it is injected by
#: :func:`build_cv_prompt`, never as a suffix to a finished document.
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

def candidate_guidance_block(instructions: tuple[str, ...], *, existing: str = "") -> str:
    """Render one guidance section for its matching provider call."""
    additions = tuple(instruction for instruction in instructions if instruction not in existing)
    if not additions:
        return ""
    return (
        "\nCANDIDATE-SPECIFIC GUIDANCE\n"
        + "\n".join(f"- {instruction}" for instruction in additions)
        + "\nApply only guidance consistent with the profile facts, applicable country rules, "
        "and output requirements.\n"
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

def layout_correction_instruction(page_count: int, budget: Optional[int], rules: ProfileRules) -> str:
    """The shortening rules for one layout retry, without a heading.

    The heading comes from :func:`layout_retry_instruction`, which is the only caller:
    a retry is no longer a whole-document ``LAYOUT CORRECTION``, and keeping that label
    here would put two names on the same brief.
    """
    target = (
        f"Aim for approximately {budget} editable prose words or fewer. "
        if budget is not None else
        "There is no visible editable prose to shorten. "
    )
    return (
        f"The current CV rendered to {page_count} pages. " + target +
        "Shorten wording first, then cut repeated wording and lower-priority supporting detail. "
        "Keep all employers and exact dates, education and core skills."
        + pinned_project_clause(rules) +
        " Do not change facts, shrink the font, or turn ongoing work into completed work."
    )

def pinned_project_clause(rules: ProfileRules) -> str:
    """The project constraint implied by the candidate's own rules, if any.

    Derived from ``rules`` rather than hardcoded, so a second candidate is not told
    to keep an employer's project shape it does not have.
    """
    clauses = []
    for needle, employer_rules in rules.special_employers.items():
        projects = employer_rules.get("project_count")
        bullets = employer_rules.get("bullets_per_project")
        employer = needle.capitalize()
        if projects is not None:
            clauses.append(f" Keep exactly {projects} project(s) for {employer}.")
        if bullets is not None:
            clauses.append(f" Keep exactly {bullets} bullets in each {employer} project.")
    return "".join(clauses)

#: Marks a retry prompt. Deliberately not ``LAYOUT CORRECTION``: that string identified
#: the old, whole-document contract, and a test must be able to tell the two apart.
LAYOUT_RETRY_MARKER = "LAYOUT RETRY"

def _cv_prose_counts(cv: TailoredCV, profile: Optional[Profile]) -> tuple[int, int, int, int]:
    """Count visible summary, role bullets, editable projects and verbatim projects."""
    hidden = profile.cv_hidden_sections if profile is not None else ()
    experience = cv.experience if "experience" not in hidden else ()
    summary = sum(len(line.split()) for line in cv.summary) if "summary" not in hidden else 0
    role = sum(len(bullet.split()) for exp in experience for bullet in exp.bullets)
    project = 0
    if "employer_projects" not in hidden:
        project = sum(len(b.split()) for exp in experience for item in exp.projects for b in item.bullets)
    fixed = 0
    if "projects" not in hidden:
        project += sum(
            len(b.split()) for item in cv.standalone_projects if not isinstance(item, str) for b in item.bullets
        )
        if profile is not None and any(isinstance(item, str) for item in cv.standalone_projects):
            fixed = sum(
                len(b.split())
                for item, resolved in zip(cv.standalone_projects, cv.resolve_standalone_projects(profile))
                if isinstance(item, str) for b in resolved.bullets
            )
    return summary, role, project, fixed


def cv_body_words(cv: TailoredCV, profile: Optional[Profile] = None) -> int:
    """Count the visible summary and role and project bullets a retry can edit."""
    summary, role, project, _ = _cv_prose_counts(cv, profile)
    return summary + role + project

def layout_inventory(cv: TailoredCV, attempt: int = 1, *, profile: Optional[Profile] = None) -> str:
    """The current CV's shape in one line: body length, summary and employer sizes.

    Gives the model the measured word count of the draft that overflowed.

    The attempt number is included so that a correction loop, which re-sends the same
    CV after an invalid retry, does not present a stale "shortening attempt 1" label.

    It deliberately does **not** quote the CV's text back: the model wrote it, and
    echoing it would restore the repetition the retry exists to remove.
    """
    summary_words, bullet_words, project_words, fixed_words = _cv_prose_counts(cv, profile)
    editable_words = summary_words + bullet_words + project_words
    employers = "; ".join(
        f"{exp.company}: {len(exp.bullets)} bullets"
        + (f", {len(exp.projects)} project(s)" if exp.projects else "")
        for exp in cv.experience
    )
    return (
        f"Shortening attempt {attempt}. Current body: {editable_words} editable prose words "
        f"({summary_words} summary + {bullet_words} role bullets + {project_words} editable project bullets)."
        + (f" Keep {fixed_words} words of verbatim standalone project bullets outside that target." if fixed_words else "")
        + (f" Employers: {employers}." if employers else "")
    )

def _standalone_clause(cv: TailoredCV, policy: str) -> str:
    """What a layout retry may do to the selected standalone projects.

    Projects are never dropped or reordered by a retry. A project the CV already
    rewords (``{name, bullets}``) may have its bullets shortened, addressed as
    ``standalone_projects[i].bullets``; one selected by name is kept as it is.
    """
    if not cv.standalone_projects:
        return ""
    clause = (
        "Keep the same standalone_projects in the same order"
        + (" (the profile requires every standalone project)" if policy == "all" else "")
        + "; never drop a project. "
    )
    reworded = [
        f"standalone_projects[{index}] ({item.name!r}, {len(item.bullets)} bullets)"
        for index, item in enumerate(cv.standalone_projects) if not isinstance(item, str)
    ]
    if reworded:
        clause += (
            "You may shorten the bullets of " + "; ".join(reworded)
            + " (keep at least one bullet, add no facts); other projects stay unchanged."
        )
    else:
        clause += "Leave them unchanged."
    return clause + "\n"


def layout_retry_instruction(
    cv: TailoredCV, page_count: int, budget: Optional[int], attempt: int, rules: ProfileRules,
    *, guidance: str = "", standalone_policy: str = "select", profile: Optional[Profile] = None,
) -> str:
    """The targeted brief for one layout retry.

    Everything the retry needs to know about the *document* is measured here, and the
    response may be a delta instead of a copy:

    * the response may be a delta object of replacement values, merged onto the CV
      that was just rendered (:func:`apply_cv_delta`);
    * the complete-CV shape is still accepted, so a model that ignores the delta is not
      a failure -- it is simply as expensive as before.

    The profile, job description, and draft prompt stay out of this brief.
    Only guidance scoped to layout is included alongside the current CV.

    The ``LAYOUT RETRY`` marker leads the brief so a retry is identifiable on its own.
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
        + "\nKeep the summary and the strongest role and project evidence. Shorten the prose "
        "without removing a field required by the output or the profile. Use one main achievement "
        "per bullet and aim for one or two lines at normal CV width. If folding a relevant project "
        "into a role would create a paragraph-length bullet, keep the project heading and shorten "
        "its bullets. For retained claims, keep the method and result tied to the achievement they support, "
        "and preserve each metric. Do not rename, re-employer, or re-date a role.\n"
        + _standalone_clause(cv, standalone_policy)
        + layout_inventory(cv, attempt + 1, profile=profile)
        + guidance
        + '\nReturn either the complete shorter CV JSON, or a delta object of only the '
        'units that change, e.g. {"summary": [...], "experience[0].bullets[1]": '
        '"shorter text"}. Units not returned are kept unchanged. '
        'Delta replacements must contain non-empty text; do not use [] or "" to delete '
        'bullets or projects. For a structural change, return the complete CV. Fold a secondary '
        'project into a role bullet only when it fits in a concise bullet with one main achievement. '
        'Preserve the strongest evidence and the required project shape.\nCURRENT CV:\n'
    )

def layout_budget(current_words: int) -> Optional[int]:
    """Suggest a shorter target for the draft that just overflowed."""
    if not current_words:
        return None
    return current_words * (100 - LAYOUT_REDUCTION_PERCENT) // 100
