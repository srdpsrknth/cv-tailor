"""Editing anything that shapes a draft must invalidate cached drafts (WP10).

The cache key hashed the prompt files but not the editorial requirements, the wording
built in code, the layout budgets or the CV template. Each is varied on its own below.
"""
from __future__ import annotations

import inspect

import pytest

from services import pipeline, prompts, tailor_service
from services.cache_store import cache_key
from services.pipeline_fingerprint import CV_TEMPLATE_PATH, pipeline_fingerprint, template_digest


def base_key(**overrides) -> str:
    values = dict(
        profile_bytes="{}", job_description="jd", company_name="C", role_title="R",
        work_country=None, prompt_cv="cv", prompt_cl="cl", prompt_version="v",
        schema_version="s", provider="p", model_cv="m", model_cl="m",
        rules_fingerprint="r", pipeline_version=pipeline_fingerprint(),
    )
    values.update(overrides)
    return cache_key(**values)


def key_now() -> str:
    return base_key(pipeline_version=pipeline_fingerprint())


def test_the_fingerprint_is_deterministic():
    assert pipeline_fingerprint() == pipeline_fingerprint()
    assert base_key() == base_key()


def test_the_real_template_exists_and_is_hashed():
    assert CV_TEMPLATE_PATH.is_file()
    assert len(template_digest()) == 64


def test_the_fingerprint_is_part_of_the_cache_key():
    assert base_key(pipeline_version="other") != base_key()


def test_a_key_built_without_the_fingerprint_is_still_valid():
    assert len(base_key(pipeline_version="")) == 64


def test_editing_the_editorial_requirements_changes_the_key(monkeypatch):
    before = key_now()
    monkeypatch.setattr(prompts, "EDITORIAL_REQUIREMENTS", prompts.EDITORIAL_REQUIREMENTS + "- New rule.\n")
    assert key_now() != before


@pytest.mark.parametrize("name", ["LAYOUT_BUDGET_START", "LAYOUT_BUDGET_STEP", "LAYOUT_BUDGET_FLOOR"])
def test_changing_a_layout_budget_changes_the_key(monkeypatch, name):
    before = key_now()
    monkeypatch.setattr(prompts, name, getattr(prompts, name) + 1)
    assert key_now() != before


@pytest.mark.parametrize("name", ["MAX_LAYOUT_ATTEMPTS", "MAX_VALIDATION_ATTEMPTS"])
def test_changing_a_retry_limit_changes_the_key(monkeypatch, name):
    before = key_now()
    monkeypatch.setattr(pipeline, name, getattr(pipeline, name) + 1)
    assert key_now() != before


def test_changing_the_context_wording_changes_the_key(monkeypatch):
    before = key_now()

    def build_context(job_description, profile):  # a differently worded context block
        return "A new wording " + job_description

    monkeypatch.setattr(prompts, "build_context", build_context)
    assert key_now() != before


def test_changing_the_template_changes_the_key(tmp_path):
    template = tmp_path / "main.tex.jinja2"
    template.write_bytes(b"\\documentclass{article}\n")
    one = pipeline_fingerprint(template)
    template.write_bytes(b"\\documentclass{altacv}\n")
    assert pipeline_fingerprint(template) != one


def test_line_endings_do_not_change_the_template_digest(tmp_path):
    """A Windows checkout (CRLF) and a macOS one (LF) must share cache entries."""
    lf, crlf = tmp_path / "lf.tex", tmp_path / "crlf.tex"
    lf.write_bytes(b"line one\nline two\n")
    crlf.write_bytes(b"line one\r\nline two\r\n")
    assert template_digest(lf) == template_digest(crlf)
    assert pipeline_fingerprint(lf) == pipeline_fingerprint(crlf)


def test_a_missing_template_does_not_raise(tmp_path):
    assert template_digest(tmp_path / "absent") == ""
    assert len(pipeline_fingerprint(tmp_path / "absent")) == 64


def test_the_service_passes_the_fingerprint_to_the_key():
    assert "pipeline_version=pipeline_fingerprint()" in inspect.getsource(tailor_service)


@pytest.mark.parametrize("module_name", ["validation", "fact_checks", "cv_structure"])
def test_changing_a_validator_module_changes_the_key(monkeypatch, module_name):
    import services

    module = getattr(services, module_name)
    before = key_now()
    real = inspect.getsource

    def patched(obj):
        text = real(obj)
        return text + "\n# a stricter rule\n" if obj is module else text

    monkeypatch.setattr(inspect, "getsource", patched)
    assert key_now() != before


def test_changing_the_leak_guard_changes_the_key(monkeypatch):
    from services import suggested_claims

    before = key_now()

    def reject_suggestion_leak(cv, texts, profile):  # a different guard
        return None

    monkeypatch.setattr(suggested_claims, "reject_suggestion_leak", reject_suggestion_leak)
    assert key_now() != before


def test_validator_source_line_endings_do_not_change_the_key(monkeypatch):
    before = key_now()
    real = inspect.getsource
    monkeypatch.setattr(inspect, "getsource", lambda obj: real(obj).replace("\n", "\r\n"))
    assert key_now() == before
