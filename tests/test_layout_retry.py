"""Phase 3, item 1: a layout retry asks for a delta, not a whole new CV.

A failed layout attempt used to re-send the entire CV prompt (prompt file, editorial
requirements, job description, the whole profile) plus the complete previous CV and
"Return the complete shorter CV JSON". That repeated the *context* to shorten a handful
of bullets: measured with a real tokenizer on the recorded Nordwind run, the retry sent
3,488 input tokens where the draft sent 2,886, and it asked for ~480 output tokens of
JSON -- almost all of it copied from the previous response.

The retry now:

* sends the retry brief and an **inventory of the current CV** -- every repeating unit
  the document contains, titled, with its current length -- instead of the whole context.
  The profile, the job description and the prompt file were already sent on the draft
  call;
* can return **either** the complete CV (the previous contract, still accepted) **or**
  a targeted delta of replacement values for the summary, skills, bullets and projects
  that repeat. :func:`services.generation.apply_cv_delta` merges a delta onto the
  previous, *already validated* CV, so a delta can never invent an employer, a title,
  a date or a project that the gate would have rejected -- the previous CV has passed
  ``validate_cv`` and a delta changes none of those fields;
* is validated exactly as before. A complete response goes through ``_build_model``
  (``validate_cv``); a delta is applied and then merged CV goes through the same
  ``_build_model``. Nothing skips the gate, and there is no fallback that accepts an
  unvalidated document.

Call counts are **unchanged at 2/3/5**: this increment lowers tokens per retry, not the
number of retries. ``test_editorial_instructions.py`` still pins the counts; the
count assertions here are deliberately repeated so a regression in either file is
visible.

Everything is offline: the recorded transcript, stub renderers, a throwaway store.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.tailored_output import TailoredCV
from services import generation
from services import tailor_service as service


def rich_cv(session) -> TailoredCV:
    """The recorded layout-retry payload, parsed -- a CV with projects and long bullets."""
    return TailoredCV.model_validate(
        service._parse_json_response(session.step_text('cv_layout_retry'))['cv']
    )


def draft_cv(session) -> TailoredCV:
    return TailoredCV.model_validate(session.step_payload('cv_draft')['cv'])


def retry_prompts(offline) -> list[str]:
    return [p for p in offline.prompts if generation.LAYOUT_RETRY_MARKER in p]


# --- what the retry sends -------------------------------------------------------------

def test_the_retry_sends_only_the_delta_brief_and_the_current_cv(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """No profile, no job description, no prompt file: those were already sent.

    The retry is a follow-up in the same conversation, so re-sending ~1,400 tokens of
    context to say "make these bullets shorter" was pure repetition. What it *does*
    send is the previous CV, because the delta refers to specific units of it.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    retries = retry_prompts(offline)
    assert len(retries) == 1, 'expected exactly one layout retry'
    retry = retries[0]

    # The delta brief is there, and it no longer asks for a whole document.
    assert generation.LAYOUT_RETRY_MARKER in retry
    assert 'LAYOUT CORRECTION' not in retry
    assert 'Return the complete shorter CV JSON' not in retry

    # The previously repeated context is not.
    assert analyst_profile.model_dump_json(indent=2) not in retry
    assert 'BASE PROFILE (authoritative JSON):' not in retry
    assert 'JOB DESCRIPTION:' not in retry
    assert 'EDITORIAL AND FACTUAL REQUIREMENTS' not in retry

    # The previous CV is still sent: a delta needs something to replace.
    assert 'CURRENT CV:' in retry

    # And the retry is materially smaller than the draft call it follows.
    assert len(retry) < len(offline.prompts[0]) * 0.75, (
        'the retry should be a fraction of a full draft prompt'
    )


