import json

import pytest
from pydantic import ValidationError

from config import Config
from models.portal_answers import AnswerEdit, AnswerQuestion, PublicAnswerSource
from services.portal_answer_store import AnswerSheetConflict, load_answer_sheet, save_answer_sheet
from services.portal_answers import draft_answers
from services.profile_store import InvalidProfileIdError, UnknownProfileError
from services.provider import Provider, ProviderError, ProviderResponse


JOB = "synthetic-portal-answers"
PROFILE = "analyst_a"


class FakeProvider(Provider):
    name = "openrouter"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, prompt, *, schema=None, max_tokens=None, model=None):
        self.calls.append((prompt, schema, max_tokens, model))
        if isinstance(self.reply, Exception):
            raise self.reply
        text = self.reply if isinstance(self.reply, str) else json.dumps({"answers": self.reply})
        return ProviderResponse(text, 120, 35, reported_cost_usd=0.004, reported_model="reported-fake")


@pytest.fixture
def application(tmp_path, profile_store, analyst_profile):
    # The suite's profiles are shared, so every case gets its own job output tree.
    config = Config.from_env().with_overrides(
        profile_store_dir=tmp_path, task_models={"portal_answers": "request-fake"}
    )
    for profile_id in (PROFILE, "marketer_b"):
        path = config.store.profile_path(profile_id)
        path.parent.mkdir(parents=True)
        path.write_bytes(profile_store.profile_path(profile_id).read_bytes())

    source = config.store.outputs_dir(PROFILE) / JOB / "source"
    source.mkdir(parents=True)
    (source / "job_description.txt").write_text(
        "Maintain warehouse reliability and help product teams use event data.", encoding="utf-8"
    )
    (source / "profile_snapshot.json").write_text(analyst_profile.model_dump_json(), encoding="utf-8")
    (source / "content.json").write_text(json.dumps({
        "cv": {"experience": [
            {"bullets": [analyst_profile.experience[0].bullets[0], "Led a 900-person committee."]}
        ]},
        "cover_letter": {"paragraphs": [
            analyst_profile.experience[0].selected_projects[0].bullets[0] + " I cut costs 90%."
        ]},
    }), encoding="utf-8")
    return config, source


def response(question_id, text="I maintain batch pipelines.", evidence_ids=None, missing_facts=None):
    return {
        "question_id": question_id,
        "text": text,
        "evidence_ids": ["profile-3"] if evidence_ids is None else evidence_ids,
        "missing_facts": missing_facts or [],
    }


def test_batch_uses_scoped_evidence_and_no_documents_or_writes(application):
    config, source = application
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    provider = FakeProvider([
        response("motivation", evidence_ids=["profile-3", "posting"]),
        response("project", text="", evidence_ids=[], missing_facts=["Confirm the outcome you want to highlight."]),
    ])
    result = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="motivation", text="Why join?", max_words=20, confirmed_facts=("I enjoy product analytics.",)),
        AnswerQuestion(id="project", text="What project made you proud?"),
        AnswerQuestion(id="salary", text="Expected salary?", manual_only=True, notes="A private note."),
    ], provider=provider)

    assert len(provider.calls) == 1
    prompt, schema, max_tokens, model = provider.calls[0]
    assert "Maintain warehouse reliability" in prompt
    assert "Own end-to-end batch pipelines" in prompt
    assert "I enjoy product analytics" in prompt
    assert "A private note" not in prompt
    assert "alex.sample@example.invalid" not in prompt
    assert "900-person committee" not in prompt
    assert "I cut costs 90%" not in prompt
    assert {item.used_in for item in result.evidence} == {(), ("cv",), ("cover_letter",)}
    assert schema["properties"]["answers"]["items"]["additionalProperties"] is False
    assert model == "request-fake"
    assert max_tokens == config.max_output_tokens
    assert [draft.status for draft in result.drafts] == ["drafted", "needs_facts", "manual"]
    assert result.drafts[0].words == 4
    assert result.drafts[0].limits_met is True
    assert result.drafts[1].missing_facts == ["Confirm the outcome you want to highlight."]
    assert result.usage.reported_model == "reported-fake"
    assert result.usage.cost_usd == 0.004
    assert result.usage.cost_source == "reported"
    assert {path.name: path.read_bytes() for path in source.iterdir()} == before


