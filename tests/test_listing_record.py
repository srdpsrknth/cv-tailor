"""The committed listing record, and the provenance it makes checkable (Q10).

Before this file, the repository recorded a *hash* of the OpenRouter listing and
gitignored the listing itself. Two consequences, both measured:

* two tests in ``test_evaluation_suite.py`` **skipped** in a fresh working copy, because
  they compare the curated set's prices against that listing and it was not there;
* a digest proves a document was read, but not what it *said* -- so no price in this
  repository could be re-checked by anyone without re-fetching.

These tests pin the properties that make the record an *artefact* rather than a cache:
it is present, it is self-consistent, it carries the full payload's digest rather than
its own, and the curated model is in it. Everything here is offline -- no network call
is made, and none is needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Imported defensively and failed, not skipped, when absent: a broken import in the real
# tree is the thing this file exists to catch.
try:
    from evaluation import listing
    from evaluation.listing import (
        LISTING_URL,
        MIN_MAX_COMPLETION_TOKENS,
        RECORD_FIELDS,
        ListingEntry,
        ListingRecord,
        entry_from_payload,
        latest_record,
        load_record,
        missing_from_record,
        parse_record,
        price_disagreements,
        screen_payload,
        sha256_of_bytes,
        structurally_usable,
    )
except ImportError as error:  # pragma: no cover - only on a broken tree
    pytest.fail(f"evaluation.listing could not be imported: {error}", pytrace=False)


# --- a record is committed, and it is the artefact the prices rest on ---------------------

def test_a_listing_record_is_committed():
    """The whole point of item 1: the provenance is in the repository.

    ``latest_record()`` returning ``None`` is the failure this asserts against. It is
    the state the repository was in before, and it is why two tests skipped.
    """
    path = latest_record()
    assert path is not None, (
        'no screened listing record is committed; without one the curated prices '
        'cannot be checked by anyone, which is exactly the gap this closes'
    )
    assert path.exists()
    assert path.name.startswith(listing.RECORD_PREFIX)
    assert path.suffix == listing.RECORD_SUFFIX


def test_the_record_is_readable_and_non_trivial():
    record = load_record(latest_record())

    assert record.read_on, 'a record with no read date cannot be aged or trusted'
    assert record.source_url == LISTING_URL
    assert len(record.source_sha256) == 64, 'the payload digest must be a full SHA-256'
    assert len(record.entries) > 1, (
        'a record with fewer than two models is not a catalogue reading; the artefact '
        'exists to let a person compare entries, not to certify one'
    )
    # The full read was much larger than the screened subset, so these must differ --
    # otherwise the screen silently did nothing and the field list is not what it says.
    assert record.source_model_count > len(record.entries), (
        'the recorded source count equals the screened count; the screen is not '
        'filtering, or source_model_count was set from the wrong side'
    )


def test_every_committed_entry_carries_exactly_the_declared_fields():
    """The field list is a promise about what can be checked without a re-fetch."""
    raw = json.loads(latest_record().read_text(encoding='utf-8'))

    assert raw['fields'] == list(RECORD_FIELDS)
    for row in raw['models']:
        assert set(row) == set(RECORD_FIELDS), (
            f"{row.get('id')} carries {sorted(set(row) ^ set(RECORD_FIELDS))} "
            f"differing from the declared field list"
        )


# --- the digest is the payload's, which is what makes a re-fetch checkable -----------------

def test_the_digest_is_the_full_payloads_not_the_records_own():
    """A digest of the reduced form would only prove the file had not been edited.

    This is the distinction the whole module turns on, so it is asserted rather than
    left to the docstring: the recorded hash must *not* equal the hash of the committed
    file, because the committed file is a subset of what was hashed.
    """
    path = latest_record()
    record = load_record(path)

    own_digest = sha256_of_bytes(path.read_bytes())
    assert record.source_sha256 != own_digest, (
        'the record hashes itself, so it cannot be tied to the payload it came from'
    )
    # And it is a real SHA-256 of something, not a placeholder.
    assert len(record.source_sha256) == 64
    assert all(character in '0123456789ABCDEF' for character in record.source_sha256)


def test_a_rescreen_of_the_same_payload_reproduces_the_record():
    """The reduction is deterministic, so a record can be regenerated and diffed.

    Without this a future session cannot tell "the catalogue changed" from "the script
    changed", and the diff of a committed record would be unreadable.
    """
    path = latest_record()
    record = load_record(path)

    payload = {
        'data': [
            {
                'id': entry.id,
                'created': _unix_for(entry.created),
                'context_length': entry.context_length,
                'pricing': {
                    'prompt': str(entry.prompt / 1e6),
                    'completion': str(entry.completion / 1e6),
                },
                'supported_parameters': (
                    ['structured_outputs'] if entry.structured_outputs else []
                ),
                'top_provider': {'max_completion_tokens': entry.max_completion_tokens},
            }
            for entry in record.entries
        ]
    }
    again = screen_payload(
        payload, read_on=record.read_on, source_sha256=record.source_sha256
    )
    assert [e.id for e in again.entries] == [e.id for e in record.entries]


def _unix_for(date_text: str) -> int:
    from datetime import datetime, timezone

    return int(
        datetime.strptime(date_text, '%Y-%m-%d')
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


# --- the curated model is verifiable, which is the reason any of this exists ---------------

def test_the_curated_model_is_in_the_record():
    """A curated model absent from the listing cannot have its price checked.

    Reported through ``missing_from_record`` rather than a bare ``find()`` so the
    failure says *what is unverifiable*, which is the thing a reader needs.
    """
    from evaluation.curated_models import CURATED_MODELS

    record = load_record(latest_record())
    missing = missing_from_record([m.id for m in CURATED_MODELS], record)

    assert missing == (), (
        f'curated models absent from the committed listing record: {missing}. Their '
        f'prices can no longer be checked against a listing, which is the one guarantee '
        f'the record exists to give'
    )


def test_the_curated_models_recorded_prices_match_the_listing():
    """**The test that could not run before.** It skipped for want of a listing.

    A price that drifted from the listing is worse than no price: the ranking metric is
    cost per accepted result, so a stale figure misranks every candidate at once while
    looking entirely plausible.
    """
    from evaluation.curated_models import CURATED_MODELS

    record = load_record(latest_record())
    disagreements = price_disagreements(
        {
            m.id: (m.input_per_1m, m.output_per_1m)
            for m in CURATED_MODELS
        },
        record,
    )

    assert disagreements == (), (
        f'curated prices disagree with the committed listing record: {disagreements}. '
        f'Re-read the listing, then update curated_models and PRICE_SOURCES together'
    )


def test_the_curated_model_advertises_structured_output_in_the_record():
    """The product requirement, checked against a listing that is in the repository."""
    from evaluation.curated_models import CURATED_MODELS

    record = load_record(latest_record())
    for model in CURATED_MODELS:
        entry = record.find(model.id)
        assert entry is not None, f'{model.id} is absent from the record'
        assert entry.structured_outputs, (
            f'{model.id} does not advertise structured_outputs; a model that cannot be '
            f'relied on for schema-valid JSON is not an option'
        )


def test_no_curated_model_is_older_than_the_owner_floor_in_the_record():
    """The listing's own date for the model, not the one the curated set records.

    Cross-checking the two is the point: ``curated_models`` asserts its own ``created``
    field against the floor, so a wrong date there would pass. This compares it to what
    the catalogue said.
    """
    from evaluation.curated_models import CURATED_MODELS

    record = load_record(latest_record())
    for model in CURATED_MODELS:
        entry = record.find(model.id)
        assert entry is not None
        assert entry.created >= listing.MIN_CREATED, (
            f'{model.id} was created {entry.created}, before the owner floor of '
            f'{listing.MIN_CREATED}'
        )
        if model.created:
            assert entry.created == model.created, (
                f'{model.id}: curated set records created={model.created}, the listing '
                f'says {entry.created}'
            )


# --- structural usability is about the request, not about quality --------------------------

def test_a_model_without_structured_output_is_not_structurally_usable():
    entry = ListingEntry(
        id='v/m', prompt=1.0, completion=1.0, created='2026-01-01',
        structured_outputs=False, context_length=100_000, max_completion_tokens=8_000,
    )
    assert structurally_usable(entry) is False


def test_a_ceiling_too_small_for_a_document_is_not_structurally_usable():
    """A CV draft is ~1,350 output tokens; an endpoint that cannot hold one is unusable
    however cheap it is."""
    entry = ListingEntry(
        id='v/m', prompt=1.0, completion=1.0, created='2026-01-01',
        structured_outputs=True, context_length=100_000,
        max_completion_tokens=MIN_MAX_COMPLETION_TOKENS - 1,
    )
    assert structurally_usable(entry) is False

    # And the boundary itself is usable, so the constant is a floor and not a strict
    # inequality that quietly excludes it.
    at_limit = ListingEntry(
        id='v/m', prompt=1.0, completion=1.0, created='2026-01-01',
        structured_outputs=True, context_length=100_000,
        max_completion_tokens=MIN_MAX_COMPLETION_TOKENS,
    )
    assert structurally_usable(at_limit) is True


def test_an_unpriced_model_is_not_structurally_usable():
    """No price means ``price_for`` borrows the fallback route's rate, so the run's
    headline metric becomes fiction for that model while looking plausible."""
    free = ListingEntry(
        id='v/m', prompt=0.0, completion=0.5, created='2026-01-01',
        structured_outputs=True, context_length=100_000, max_completion_tokens=8_000,
    )
    assert structurally_usable(free) is False


def test_the_screen_keeps_a_model_below_the_recency_floor_out():
    """The floor is the owner's rule, and applying it in the screen is a size decision.

    Asserted on the *screen* rather than on ``structurally_usable``, because the two are
    deliberately different questions: recency is a curation rule, not a structural
    property of a request.
    """
    payload = {
        'data': [
            {
                'id': 'vendor/too-old',
                'created': _unix_for('2024-01-01'),
                'pricing': {'prompt': '0.000001', 'completion': '0.000002'},
                'supported_parameters': ['structured_outputs'],
                'top_provider': {'max_completion_tokens': 8_000},
            },
            {
                'id': 'vendor/recent-enough',
                'created': _unix_for('2026-01-01'),
                'pricing': {'prompt': '0.000001', 'completion': '0.000002'},
                'supported_parameters': ['structured_outputs'],
                'top_provider': {'max_completion_tokens': 8_000},
            },
        ]
    }
    record = screen_payload(payload, read_on='2026-10-30', source_sha256='A' * 64)

    assert [e.id for e in record.entries] == ['vendor/recent-enough']


def test_a_model_with_no_usable_date_is_not_kept():
    """An absent date must not be defaulted to today, or it satisfies the floor silently.

    This is the failure the floor exists to prevent, so a missing date fails *closed*:
    ``""`` sorts below ``"2025-10-01"``, so the screen's ``>=`` test drops it. Asserted
    through the **screen**, because that is where the consequence lives -- asserting only
    that ``created == ""`` would pin the representation and not the behaviour.
    """
    row = {
        'id': 'vendor/no-date',
        'created': None,
        'pricing': {'prompt': '0.000001', 'completion': '0.000002'},
        'supported_parameters': ['structured_outputs'],
        'top_provider': {'max_completion_tokens': 8_000},
    }
    entry = entry_from_payload(row)
    assert entry.created == '', 'an unusable date must be reported absent, not defaulted'
    assert not (entry.created >= listing.MIN_CREATED), (
        'an empty date compared as if it satisfied the floor; the entry would be kept'
    )

    record = screen_payload(
        {'data': [row]}, read_on='2026-10-30', source_sha256='A' * 64
    )
    assert record.entries == (), 'a model with no usable date survived the screen'
    # And the payload was still counted, so the drop is visible rather than silent.
    assert record.source_model_count == 1


# --- malformed input is refused, not silently emptied --------------------------------------

def test_a_payload_without_a_data_list_is_refused():
    """OpenRouter returns ``{'data': [...]}``; anything else is not that payload."""
    with pytest.raises(ValueError, match="no 'data' list"):
        screen_payload({'models': []}, read_on='2026-10-30', source_sha256='A' * 64)


def test_a_record_missing_a_field_is_refused():
    """A record that cannot be read must not be mistakable for a catalogue with no
    models, so parsing raises rather than dropping the row."""
    text = json.dumps(
        {
            'read_on': '2026-10-30',
            'source_url': LISTING_URL,
            'source_sha256': 'A' * 64,
            'source_model_count': 1,
            'models': [{'id': 'v/m', 'prompt': 1.0}],
        }
    )
    with pytest.raises(ValueError, match='is missing'):
        parse_record(text)


def test_a_record_that_is_not_a_record_is_refused():
    with pytest.raises(ValueError, match="no 'models' key"):
        parse_record(json.dumps({'something': 'else'}))


# --- disagreement is reported, never corrected ---------------------------------------------

def test_a_price_disagreement_is_reported_with_both_figures():
    """Which figure is right is a curation decision; the record's job is to show the gap."""
    record = ListingRecord(
        read_on='2026-10-30', source_url=LISTING_URL, source_sha256='A' * 64,
        source_model_count=1,
        entries=(ListingEntry(
            id='v/m', prompt=1.0, completion=2.0, created='2026-01-01',
            structured_outputs=True, context_length=1, max_completion_tokens=1,
        ),),
    )
    found = price_disagreements({'v/m': (9.0, 9.0)}, record)

    assert len(found) == 1
    assert found[0]['id'] == 'v/m'
    assert found[0]['recorded'] == (9.0, 9.0)
    assert found[0]['listing'] == (1.0, 2.0)


