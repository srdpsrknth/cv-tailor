# ADR 0026 — Profile-grounded tailoring: no gap statements, correct tense, skills and numbers from the profile

**Status:** Proposed, 2026-11-27 (multi-candidate cleanup, PR #1). Awaiting owner approval.
**Related:** ADR 0003 (profile identity), ADR 0012 (structured output), ADR 0015 (cache), ADR 0016.

## Context

The first real applications for a second, early-career candidate showed failures that the
validators did not catch:

- A CV summary ended with "...but no direct Clinical Research Coordinator experience is listed".
  The model had copied its own gap analysis into the document.
- A cover letter apologised for missing experience and limited language skills.
- A role that had ended months earlier was called "my current research".
- Spoken languages were repeated as a skills category.

Separately, apart from opt-in banned tools, nothing stopped a draft or a layout retry from
adding skills or metrics that are not in the profile.

## Decision

1. **Unmatched requirements are omitted silently.** Both prompts say: never state, imply,
   summarise or apologise for missing qualifications, experience, languages or requirements.
   A validator rejects gap phrasing ("no direct … experience", "limited experience",
   "lack of <qualification>", "not listed", "despite not having", and similar) in the CV summary,
   all CV bullets and the cover-letter paragraphs. Patterns are narrowed to avoid false
   positives ("reduced lack of data", "the pipeline does not have duplicates" pass).
2. **Tense follows the profile.** Roles whose `end_date` is not `present` must not be described as
   current. This is checked in that role's bullets and in letter sentences that name the employer.
3. **Skills must be supported by the profile.** A skill is accepted if it matches a profile skill,
   technology or language name, or if every significant word appears in the profile facts.
   `rules` are excluded, so a banned tool stays an invention. Spoken languages are rejected
   from skills when the profile has a languages section. `cv_delta` retries may not add skill
   categories.
4. **Numbers must come from the profile.** Every number in the summary, experience bullets and
   project bullets must appear in the profile facts, compared by value: 1,200 = 1.2k. Ordinals,
   names containing digits (GA4, Q3), labels (Phase 2), tool versions and dates within the
   career span are skipped. Metrics are never required.
5. All checks raise ordinary validation errors, so the existing retry flow handles them, and
   cache hits are re-validated.

## Consequences

- Retries can cost money when a model repeatedly violates a rule. The rules are deliberately
  conservative and their error messages are precise, so one retry usually fixes them.
- Candidate-specific constraints that are not facts belong in the private
  `candidate_guidance.json` (ADR 0023 family), never in the public prompts.