def test_the_retry_inventory_lists_every_repeating_unit_with_its_current_length(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A delta needs stable unit ids, so the brief enumerates them with a word count.

    The model cannot be asked to "shorten experience 1, bullet 2" unless it is told
    what "experience 1, bullet 2" currently says and how long it is. The inventory is
    derived from the CV that was actually rendered, so it can never drift from it.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    retry = retry_prompts(offline)[0]
    rendered = draft_cv(analyst_session)
    inventory = generation.layout_inventory(rendered, attempt=1)

    assert inventory in retry
    # Every employer is sized, in the order the document lists them, so the model can
    # tell a six-bullet role from a one-bullet one.
    for exp in rendered.experience:
        assert exp.company in inventory
    # And the summary/body split is measured from the document, not a constant.
    assert str(generation.cv_body_words(rendered)) in inventory


def test_the_inventory_reports_the_documents_real_body_length(isolated_service, analyst_session):
    """The brief must not hand the model the prompt file's 650-750 word ambition.

    The recorded fixtures are ~80-100 real words: a brief that says "approximately 650
    words" describes a document three to eight times longer than the one being
    shortened, which is worse than saying nothing.
    """
    rendered = draft_cv(analyst_session)
    body = generation.cv_body_words(rendered)

    assert body == sum(len(b.split()) for e in rendered.experience for b in e.bullets) + sum(
        len(s.split()) for s in rendered.summary
    ), 'body words must be the text the renderer lays out, measured on the same CV'


# --- what the retry may return --------------------------------------------------------

def test_a_delta_response_is_merged_onto_the_validated_cv(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The common case: replacement values only.

    The retry step of the recorded transcript is replaced with a delta, so this drives
    the delta path end to end -- and the document that is saved is the draft with only
    the delta's units changed.
    """
    delta = {
        'experience[0].bullets[0]': 'Own batch pipelines end to end.',
        'experience[1].bullets': ['Built fixture reporting models.'],
    }
    offline = offline_service([
        analyst_session.step_text('cv_draft'),
        analyst_session.step_text('cover_letter'),
        json.dumps(delta),
    ])
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    # One draft call and one merged retry: still 2 CV calls, unchanged by this increment.
    assert result.cv_page_count == 2
    assert result.token_usage.cv_attempts == 2
    assert result.token_usage.cl_attempts == 1

    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))
    before = draft_cv(analyst_session)
    assert saved['cv']['summary'] == before.summary
    assert saved['cv']['experience'][0]['bullets'][0] == delta['experience[0].bullets[0]']
    assert saved['cv']['experience'][1]['bullets'] == delta['experience[1].bullets']
    # Everything the delta did not mention is the validated draft's text, untouched.
    assert saved['cv']['experience'][0]['bullets'][1] == before.experience[0].bullets[1]
    assert saved['cv']['experience'][0]['projects'] == [
        project.model_dump() for project in before.experience[0].projects
    ]


def test_a_delta_that_breaks_a_profile_rule_is_rejected(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Merging is not a bypass: the merged CV is still validated against the profile.

    A prosaic shortening is accepted, but the same mechanism lets the model put
    anything into a bullet -- so the summary rule, the thesis of this increment, is
    checked on a *merged* document, not only on a whole response.
    """
    # The fixture profile forbids third-person verbs in the summary.
    forbidden = ['Analytical engineer combines warehouse modelling and reporting.']
    accepted = {
        'experience[0].bullets': ['Own batch pipelines from ingestion to reporting.'],
    }
    offline = offline_service([
        analyst_session.step_text('cv_draft'),
        analyst_session.step_text('cover_letter'),
        json.dumps(accepted),
    ])
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    assert result.cv_page_count == 2

    # The same run, but the delta also rewrites the summary against the profile's rule.
    offline_service([
        analyst_session.step_text('cv_draft'),
        analyst_session.step_text('cover_letter'),
        json.dumps({**accepted, 'summary': forbidden}),
    ])
    stub_renderers([3, 2])
    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )


def test_a_delta_cannot_invent_an_employer_or_change_dates(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A delta addresses existing units; a path outside the document is a hard error.

    This is the structural guarantee: the previous CV has already passed
    ``validate_cv``, so a delta that can only replace existing bullets, projects,
    summaries and skill categories cannot introduce a bad employer, title or date at
    all -- there is no key through which they could be written. Anything else is
    rejected rather than merged, and the run fails; it does not silently keep the
    unshortened CV.
    """
    merged = rich_cv(analyst_session)
    for payload in (
        {'experience[9].bullets[0]': 'nope'},          # no such employer
        {'experience[0].dates': '2020-01'},            # dates are not addressable
        {'companies[0].name': 'Invented Ltd'},         # not a section of the document
        {'experience[0].bullets[0]': 42},              # wrong type for a unit
    ):
        with pytest.raises(ValueError, match='unknown unit'):
            generation.apply_cv_delta(merged, payload)
    # Rejection must not have mutated the CV that was passed in.
    assert merged.experience[0].bullets[0] == rich_cv(analyst_session).experience[0].bullets[0]


def test_a_delta_merges_rather_than_replaces_so_unchanged_units_survive(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Untouched bullets must survive verbatim, or a retry would silently drop content."""
    before = rich_cv(analyst_session)
    merged = generation.apply_cv_delta(before, {
        'experience[1].bullets[0]': 'Built fixture reporting models across marketing and revenue.',
    })

    assert merged.experience[1].bullets[1] == before.experience[1].bullets[1]
    assert merged.experience[0].bullets == before.experience[0].bullets
    assert merged.experience[0].projects == before.experience[0].projects
    assert [e.company for e in merged.experience] == [e.company for e in before.experience]
    assert [(e.role, e.start_date, e.end_date) for e in merged.experience] == [
        (e.role, e.start_date, e.end_date) for e in before.experience
    ]


def test_a_delta_can_shorten_a_project_and_a_skills_category(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Projects are usually the first thing the brief asks to fold away, so they are addressable."""
    before = rich_cv(analyst_session)
    merged = generation.apply_cv_delta(before, {
        'experience[0].projects[0].name': 'Attribution Overhaul',
        'experience[0].projects[0].bullets[0]': 'Designed incremental attribution pipelines.',
        'skills.Collaboration': ['Stakeholder Management'],
    })

    assert merged.experience[0].projects[0].name == 'Attribution Overhaul'
    assert merged.experience[0].projects[0].bullets[1] == before.experience[0].projects[0].bullets[1]
    assert merged.skills['Collaboration'] == ['Stakeholder Management']
    assert merged.skills['Core Analytics'] == before.skills['Core Analytics']


def test_a_complete_cv_response_is_still_accepted(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The previous contract is not removed: a model that ignores the delta still works.

    The recorded layout-retry step is a complete CV, so this is the path every existing
    test and both fixture transcripts take. It must keep working exactly as before.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    accepted = service._parse_json_response(analyst_session.step_text('cv_layout_retry'))['cv']
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))
    assert saved['cv']['summary'] == accepted['summary']
    assert result.token_usage.cv_attempts == 2


# --- no silent fallback ---------------------------------------------------------------

def test_an_invalid_delta_fails_the_run_rather_than_keeping_the_long_cv(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A malformed retry must not be swallowed into "keep the previous CV".

    Keeping the unshortened CV would report a 2-page document while the model was never
    successfully asked to shorten anything -- and it would hide a model that stopped
    following the delta contract. The three-attempt correction loop applies, then the
    run raises.
    """
    bad_delta = {'experience[12].bullets[0]': 'not a real unit'}
    offline = offline_service([
        analyst_session.step_text('cv_draft'),
        analyst_session.step_text('cover_letter'),
        json.dumps(bad_delta),
    ])
    stub_renderers([3, 2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )
    # The correction loop did its job: the error went back to the model, three times.
    retries = retry_prompts(offline)
    assert len(retries) == generation.MAX_VALIDATION_ATTEMPTS
    assert 'CORRECTION REQUIRED' in retries[-1]


def test_a_merged_cv_still_goes_through_validate_cv(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
    monkeypatch,
):
    """The gate is not bypassed for the delta path -- it is called on the merged CV.

    Asserting on the call, not on the outcome: a merged CV that happened to be valid
    would hide a missing gate if only the result were checked.
    """
    seen = []
    original = generation.validate_cv

    def recording(cv, profile, rules):
        seen.append(cv)
        return original(cv, profile, rules)

    monkeypatch.setattr(generation, 'validate_cv', recording)
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    # Draft validated, then the retry's merged CV validated: one gate per accepted CV.
    assert len(seen) == 2, f'expected the draft and the retry CV to be gated, saw {len(seen)}'


def test_a_bullet_that_claims_a_banned_tool_is_rejected_on_the_delta_path(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The validity checks that matter survive a delta.

    The fixture profile bans several tools (``aws`` among them). A delta bullet that
    claims one must be rejected by the gate, not merged in.

    Note the word boundary in the validator: "AWSome" is a substring, not the tool, so
    it is (correctly) not a claim. The delta has to say "AWS" as a word.
    """
    bad_delta = {
        'experience[1].bullets[0]': 'Migrated the reporting models to AWS.',
    }
    offline = offline_service([
        analyst_session.step_text('cv_draft'),
        analyst_session.step_text('cover_letter'),
        json.dumps(bad_delta),
    ])
    stub_renderers([3, 2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )
    assert 'AWS' in retry_prompts(offline)[-1]


# --- the load-bearing constraints survive ---------------------------------------------

def test_an_ongoing_role_is_not_turned_into_completed_work_by_a_delta(
    isolated_service, analyst_profile, analyst_session,
):
    """Delta keys never reach ``end_date``, which is what "ongoing" means here.

    The recorded fixture's first role ends in ``present``. No delta path can address a
    date, so a shortening retry cannot complete ongoing work even if the model tries:
    an attempted date write is an unknown unit, i.e. a hard error.
    """
    current = draft_cv(analyst_session)
    assert any(e.end_date.lower() == 'present' for e in current.experience), \
        'the fixture must contain an ongoing role or this test is vacuous'

    with pytest.raises(ValueError, match='unknown unit'):
        generation.apply_cv_delta(current, {'experience[0].end_date': '2024-01'})


def test_the_retry_brief_keeps_every_constraint_the_old_instruction_carried(
    analyst_session,
):
    """A shorter prompt must not quietly drop a load-bearing rule.

    These are the constraints the old ``layout_correction_instruction`` stated and the
    profile relies on: keep every employer and exact dates, keep education and core
    skills, never shrink the font, never complete ongoing work, do not remove fields.
    Each is asserted in the text that is actually built.
    """
    rules = generation.ProfileRules.from_profile(analyst_session.profile)
    current = draft_cv(analyst_session)
    instruction = generation.layout_retry_instruction(current, 3, 650, 0, rules)

    for needle in ('all employers', 'exact dates', 'education', 'core skills',
                   'font', 'ongoing', 'removing a field', 'rename', 'achievement', 'metric'):
        assert needle in instruction, f'the retry instruction lost {needle!r}'

    # The project constraint is derived from the *profile's* rules, not hardcoded. This
    # fixture declares no ``rules`` block, so it inherits DEFAULT_PROFILE_RULES (the
    # pre-existing single-candidate behaviour) -- and therefore the Aklamio clause. The
    # negative half: a profile whose own rules declare no project shape gets no clause.
    assert generation.pinned_project_clause(rules) == generation.pinned_project_clause(
        generation.DEFAULT_PROFILE_RULES
    )
    assert 'Aklamio' in instruction and 'three concise bullets' in instruction
    assert generation.pinned_project_clause(
        generation.ProfileRules(special_employers={'acme': {'project_count': 2}})
    ).strip().startswith('Keep one Acme')
    assert generation.pinned_project_clause(generation.ProfileRules()) == ''


def test_the_retry_still_receives_a_word_budget_that_shrinks(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The shrinking budget is unchanged: 650, 550 for the first two retries.

    The *number* stays as it was -- what changed is that the model is now also told how
    long the document currently is, so the target is readable against reality.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([4, 3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    retries = retry_prompts(offline)
    assert len(retries) == 2
    assert 'approximately 650 words' in retries[0]
    assert 'approximately 550 words' in retries[1]
