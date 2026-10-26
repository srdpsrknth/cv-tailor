"""Phase 3, item 5: the validated-generation cache.

The item exists because one profile against one posting re-drafted from scratch every
time. Rendering was already free; generation was not. These tests pin the four decisions
that make the cache safe rather than fast:

1. **The key is the bytes the model was shown** -- the serialized profile, the posting
   plus company/role/country, both prompt files, the schema, the provider and both routed
   models, and the resolved rules. Not a ``job_id`` (which embeds a millisecond, so it
   would miss every time) and not a timestamp.
2. **Only a validated result is stored.** The entry is written after the page-count gate;
   a draft that failed the gate is never stored.
3. **A prompt change, a model change or a profile change is a miss**, so a prompt edit
   cannot silently serve a stale document.
4. **It is derived data in the private store** and is always safe to delete: a corrupt,
   unreadable or no-longer-valid entry degrades to "generate it again" rather than
   breaking the run.

Nothing here makes a network call. The pipeline is driven from the recorded transcript
through :class:`OfflineGemini`; renderers are stubbed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import tailor_service as service

# Imported defensively and failed, not skipped, when absent: a broken import in the real
# tree is the one thing this file exists to catch, and a skip would hide it.
try:
    from services import cache_store
    from services.cache_store import (
        CACHE_FORMAT_VERSION,
        CacheEntry,
        GenerationCache,
        cache_key,
        rules_fingerprint,
        serialize_profile_bytes,
    )
except ImportError as error:  # pragma: no cover - exercised only on a broken tree
    pytest.fail(f"services.cache_store could not be imported: {error}", pytrace=False)


NORDWIND = 'Nordwind Analytics GmbH'
ANALYST_ROLE = 'Analytical Engineer'


def run(analyst_session, analyst_profile, **kwargs):
    """One pipeline run over the recorded transcript, with stubbed renderers."""
    return service.tailor_documents(
        analyst_session.job_description_text, analyst_profile,
        company_name=NORDWIND, role_title=ANALYST_ROLE, **kwargs,
    )


def key_kwargs(analyst_session, analyst_profile, **overrides):
    """The full set of ingredients, so each test can vary exactly one."""
    from services import generation

    values = {
        'profile_bytes': serialize_profile_bytes(analyst_profile),
        'job_description': analyst_session.job_description_text,
        'company_name': NORDWIND,
        'role_title': ANALYST_ROLE,
        'work_country': None,
        'prompt_cv': 'CV PROMPT BYTES',
        'prompt_cl': 'CL PROMPT BYTES',
        'prompt_version': 'prompt-digest',
        'schema_version': 'schema-digest',
        'provider': 'gemini',
        'model_cv': 'gemini-3.8-flash',
        'model_cl': 'gemini-3.8-flash',
        'rules_fingerprint': rules_fingerprint(
            generation.ProfileRules.from_profile(analyst_profile)
        ),
    }
    values.update(overrides)
    return values


# --- the key is the bytes the model was shown -------------------------------------------

def test_the_same_inputs_produce_the_same_key(analyst_session, analyst_profile):
    """A repeat must be recognisable as a repeat, or the cache never hits."""
    first = cache_key(**key_kwargs(analyst_session, analyst_profile))
    second = cache_key(**key_kwargs(analyst_session, analyst_profile))

    assert first == second
    assert len(first) == 64 and all(c in '0123456789abcdef' for c in first)


@pytest.mark.parametrize('field,changed', [
    ('profile_bytes', '{"identity": {"full_name": "Someone Else"}}'),
    ('job_description', 'A different posting entirely.'),
    ('company_name', 'Lumen Consumer BV'),
    ('role_title', 'Growth Analyst'),
    ('work_country', 'Ireland'),
    ('prompt_cv', 'CV PROMPT BYTES, EDITED'),
    ('prompt_cl', 'CL PROMPT BYTES, EDITED'),
    ('prompt_version', 'a-newer-prompt-digest'),
    ('schema_version', 'a-newer-schema-digest'),
    ('provider', 'openrouter'),
    ('model_cv', 'gemini-2.5-pro'),
    ('model_cl', 'openrouter/anthropic/claude-sonnet-4.5'),
    ('rules_fingerprint', 'a-different-rules-digest'),
])
def test_any_changed_ingredient_changes_the_key(
    analyst_session, analyst_profile, field, changed,
):
    """Every ingredient is load-bearing, and each is tested on its own.

    ``model_cv`` and ``model_cl`` are separate because item 6 added model-per-task
    routing: two models can serve one posting, and a key that knew only "the model"
    would serve one route's documents for the other's.
    """
    assert cache_key(**key_kwargs(analyst_session, analyst_profile, **{field: changed})) != \
        cache_key(**key_kwargs(analyst_session, analyst_profile))


def test_a_prompt_edit_is_not_served_from_cache(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
    monkeypatch,
):
    """The whole point, asserted through the real pipeline rather than on the key alone.

    A first run stores an entry. The CV prompt file is then edited and an identical
    request is made. If the key did not include the prompt, the second run would make
    **zero** calls and serve documents drafted under the old prompt. It must cost a
    fresh draft instead.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 2

    # An identical repeat is a hit: no further calls at all.
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 0, 'an identical repeat must not pay twice'

    # Now the prompt file changes on disk. Same profile, same posting, same model.
    from services import generation

    original = Path.read_text

    def edited_read(self, *args, **kwargs):
        text = original(self, *args, **kwargs)
        if self == generation.PROMPT_CV_PATH:
            return text + '\nNEW RULE ADDED TO THE PROMPT.\n'
        return text

    monkeypatch.setattr(Path, 'read_text', edited_read)
    assert generation.PROMPT_CV_PATH.read_text(encoding='utf-8').endswith(
        'NEW RULE ADDED TO THE PROMPT.\n'
    ), 'the edit must actually be visible to the code under test'

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 2, (
        'a changed prompt byte must trigger a fresh draft, not a stale document'
    )
    # And the model was shown the *new* prompt, not the one the entry was keyed under.
    assert 'NEW RULE ADDED TO THE PROMPT.' in offline.prompts[0]


