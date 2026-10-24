"""Isolation tests: two candidates must not contaminate each other (ADR 0003).

This is Phase 2's definition of done. ADR 0003 lists five verified hazards that a
second profile would introduce, and each one has a test here:

1. both candidates sharing one profile file;
2. two candidates applying to the same posting colliding on one output folder;
3. ``profile_snapshot.json`` silently replaced by the other candidate's identity;
4. candidate B's draft validated against candidate A's facts and wrongly passing;
5. the mirror path having no candidate segment.

The two synthetic fixtures are deliberately divergent (different employers,
different names, one has a visa and certifications and the other has neither), so
contamination shows up as a factual mismatch rather than a coincidence.

Everything here is offline: recorded responses through the offline double, stubbed
renderers, and a throwaway store.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from services import tailor_service as service  # noqa: E402

from support import read_json  # noqa: E402

# Tokens that identify one candidate and never the other (test_profile_loading
# asserts the same disjointness, so these are safe to use as contaminaion needles).
ANALYST_ONLY = ('Alex Sample', 'Northwind', 'Contoso', 'Fabrikam', 'alex.sample@example.invalid')
MARKETER_ONLY = ('Robin Example', 'Initech', 'Globex', 'robin.example@example.invalid')


def _generate(profile, session, **kwargs):
    """Run the pipeline for one candidate against the temp project root."""
    return service.tailor_documents(
        session.job_description_text, profile,
        company_name=kwargs.pop('company_name', 'Shared Posting Ltd'),
        role_title=kwargs.pop('role_title', 'Data Analyst'),
        **kwargs,
    )


# --- 1 & 2: separate folders, even for the identical posting ---------------------------

def test_two_candidates_on_the_same_posting_do_not_share_a_folder(
    isolated_service, offline_service, stub_renderers, analyst_profile, marketer_profile,
    analyst_session, marketer_session,
):
    """Hazard 2. Identical company and role: the candidate segment must separate them."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    first = _generate(analyst_profile, analyst_session, profile_id='analyst_a')

    offline_service(marketer_session.texts())
    stub_renderers([2])
    second = _generate(marketer_profile, marketer_session, profile_id='marketer_b')

    # The slug convention is unchanged: only the millisecond timestamp differs, so
    # without the candidate segment these two runs would target the same folder.
    slug = lambda job_id: job_id.rsplit('_', 1)[0]  # noqa: E731
    assert slug(first.job_id) == slug(second.job_id), 'the posting slug is expected to match'

    first_folder = Path(first.source_path).parent.parent
    second_folder = Path(second.source_path).parent.parent
    assert first_folder != second_folder
    assert first_folder.parent.name == 'analyst_a'
    assert second_folder.parent.name == 'marketer_b'


def test_generating_for_one_candidate_leaves_the_other_untouched(
    isolated_service, offline_service, stub_renderers, analyst_profile, marketer_profile,
    analyst_session, marketer_session,
):
    """Hazard 2, stated as the requirement: A generates, then B's files are unchanged."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    a = _generate(analyst_profile, analyst_session, profile_id='analyst_a')
    a_folder = Path(a.source_path).parent.parent

    def snapshot(folder: Path) -> dict:
        return {
            path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob('*'))
            if path.is_file()
        }

    before = snapshot(a_folder)
    assert before, 'the first candidate produced no files to protect'

    # A different candidate, same posting, same project root.
    offline_service(marketer_session.texts())
    stub_renderers([2])
    b = _generate(marketer_profile, marketer_session, profile_id='marketer_b')
    b_folder = Path(b.source_path).parent.parent

    assert snapshot(a_folder) == before, "candidate B's run modified candidate A's files"
    assert b_folder != a_folder
    assert not b_folder.is_relative_to(a_folder)
    assert not a_folder.is_relative_to(b_folder)


# --- 3: the profile snapshot identifies the right candidate ---------------------------

def test_each_snapshot_records_its_own_candidate(
    isolated_service, offline_service, stub_renderers, analyst_profile, marketer_profile,
    analyst_session, marketer_session,
):
    """Hazard 3. A snapshot replaced by the other identity is a silent factual error."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    a = _generate(analyst_profile, analyst_session, profile_id='analyst_a')
    a_snapshot = read_json(Path(a.source_path).parent / 'profile_snapshot.json')

    offline_service(marketer_session.texts())
    stub_renderers([2])
    b = _generate(marketer_profile, marketer_session, profile_id='marketer_b')
    b_snapshot = read_json(Path(b.source_path).parent / 'profile_snapshot.json')

    a_bytes = json.dumps(a_snapshot)
    b_bytes = json.dumps(b_snapshot)

    for needle in ANALYST_ONLY:
        assert needle in a_bytes, f'analyst snapshot is missing {needle}'
        assert needle not in b_bytes, f'marketer snapshot leaked analyst data: {needle}'
    for needle in MARKETER_ONLY:
        assert needle in b_bytes, f'marketer snapshot is missing {needle}'
        assert needle not in a_bytes, f'analyst snapshot leaked marketer data: {needle}'


