"""``cvtailor claims`` -- list, accept (with confirmation) and reject. Offline, synthetic."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from cli.main import build_parser, main  # noqa: E402
from services import suggested_claims as claims  # noqa: E402
from support import load_profile  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "profiles" / "synthetic_analyst.yaml"
TEXT = "Applied inclusion and exclusion criteria to define eligible cohorts from source records."


@pytest.fixture
def store(tmp_path, monkeypatch):
    for profile_id in ("analyst_a", "analyst_b"):
        folder = tmp_path / "profiles" / profile_id
        folder.mkdir(parents=True)
        shutil.copy2(FIXTURE, folder / "profile.yaml")
    source = tmp_path / "outputs" / "analyst_a" / "job1" / "source"
    source.mkdir(parents=True)
    (source / "content.json").write_text("{}", encoding="utf-8")
    kept, _ = claims.validate_suggestions([
        {"requirement": "Cohort definition", "proposed_text": TEXT, "rationale": "Plausible.",
         "attach_to": {"type": "experience_project", "company": "Northwind Analytics GmbH",
                       "project": "Attribution Rebuild"}},
        {"requirement": "Cohorts", "proposed_text": "Cohort definition", "rationale": "Plausible.",
         "attach_to": {"type": "skill", "category": "core_analytics"}},
    ], load_profile("synthetic_analyst"))
    claims.save_suggestions(source, kept, [])
    monkeypatch.setenv("CVTAILOR_STORE", str(tmp_path))
    return tmp_path


def argv(store, *rest, profile="analyst_a"):
    return ["--store", str(store), "--profile-id", profile, *rest]


def content_of(store):
    return str(store / "outputs" / "analyst_a" / "job1" / "source" / "content.json")


def profile_text(store, profile="analyst_a"):
    return (store / "profiles" / profile / "profile.yaml").read_text(encoding="utf-8")


def test_list_shows_numbered_suggestions_and_the_truth_warning(store, capsys):
    assert main(argv(store, "claims", "list", "--content", content_of(store))) == 0
    out = capsys.readouterr().out
    assert "1. [pending]" in out and "2. [pending]" in out
    assert TEXT in out and "Attribution Rebuild" in out and "TRUE" in out


def test_list_json_and_no_suggestions(store, capsys):
    assert main(["--json"] + argv(store, "claims", "list", "--content", content_of(store))) == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["number"] for s in data["suggestions"]] == [1, 2]

    empty = store / "outputs" / "analyst_a" / "job2" / "source"
    empty.mkdir(parents=True)
    (empty / "content.json").write_text("{}", encoding="utf-8")
    assert main(argv(store, "claims", "list", "--content", str(empty / "content.json"))) == 0
    assert "No suggested claims" in capsys.readouterr().out


def test_accept_with_yes_shows_the_changes_and_updates_the_profile(store, capsys):
    before = profile_text(store)
    assert main(argv(store, "claims", "accept", "--content", content_of(store), "1", "2", "--yes")) == 0
    out = capsys.readouterr().out
    assert "These statements will be added" in out and TEXT in out and "targeted-insert" in out
    after = profile_text(store)
    assert "# SYNTHETIC FIXTURE" in after
    data = yaml.safe_load(after)
    assert data["experience"][0]["selected_projects"][0]["bullets"][-1] == TEXT
    assert data["skills"]["core_analytics"][-1] == "Cohort definition"
    assert len(list((store / "profiles" / "analyst_a").glob("profile.backup-*.yaml"))) == 1
    assert profile_text(store, "analyst_b") == before, "another candidate's profile is untouched"
    assert [s["status"] for s in claims.load_suggestions(content_of(store))["suggestions"]] == ["accepted"] * 2


def test_accept_without_yes_in_a_script_refuses_and_changes_nothing(store, capsys):
    before = profile_text(store)
    assert main(argv(store, "claims", "accept", "--content", content_of(store), "1")) != 0
    assert "--yes" in capsys.readouterr().err
    assert profile_text(store) == before


@pytest.mark.parametrize("answer, changed", [("y", True), ("n", False), ("", False)])
def test_interactive_confirmation(store, monkeypatch, capsys, answer, changed):
    before = profile_text(store)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or answer)
    assert main(argv(store, "claims", "accept", "--content", content_of(store), "1")) == 0
    assert (profile_text(store) != before) is changed
    assert len(prompts) == 1 and "true" in prompts[0].lower()


def test_a_bad_number_and_another_profiles_application_are_refused(store, capsys):
    assert main(argv(store, "claims", "accept", "--content", content_of(store), "7", "--yes")) != 0
    assert "No suggestion number 7" in capsys.readouterr().err
    code = main(argv(store, "claims", "accept", "--content", content_of(store), "1", "--yes", profile="analyst_b"))
    assert code != 0 and "belongs to profile" in capsys.readouterr().err
    assert "Cohort definition" not in profile_text(store, "analyst_b").replace(
        '"Cohort & Funnel Analysis"', "")


def test_reject_records_and_leaves_the_profile_alone(store, capsys):
    before = profile_text(store)
    assert main(argv(store, "claims", "reject", "--content", content_of(store), "2")) == 0
    assert profile_text(store) == before
    assert claims.load_suggestions(content_of(store))["suggestions"][1]["status"] == "rejected"


def test_the_help_tells_the_user_to_accept_only_true_statements(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["claims", "accept", "--help"])
    out = capsys.readouterr().out
    assert "TRUE" in out
    with pytest.raises(SystemExit):
        parser.parse_args(["claims", "--help"])
    assert "TRUE" in capsys.readouterr().out


def test_generate_hints_at_stored_suggestions(store, monkeypatch, capsys):
    from types import SimpleNamespace
    from services import tailor_service

    content = store / "outputs" / "analyst_a" / "job1" / "source" / "content.json"
    result = SimpleNamespace(
        job_id="job1", cv_page_count=2, cover_letter_page_count=1, cv_path="cv.pdf",
        cover_letter_path="cl.pdf", cl_pdf_path=None, source_path=str(content),
        tailoring_explanation=None,
        token_usage=SimpleNamespace(total_tokens=10, cv_attempts=1, cl_attempts=1,
                                    estimated_cost_usd=0.0),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("CVTAILOR_PROVIDER", "gemini")
    monkeypatch.setattr(tailor_service, "tailor_documents", lambda **kw: result)

    assert main(["--profile-id", "analyst_a", "generate", "--job", "x" * 200]) == 0
    out = capsys.readouterr().out
    assert "2 suggested claims to review: cvtailor --profile-id analyst_a claims list --content" in out
    assert str(content) in out

    # No suggestions file -> no hint.
    (content.parent / claims.SUGGESTIONS_FILENAME).unlink()
    assert main(["--profile-id", "analyst_a", "generate", "--job", "x" * 200]) == 0
    assert "suggested claim" not in capsys.readouterr().out