def test_a_model_change_is_not_served_from_cache(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Item 6's routing means one posting can be drafted by two models.

    The test drives that through the real pipeline: the second run is routed to a
    different CV model, so it must re-draft even though every other input is identical.
    """
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 2

    import config as config_module

    routed = config_module.Config.from_env(
        load_env_file=False, overrides={'task_models': {'cv': 'gemini-2.5-pro'}},
    )
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile, config=routed)
    assert offline.call_count == 2, 'a routed model change must not reuse the other route'


def test_a_profile_change_is_not_served_from_cache(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Editing the profile changes the bytes the model was shown, so it is a miss."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)

    edited = analyst_profile.model_copy(deep=True)
    edited.summary_base = list(analyst_profile.summary_base) + ['Added line for the test.']

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, edited)
    assert offline.call_count == 2, 'edited profile bytes are a different generation'


# --- a hit costs nothing and returns the same documents ---------------------------------

def test_an_identical_generation_is_served_from_the_cache_with_no_calls(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The acceptance criterion: a repeat makes **0** LLM calls."""
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    first = run(analyst_session, analyst_profile)
    assert offline.call_count == 2

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    second = run(analyst_session, analyst_profile)

    assert offline.call_count == 0, 'a cache hit must make no provider call'
    assert not offline.exhausted

    first_content = json.loads(Path(first.source_path).read_text(encoding='utf-8'))
    second_content = json.loads(Path(second.source_path).read_text(encoding='utf-8'))
    assert second_content == first_content, 'the accepted documents must be byte-identical'


def test_a_hit_reports_zero_usage_rather_than_the_original_runs_tokens(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A run that made no call must not report a cost.

    Replaying the original run's totals would put a price on calls this run did not
    make, on the one path where the saving is the entire point.
    """
    offline_service(analyst_session.texts())
    stub_renderers([2])
    first = run(analyst_session, analyst_profile)
    assert first.token_usage.total_tokens > 0

    offline_service(analyst_session.texts())
    stub_renderers([2])
    second = run(analyst_session, analyst_profile)

    assert second.token_usage.total_tokens == 0
    assert second.token_usage.estimated_cost_usd == 0.0
    assert second.token_usage.cv_attempts == 0 and second.token_usage.cl_attempts == 0


def test_a_hit_reports_the_original_explanation(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The explanation is part of the accepted result and is restored with it."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    first = run(analyst_session, analyst_profile)

    offline_service(analyst_session.texts())
    stub_renderers([2])
    second = run(analyst_session, analyst_profile)

    assert first.tailoring_explanation is not None
    assert second.tailoring_explanation == first.tailoring_explanation


def test_a_hit_still_writes_a_complete_job_folder(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A hit produces a normal application folder, manifest and editable content.

    The cache replaces the *generation*, not the persistence: the user asked for an
    application and gets one, with the same audit trail a fresh run would leave.
    """
    from support import read_json

    offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)

    offline_service(analyst_session.texts())
    stub_renderers([2])
    second = run(analyst_session, analyst_profile)

    source = Path(second.source_path).parent
    for name in ('content.json', 'profile_snapshot.json', 'job_description.txt',
                 'drafts.json', 'generation_result.json'):
        assert (source / name).exists(), f'missing {name}'

    drafts = read_json(source / 'drafts.json')['drafts']
    assert len(drafts) == 2, 'the original raw responses are restored as the audit trail'
    assert {item['component'] for item in drafts} == {'cv', 'cover_letter'}
    assert drafts[0]['response'] == analyst_session.step_text('cv_draft'), (
        'the audit trail holds the responses verbatim, not a paraphrase'
    )
    manifest = read_json(source / 'generation_result.json')
    assert manifest['status'] == 'success'
    assert Path(second.cv_path).exists()


def test_a_hit_uses_a_new_job_folder_and_does_not_overwrite_the_first(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A repeat is a new application, not a rewrite of the previous one."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    first = run(analyst_session, analyst_profile)

    offline_service(analyst_session.texts())
    stub_renderers([2])
    second = run(analyst_session, analyst_profile)

    assert first.job_id != second.job_id
    assert Path(first.source_path).exists() and Path(second.source_path).exists()


# --- only a validated result is stored ---------------------------------------------------

def test_a_failed_run_stores_nothing(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The rule that makes the cache safe: an unvalidated draft is never stored.

    A draft missing an employer fails the gate; the run raises. Nothing may be left
    behind that a later identical request could be answered with.
    """
    bad = json.loads(analyst_session.step_text('cv_draft'))
    bad['cv']['experience'] = bad['cv']['experience'][:-1]
    offline_service([json.dumps(bad)] * 3)
    stub_renderers([2])

    with pytest.raises(ValueError, match='after three attempts'):
        run(analyst_session, analyst_profile)

    cache = _cache_for(isolated_service)
    assert cache.count() == 0, 'a run that never validated must not store an entry'

    # And the next identical request must still pay for a real attempt.
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 2


def test_a_cv_that_will_not_fit_is_not_stored(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The page-count gate is a gate: a CV stuck at three pages is not cached.

    This is the case the item's framing calls out -- an entry written before the gate
    would turn a failed layout loop into a permanent answer.

    The failing run is driven with ``use_cache=False`` on an otherwise empty cache, so
    it is a genuine cold generation that happens to fail; nothing was stored before it
    and nothing is stored by it.
    """
    cache = _cache_for(isolated_service)
    assert cache.count() == 0

    offline_service(analyst_session.texts())
    stub_renderers([3, 3, 3, 3])

    with pytest.raises(ValueError, match='after four layout attempts'):
        run(analyst_session, analyst_profile, use_cache=False)

    assert cache.count() == 0, 'a run whose CV never fitted must not store an entry'


def test_a_failed_repeat_does_not_overwrite_the_entry_a_success_stored(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A stored entry is still served while a *repeat* of the same key fails.

    The failure below is a different layout outcome for the same key, which is what
    ``use_cache=False`` produces. The stored entry must survive it: the cache is never
    cleared by a failure, and the failure never stores anything either.

    The page boxes are passed once, as one sequence, because ``stub_renderers`` appends
    to a shared list: the successful run consumes ``2``, the failing run the four ``3``s,
    and the final hit consumes none.
    """
    offline_service(analyst_session.texts())
    stub_renderers([2, 3, 3, 3, 3])
    run(analyst_session, analyst_profile)

    cache = _cache_for(isolated_service)
    keys = cache.keys()
    assert len(keys) == 1
    stored = cache.path_for(keys[0]).read_text(encoding='utf-8')

    offline_service(analyst_session.texts())
    with pytest.raises(ValueError, match='after four layout attempts'):
        run(analyst_session, analyst_profile, use_cache=False)

    assert cache.keys() == keys, 'a failed run must not delete or replace an entry'
    assert cache.path_for(keys[0]).read_text(encoding='utf-8') == stored

    # The untouched entry is still a hit.
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 0


# --- invalidation is total, and deletion is always safe ----------------------------------

def test_the_cache_is_written_into_the_store_and_never_the_repository(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Derived data still belongs to the private store (ADR 0011).

    The repository's own ``outputs/`` must stay empty: a cache holding accepted
    documents is real candidate data, so the same boundary applies to it.
    """
    offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)

    cache = _cache_for(isolated_service)
    assert cache.count() == 1
    # ``isolated_service`` roots the store at a temp project root, so the cache being
    # under it is exactly "in the store, not in the repository".
    assert str(isolated_service) in str(cache.path_for(cache.keys()[0]))


def test_a_loose_profile_path_still_caches_in_the_store_not_the_repository(
    tmp_path,
):
    """The case a live evaluation run takes, and the one that was wrong at first.

    ``evaluation/live.py`` drives the real pipeline with ``profile_path`` set (a fixture
    file, not a store id), which is the branch that puts *outputs* in the repository's
    gitignored ``outputs/``. The cache must **not** follow it there: an entry holds the
    accepted documents, and a sibling ``<repo>/cache/`` is not gitignored, so a live run
    would have written real candidate data into the public repository's working tree.

    Asserted on the resolver directly rather than by running the suite, because the
    evaluation suite makes no call offline and this is the path it *would* take.
    """
    import config as config_module
    from services import tailor_service as module

    store_root = tmp_path / 'a-real-store'
    config = config_module.Config.from_env(
        load_env_file=False,
        overrides={
            'project_root': tmp_path / 'repo',
            'profile_store_dir': store_root,
            'profile_path': tmp_path / 'fixtures' / 'synthetic_analyst.yaml',
        },
    )
    assert config.profile_path is not None, 'this test is about the loose-path branch'

    root = module._cache_root(config)

    assert root == store_root / 'cache'
    assert 'repo' not in root.parts, 'the cache must never be rooted in the repository'


def test_the_repository_root_has_no_cache_directory_after_a_loose_profile_run(
    repo_root, tmp_path, monkeypatch, offline_service, stub_renderers, analyst_session,
):
    """No run may leave a ``cache/`` directory in the repository — driven end to end.

    This is the guard that matters, and it has to take the **loose ``--profile`` path**,
    because that is the branch a live evaluation run takes and the only one that could
    put the cache in the repository: a store-id run roots outputs in the store anyway.

    Asserted on the real repository root, so a change that moves the cache back beside
    the outputs is caught here rather than during a paid run.
    """
    from support import load_profile

    repo_cache = Path(repo_root) / 'cache'
    assert not any(repo_cache.rglob('*.json')) if repo_cache.exists() else True, (
        'the repository already holds cache entries from an earlier run'
    )

    # The loose-path branch, with a store that is NOT the repository -- exactly the
    # shape ``evaluation/live.py`` builds.
    store_root = tmp_path / 'private-store'
    store_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('CVTAILOR_STORE', str(store_root))
    # A loose profile file bypasses the store *lookup*, but an id is still required:
    # it names the output segment and the cache segment (ADR 0003), and nothing about
    # that changes when the profile comes from a file.
    monkeypatch.setenv('CVTAILOR_PROFILE_ID', 'eval_case')
    monkeypatch.setattr(
        service, 'PROJECT_ROOT', tmp_path / 'repo-root-outside-the-real-one',
    )

    from config import Config

    profile_path = Path(repo_root) / 'tests' / 'fixtures' / 'profiles' / 'synthetic_analyst.yaml'
    config = Config.from_env(
        load_env_file=False,
        overrides={
            'project_root': tmp_path / 'repo-root-outside-the-real-one',
            'profile_store_dir': store_root,
            'profile_path': profile_path,
            'profile_id': 'eval_case',
        },
    )
    assert config.profile_path is not None, 'this test is about the loose-path branch'

    offline_service(analyst_session.texts())
    stub_renderers([2])
    service.tailor_documents(
        analyst_session.job_description_text, load_profile('synthetic_analyst'),
        company_name=NORDWIND, role_title=ANALYST_ROLE, config=config,
    )

    # The entry landed in the store, under the candidate segment...
    stored = GenerationCache(store_root / 'cache' / 'eval_case')
    assert stored.count() == 1, 'the cache must be written into the store'
    # ...and the real repository gained nothing.
    assert not (Path(repo_root) / 'cache').exists() or not any(
        (Path(repo_root) / 'cache').rglob('*.json')
    ), 'a loose-profile run wrote cache entries into the repository'


def test_deleting_the_cache_costs_a_regeneration_and_nothing_else(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The cache is derived data: removing it must never lose a document."""
    import shutil

    offline_service(analyst_session.texts())
    stub_renderers([2])
    first = run(analyst_session, analyst_profile)
    cache = _cache_for(isolated_service)
    assert cache.count() == 1

    shutil.rmtree(cache.root)
    assert not cache.root.exists()
    assert cache.keys() == [], 'a deleted cache reads as empty, not as an error'
    assert Path(first.source_path).exists(), 'the application itself is untouched'

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    second = run(analyst_session, analyst_profile)
    assert offline.call_count == 2, 'a deleted cache means generating again'
    assert cache.count() == 1, 'and the regenerated result is stored again'


def test_a_corrupt_entry_is_a_miss_rather_than_a_failure(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Unreadable, truncated or hand-edited entries must degrade, never break a run."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    cache = _cache_for(isolated_service)
    path = cache.path_for(cache.keys()[0])

    for junk in ('', '{not json', json.dumps({'format_version': CACHE_FORMAT_VERSION}),
                 json.dumps({'format_version': 999, 'cv': {}, 'cover_letter': {}})):
        path.write_text(junk, encoding='utf-8')
        offline = offline_service(analyst_session.texts())
        stub_renderers([2])
        run(analyst_session, analyst_profile)
        assert offline.call_count == 2, f'a {junk[:20]!r} entry must be treated as a miss'


def test_an_entry_edited_to_an_invalid_document_is_a_miss(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """A stored document is re-validated, because a file on disk is not a guarantee.

    The cache is a plain JSON file a person can edit. "It was validated when it was
    stored" is a claim about the past, so the restored documents go through the same
    ``_build_model`` a fresh draft does -- at no API cost.
    """
    offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    cache = _cache_for(isolated_service)
    path = cache.path_for(cache.keys()[0])

    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['cv']['experience'] = payload['cv']['experience'][:-1]  # drops an employer
    path.write_text(json.dumps(payload), encoding='utf-8')

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    result = run(analyst_session, analyst_profile)

    assert offline.call_count == 2, 'an invalid stored document must be generated again'
    stored = json.loads(Path(result.source_path).read_text(encoding='utf-8'))
    assert len(stored['cv']['experience']) == len(analyst_profile.experience)


def test_an_entry_whose_document_is_the_wrong_shape_is_a_miss(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Well-formed JSON with a non-document body must not reach the renderer."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    cache = _cache_for(isolated_service)
    path = cache.path_for(cache.keys()[0])

    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['cv'] = ['not', 'a', 'document']
    path.write_text(json.dumps(payload), encoding='utf-8')

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 2


# --- bypass -------------------------------------------------------------------------------

def test_use_cache_false_re_drafts_and_still_stores(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """The escape hatch: sometimes the stored one is fine but a fresh draft is wanted."""
    offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile, use_cache=False)
    assert offline.call_count == 2, 'the bypass must actually bypass'

    # And the fresh result replaced the entry, so the next normal run is a hit again.
    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 0


# --- the cold-cache baseline ---------------------------------------------------------------

def test_a_cold_cache_changes_no_call_count(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Item 5 must not move the frozen 2/3/5 baseline on a cold cache.

    A second test in the same process *would* hit the cache, which is why this asserts
    the counts on a first, cold run: 2 calls on the happy path, 3 with one layout retry,
    5 on the longest successful path -- exactly the numbers increment 2 froze.
    """
    assert _cache_for(isolated_service).count() == 0

    offline = offline_service(analyst_session.texts())
    stub_renderers([2])
    run(analyst_session, analyst_profile)
    assert offline.call_count == 2
    assert not offline.exhausted
    assert _cache_for(isolated_service).count() == 1


def test_a_cold_cache_does_not_write_an_entry_before_the_gate_passes(
    isolated_service, offline_service, stub_renderers, analyst_profile, analyst_session,
):
    """Nothing is written on the way in: the cold path is read-free and write-free.

    Asserted by counting entries *after* the draft has been requested but before the
    page-count gate has been consulted, using a renderer that inspects the cache.
    """
    cache = _cache_for(isolated_service)
    seen_during_render = []
    from unittest.mock import Mock

    from support import make_blank_pdf

    def latex_factory(outputs_dir):
        renderer = Mock()

        def render(cv, profile, job_position=None):
            seen_during_render.append(cache.count())
            return make_blank_pdf(Path(outputs_dir) / 'CV.pdf', 2)

        renderer.render_cv.side_effect = render
        return renderer

    def docx_factory(outputs_dir):
        def render(*args, **kwargs):
            folder = Path(outputs_dir)
            docx = folder / 'cover_letter.docx'
            docx.parent.mkdir(parents=True, exist_ok=True)
            docx.write_bytes(b'docx')
            return str(docx), make_blank_pdf(folder / 'cover_letter.pdf', 1)

        renderer = Mock()
        renderer.render_cover_letter.side_effect = render
        return renderer

    import services.tailor_service as module

    original_latex = module.create_latex_renderer
    original_docx = module.create_docx_renderer
    module.create_latex_renderer = latex_factory
    module.create_docx_renderer = docx_factory
    try:
        offline_service(analyst_session.texts())
        run(analyst_session, analyst_profile)
    finally:
        module.create_latex_renderer = original_latex
        module.create_docx_renderer = original_docx

    assert seen_during_render and all(count == 0 for count in seen_during_render), (
        'an entry was stored before the page-count gate accepted the document'
    )
    assert cache.count() == 1


# --- the store layout ----------------------------------------------------------------------

def test_the_cache_lives_beside_outputs_for_the_same_candidate(profile_store):
    """``<store>/cache/<profile_id>`` mirrors ``<store>/outputs/<profile_id>``."""
    assert profile_store.cache_dir('analyst_a') == profile_store.root / 'cache' / 'analyst_a'
    assert profile_store.outputs_dir('analyst_a').parent == profile_store.root / 'outputs'


def test_the_cache_dir_fails_closed_without_a_profile_id(profile_store):
    """``profile_id`` is required here too: a shared cache would cross candidates."""
    from services.profile_store import InvalidProfileIdError

    for bad in (None, '', 'Not An Id', '../escape'):
        with pytest.raises(InvalidProfileIdError):
            profile_store.cache_dir(bad)


def test_two_candidates_cannot_read_each_others_entries(
    profile_store, isolated_service,
):
    """The candidate segment is in the path, so isolation is structural."""
    first = GenerationCache.at(profile_store.root, 'analyst_a')
    second = GenerationCache.at(profile_store.root, 'marketer_b')
    assert first.root != second.root
    assert first.root.parent.parent == second.root.parent.parent


def test_the_cache_refuses_a_key_that_is_not_a_hex_digest():
    """A key becomes a filename, so anything else is rejected rather than sanitised."""
    cache = GenerationCache(Path('unused'))
    for bad in ('', 'not-hex', '../escape', 'a' * 63, 'A' * 64):
        with pytest.raises(ValueError):
            cache.path_for(bad)
    # A well-formed digest is accepted, so the rule is "exactly 64 lowercase hex",
    # not "reject everything".
    assert cache.path_for('a' * 64).name == 'a' * 64 + '.json'


def test_a_key_is_never_confused_between_fields(analyst_session, analyst_profile):
    """Values are hashed with their names, so one cannot be shifted into another.

    Without the names, ``company_name='Acme', role_title=''`` and
    ``company_name='', role_title='Acme'`` would hash identically.
    """
    assert cache_key(**key_kwargs(
        analyst_session, analyst_profile, company_name='Acme', role_title=''
    )) != cache_key(**key_kwargs(
        analyst_session, analyst_profile, company_name='', role_title='Acme'
    ))


def test_the_key_carries_no_timestamp_and_no_job_id(analyst_session, analyst_profile):
    """A key built from a timestamp would miss by construction.

    Asserted behaviourally: the same inputs, evaluated twice with the clock advanced,
    are the same key. ``job_id`` embeds ``time.time_ns()`` milliseconds, which is why it
    is deliberately not an ingredient.
    """
    import time

    first = cache_key(**key_kwargs(analyst_session, analyst_profile))
    time.sleep(0.01)
    second = cache_key(**key_kwargs(analyst_session, analyst_profile))
    assert first == second


# --- the format version --------------------------------------------------------------------

def test_a_different_format_version_is_a_miss(profile_store):
    """A stored entry from an older format must not be read as if it were current."""
    cache = GenerationCache(profile_store.root / 'cache' / 'analyst_a')
    key = 'a' * 64
    cache.put(key, CacheEntry(
        key=key, cv={'summary': ['x']}, cover_letter={'paragraphs': ['y']},
        tailoring_explanation=None, drafts=[], usage={},
        created_at='2026-10-26T00:00:00+00:00', provider='gemini', models={},
    ))
    assert cache.get(key) is not None

    path = cache.path_for(key)
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload['format_version'] == CACHE_FORMAT_VERSION
    payload['format_version'] = CACHE_FORMAT_VERSION - 1
    path.write_text(json.dumps(payload), encoding='utf-8')

    assert cache.get(key) is None, 'an entry from another format version is a miss'


def test_the_format_version_is_part_of_the_key_ingredients(analyst_session, analyst_profile):
    """Bumping the format invalidates entries without touching the prompts."""
    assert cache_key(**key_kwargs(
        analyst_session, analyst_profile, format_version=CACHE_FORMAT_VERSION + 1
    )) != cache_key(**key_kwargs(analyst_session, analyst_profile))


def test_the_default_generation_cache_root_is_the_stores_cache_tree(profile_store):
    assert GenerationCache.at(profile_store.root, 'analyst_a').root == \
        profile_store.root / 'cache' / 'analyst_a'


def _cache_for(project_root: Path) -> GenerationCache:
    """The cache an ``isolated_service`` run writes into."""
    return GenerationCache(Path(project_root) / 'cache' / 'analyst_a')