def test_an_agreeing_price_is_not_reported():
    """Reporting a match as a disagreement would make the guard useless."""
    record = ListingRecord(
        read_on='2026-10-30', source_url=LISTING_URL, source_sha256='A' * 64,
        source_model_count=1,
        entries=(ListingEntry(
            id='v/m', prompt=0.1, completion=0.5, created='2026-01-01',
            structured_outputs=True, context_length=1, max_completion_tokens=1,
        ),),
    )
    assert price_disagreements({'v/m': (0.1, 0.5)}, record) == ()


def test_float_noise_does_not_register_as_a_disagreement():
    """Both sides are parsed from decimal strings, so exact equality would report every
    model as disagreeing.

    The listing says ``"0.0000001"``; ``float(...) * 1e6`` is ``0.09999999999999999``.
    That was measured while building the record, and it is why the comparison carries a
    tolerance and the read rounds.
    """
    record = ListingRecord(
        read_on='2026-10-30', source_url=LISTING_URL, source_sha256='A' * 64,
        source_model_count=1,
        entries=(ListingEntry(
            id='v/m', prompt=0.1, completion=0.5, created='2026-01-01',
            structured_outputs=True, context_length=1, max_completion_tokens=1,
        ),),
    )
    assert price_disagreements({'v/m': (0.09999999999999999, 0.5)}, record) == ()


