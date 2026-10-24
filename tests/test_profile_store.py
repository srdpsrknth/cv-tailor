"""Tests for the multi-profile store and its fail-closed rule (ADR 0003, ADR 0004).

The behaviour under test is mostly *refusal*. A store that quietly falls back to a
default profile is worse than one that crashes, because the failure it produces --
candidate B's draft validated against candidate A's facts, or written into A's
folder -- looks exactly like success.

Every test here is offline and uses synthetic fixtures. ``conftest`` points the
store at a throwaway directory, so the owner's real profiles are never read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from config import Config  # noqa: E402
from services.profile_store import (  # noqa: E402
    InvalidProfileIdError,
    ProfileStore,
    ProfileStoreError,
    UnknownProfileError,
    resolve_profile_id,
    validate_profile_id,
)

ANALYST = ROOT / 'tests' / 'fixtures' / 'profiles' / 'synthetic_analyst.yaml'
MARKETER = ROOT / 'tests' / 'fixtures' / 'profiles' / 'synthetic_marketer.yaml'


@pytest.fixture(autouse=True)
def _no_ambient_profile(monkeypatch):
    """Remove the suite-wide synthetic id.

    The rest of the suite runs with ``CVTAILOR_PROFILE_ID`` set (see ``conftest``) so
    that pre-existing tests do not have to thread an argument they are not about.
    These tests are precisely about a *missing* id, so they must not inherit one --
    otherwise every fail-closed assertion here would pass for the wrong reason.
    """
    monkeypatch.delenv('CVTAILOR_PROFILE_ID', raising=False)


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    """An empty store, so population is explicit in each test."""
    return ProfileStore.at(tmp_path / 'store')


@pytest.fixture
def populated(store) -> ProfileStore:
    store.import_file(ANALYST, 'analyst_a')
    store.import_file(MARKETER, 'marketer_b')
    return store


# --- fail closed: the central rule -----------------------------------------------------

@pytest.mark.parametrize('missing', [None, '', '   '])
def test_a_missing_profile_id_raises_rather_than_defaulting(missing):
    """No id never resolves to a profile. This is the whole of ADR 0003."""
    with pytest.raises(InvalidProfileIdError):
        validate_profile_id(missing)


def test_the_missing_id_error_says_how_to_choose():
    """A refusal must be actionable, or users will work around it by guessing."""
    with pytest.raises(InvalidProfileIdError) as error:
        validate_profile_id(None)
    message = str(error.value)
    assert 'profile list' in message
    assert '--profile-id' in message


@pytest.mark.parametrize('bad', [
    '../escape', 'a/b', 'a\\b', 'Upper', 'has space', '-leading', '_leading',
    'semi;colon', 'dot.dot', 'ünïcode', 'null\x00byte',
])
def test_profile_ids_that_are_not_plain_directory_names_are_rejected(bad):
    """The id becomes a directory name, so traversal is rejected structurally."""
    with pytest.raises(InvalidProfileIdError):
        validate_profile_id(bad)


@pytest.mark.parametrize('good', ['a', 'analyst', 'analyst_a', 'candidate-2', 'a1'])
def test_legal_profile_ids_are_accepted_unchanged(good):
    assert validate_profile_id(good) == good


def test_an_unknown_profile_id_raises_and_lists_what_exists(populated):
    """An unknown id must not be answered with a different, existing profile."""
    with pytest.raises(UnknownProfileError) as error:
        populated.load('nobody')
    message = str(error.value)
    assert 'nobody' in message
    assert 'analyst_a' in message and 'marketer_b' in message


def test_an_unknown_profile_id_is_not_reported_as_merely_absent(populated):
    """``exists`` raises on a malformed id instead of returning a misleading False."""
    assert populated.exists('analyst_a') is True
    assert populated.exists('nobody') is False
    with pytest.raises(InvalidProfileIdError):
        populated.exists('../escape')


def test_an_empty_store_explains_how_to_create_the_first_profile(store):
    with pytest.raises(UnknownProfileError) as error:
        store.load('analyst_a')
    message = str(error.value)
    assert 'profile new' in message
    assert 'profile import' in message


def test_resolve_profile_id_prefers_the_explicit_argument(tmp_path):
    config = Config.from_env(load_env_file=False, overrides={
        'project_root': tmp_path, 'profile_id': 'from_config',
    })
    assert resolve_profile_id(config, 'explicit') == 'explicit'
    assert resolve_profile_id(config) == 'from_config'


def test_resolve_profile_id_raises_when_neither_source_has_one(tmp_path):
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})
    assert config.profile_id is None
    with pytest.raises(InvalidProfileIdError):
        resolve_profile_id(config)


def test_a_blank_configured_id_is_not_treated_as_a_choice(tmp_path, monkeypatch):
    """An empty CVTAILOR_PROFILE_ID means 'not chosen', never 'use the first one'."""
    monkeypatch.setenv('CVTAILOR_PROFILE_ID', '   ')
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})
    assert config.profile_id is None
    with pytest.raises(InvalidProfileIdError):
        config.require_profile_id()


# --- layout ---------------------------------------------------------------------------

def test_the_layout_is_keyed_by_profile_id(store):
    assert store.profile_path('analyst_a') == \
        store.root / 'profiles' / 'analyst_a' / 'profile.yaml'
    assert store.outputs_dir('analyst_a') == store.root / 'outputs' / 'analyst_a'


def test_two_profiles_never_share_a_path(populated):
    """The structural guarantee: distinct ids cannot resolve to one folder."""
    assert populated.profile_dir('analyst_a') != populated.profile_dir('marketer_b')
    assert populated.outputs_dir('analyst_a') != populated.outputs_dir('marketer_b')


def test_the_outputs_path_has_a_candidate_segment_even_for_one_profile(store):
    """Not 'outputs/<job_id>': the segment exists before a second profile does."""
    assert store.outputs_dir('analyst_a').name == 'analyst_a'
    assert store.outputs_dir('analyst_a').parent.name == 'outputs'


# --- listing and round trips ----------------------------------------------------------

def test_listing_is_empty_until_populated(store):
    assert store.list_ids() == []


def test_listing_is_sorted(populated):
    assert populated.list_ids() == ['analyst_a', 'marketer_b']


def test_files_without_a_profile_do_not_appear_in_the_listing(populated):
    """A stray directory is not a profile."""
    (populated.profiles_dir / 'not_a_profile').mkdir()
    assert populated.list_ids() == ['analyst_a', 'marketer_b']


def test_a_profile_round_trips_through_the_store(populated):
    from services.profile_loader import load_profile

    loaded = populated.load('analyst_a')
    direct = load_profile(str(ANALYST))
    assert loaded == direct
    assert loaded.identity.full_name == direct.identity.full_name


def test_import_copies_the_file_verbatim_rather_than_reformatting(store, tmp_path):
    """Manual edits, key order and comments must survive migration exactly.

    ADR 0003 requires the existing profile to migrate with its facts intact, and a
    YAML round-trip is the obvious way to lose a comment or reorder a key.
    """
    source = tmp_path / 'profile.yaml'
    source.write_text(
        '# a comment the owner wrote\n'
        'version: "1.0"\n'
        'identity:\n'
        '  full_name: "Test Person"\n'
        '  email: "test@example.com"\n',
        encoding='utf-8',
    )
    destination = store.import_file(source, 'test_person')

    assert destination.read_bytes() == source.read_bytes()
    assert destination.read_text(encoding='utf-8').startswith('# a comment')


def test_import_validates_before_writing_anything(store, tmp_path):
    """A broken profile must not land in the store, not even partially."""
    broken = tmp_path / 'broken.yaml'
    broken.write_text('version: "1.0"\nunexpected_key: true\n', encoding='utf-8')

    with pytest.raises(ValueError):
        store.import_file(broken, 'broken')
    assert not store.profile_path('broken').exists()


def test_import_refuses_to_overwrite_a_maintained_profile(populated):
    """Re-importing must not silently replace facts someone has since edited."""
    with pytest.raises(ProfileStoreError) as error:
        populated.import_file(MARKETER, 'analyst_a')
    assert '--force' in str(error.value)
    # And the original is untouched.
    assert populated.load('analyst_a').identity.full_name == \
        __import__('services.profile_loader', fromlist=['x']).load_profile(str(ANALYST)).identity.full_name


def test_import_with_force_replaces_deliberately(populated):
    populated.import_file(MARKETER, 'analyst_a', overwrite=True)
    assert populated.load('analyst_a').identity.full_name == \
        __import__('services.profile_loader', fromlist=['x']).load_profile(str(MARKETER)).identity.full_name


def test_import_rejects_an_invalid_destination_id(store):
    with pytest.raises(InvalidProfileIdError):
        store.import_file(ANALYST, '../escape')


def test_import_reports_a_missing_source(store):
    with pytest.raises(ProfileStoreError, match='not found'):
        store.import_file(ANALYST.parent / 'absent.yaml', 'absent')


# --- Config integration ---------------------------------------------------------------

def test_config_exposes_a_store_rooted_at_the_configured_directory(tmp_path):
    store_dir = tmp_path / 'private-store'
    config = Config.from_env(load_env_file=False, overrides={
        'project_root': tmp_path, 'profile_store_dir': store_dir,
    })
    assert config.profile_store_dir == store_dir.resolve()
    assert config.store.root == store_dir.resolve()


def test_the_store_environment_variable_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path / 'from-env'))
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})
    assert config.profile_store_dir == (tmp_path / 'from-env').resolve()


def test_a_relative_store_value_is_project_relative(tmp_path, monkeypatch):
    monkeypatch.setenv('CVTAILOR_STORE', 'relative-store')
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})
    assert config.profile_store_dir == (tmp_path / 'relative-store').resolve()


def test_config_require_profile_path_derives_from_the_id(tmp_path):
    config = Config.from_env(load_env_file=False, overrides={
        'project_root': tmp_path, 'profile_store_dir': tmp_path / 's', 'profile_id': 'someone',
    })
    assert config.require_profile_path() == \
        (tmp_path / 's' / 'profiles' / 'someone' / 'profile.yaml')


def test_config_fails_closed_when_no_id_is_configured(tmp_path):
    config = Config.from_env(load_env_file=False, overrides={
        'project_root': tmp_path, 'profile_store_dir': tmp_path / 's',
    })
    with pytest.raises(InvalidProfileIdError):
        config.require_profile_path()
    with pytest.raises(InvalidProfileIdError):
        config.load_profile()


def test_an_explicit_profile_path_bypasses_the_store_but_is_still_explicit(tmp_path):
    config = Config.from_env(load_env_file=False, overrides={
        'project_root': tmp_path, 'profile_path': ANALYST,
    })
    assert config.profile_path == ANALYST
    assert config.load_profile().identity.full_name == \
        __import__('services.profile_loader', fromlist=['x']).load_profile(str(ANALYST)).identity.full_name


def test_config_does_not_invent_a_default_profile_path(tmp_path):
    """The Phase 1 behaviour -- always having a profile_path -- is gone by design."""
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})
    assert config.profile_path is None
