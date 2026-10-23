"""Characterization tests for profile loading and validation.

Covers the *profile loading* and *profile validation* workflows of ASSESSMENT.md §1.
These lock in current behaviour so Phase 2's `ProfileStore` migration can be proven safe.
"""
from __future__ import annotations

import pytest

from support import PROFILES, load_profile


# --- loading ------------------------------------------------------------------------

def test_synthetic_profiles_load_and_round_trip():
    for name in ('synthetic_analyst', 'synthetic_marketer'):
        profile = load_profile(name)
        assert profile.version == '1.0'
        assert profile.identity.full_name
        # A successful load must survive a JSON round-trip unchanged.
        assert type(profile).model_validate_json(profile.model_dump_json()) == profile


def test_default_path_resolves_to_the_repository_profile(monkeypatch, tmp_path):
    """With no argument the loader uses storage/profile/profile.yaml relative to backend/."""
    from services import profile_loader

    expected = profile_loader.Path(profile_loader.__file__).parent.parent.parent \
        / 'storage' / 'profile' / 'profile.yaml'
    captured = {}

    real_open = profile_loader.open if hasattr(profile_loader, 'open') else open

    def spy(path, *args, **kwargs):
        captured['path'] = str(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr('builtins.open', spy)
    try:
        profile_loader.load_profile()
    except ValueError:
        # The real profile is expected to load; a validation error would itself be a
        # finding, but the path assertion below is what this test is about.
        pass
    assert captured['path'] == str(expected)
    assert expected.exists()


def test_missing_profile_raises_file_not_found(tmp_path):
    from services.profile_loader import load_profile as load

    with pytest.raises(FileNotFoundError, match='Profile not found'):
        load(str(tmp_path / 'absent.yaml'))


def test_profile_path_is_accepted_as_string_and_path(analyst_profile):
    service_path = PROFILES / 'synthetic_analyst.yaml'
    from_str = load_profile('synthetic_analyst')
    from services.profile_loader import load_profile as load

    assert load(str(service_path)) == from_str
    assert load(service_path) == from_str


# --- validation: known-good shape ----------------------------------------------------

def test_analyst_profile_shape_is_as_documented(analyst_profile):
    """The fixture is relied on for specific edge cases; assert that shape explicitly."""
    employers = [exp.company for exp in analyst_profile.experience]
    assert employers == [
        'Northwind Analytics GmbH',
        'Contoso Metrics Ltd',
        'Fabrikam Internship',
    ]
    # Fabrikam deliberately has no bullets — this drives the "do not invent
    # responsibilities" validator rule.
    fabrikam = analyst_profile.experience[-1]
    assert fabrikam.bullets == [] and fabrikam.selected_projects == []
    assert analyst_profile.identity.visa_status
    assert analyst_profile.certifications


def test_marketer_profile_shape_is_as_documented(marketer_profile):
    assert [e.company for e in marketer_profile.experience] == [
        'Initech Growth BV',
        'Globex Media NV',
    ]
    assert all(e.selected_projects == [] for e in marketer_profile.experience)
    assert marketer_profile.identity.visa_status is None
    assert marketer_profile.certifications == []


def test_profiles_share_no_identifiers(analyst_profile, marketer_profile):
    """Guards the cross-profile contamination tests: the two must not overlap."""
    a = analyst_profile.model_dump_json().lower()
    b = marketer_profile.model_dump_json().lower()
    for token in ('alex sample', 'northwind', 'contoso', 'fabrikam'):
        assert token in a and token not in b
    for token in ('robin example', 'initech', 'globex'):
        assert token in b and token not in a


# --- validation: rejection paths -----------------------------------------------------

def test_unknown_keys_are_rejected():
    """`extra="forbid"` on every model must reject hand-edited typos."""
    from services.profile_loader import load_profile as load

    with pytest.raises(ValueError, match='Profile validation failed'):
        load(str(PROFILES / 'invalid' / 'unknown_key.yaml'))


def test_missing_required_identity_is_rejected():
    from services.profile_loader import load_profile as load

    with pytest.raises(ValueError, match='Profile validation failed'):
        load(str(PROFILES / 'invalid' / 'missing_identity.yaml'))


def test_structurally_malformed_profile_is_rejected():
    from services.profile_loader import load_profile as load

    with pytest.raises(ValueError, match='Profile validation failed'):
        load(str(PROFILES / 'invalid' / 'malformed.yaml'))


def test_unparseable_yaml_is_reported_as_invalid_yaml():
    from services.profile_loader import load_profile as load

    with pytest.raises(ValueError, match='Invalid YAML'):
        load(str(PROFILES / 'invalid' / 'broken_syntax.yaml'))


def test_empty_profile_file_is_rejected(tmp_path):
    """An empty file yields None, which must surface as a validation error, not a crash."""
    from services.profile_loader import load_profile as load

    empty = tmp_path / 'empty.yaml'
    empty.write_text('', encoding='utf-8')
    with pytest.raises(ValueError):
        load(str(empty))


# --- documented gaps -----------------------------------------------------------------

def test_start_date_is_not_validated_yet(tmp_path):
    """ASSESSMENT A-6: dates are unvalidated strings.

    This test pins the *current* behaviour, which is wrong. Phase 1/2 will add real
    date validation and this test must then be inverted deliberately — it is the
    regression tripwire for that change, not an endorsement of it.
    """
    import yaml

    data = yaml.safe_load((PROFILES / 'synthetic_analyst.yaml').read_text(encoding='utf-8'))
    data['experience'][0]['start_date'] = 'not-a-date'
    candidate = tmp_path / 'bad_date.yaml'
    candidate.write_text(yaml.safe_dump(data), encoding='utf-8')

    profile = _load_file(candidate)
    assert profile.experience[0].start_date == 'not-a-date'


def test_reversed_date_range_is_not_validated_yet(tmp_path):
    """ASSESSMENT A-6: an end date before the start date is currently accepted."""
    import yaml

    data = yaml.safe_load((PROFILES / 'synthetic_analyst.yaml').read_text(encoding='utf-8'))
    data['experience'][0]['start_date'] = '2025-01'
    data['experience'][0]['end_date'] = '2020-01'
    candidate = tmp_path / 'reversed.yaml'
    candidate.write_text(yaml.safe_dump(data), encoding='utf-8')

    profile = _load_file(candidate)
    assert profile.experience[0].end_date == '2020-01'


def _load_file(path):
    from services.profile_loader import load_profile as load

    return load(str(path))