# --- 4: validation uses the candidate's own facts --------------------------------------

def test_a_draft_for_one_candidate_is_not_validated_against_the_other(
    isolated_service, offline_service, stub_renderers, analyst_profile, marketer_profile,
    analyst_session,
):
    """Hazard 4. The dangerous case: B's CV wrongly passing as A's.

    The analyst's recorded draft names the analyst's employers. Validating it against
    the marketer's profile must fail loudly -- if it passed, a wrong-candidate draft
    would be silently accepted.
    """
    offline_service(analyst_session.texts())
    stub_renderers([2])
    result = _generate(analyst_profile, analyst_session, profile_id='analyst_a')
    saved = json.loads(Path(result.source_path).read_text(encoding='utf-8'))

    from models.tailored_output import TailoredCV

    cv = TailoredCV.model_validate(saved['cv'])
    # Correct candidate: accepted.
    service._validate_cv(cv, analyst_profile)
    # Wrong candidate: refused, because the employers cannot match.
    with pytest.raises(ValueError):
        service._validate_cv(cv, marketer_profile)


def test_candidate_specific_rules_are_not_borrowed_across_profiles(
    analyst_profile, marketer_profile,
):
    """A-1 held per profile: each candidate's own rules apply, not the other's."""
    from services.generation import ProfileRules

    a_rules = ProfileRules.from_profile(analyst_profile)
    b_rules = ProfileRules.from_profile(marketer_profile)

    # The fixtures were built to diverge here; if they ever stop diverging this test
    # would pass vacuously, so assert the divergence explicitly.
    assert a_rules.banned_tools != b_rules.banned_tools
    assert a_rules.visa_label != b_rules.visa_label


# --- 5: the mirror path carries the candidate too --------------------------------------

def test_mirroring_keeps_the_candidates_apart(
    isolated_service, offline_service, stub_renderers, analyst_profile, marketer_profile,
    analyst_session, marketer_session, monkeypatch,
):
    """Hazard 5. A mirror without the candidate segment would reintroduce hazard 2."""
    monkeypatch.setenv('OUTPUTS_DIR', str(isolated_service / 'mirror'))

    offline_service(analyst_session.texts())
    stub_renderers([2])
    _generate(analyst_profile, analyst_session, profile_id='analyst_a')

    offline_service(marketer_session.texts())
    stub_renderers([2])
    _generate(marketer_profile, marketer_session, profile_id='marketer_b')

    mirror = isolated_service / 'mirror'
    assert (mirror / 'analyst_a').is_dir()
    assert (mirror / 'marketer_b').is_dir()
    # Two mirrors, not one merged folder.
    job_folders = [p for p in mirror.glob('*/*') if p.is_dir()]
    assert len(job_folders) == 2


# --- prompts contain only the right candidate's facts ----------------------------------

