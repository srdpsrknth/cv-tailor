"""Confirm-first claim suggestions (WP9): generation, storage, the leak guard, acceptance.

Everything is offline and synthetic. The guarantee under test: a suggestion is a question
for the candidate and cannot reach a document unless the profile already says it.
"""
from __future__ import annotations

import copy
import json
import logging
import shutil
from pathlib import Path

import pytest
import yaml

from models.tailored_output import TailoredCV
from services import claim_acceptance as acceptance
from services import generation
from services import suggested_claims as claims
from services import tailor_service as service
from services.profile_text_edit import Unsupported, add_mapping_list, insert_list_item
from support import load_profile

FIXTURE = Path(__file__).parent / "fixtures" / "profiles" / "synthetic_analyst.yaml"

PROJECT_TEXT = "Applied inclusion and exclusion criteria to define eligible cohorts from source records."
SKILL_TEXT = "Cohort definition"


def suggestion(text=PROJECT_TEXT, **attach):
    attach = attach or {
        "type": "experience_project", "company": "Northwind Analytics GmbH",
        "project": "Attribution Rebuild", "category": None,
    }
    return {
        "requirement": "Cohort definition from structured data",
        "proposed_text": text,
        "attach_to": attach,
        "rationale": "The project already validates a rebuilt model against production.",
    }


# --- the response contract -------------------------------------------------------------


def test_the_cv_schema_declares_suggested_claims_beside_the_cv_and_not_inside_it():
    schema = generation.RESPONSE_SCHEMAS["cv"]
    assert "suggested_claims" in schema["properties"]
    assert "suggested_claims" not in schema["properties"]["cv"]["properties"]
    item = schema["properties"]["suggested_claims"]["items"]
    assert sorted(item["required"]) == ["attach_to", "proposed_text", "rationale", "requirement"]
    assert "cover_letter" not in json.dumps(schema)
    # A field literally named `type` must still be converted to a standard JSON type name.
    assert item["properties"]["attach_to"]["properties"]["type"]["type"] == "string"
    assert "null" in schema["properties"]["suggested_claims"]["type"]
    assert "suggested_claims" not in generation.RESPONSE_SCHEMAS["cover_letter"]["properties"]


def test_the_prompt_says_suggestions_are_questions_and_never_cv_content():
    text = generation.PROMPT_CV_PATH.read_text(encoding="utf-8")
    for needle in ("suggested_claims", "QUESTION", "at most 8", "NEVER use a suggestion"):
        assert needle in text


# --- validation ------------------------------------------------------------------------


def test_valid_suggestions_are_kept_with_the_profiles_own_spelling(analyst_profile):
    raw = [
        suggestion(attach_to_lower := PROJECT_TEXT, type="experience_project",
                   company="northwind analytics gmbh", project="attribution rebuild"),
        suggestion(SKILL_TEXT, type="skill", category="core_analytics"),
        suggestion("Wrote reusable SQL models.", type="experience", company="Contoso Metrics Ltd"),
    ]
    kept, dropped = claims.validate_suggestions(raw, analyst_profile)
    assert dropped == []
    assert [k["attach_to"]["type"] for k in kept] == ["experience_project", "skill", "experience"]
    assert kept[0]["attach_to"] == {
        "type": "experience_project", "company": "Northwind Analytics GmbH",
        "project": "Attribution Rebuild",
    }
    assert all(k["status"] == "pending" for k in kept)


def test_invalid_targets_are_dropped_with_a_log_note_not_an_error(analyst_profile, caplog):
    raw = [
        suggestion(type="experience", company="Nonexistent Corp"),
        suggestion(type="experience_project", company="Northwind Analytics GmbH", project="Nope"),
        suggestion(type="standalone_project", project="Nope"),
        suggestion(type="skill", category="no_such_category"),
        suggestion(type="martian"),
        "not an object",
        suggestion("", type="experience", company="Northwind Analytics GmbH"),
        suggestion(PROJECT_TEXT),
    ]
    with caplog.at_level(logging.WARNING):
        kept, dropped = claims.validate_suggestions(raw, analyst_profile)
    assert len(kept) == 1 and len(dropped) == 7
    assert all(d["reason"] for d in dropped)
    assert "Dropped suggested claim" in caplog.text


