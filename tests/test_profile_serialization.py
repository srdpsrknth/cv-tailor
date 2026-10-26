"""Phase 3, item 4: the profile is serialized once per application.

Serializing the profile is pure cost -- it produces the same bytes every time -- so
it must happen once per run and be reused by the CV prompt, the cover-letter prompt
and every layout retry.

Two things this file is careful about:

* **It is not a prompt change.** The text the model receives must be byte-identical
  to what it received before, so the central assertion compares the rendered prompt
  against ``profile.model_dump_json(indent=2)`` directly rather than against a
  paraphrase of it. Wording changes belong to Phase 3 item 2, not here.
* **It is not a call-count change.** The number of ``_call_gemini`` calls is pinned
  by ``test_tailoring_pipeline.py`` and is asserted again here, because the whole
  point of removing repeated *work* is that repeated *calls* stay put.

Everything is offline: recorded responses through the offline double, stubbed
renderers, and a throwaway store.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from services import tailor_service as service  # noqa: E402
from services import generation  # noqa: E402

from support import load_profile, recorded_session  # noqa: E402


def fresh_profile():
    """A profile object no earlier test has memoized onto.

    ``load_profile`` constructs a new object per call, so this is genuinely fresh
    even though the file it reads is shared.
    """
    return load_profile('synthetic_analyst')


# --- the prompt bytes are unchanged ---------------------------------------------------

def test_the_prompt_profile_block_is_the_exact_profile_serialization(analyst_profile):
    """The bytes must be the model's own dump, not a re-rendering of it."""
    block = generation.build_context('A job description.', analyst_profile)
    expected = analyst_profile.model_dump_json(indent=2)

    assert expected in block
    assert block.endswith('BASE PROFILE (authoritative JSON):\n' + expected)


def test_passing_the_serialization_explicitly_is_byte_identical(analyst_profile):
    """The new parameter must be able to change nothing at all.

    This is the guard for the whole increment: if supplying ``profile_json`` could
    alter the rendered prompt, the refactor would have become a prompt change.
    """
    plain = generation.build_context(
        'A job description.', analyst_profile, 'Nordwind Analytics GmbH',
        'Analytical Engineer', 'Ireland',
    )
    supplied = generation.build_context(
        'A job description.', analyst_profile, 'Nordwind Analytics GmbH',
        'Analytical Engineer', 'Ireland',
        profile_json=analyst_profile.model_dump_json(indent=2),
    )

    assert plain == supplied
    assert len(plain) == len(supplied)


@pytest.mark.parametrize('country', [None, 'Ireland', 'Germany'])
def test_the_header_is_unaffected_by_the_new_parameter(analyst_profile, country):
    """Every branch of the country header renders the same with and without it."""
    kwargs = dict(company_name='Example Ltd', role_title='Analyst', work_country=country)
    assert generation.build_context('JD', analyst_profile, **kwargs) == generation.build_context(
        'JD', analyst_profile, profile_json=analyst_profile.model_dump_json(indent=2), **kwargs
    )


# --- the pipeline sends that same block, once ------------------------------------------