def test_an_absent_model_is_not_reported_as_a_price_disagreement():
    """The two failures are different and must not be conflated.

    A wrong price is *reported evidence*; a missing model is *no evidence*.
    ``missing_from_record`` is where the second belongs.
    """
    record = ListingRecord(
        read_on='2026-10-30', source_url=LISTING_URL, source_sha256='A' * 64,
        source_model_count=0, entries=(),
    )
    assert price_disagreements({'v/absent': (1.0, 1.0)}, record) == ()
    assert missing_from_record(['v/absent'], record) == ('v/absent',)


# --- parsing details that a reader of the record depends on --------------------------------

def test_prices_are_stored_per_million_and_rounded():
    """The listing quotes per-token strings; the record stores USD per 1M.

    Rounded because ``float('0.0000001') * 1e6`` is ``0.09999999999999999``, which would
    appear in the committed file for every entry -- 20 characters instead of 4, in a file
    whose purpose is to be read by a person reviewing prices.
    """
    entry = entry_from_payload(
        {'id': 'v/m', 'pricing': {'prompt': '0.0000001', 'completion': '0.0000005'}}
    )
    assert entry.prompt == 0.1
    assert entry.completion == 0.5
    # Exactly representable, so the committed JSON has no noise in it.
    assert '0.09999999999999999' not in json.dumps(entry.as_dict())