def test_limits_duplicate_rows_and_cross_question_evidence_do_not_block_other_answers(application):
    config, _ = application
    provider = FakeProvider([
        response("char", "I build 🛠"),
        response("word", "I build reports."),
        response("duplicate"),
        response("duplicate"),
        response("wrong-source", evidence_ids=["fact-char-1"]),
        response("fabricated-source", evidence_ids=["cv-unsupported"]),
        response("valid"),
    ])
    result = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="char", text="What do you build?", max_characters=9, confirmed_facts=("I build tools.",)),
        AnswerQuestion(id="word", text="What else?", max_words=2),
        AnswerQuestion(id="duplicate", text="What did you learn?"),
        AnswerQuestion(id="wrong-source", text="What did you change?"),
        AnswerQuestion(id="fabricated-source", text="What did you save?"),
        AnswerQuestion(id="omitted", text="What tasks did you own?"),
        AnswerQuestion(id="valid", text="What did you maintain?"),
    ], provider=provider)

    assert [draft.status for draft in result.drafts] == [
        "over_limit", "over_limit", "invalid", "invalid", "invalid", "invalid", "drafted"
    ]
    assert result.drafts[0].characters == 10  # UTF-16 counts for a portal maxlength.
    assert result.drafts[0].limits_met is False
    assert result.drafts[1].words == 3
    assert result.drafts[2].text == ""

    retry = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="char", text="What do you build?", max_characters=9),
    ], provider=FakeProvider([response("char", "Reports.")]))
    assert retry.drafts[0].status == "drafted"


def test_legacy_uses_current_profile_only_with_explicit_opt_in(application):
    config, source = application
    (source / "profile_snapshot.json").unlink()
    provider = FakeProvider([response("q")])
    args = {"profile_id": PROFILE, "job_id": JOB, "questions": [AnswerQuestion(id="q", text="What do you maintain?")]}

    unavailable = draft_answers(config, **args, provider=provider)
    assert unavailable.drafts[0].status == "unavailable"
    assert not provider.calls

    fallback = draft_answers(config, **args, provider=provider, use_current_profile=True)
    assert fallback.drafts[0].status == "drafted"
    assert {item.source for item in fallback.evidence} == {"current_profile", "posting"}
    assert any("current profile" in warning for warning in fallback.warnings)
    assert len(provider.calls) == 1


def test_profile_and_job_are_explicit_before_provider_work(application):
    config, _ = application
    provider = FakeProvider([response("q")])
    questions = [AnswerQuestion(id="q", text="Why this role?")]
    for profile, job, failure in (
        ("marketer_b", JOB, ValueError),
        ("missing", JOB, UnknownProfileError),
        (None, JOB, InvalidProfileIdError),
        (PROFILE, "../marketer_b", ValueError),
    ):
        with pytest.raises(failure):
            draft_answers(config, profile_id=profile, job_id=job, questions=questions, provider=provider)
    assert not provider.calls


def test_provider_failure_keeps_manual_questions_and_saved_sources_available(application):
    config, _ = application
    provider = FakeProvider(ProviderError("private provider details that should not reach the UI"))
    result = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="q", text="Why this role?"),
        AnswerQuestion(id="manual", text="Can you start Monday?", manual_only=True),
    ], provider=provider)
    assert [draft.status for draft in result.drafts] == ["unavailable", "manual"]
    assert "private provider details" not in result.drafts[0].message
    assert result.evidence
    assert result.usage is None


def test_missing_posting_and_manual_only_skip_provider(application):
    config, source = application
    (source / "job_description.txt").unlink()
    provider = FakeProvider([])
    result = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="q", text="Why this role?"),
    ], provider=provider)
    assert result.drafts[0].status == "unavailable"
    assert any("saved posting" in warning for warning in result.warnings)
    result = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="manual", text="Expected salary?", manual_only=True),
    ], provider=provider)
    assert result.drafts[0].status == "manual"
    assert not provider.calls