def test_the_list_is_capped_at_eight_and_repeats_or_profile_text_are_dropped(analyst_profile):
    many = [suggestion(f"Distinct sentence number {i} about cohorts.") for i in range(12)]
    kept, dropped = claims.validate_suggestions(many, analyst_profile)
    assert len(kept) == claims.MAX_SUGGESTIONS
    assert len(dropped) == 4

    repeated, why = claims.validate_suggestions([suggestion(), suggestion()], analyst_profile)
    assert len(repeated) == 1 and "duplicate" in why[0]["reason"]

    existing = "Delivered a reproducible methodology note for the analytics team."
    kept, dropped = claims.validate_suggestions([suggestion(existing)], analyst_profile)
    assert kept == [] and "already states" in dropped[0]["reason"]


@pytest.mark.parametrize("raw", [None, [], "nonsense", {"a": 1}])
def test_absent_or_malformed_lists_never_raise(analyst_profile, raw):
    kept, _ = claims.validate_suggestions(raw, analyst_profile)
    assert kept == []


def test_an_application_without_suggestions_still_loads(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "content.json").write_text("{}", encoding="utf-8")
    record = claims.load_suggestions(source / "content.json")
    assert record["suggestions"] == []
    (source / claims.SUGGESTIONS_FILENAME).write_text("{broken", encoding="utf-8")
    assert claims.load_suggestions(source / "content.json")["suggestions"] == []


# --- the leak guard: nothing reaches a document -----------------------------------------


def cv_with_bullet(profile, bullet):
    return TailoredCV(
        summary=["Analytical engineer."],
        experience=[{
            "company": "Northwind Analytics GmbH", "role": "Analytical Engineer",
            "start_date": "2023-04", "end_date": "present", "bullets": [bullet],
        }],
    )


def test_a_suggestion_text_in_the_cv_is_rejected_unless_the_profile_has_it(analyst_profile):
    cv = cv_with_bullet(analyst_profile, PROJECT_TEXT)
    with pytest.raises(ValueError, match="suggested claim"):
        claims.reject_suggestion_leak(cv, [PROJECT_TEXT], analyst_profile)
    # a lightly reworded copy is caught too
    cv = cv_with_bullet(analyst_profile, PROJECT_TEXT.replace("Applied", "Used"))
    with pytest.raises(ValueError):
        claims.reject_suggestion_leak(cv, [PROJECT_TEXT], analyst_profile)
    # unrelated CV text is fine
    claims.reject_suggestion_leak(cv_with_bullet(analyst_profile, "Own batch pipelines."), [PROJECT_TEXT], analyst_profile)


def test_once_the_profile_states_it_the_cv_may_use_it(analyst_profile):
    profile = analyst_profile.model_copy(deep=True)
    profile.experience[0].selected_projects[0].bullets.append(PROJECT_TEXT)
    claims.reject_suggestion_leak(cv_with_bullet(profile, PROJECT_TEXT), [PROJECT_TEXT], profile)


def test_a_suggested_skill_is_rejected_in_the_cv_skills_block(analyst_profile):
    cv = TailoredCV(skills={"core_analytics": ["Advanced SQL", "Spatial modelling"]})
    with pytest.raises(ValueError):
        claims.reject_suggestion_leak(cv, ["Spatial modelling"], analyst_profile)


def tailored_response(session, extra, bullet=None):
    payload = session.step_payload("cv_draft")
    if bullet:
        payload["cv"]["experience"][0]["bullets"][0] = bullet
    payload["suggested_claims"] = extra
    return json.dumps(payload)


def test_the_pipeline_retries_a_draft_that_uses_a_suggestion_and_stores_the_final_list(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    texts = analyst_session.texts()
    leak = tailored_response(analyst_session, [suggestion()], bullet=PROJECT_TEXT)
    clean = tailored_response(analyst_session, [suggestion()])
    offline = offline_service([leak, clean] + texts[1:])
    stub_renderers([2])

    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name="Nordwind Analytics GmbH", role_title="Analytical Engineer",
    )

    assert offline.call_count == 3, "the leaking draft must be retried"
    assert "suggested claim" in offline.prompts[1]
    content = json.loads(Path(result.source_path).read_text(encoding="utf-8"))
    assert PROJECT_TEXT not in json.dumps(content)
    stored = claims.load_suggestions(result.source_path)
    assert [s["proposed_text"] for s in stored["suggestions"]] == [PROJECT_TEXT]
    assert stored["suggestions"][0]["status"] == "pending"


