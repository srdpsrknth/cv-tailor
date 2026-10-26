"""Both spellings of ``skills`` must produce the same document (ADR 0016).

A free-form map cannot be expressed in a strict JSON-schema dialect, so a model asked
with ``additionalProperties: false`` is asked for ``[{category, items}, ...]`` instead.
The *request* differs; the *document* must not -- otherwise a retooled candidate would
be penalised for obeying the schema it was given, which is precisely what happened on
the first live attempt: both retooled models returned the array correctly and were
rejected by the validator for it.

Nothing here makes a network call.
"""
from __future__ import annotations

import pytest


def test_the_dict_spelling_is_unchanged():
    """The shape every existing consumer already produces must keep working."""
    from models.tailored_output import TailoredCV

    cv = TailoredCV.model_validate({'skills': {'Analytics': ['SQL', 'Python']}})

    assert cv.skills == {'Analytics': ['SQL', 'Python']}


def test_the_array_spelling_normalises_to_the_same_dict():
    """The strict-dialect spelling carries the same information, so it lands the same."""
    from models.tailored_output import TailoredCV

    as_array = TailoredCV.model_validate({
        'skills': [
            {'category': 'Analytics', 'items': ['SQL', 'Python']},
            {'category': 'Tools', 'items': ['Tableau']},
        ]
    })
    as_dict = TailoredCV.model_validate({
        'skills': {'Analytics': ['SQL', 'Python'], 'Tools': ['Tableau']}
    })

    assert as_array.skills == as_dict.skills
    assert as_array.model_dump() == as_dict.model_dump(), (
        'the two spellings must produce an identical document, or the renderer would '
        'receive different input depending on which dialect a model was asked in'
    )


def test_a_malformed_array_is_not_coerced():
    """Coercing a bad entry would invent a category the model never produced.

    The normaliser passes anything it does not fully recognise straight through, so the
    ordinary validation error still fires rather than a plausible-looking document being
    fabricated from a partial one.
    """
    from pydantic import ValidationError

    from models.tailored_output import TailoredCV

    for malformed in (
        [{'category': 'X'}],                      # no items
        [{'items': ['a']}],                       # no category
        [{'category': 'X', 'items': 'not-a-list'}],
        [{'category': 7, 'items': ['a']}],        # category is not a string
        ['just-a-string'],
    ):
        with pytest.raises(ValidationError):
            TailoredCV.model_validate({'skills': malformed})


def test_non_list_skills_are_left_alone():
    """A dict stays a dict; the validator is a widening, not a replacement."""
    from models.tailored_output import TailoredCV

    assert TailoredCV.model_validate({'skills': {}}).skills == {}
    assert TailoredCV.model_validate({}).skills == {}