def test_complete_structured_output_can_be_fenced_but_never_repaired(application):
    config, _ = application
    args = {"profile_id": PROFILE, "job_id": JOB, "questions": [AnswerQuestion(id="q", text="Why this role?")]}
    payload = json.dumps({"answers": [response("q")]})
    complete = draft_answers(config, **args, provider=FakeProvider(f"```json\n{payload}\n```"))
    truncated = draft_answers(config, **args, provider=FakeProvider(payload[:-1]))
    assert complete.drafts[0].status == "drafted"
    assert truncated.drafts[0].status == "invalid"
    assert truncated.usage.output_tokens == 35


def test_invalid_limits_and_duplicate_question_ids_fail_before_any_call(application):
    config, _ = application
    with pytest.raises(ValidationError):
        AnswerQuestion(id="q", text="Why this role?", max_characters=0)
    question = AnswerQuestion(id="q", text="Why this role?")
    provider = FakeProvider([])
    with pytest.raises(ValueError, match="unique"):
        draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[question, question], provider=provider)
    assert not provider.calls


def test_public_company_snippets_are_labelled_with_the_original_url(application):
    config, _ = application
    url = "https://example.invalid/engineering"
    source = PublicAnswerSource(url=url, snippet="The company operates a public data engineering blog.")
    provider = FakeProvider([response("q", evidence_ids=["company-1", "profile-3"])])
    result = draft_answers(config, profile_id=PROFILE, job_id=JOB, questions=[
        AnswerQuestion(id="q", text="Why do you want to join?"),
    ], provider=provider, public_sources=[source])
    assert result.drafts[0].status == "drafted"
    evidence = next(item for item in result.evidence if item.id == "company-1")
    assert evidence.source == "company_public"
    assert evidence.url == url
    assert source.snippet in provider.calls[0][0]
    assert url in provider.calls[0][0]
    with pytest.raises(ValidationError):
        PublicAnswerSource(url="https://user:secret@example.invalid", snippet="Invalid source.")


def test_edit_revisions_round_trip_and_fail_stale_writes(application):
    config, source = application
    target = {"profile_id": PROFILE, "job_id": JOB}
    empty = load_answer_sheet(config, **target)
    assert empty.revision is None
    assert not (source / "portal_answers").exists()
    questions = [AnswerQuestion(id="q", text="Why join?", max_characters=100, confirmed_facts=("I like SQL.",))]
    public_sources = [PublicAnswerSource(url="https://example.invalid", snippet="The team uses SQL.")]
    first = save_answer_sheet(config, **target, expected_revision=None, questions=questions,
                              edits=[AnswerEdit(question_id="q", text="First draft.")], public_sources=public_sources)
    second = save_answer_sheet(config, **target, expected_revision=first.revision, questions=questions,
                               edits=[AnswerEdit(question_id="q", text="Edited draft.\n")], public_sources=public_sources)

    loaded = load_answer_sheet(config, **target)
    assert loaded == second
    assert second.revision != first.revision
    assert second.edits[0].text == "Edited draft.\n"
    assert second.questions == questions
    assert second.public_sources == public_sources
    history = source / "portal_answers"
    assert {path.name for path in history.iterdir()} == {f"{first.revision}.json", f"{second.revision}.json"}
    assert "First draft." in (history / f"{first.revision}.json").read_text(encoding="utf-8")
    with pytest.raises(AnswerSheetConflict, match="changed"):
        save_answer_sheet(config, **target, expected_revision=first.revision, questions=[], edits=[])
    assert load_answer_sheet(config, **target) == second
    repeated = save_answer_sheet(config, **target, expected_revision=second.revision,
                                 questions=questions, edits=second.edits, public_sources=public_sources)
    assert repeated == second
    assert len(list(history.iterdir())) == 2