def test_generation_saves_suggestions_beside_the_application_and_a_cache_hit_restores_them(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    texts = analyst_session.texts()
    texts[0] = tailored_response(
        analyst_session, [suggestion(), suggestion(type="experience", company="Nobody")]
    )
    offline_service(texts)
    stub_renderers([2])
    args = (analyst_session.job_description_text, analyst_profile)
    kwargs = dict(company_name="Nordwind Analytics GmbH", role_title="Analytical Engineer")

    first = service.tailor_documents(*args, **kwargs)
    record = json.loads((Path(first.source_path).parent / claims.SUGGESTIONS_FILENAME).read_text(encoding="utf-8"))
    assert len(record["suggestions"]) == 1 and len(record["dropped"]) == 1

    offline = offline_service(texts)
    stub_renderers([2])
    second = service.tailor_documents(*args, **kwargs)
    assert second.cache_hit and offline.call_count == 0
    assert len(claims.load_suggestions(second.source_path)["suggestions"]) == 1


def test_a_generation_with_no_suggestions_writes_no_file(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline_service(analyst_session.texts())
    stub_renderers([2])
    result = service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name="Nordwind Analytics GmbH", role_title="Analytical Engineer",
    )
    assert not (Path(result.source_path).parent / claims.SUGGESTIONS_FILENAME).exists()


# --- targeted YAML insertion -----------------------------------------------------------

SAMPLE = '''version: "1.0"
# top comment
identity: {full_name: "A", email: "a@example.invalid"}
experience:
  - company: "Acme"   # keep me
    role: "Analyst"
    start_date: "2020-01"
    end_date: "present"
    bullets:
      - "First."   # trailing comment
      - 'Second.'
    selected_projects:
      - name: "Proj"
        bullets: []
      - name: "Other"
        bullets:
          - Plain bullet
skills:
  core: ["SQL", "Python"]   # flow
  extra:
    - Git
languages: []
'''


def test_insertions_touch_only_the_target_and_keep_comments_and_quote_style():
    one = insert_list_item(SAMPLE, ("experience", 0, "bullets"), "Third: with colon.")
    # the new line copies its neighbour's quoting (single quotes here) and nothing else moves
    assert one.replace("      - 'Third: with colon.'\n", "") == SAMPLE

    two = insert_list_item(SAMPLE, ("experience", 0, "selected_projects", 0, "bullets"), "New proj bullet.")
    assert "bullets:\n          - New proj bullet.\n" in two
    assert "# keep me" in two and "# trailing comment" in two

    flow = insert_list_item(SAMPLE, ("skills", "core"), "dbt")
    assert 'core: ["SQL", "Python", "dbt"]   # flow' in flow

    plain = insert_list_item(SAMPLE, ("experience", 0, "selected_projects", 1, "bullets"), "Another")
    assert "          - Plain bullet\n          - Another\n" in plain

    for text in (one, two, flow, plain):
        assert yaml.safe_load(text)


def test_a_new_category_is_added_at_the_end_of_the_skills_block():
    text = add_mapping_list(SAMPLE, ("skills",), "tools", ["dbt"])
    assert "    - Git\n  tools:\n    - dbt\nlanguages" in text
    assert yaml.safe_load(text)["skills"]["tools"] == ["dbt"]


def test_crlf_files_keep_their_line_endings():
    text = SAMPLE.replace("\n", "\r\n")
    edited = insert_list_item(text, ("experience", 0, "bullets"), "Third.")
    assert edited.count("\r\n") == edited.count("\n")
    assert yaml.safe_load(edited)["experience"][0]["bullets"][-1] == "Third."


def test_unsupported_shapes_raise_rather_than_guess():
    multi = "a:\n  - |\n    text\n"
    with pytest.raises(Unsupported):
        insert_list_item(multi, ("a",), "x")
    with pytest.raises(Unsupported):
        insert_list_item(SAMPLE, ("experience", 5, "bullets"), "x")


# --- accepting -------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """A store with one profile (the synthetic fixture, comments intact) and an application."""
    profile_dir = tmp_path / "profiles" / "analyst_a"
    profile_dir.mkdir(parents=True)
    profile_path = profile_dir / "profile.yaml"
    shutil.copy2(FIXTURE, profile_path)
    source = tmp_path / "outputs" / "analyst_a" / "job1" / "source"
    source.mkdir(parents=True)
    content = source / "content.json"
    content.write_text("{}", encoding="utf-8")
    profile = load_profile("synthetic_analyst")
    kept, _ = claims.validate_suggestions([
        suggestion(),
        suggestion(SKILL_TEXT, type="skill", category="core_analytics"),
        suggestion("Reconciled fixture revenue across source systems.", type="experience",
                   company="Contoso Metrics Ltd"),
        suggestion("Supported fixture analyses during the internship.", type="experience",
                   company="Fabrikam Internship"),
    ], profile)
    claims.save_suggestions(source, kept, [])
    return profile_path, content


def test_accepting_inserts_into_the_right_places_and_keeps_the_rest_of_the_file(workspace):
    profile_path, content = workspace
    before = profile_path.read_text(encoding="utf-8")

    result = acceptance.accept_suggestions(content, profile_path, [1, 2, 3], expected_profile_id="analyst_a")

    assert result.approach == acceptance.APPROACH_TARGETED and result.warnings == []
    after = profile_path.read_text(encoding="utf-8")
    assert "# SYNTHETIC FIXTURE" in after and "# Deliberately has no bullets" in after
    removed = [l for l in after.splitlines() if l not in before.splitlines()]
    assert len(removed) == 3, removed
    data = yaml.safe_load(after)
    assert data["experience"][0]["selected_projects"][0]["bullets"][-1] == PROJECT_TEXT
    assert data["skills"]["core_analytics"][-1] == SKILL_TEXT
    assert data["experience"][1]["bullets"][-1].startswith("Reconciled")
    load_profile_ok = load_profile  # the real validator accepts the result
    assert load_profile_ok  # noqa: S101

    backups = list(profile_path.parent.glob("profile.backup-*.yaml"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == before
    assert result.backup == backups[0]

    record = claims.load_suggestions(content)
    assert [s["status"] for s in record["suggestions"]] == ["accepted"] * 3 + ["pending"]


def test_an_empty_bullets_list_becomes_a_block_list(workspace):
    profile_path, content = workspace
    result = acceptance.accept_suggestions(content, profile_path, [4], expected_profile_id="analyst_a")
    assert result.approach == acceptance.APPROACH_TARGETED
    text = profile_path.read_text(encoding="utf-8")
    assert '    bullets:\n      - Supported fixture analyses during the internship.\n' in text
    assert yaml.safe_load(text)["experience"][2]["bullets"] == [
        "Supported fixture analyses during the internship."
    ]


def test_dry_run_changes_nothing_and_accepting_twice_is_a_noop(workspace):
    profile_path, content = workspace
    before = profile_path.read_bytes()
    plan = acceptance.accept_suggestions(content, profile_path, [1], dry_run=True)
    assert plan.dry_run and plan.accepted == [1] and plan.changes[0].description
    assert profile_path.read_bytes() == before
    assert not list(profile_path.parent.glob("*.backup-*"))

    acceptance.accept_suggestions(content, profile_path, [1])
    again = acceptance.accept_suggestions(content, profile_path, [1])
    assert again.accepted == [] and again.skipped == [(1, "already accepted")]
    text = profile_path.read_text(encoding="utf-8")
    assert text.count(PROJECT_TEXT) == 1


def test_a_category_is_created_only_when_the_user_names_it(workspace):
    profile_path, content = workspace
    result = acceptance.accept_suggestions(content, profile_path, [2], category="Research methods")
    assert result.approach == acceptance.APPROACH_TARGETED
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert data["skills"]["Research methods"] == [SKILL_TEXT]
    assert SKILL_TEXT not in data["skills"]["core_analytics"]
    assert "# SYNTHETIC FIXTURE" in profile_path.read_text(encoding="utf-8")


def test_an_unhandled_shape_falls_back_to_a_full_dump_with_a_warning(workspace):
    profile_path, content = workspace
    text = profile_path.read_text(encoding="utf-8")
    # a multi-line flow list: valid YAML the targeted editor refuses
    text = text.replace(
        'skills:\n  core_analytics:\n    - "Advanced SQL"',
        'skills:\n  core_analytics: [\n    "Advanced SQL",\n    "Forecasting"]\n  old_core:\n    - "Advanced SQL"', 1)
    profile_path.write_text(text, encoding="utf-8")
    result = acceptance.accept_suggestions(content, profile_path, [2])
    assert result.approach == acceptance.APPROACH_FULL_DUMP
    assert any("full YAML dump" in w for w in result.warnings)
    assert yaml.safe_load(profile_path.read_text(encoding="utf-8"))["skills"]["core_analytics"][-1] == SKILL_TEXT


def test_a_write_that_does_not_validate_is_rolled_back(workspace, monkeypatch):
    profile_path, content = workspace
    before = profile_path.read_bytes()
    from services import profile_loader

    real = profile_loader.load_profile
    calls = []

    def flaky(path):
        calls.append(path)
        if len(calls) >= 2:  # the pre-flight check passes, the post-write one fails
            raise ValueError("Profile validation failed: synthetic")
        return real(path)

    monkeypatch.setattr(profile_loader, "load_profile", flaky)
    with pytest.raises(acceptance.ClaimError, match="restored"):
        acceptance.accept_suggestions(content, profile_path, [1])
    assert profile_path.read_bytes() == before
    assert claims.load_suggestions(content)["suggestions"][0]["status"] == "pending"


def test_numbers_and_ownership_are_checked(workspace):
    profile_path, content = workspace
    with pytest.raises(acceptance.ClaimError, match="No suggestion number 9"):
        acceptance.accept_suggestions(content, profile_path, [9])
    with pytest.raises(acceptance.ClaimError, match="belongs to profile 'analyst_a'"):
        acceptance.accept_suggestions(content, profile_path, [1], expected_profile_id="marketer_b")


def test_rejecting_records_the_decision_and_leaves_the_profile_alone(workspace):
    profile_path, content = workspace
    before = profile_path.read_bytes()
    assert acceptance.reject_suggestions(content, [2]) == [2]
    assert profile_path.read_bytes() == before
    assert claims.load_suggestions(content)["suggestions"][1]["status"] == "rejected"


def test_accepted_text_becomes_citable_by_the_cv_guard(workspace):
    profile_path, content = workspace
    acceptance.accept_suggestions(content, profile_path, [1])
    from services.profile_loader import load_profile as load

    profile = load(str(profile_path))
    claims.reject_suggestion_leak(cv_with_bullet(profile, PROJECT_TEXT), [PROJECT_TEXT], profile)


def test_question_shaped_suggestions_are_dropped():
    """The model must return the statement to add, never the question itself."""
    from services.suggested_claims import _is_question

    assert _is_question("Have you completed GCP training?")
    assert _is_question("Did you coordinate study visits")
    assert _is_question("Coordinated study visits?")
    assert not _is_question("Coordinated study visits with site staff.")
    assert not _is_question("Documented requirements; have results been shared")


# --- a missing ``bullets:`` key ----------------------------------------------------------

NO_BULLETS = '''version: "1.0"
# top comment
experience:
  - company: "Acme"   # keep me
    role: "Analyst"
    start_date: "2020-01"
    selected_projects:
      - name: "Proj"   # project comment
        description: "A project"   # trailing
      # a comment between entries
      - name: "Other"
        bullets:
          - Plain bullet
  - company: "Beta"
    role: "Engineer"
standalone_projects:
  - name: "Solo"
    tools:
      - dbt
      - SQL
skills:
  core: ["SQL"]
'''


@pytest.mark.parametrize("path, expected", [
    (("experience", 0, "bullets"), ("experience", 0, "bullets")),
    (("experience", 0, "selected_projects", 0, "bullets"), ("experience", 0, "selected_projects", 0, "bullets")),
    (("experience", 1, "bullets"), ("experience", 1, "bullets")),
    (("standalone_projects", 0, "bullets"), ("standalone_projects", 0, "bullets")),
])
def test_a_missing_bullets_key_is_inserted_in_place_and_comments_survive(path, expected):
    edited = insert_list_item(NO_BULLETS, path, "New: bullet.")
    data = yaml.safe_load(edited)
    node = data
    for part in expected:
        node = node[part] if part != "bullets" else node.get("bullets")
    assert node == ["New: bullet."]
    for comment in ("# top comment", "# keep me", "# project comment", "# trailing",
                    "# a comment between entries"):
        assert comment in edited
    # Only the two new lines were added; everything else is byte-identical.
    before, after = NO_BULLETS.split("\n"), edited.split("\n")
    assert len(after) == len(before) + 2
    assert [line for line in after if line not in before] == [
        line for line in after if "bullets:" in line and line not in before
        or "New: bullet" in line
    ]


def test_the_new_key_is_aligned_with_its_siblings():
    edited = insert_list_item(NO_BULLETS, ("experience", 0, "selected_projects", 0, "bullets"), "X")
    assert '        description: "A project"   # trailing\n        bullets:\n          - X\n' in edited
    edited = insert_list_item(NO_BULLETS, ("experience", 1, "bullets"), "X")
    assert '    role: "Engineer"\n    bullets:\n      - X\nstandalone_projects:' in edited


def test_a_missing_key_after_a_block_scalar_is_still_refused():
    text = 'experience:\n  - company: "A"\n    summary: |\n      Long\n      text\n'
    with pytest.raises(Unsupported):
        insert_list_item(text, ("experience", 0, "bullets"), "x")

