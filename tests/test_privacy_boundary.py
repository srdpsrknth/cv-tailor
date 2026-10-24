"""Guard the public/private boundary (ADR 0002, ADR 0011).

The privacy split is the one decision in this project that is expensive to get
wrong and impossible to undo by editing code: once real personal data is pushed
to a public remote, untracking it does not un-publish it. So the boundary is
asserted rather than assumed.

These tests read git's index and the .gitignore, and never open the real profile:
they check *where data is allowed to live*, not what it contains.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Paths that must never be tracked in the public repository (ADR 0011).
PRIVATE_PATHS = (
    'storage/profile/profile.yaml',
    'storage/profiles',
    'applications',
    'outputs',
)


def _git(*args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=str(ROOT), capture_output=True, text=True, check=True
    ).stdout


def _tracked(prefix: str) -> list:
    """Tracked paths under ``prefix``. Empty when the prefix is untracked."""
    return [line for line in _git('ls-files', prefix).splitlines() if line.strip()]


# --- the real data is not tracked ------------------------------------------------------

def test_the_real_profile_is_not_tracked():
    """The single most important assertion in Phase 2."""
    assert _tracked('storage/profile/profile.yaml') == []


@pytest.mark.parametrize('prefix', ['applications', 'storage/profiles'])
def test_application_archives_are_not_tracked(prefix):
    assert _tracked(prefix) == []


def test_no_generated_document_is_tracked():
    """Only the directory placeholder may be tracked under outputs/."""
    tracked = _tracked('outputs')
    assert tracked == ['outputs/.gitkeep'], f'unexpected tracked output files: {tracked}'


def test_the_repository_contains_no_tracked_profile_snapshot():
    """A profile_snapshot.json is a full copy of someone's profile (ADR 0002 §6)."""
    snapshots = [p for p in _git('ls-files').splitlines() if p.endswith('profile_snapshot.json')]
    assert snapshots == []


# --- and cannot be re-added by accident ------------------------------------------------

@pytest.mark.parametrize('path', [
    'storage/profile/profile.yaml',
    'storage/profiles/',
    'applications/',
    'outputs/2026_adjoe_senior_data_analyst_1769343142/2026_CV_example.pdf',
])
def test_private_paths_are_gitignored(path):
    """Without this, a routine `git add -A` re-publishes the owner's data.

    .gitignore is the only thing standing between an untracked profile and the
    public remote, so it is asserted rather than trusted.
    """
    result = subprocess.run(
        ['git', 'check-ignore', '-q', path], cwd=str(ROOT), capture_output=True
    )
    assert result.returncode == 0, f'{path} is not ignored -- it could be re-committed'


def test_a_broad_git_add_would_not_stage_personal_data():
    """The realistic accident: `git add -A` from the repository root.

    Simulated with ``git status --porcelain`` rather than ``git add --dry-run``:
    staging takes a write lock on the index, which the test sandbox denies, and a
    read-only check proves the same property. Anything untracked and *not* ignored
    is exactly what a broad add would pick up.
    """
    output = _git('status', '--porcelain', '--untracked-files=all')
    offenders = [
        line for line in output.splitlines()
        if line.startswith('??')
        and any(f'/{marker}' in line or line.endswith(marker)
                for marker in ('storage/profile', 'storage/profiles', 'applications'))
        and '.gitkeep' not in line
    ]
    assert not offenders, f'a broad `git add -A` would stage private data: {offenders}'


# --- the synthetic fixtures are still available for tests ------------------------------

def test_synthetic_fixtures_remain_tracked():
    """The split must not have removed the only safe sample data."""
    profiles = _tracked('tests/fixtures/profiles')
    assert any(p.endswith('synthetic_analyst.yaml') for p in profiles)
    assert any(p.endswith('synthetic_marketer.yaml') for p in profiles)


def test_fixtures_contain_no_real_identity():
    """A regression guard on the fixtures themselves.

    The owner's real name and email must never appear in committed test data --
    that is the whole point of synthetic fixtures.
    """
    real_profile = ROOT / 'storage' / 'profile' / 'profile.yaml'
    if not real_profile.exists():
        pytest.skip('no local real profile to compare against')

    import yaml

    identity = (yaml.safe_load(real_profile.read_text(encoding='utf-8')) or {}).get('identity', {})
    needles = [identity.get('full_name'), identity.get('email')]
    needles = [n for n in needles if n]

    for fixture in (ROOT / 'tests' / 'fixtures').rglob('*'):
        if not fixture.is_file():
            continue
        text = fixture.read_text(encoding='utf-8', errors='ignore')
        for needle in needles:
            assert needle not in text, f'{fixture.relative_to(ROOT)} contains real personal data'


# --- the store is configuration, not a hardcoded path ----------------------------------

def test_the_public_tree_has_no_hardcoded_private_store_path():
    """A machine-specific absolute path in committed code is both a leak and a bug."""
    offenders = []
    for source in list(ROOT.glob('backend/**/*.py')) + list(ROOT.glob('scripts/*.py')):
        text = source.read_text(encoding='utf-8', errors='ignore')
        for marker in ('cv-tailor-data', 'C:\\\\coding', 'D:\\\\coding'):
            if marker in text:
                offenders.append(f'{source.relative_to(ROOT)}: {marker}')
    assert not offenders, f'hardcoded private paths found: {offenders}'