def test_a_row_without_an_id_is_skipped_rather_than_raising():
    """One malformed entry must not make a 456-model payload unreadable."""
    assert entry_from_payload({'pricing': {}}) is None
    assert entry_from_payload({'id': '   '}) is None

    record = screen_payload(
        {'data': [{'id': ''}, {'not': 'a-row'}, 42]},
        read_on='2026-10-30', source_sha256='A' * 64,
    )
    assert record.entries == ()
    assert record.source_model_count == 3


def test_a_duplicate_id_is_recorded_once():
    """A duplicate would make ``by_id`` order-dependent, so lookups stop being stable."""
    row = {
        'id': 'v/m', 'created': _unix_for('2026-01-01'),
        'pricing': {'prompt': '0.000001', 'completion': '0.000002'},
        'supported_parameters': ['structured_outputs'],
        'top_provider': {'max_completion_tokens': 8_000},
    }
    record = screen_payload(
        {'data': [row, dict(row)]},
        read_on='2026-10-30', source_sha256='A' * 64,
    )
    assert [e.id for e in record.entries] == ['v/m']


def test_the_committed_record_is_valid_json_with_a_trailing_newline():
    """Committed text, so it must diff cleanly: identical content, identical bytes."""
    path = latest_record()
    text = path.read_text(encoding='utf-8')

    assert text.endswith('\n')
    assert json.loads(text)['read_on']
    assert not text.startswith('\ufeff'), (
        'the record starts with a UTF-8 BOM, which PowerShell\'s redirection adds and '
        'which makes a JSON file unparseable by strict readers'
    )