def test_every_prompt_carries_the_serialized_profile(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Draft and letter carry the identical profile block; the editorial review is gone."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    block = 'BASE PROFILE (authoritative JSON):\n' + analyst_profile.model_dump_json(indent=2)
    assert offline.call_count == 2
    assert all(block in prompt for prompt in offline.prompts), \
        'a prompt did not carry the exact serialized profile'


def test_a_layout_retry_does_not_re_send_the_serialized_profile(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The retry stopped appending the context, so the profile is sent exactly once.

    Until Phase 3 item 1 this asserted the *opposite* -- that the retry re-used the
    same serialized profile block -- because the retry re-sent the whole context and it
    was that increment's job to prove the bytes were shared rather than rebuilt. Item 1
    went further: the retry no longer re-sends the context at all, so the invariant
    changed from "the same bytes every time" to "the context is sent once per
    application". Re-sending it would now be the regression.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([3, 2])

    service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    assert offline.call_count == 3
    block = 'BASE PROFILE (authoritative JSON):\n' + analyst_profile.model_dump_json(indent=2)
    carrying = [p for p in offline.prompts if block in p]
    assert len(carrying) == 2, (
        'the profile block belongs on the draft and the letter, not on the retry'
    )
    shortening = [p for p in offline.prompts if 'LAYOUT RETRY' in p]
    assert len(shortening) == 1, 'expected exactly one layout retry'
    assert block not in shortening[0]
    assert 'CURRENT CV:' in shortening[0]


# --- the serialization itself now happens once ----------------------------------------

def test_the_pipeline_serializes_the_profile_exactly_once(
    isolated_service, offline_service, stub_renderers, analyst_session, monkeypatch,
):
    """The count is the point of the increment, so it is asserted, not assumed.

    A layout retry is forced so the run covers the longest path a successful
    application can take through prompt construction.
    """
    profile = fresh_profile()
    original = type(profile).model_dump_json
    calls = []

    def counting(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(type(profile), 'model_dump_json', counting)

    offline_service(analyst_session.texts())
    stub_renderers([3, 2])
    service.tailor_documents(
        analyst_session.job_description_text, profile,
        company_name='Nordwind Analytics GmbH', role_title='Analytical Engineer',
    )

    indented = [call for call in calls if call.get('indent') == 2]
    assert len(indented) == 1, (
        f'the profile was serialized for a prompt {len(indented)} times; expected once '
        f'for the whole application'
    )


# --- the facts memo ---------------------------------------------------------------------

def test_the_facts_memo_returns_the_same_text_without_reserializing(analyst_profile):
    """The memo is an optimization: same value, less work."""
    direct = generation._profile_facts_json(analyst_profile)
    first = generation.profile_facts_json(analyst_profile)
    second = generation.profile_facts_json(analyst_profile)

    assert first == second == direct


def test_the_facts_memo_avoids_repeated_serialization(monkeypatch):
    """Counting the dumps is the only honest way to show the work is gone.

    The facts block is built from ``model_dump()`` (a dict, then ``json.dumps``),
    not from ``model_dump_json``, so that is the method to count.
    """
    profile = fresh_profile()
    original = type(profile).model_dump
    calls = []

    def counting(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(type(profile), 'model_dump', counting)

    for _ in range(5):
        generation.profile_facts_json(profile)

    assert len(calls) == 1, f'expected one dump for five reads, got {len(calls)}'


def test_the_facts_block_excludes_the_rules(analyst_profile):
    """The load-bearing invariant: a banned tool must not become evidence.

    Declaring a tool banned must not silently un-ban it, so the text scanned for
    claims cannot contain the rules block that names the tool.
    """
    facts = generation.profile_facts_json(analyst_profile)

    assert generation.ProfileRules.from_profile(analyst_profile).banned_tools, \
        'the fixture must declare banned tools or this test is vacuous'
    for tool in generation.ProfileRules.from_profile(analyst_profile).banned_tools:
        assert tool not in facts
    assert 'banned_tools' not in facts
    assert json.loads(facts) == {
        key: value
        for key, value in analyst_profile.model_dump().items()
        if key != 'rules'
    }


def test_a_banned_tool_is_still_rejected_after_memoization(analyst_profile, analyst_session):
    """The cached path must not weaken the rule it exists to speed up."""
    from models.tailored_output import TailoredCV

    rules = generation.ProfileRules.from_profile(analyst_profile)
    payload = analyst_session.step_payload('cv_draft')
    cv = TailoredCV.model_validate(payload['cv'])
    for tool in rules.banned_tools:
        cv.skills = {'Data': [tool]}
        with pytest.raises(ValueError, match='it is not in the profile'):
            generation.validate_cv(cv, analyst_profile, rules)


def test_the_memo_is_not_part_of_the_profile(analyst_profile):
    """The cache must never become a fact.

    It lives in the module namespace by design, so a serialized profile cannot
    contain it -- otherwise the cached text would leak into the prompt, and the
    facts block (which serializes the model) would recurse into itself.
    """
    generation.profile_facts_json(analyst_profile)

    assert generation._FACTS_CACHE_FIELD not in type(analyst_profile).model_fields
    assert generation._FACTS_CACHE_FIELD not in analyst_profile.model_dump()
    assert generation._FACTS_CACHE_FIELD not in analyst_profile.model_dump_json()


def test_a_fresh_profile_is_not_affected_by_another_profiles_cache(
    analyst_profile, marketer_profile,
):
    """Per-object memoization, not a process-global map: two candidates cannot collide."""
    analyst = generation.profile_facts_json(analyst_profile)
    marketer = generation.profile_facts_json(marketer_profile)

    assert analyst != marketer
    assert 'Alex Sample' in analyst and 'Alex Sample' not in marketer
    assert generation.profile_facts_json(analyst_profile) == analyst


def test_the_cache_field_must_stay_underscore_prefixed(analyst_profile):
    """Why the memo's attribute name is private, and why it is not a model field.

    ``Profile`` is a pydantic model with ``extra='forbid'``. Pydantic admits an
    undeclared attribute only while its name is underscore-prefixed; a public
    undeclared name raises. So the *private* name is what makes the cache legal.

    Declaring it as a field instead would be the opposite of what is wanted: a
    declared field joins ``model_dump()``, which would send the cached text to the
    model as though it were a profile fact -- and the facts block serializes the
    model, so it would contain itself.

    Both halves are pinned here so the naming or the field-ness is not silently
    "simplified" into a leak later.
    """
    assert generation._FACTS_CACHE_FIELD.startswith('_')
    assert generation._FACTS_CACHE_FIELD not in type(analyst_profile).model_fields

    # A public undeclared attribute is rejected; the private one is not.
    with pytest.raises(Exception):
        setattr(analyst_profile, 'public_probe', 'x')
    generation.profile_facts_json(analyst_profile)

    # And the cache never becomes part of the serialized profile.
    assert generation._FACTS_CACHE_FIELD not in analyst_profile.model_dump()
    assert generation._FACTS_CACHE_FIELD not in analyst_profile.model_dump_json()


def test_an_uncacheable_profile_still_validates(analyst_profile):
    """Caching is an optimization; a profile that refuses the attribute must still work.

    The fallback is the pre-existing behaviour, so a shape the model rejects must
    still validate rather than raise.
    """
    from models.tailored_output import TailoredCV

    class Uncacheable:
        """Delegates to a real profile but swallows the memo attribute."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            if name == '_inner':
                raise AttributeError(name)
            return getattr(self._inner, name)

    wrapper = Uncacheable(analyst_profile)
    facts = generation.profile_facts_json(wrapper)

    assert facts == generation._profile_facts_json(analyst_profile)
    assert generation.profile_facts_json(wrapper) == facts, 'recomputes rather than caching'

    rules = generation.ProfileRules.from_profile(analyst_profile)
    cv = TailoredCV.model_validate(
        recorded_session('analyst_nordwind').step_payload('cv_draft')['cv']
    )
    generation.validate_cv(cv, wrapper, rules)  # must not raise
