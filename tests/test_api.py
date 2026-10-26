"""API tests for ``backend/main.py`` (blocker 7).

These are the first tests this module has ever had. They exist because the API
was, until now, the last place in the codebase that resolved a profile by
*default*: it called ``load_profile()`` with no argument, which read the
pre-Phase-2 path ``storage/profile/profile.yaml``. On a machine where that stale
duplicate still existed the endpoint appeared to work while silently ignoring the
store; on a fresh clone it raised. Both are wrong, and the working-looking one is
the dangerous one (ADR 0003 fails closed).

Everything here is offline: no test reaches the network, and none makes a paid
call. ``/api/tailor`` is exercised only up to the point where it has resolved a
candidate, which is exactly the behaviour this file is about.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as api  # noqa: E402


@pytest.fixture
def client():
    return TestClient(api.app)


@pytest.fixture
def store_outputs(monkeypatch, tmp_path):
    """A throwaway store whose ``outputs/<profile_id>/`` we can populate.

    Returns ``(profile_id, job_id, folder)`` with the folder created but empty, so
    each test decides what documents exist inside it.
    """
    store = tmp_path / 'store'
    profile_id, job_id = 'analyst_a', '2026_acme_data_analyst_1769343142'
    folder = store / 'outputs' / profile_id / job_id
    folder.mkdir(parents=True)
    monkeypatch.setenv('CVTAILOR_STORE', str(store))
    return profile_id, job_id, folder


# --- health ---------------------------------------------------------------------------

def test_health_does_not_need_a_profile(client):
    """The liveness probe must not fail closed; it has no candidate to act for."""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


# --- the endpoint fails closed rather than guessing a candidate ------------------------

def test_tailor_fails_closed_without_any_profile_id(client, monkeypatch, tmp_path):
    """No id in the request and none configured is a 400, never a default profile.

    This is the regression guard for the bug this file was written for: the old
    code called ``load_profile()``, which read ``storage/profile/profile.yaml``
    regardless of what the caller asked for.
    """
    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path / 'store'))
    monkeypatch.delenv('CVTAILOR_PROFILE_ID', raising=False)

    response = client.post('/api/tailor', json={'job_description': 'x' * 60})
    assert response.status_code == 400
    assert 'profile' in response.json()['detail'].lower()


def test_tailor_rejects_an_unknown_profile_id(client, monkeypatch, tmp_path):
    """A well-formed id that names nobody must not invent a profile."""
    store = tmp_path / 'store'
    (store / 'profiles' / 'someone').mkdir(parents=True)
    monkeypatch.setenv('CVTAILOR_STORE', str(store))

    response = client.post(
        '/api/tailor',
        json={'job_description': 'x' * 60, 'profile_id': 'nobody_here'},
    )
    assert response.status_code == 400


def test_tailor_rejects_a_malformed_profile_id(client, monkeypatch, tmp_path):
    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path / 'store'))
    response = client.post(
        '/api/tailor',
        json={'job_description': 'x' * 60, 'profile_id': '../../etc/passwd'},
    )
    assert response.status_code == 400


def test_tailor_still_rejects_a_short_job_description(client, monkeypatch, tmp_path):
    """Validation that predates this change must keep working."""
    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path / 'store'))
    response = client.post('/api/tailor', json={'job_description': 'too short'})
    assert response.status_code == 422


# --- resolution rules ------------------------------------------------------------------

def test_an_explicit_request_id_beats_the_configured_one(monkeypatch, tmp_path):
    """A per-request candidate must win over the ambient environment."""
    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path / 'store'))
    monkeypatch.setenv('CVTAILOR_PROFILE_ID', 'from_env')
    config = api.get_config()

    assert api.resolve_profile_id(config, 'from_request') == 'from_request'
    assert api.resolve_profile_id(config, None) == 'from_env'


def test_the_endpoint_does_not_read_the_legacy_default_path(monkeypatch, tmp_path):
    """The specific bug: a stale ``storage/profile/profile.yaml`` must be ignored.

    The old code would have loaded that file. Writing a real-looking decoy and
    asserting the request still fails closed proves the endpoint resolves through
    the store instead (ADR 0003, ADR 0011).
    """
    store = tmp_path / 'store'
    store.mkdir()
    decoy = tmp_path / 'storage' / 'profile' / 'profile.yaml'
    decoy.parent.mkdir(parents=True)
    decoy.write_text('identity:\n  full_name: Decoy Person\n', encoding='utf-8')

    monkeypatch.setenv('CVTAILOR_STORE', str(store))
    monkeypatch.delenv('CVTAILOR_PROFILE_ID', raising=False)

    response = TestClient(api.app).post(
        '/api/tailor', json={'job_description': 'x' * 60}
    )
    assert response.status_code == 400, 'the endpoint must not fall back to a default file'


# --- job_id containment (ASSESSMENT.md §6) ---------------------------------------------

@pytest.mark.parametrize('job_id', [
    '../../etc/passwd',
    'a/b',
    'a\\b',
    '..',
    'a b',
    '',
])
def test_a_job_id_cannot_escape_the_profile_outputs_directory(job_id, monkeypatch, tmp_path):
    """Traversal must be rejected outright, not merely unlikely to resolve."""
    monkeypatch.setenv('CVTAILOR_STORE', str(tmp_path / 'store'))
    config = api.get_config()

    with pytest.raises(HTTPException) as error:
        api.job_folder(config, 'analyst_a', job_id)
    assert error.value.status_code == 400


def test_a_well_formed_job_id_resolves_inside_the_profile_folder(monkeypatch, tmp_path):
    """The positive control for the containment test above."""
    store = tmp_path / 'store'
    monkeypatch.setenv('CVTAILOR_STORE', str(store))
    config = api.get_config()

    folder = api.job_folder(config, 'analyst_a', '2026_acme_analyst_1')
    assert folder == store / 'outputs' / 'analyst_a' / '2026_acme_analyst_1'


# --- downloads resolve through the store, not the mirror -------------------------------

def test_download_cv_finds_a_document_in_the_store(client, store_outputs):
    profile_id, job_id, folder = store_outputs
    (folder / '2026_CV_Someone_analyst.pdf').write_bytes(b'%PDF-1.4 fake')

    response = client.get(f'/api/download/cv/{job_id}', params={'profile_id': profile_id})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'


def test_download_cv_404s_when_the_job_folder_is_empty(client, store_outputs):
    profile_id, job_id, _ = store_outputs
    response = client.get(f'/api/download/cv/{job_id}', params={'profile_id': profile_id})
    assert response.status_code == 404


def test_download_cover_letter_finds_the_docx(client, store_outputs):
    profile_id, job_id, folder = store_outputs
    (folder / 'cover_letter.docx').write_bytes(b'docx')

    response = client.get(
        f'/api/download/cover-letter/{job_id}', params={'profile_id': profile_id}
    )
    assert response.status_code == 200
    assert 'wordprocessingml' in response.headers['content-type']


def test_download_cover_letter_pdf_excludes_the_cv(client, store_outputs):
    """The letter route must not hand back the CV just because both are PDFs."""
    profile_id, job_id, folder = store_outputs
    (folder / f'{job_id}.pdf').write_bytes(b'%PDF-1.4 cv')
    (folder / 'cover_letter.pdf').write_bytes(b'%PDF-1.4 letter')

    response = client.get(
        f'/api/download/cover-letter-pdf/{job_id}', params={'profile_id': profile_id}
    )
    assert response.status_code == 200
    assert 'cover_letter' in response.headers['content-disposition']


def test_downloads_are_isolated_between_two_profiles(client, store_outputs):
    """Two candidates on one posting must not see each other's documents.

    This is ADR 0003's headline hazard, asserted at the API layer: the download
    routes take a ``profile_id``, so the candidate segment is part of the lookup.
    """
    profile_id, job_id, folder = store_outputs
    (folder / 'cover_letter.docx').write_bytes(b'analyst docx')

    other = api.get_config().store.outputs_dir('marketer_b') / job_id
    other.mkdir(parents=True)
    (other / 'cover_letter.docx').write_bytes(b'marketer docx')

    first = client.get(
        f'/api/download/cover-letter/{job_id}', params={'profile_id': profile_id}
    )
    second = client.get(
        f'/api/download/cover-letter/{job_id}', params={'profile_id': 'marketer_b'}
    )

    assert first.content == b'analyst docx'
    assert second.content == b'marketer docx'


def test_download_rejects_a_traversing_job_id(client, store_outputs):
    profile_id, _, _ = store_outputs
    response = client.get(
        '/api/download/cv/..%2F..%2Fetc%2Fpasswd', params={'profile_id': profile_id}
    )
    assert response.status_code in (400, 404)