def test_partial_and_diverged_revisions_preserve_the_shared_editor_state(application):
    config, source = application
    target = {"profile_id": PROFILE, "job_id": JOB}
    questions = [AnswerQuestion(id="q", text="Why join?")]
    first = save_answer_sheet(config, **target, expected_revision=None, questions=questions, edits=[])
    second = save_answer_sheet(config, **target, expected_revision=first.revision, questions=questions,
                               edits=[AnswerEdit(question_id="q", text="Windows edit.")])
    history = source / "portal_answers"
    first_file = history / f"{first.revision}.json"
    second_file = history / f"{second.revision}.json"
    first_bytes = first_file.read_bytes()
    first_file.unlink()
    partial = load_answer_sheet(config, **target)
    assert not partial.revision
    assert any("incomplete" in warning for warning in partial.warnings)
    with pytest.raises(AnswerSheetConflict, match="incomplete"):
        save_answer_sheet(config, **target, expected_revision=None, questions=questions, edits=[])
    first_file.write_bytes(first_bytes)

    windows_bytes = second_file.read_bytes()
    second_file.unlink()
    third = save_answer_sheet(config, **target, expected_revision=first.revision, questions=questions,
                              edits=[AnswerEdit(question_id="q", text="Mac edit.")])
    second_file.write_bytes(windows_bytes)
    fork = load_answer_sheet(config, **target)
    assert fork.revision == first.revision
    assert not fork.edits
    assert any("diverged" in warning for warning in fork.warnings)
    with pytest.raises(AnswerSheetConflict, match="diverged"):
        save_answer_sheet(config, **target, expected_revision=first.revision, questions=[], edits=[])
    assert {path.stem for path in history.iterdir()} == {first.revision, second.revision, third.revision}


def test_sync_conflict_copy_blocks_saves_even_if_the_main_revision_is_readable(application):
    config, source = application
    target = {"profile_id": PROFILE, "job_id": JOB}
    questions = [AnswerQuestion(id="q", text="Why join?")]
    first = save_answer_sheet(config, **target, expected_revision=None, questions=questions, edits=[])
    history = source / "portal_answers"
    conflict = history / f"{first.revision}.sync-conflict-20261124-140000-TEST.json"
    conflict.write_bytes((history / f"{first.revision}.json").read_bytes())
    loaded = load_answer_sheet(config, **target)
    assert loaded.revision == first.revision
    assert any("sync conflict" in warning for warning in loaded.warnings)
    with pytest.raises(AnswerSheetConflict, match="sync conflict"):
        save_answer_sheet(config, **target, expected_revision=first.revision, questions=[], edits=[])


def test_failed_publication_leaves_current_revision_and_removes_temporary_file(application, monkeypatch):
    from services import portal_answer_store

    config, source = application
    target = {"profile_id": PROFILE, "job_id": JOB}
    questions = [AnswerQuestion(id="q", text="Why join?")]
    first = save_answer_sheet(config, **target, expected_revision=None, questions=questions, edits=[])

    def fail_replace(*args):
        raise OSError("Test publication failure")

    monkeypatch.setattr(portal_answer_store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Test publication failure"):
        save_answer_sheet(config, **target, expected_revision=first.revision, questions=[], edits=[])
    assert load_answer_sheet(config, **target) == first
    assert [path.name for path in (source / "portal_answers").iterdir()] == [f"{first.revision}.json"]


def test_revisions_reject_out_of_scope_edits_candidates_and_corrupt_history(application):
    config, source = application
    target = {"profile_id": PROFILE, "job_id": JOB}
    with pytest.raises(ValidationError, match="distinct question"):
        save_answer_sheet(config, **target, expected_revision=None, questions=[],
                          edits=[AnswerEdit(question_id="orphaned", text="Do not save.")])
    with pytest.raises(ValueError, match="not found"):
        load_answer_sheet(config, profile_id="marketer_b", job_id=JOB)
    first = save_answer_sheet(config, **target, expected_revision=None,
                              questions=[AnswerQuestion(id="q", text="Why join?")], edits=[])
    path = source / "portal_answers" / f"{first.revision}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sheet"]["profile_id"] = "marketer_b"
    path.write_text(json.dumps(payload), encoding="utf-8")
    unreadable = load_answer_sheet(config, **target)
    assert not unreadable.revision
    assert any("could not be read" in warning for warning in unreadable.warnings)
    with pytest.raises(AnswerSheetConflict, match="could not be read"):
        save_answer_sheet(config, **target, expected_revision=None, questions=[], edits=[])
