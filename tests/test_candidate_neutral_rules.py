"""Explicit project rules should not imply another candidate's project shape."""

from types import SimpleNamespace

import pytest

from services.prompts import pinned_project_clause
from services.validation import ProfileRules, _apply_employer_rules


def test_layout_mentions_each_explicit_project_and_bullet_count():
    rules = ProfileRules(special_employers={
        "sample one": {"project_count": 2, "bullets_per_project": 1},
        "sample two": {"project_count": 0},
    })
    text = pinned_project_clause(rules)
    assert "2 project(s) for Sample one" in text
    assert "1 bullets in each Sample one project" in text
    assert "0 project(s) for Sample two" in text
    assert "attribution" not in text


def test_project_count_does_not_require_an_undeclared_bullet_count():
    rules = ProfileRules(special_employers={"sample": {"project_count": 1}})
    exp = SimpleNamespace(company="Sample", bullets=[], projects=[SimpleNamespace(name="Project", bullets=["One"])])
    _apply_employer_rules(exp, rules)


def test_project_name_rule_checks_every_project():
    rules = ProfileRules(special_employers={"sample": {"forbidden_project_name": "internal"}})
    exp = SimpleNamespace(company="Sample", bullets=[], projects=[
        SimpleNamespace(name="Public project", bullets=[]),
        SimpleNamespace(name="Internal project", bullets=[]),
    ])
    with pytest.raises(ValueError, match="naming rules"):
        _apply_employer_rules(exp, rules)
