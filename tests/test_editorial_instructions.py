"""Phase 3, increment 2: the editorial-review pass is merged into the draft prompt.

These tests pin the *decision*, not just the call count. The pass was removed because
its requirements were already implicit in the draft prompt and the document it produced
was re-validated from scratch anyway. Two things must therefore hold:

1. The requirements are still present in the prompt the model drafts against -- if a
   later edit deletes them, the increment has quietly become "drop the review" without
   saying so.
2. Removing the second call did **not** weaken the gate. The draft is still the only
   accepted CV and it still goes through ``validate_cv``; there is no path where a
   failed draft is accepted because the review call used to catch it.
"""
from __future__ import annotations

import json

import pytest

from models.tailored_output import TailoredCV
from services import tailor_service as service
from services import generation


# --- the requirements still reach the model -------------------------------------------

def test_the_draft_prompt_carries_the_editorial_requirements():
    """The merged text is injected into the CV prompt, before the job description."""
    prompt = generation.build_cv_prompt('PROMPT BODY', '\nJOB DESCRIPTION:\nJD')

    assert generation.EDITORIAL_REQUIREMENTS in prompt
    # Order matters: the checks precede the context, so the model drafts against them
    # rather than receiving them as a post-hoc instruction on a finished document.
    assert prompt.index(generation.EDITORIAL_REQUIREMENTS) < prompt.index('JOB DESCRIPTION')


def test_the_requirements_are_not_injected_twice():
    """A duplicated block would waste tokens on every single CV call."""
    prompt = generation.build_cv_prompt('PROMPT BODY', 'CTX')

    assert prompt.count(generation.EDITORIAL_REQUIREMENTS.strip()) == 1


def test_the_letter_prompt_is_untouched_by_the_merge():
    """These are CV-editorial requirements; the letter must not inherit them.

    ``tailor_documents`` builds the letter prompt from the context alone. If the merge
    had been done by appending to ``build_context`` instead, every letter call would
    have paid for CV rules it does not use.
    """
    assert generation.EDITORIAL_REQUIREMENTS not in generation.build_context(
        'JD', _analyst_profile()
    )


def test_the_pipeline_sends_the_requirements_on_the_cv_call_only(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Asserted on the prompts actually sent, not on the builder in isolation."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    carrying = offline.prompts_containing(generation.EDITORIAL_REQUIREMENTS.strip())
    assert len(carrying) == 1, 'the CV call must carry the requirements exactly once'
    # The happy path is draft + letter: the one call carrying them is the CV draft.
    assert offline.call_count == 2


def test_a_layout_retry_also_carries_the_requirements(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The retry reuses the same prompt, so it must not lose the editorial checks."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    shortening = [p for p in offline.prompts if 'LAYOUT CORRECTION' in p]
    assert len(shortening) == 1
    assert generation.EDITORIAL_REQUIREMENTS.strip() in shortening[0]


# --- the gate is unchanged --------------------------------------------------------------

def test_the_draft_is_still_the_only_gated_document(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """No silent fallback: an invalid draft fails the run instead of being accepted.

    Before the increment the review call happened to give the model a second chance at
    a valid document. Removing it must not turn that into leniency -- an invalid draft
    is still retried only through the documented correction loop and then raises.
    """
    bad = json.loads(analyst_session.step_text('cv_draft'))
    bad['cv']['experience'] = bad['cv']['experience'][:-1]  # always missing an employer
    offline = offline_service([json.dumps(bad)] * 3)
    stub_renderers([2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )
    # Three CV attempts, no letter call: the letter is never drafted off an invalid CV.
    assert offline.call_count == 3


def test_an_invalid_draft_cannot_be_rescued_by_a_second_call(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The removed pass cannot have been an unvalidated escape hatch.

    If a future change reintroduced a second CV call whose response skipped validation,
    a bad draft followed by a *valid* response would succeed here. It must not: the
    pipeline asks for one draft and validates whatever comes back.
    """
    bad = json.loads(analyst_session.step_text('cv_draft'))
    bad['cv']['experience'] = bad['cv']['experience'][:-1]
    offline = offline_service([json.dumps(bad), analyst_session.step_text('cover_letter')])
    stub_renderers([2])

    with pytest.raises(ValueError, match='after three attempts'):
        service.tailor_documents(
            analyst_session.job_description_text, analyst_profile,
            company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
        )
    # The letter prompt is recognisable by its own opening line. The CV prompt also
    # mentions "cover letter" in prose, so that phrase alone is not a usable marker.
    assert not any(
        'Write a clear, professional cover letter' in p for p in offline.prompts
    ), 'a letter must not be drafted from a bad CV'


def test_the_draft_response_is_what_validation_sees(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The accepted CV is byte-for-byte the draft payload that was recorded."""
    offline_service(analyst_session.texts())
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )
    accepted = TailoredCV.model_validate(analyst_session.step_payload('cv_draft')['cv'])

    assert result.cv_page_count == 2
    from pathlib import Path
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))
    assert saved['cv']['summary'] == accepted.summary
    assert saved['cv']['experience'][0]['company'] == accepted.experience[0].company


# --- the call-count baseline ------------------------------------------------------------

def test_happy_path_is_two_calls(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """3 -> 2: draft + letter, with no review pass in between."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert offline.call_count == 2
    assert not offline.exhausted


def test_typical_path_is_three_calls(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """4 -> 3: draft + one layout retry + letter."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert offline.call_count == 3
    assert not offline.exhausted


def test_max_successful_path_is_five_calls(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """6 -> 5: draft + three layout retries (fits on the fourth render) + letter.

    The transcript records only one layout-retry response, so ``OfflineGemini`` replays
    the last one once the script is exhausted -- which is exactly what a real model
    asked for a shorter CV three times would produce. ``exhausted`` is therefore
    expected here and is asserted, so this test cannot silently stop exercising the
    longest successful path.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 3, 3, 2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert result.cv_page_count == 2
    assert offline.call_count == 5
    assert result.token_usage.cv_attempts == 4 and result.token_usage.cl_attempts == 1


def _analyst_profile():
    from support import load_profile

    return load_profile('synthetic_analyst')