def test_prompts_never_carry_the_other_candidates_facts(
    isolated_service, offline_service, stub_renderers, analyst_profile, marketer_profile,
    analyst_session, marketer_session,
):
    """Contamination in a prompt is invisible in the output folder but corrupts a draft."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    _generate(analyst_profile, analyst_session, profile_id='analyst_a')

    joined = '\n'.join(offline.prompts)
    for needle in MARKETER_ONLY:
        assert needle not in joined, f"analyst's prompts contained {needle}"
    assert 'Alex Sample' in joined, 'the right candidate was not in the prompt at all'


# --- fail closed through the pipeline --------------------------------------------------

def test_generating_without_a_profile_id_fails_before_any_api_call(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
    monkeypatch,
):
    """The id is resolved first, so an unnameable candidate costs nothing."""
    monkeypatch.delenv('CVTAILOR_PROFILE_ID', raising=False)
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    from services.profile_store import InvalidProfileIdError

    with pytest.raises(InvalidProfileIdError):
        _generate(analyst_profile, analyst_session)

    assert offline.call_count == 0, 'a paid call was made before the candidate was known'
    # And nothing was written: no half-created folder to confuse the next run.
    assert not (isolated_service / 'outputs').exists()


def test_an_unknown_profile_id_writes_nothing(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])

    from services.profile_store import UnknownProfileError

    with pytest.raises(UnknownProfileError):
        _generate(analyst_profile, analyst_session, profile_id='nobody')

    assert offline.call_count == 0
    assert not (isolated_service / 'outputs').exists()


def test_a_profile_id_paired_with_another_candidates_profile_is_refused(
    isolated_service, offline_service, stub_renderers, marketer_profile, marketer_session,
):
    """The worst silent failure: B's documents filed under A's id.

    ``profile`` and ``profile_id`` are separate arguments, so nothing in the type
    system stops this pairing. Left unchecked it files the wrong person's documents
    in the wrong folder -- and unlike a crash, the result looks entirely normal.
    """
    offline = offline_service(marketer_session.texts())
    stub_renderers([2])

    from services.profile_store import ProfileMismatchError

    with pytest.raises(ProfileMismatchError) as error:
        _generate(marketer_profile, marketer_session, profile_id='analyst_a')

    assert 'Robin Example' in str(error.value)
    assert 'Alex Sample' in str(error.value)
    assert offline.call_count == 0, 'the mismatch was detected only after paying for it'
    assert not (isolated_service / 'outputs').exists()


def test_a_matching_profile_and_id_together_are_accepted(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
    profile_store,
):
    """The guard must not reject the correct pairing."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    result = _generate(analyst_profile, analyst_session, profile_id='analyst_a')
    assert Path(result.source_path).parent.parent.parent.name == 'analyst_a'


def test_the_same_candidate_can_run_twice_without_colliding(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Guards the fix from the other side: separation must not break re-runs."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    first = _generate(analyst_profile, analyst_session, profile_id='analyst_a')

    offline_service(analyst_session.texts())
    stub_renderers([2])
    second = _generate(analyst_profile, analyst_session, profile_id='analyst_a')

    assert Path(first.source_path).parent.parent.parent.name == 'analyst_a'
    assert Path(second.source_path).parent.parent.parent.name == 'analyst_a'
    assert first.job_id != second.job_id


def test_documents_are_written_into_the_store_not_the_repository(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
    monkeypatch,
):
    """ADR 0011 puts real documents in the store; writing them beside the code breaks it.

    This went unnoticed because every other test asserted *a* path under the project
    root rather than *which* root. Rooting ``ApplicationStore`` at ``PROJECT_ROOT``
    still produced correct-looking folders, in the public repository's gitignored
    ``outputs/`` -- one ``git add -f`` or one archive away from publishing a real CV.

    The store is moved to a sibling directory so the two roots cannot coincide; when
    the store sits at the project root the assertion would pass either way.
    """
    from config import Config

    separate_store = Path(isolated_service).parent / 'separate-store'
    shutil.copytree(
        Path(isolated_service) / 'profiles', separate_store / 'profiles',
        dirs_exist_ok=True,
    )
    monkeypatch.setenv('CVTAILOR_STORE', str(separate_store))

    offline_service(analyst_session.texts())
    stub_renderers([2])
    result = _generate(analyst_profile, analyst_session, profile_id='analyst_a')

    config = Config.from_env(load_env_file=False)
    store_outputs = config.store.outputs_dir('analyst_a')
    assert str(store_outputs).startswith(str(separate_store)), 'the store did not move'

    source = Path(result.source_path)
    assert store_outputs in source.parents, (
        f'documents were written to {source}, outside the store at {store_outputs}'
    )
    # Exactly ``<store>/outputs/<profile_id>/<job_id>/source/content.json``: the
    # candidate segment appears once. Passing ``outputs_dir(profile_id)`` straight to
    # ApplicationStore nested the id twice and broke this silently.
    assert source.relative_to(store_outputs) == Path(result.job_id) / 'source' / 'content.json'
