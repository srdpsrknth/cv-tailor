"""Private per-profile writing guidance changes only the letter and its cache key."""

import json
from pathlib import Path
import pytest


@pytest.fixture
def profile_store(tmp_path):
    import shutil
    from services.profile_store import ProfileStore

    store = ProfileStore.at(tmp_path)
    for candidate, filename in [
        ("analyst_a", "synthetic_analyst.yaml"),
        ("marketer_b", "synthetic_marketer.yaml"),
    ]:
        path = store.profile_path(candidate)
        path.parent.mkdir(parents=True)
        shutil.copy2(Path(__file__).parent / "fixtures/profiles" / filename, path)
    return store


def write_style(config, profile_id, **changes):
    path = config.store.profile_path(profile_id).with_name("writing_style.json")
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tone": "Warm and direct",
                "preferences": ["Explain what the work changed for its users."],
                "avoid": ["Empty corporate flattery"],
                "sign_off": "Warm regards,",
                "reference_sources": ["C:/private-reference/source.docx"],
                **changes,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_missing_voice_file_keeps_the_letter_prompt_unchanged(profile_store):
    from config import Config
    from services.writing_voice import writing_voice_context

    config = Config.from_env(
        load_env_file=False, overrides={"profile_store_dir": profile_store.root}
    )
    assert writing_voice_context(config, "analyst_a") == ""


def test_voice_is_style_only_and_does_not_send_reference_paths(profile_store):
    from config import Config
    from services.writing_voice import writing_voice_context

    config = Config.from_env(
        load_env_file=False, overrides={"profile_store_dir": profile_store.root}
    )
    write_style(config, "analyst_a")
    context = writing_voice_context(config, "analyst_a")
    assert "Warm and direct" in context
    assert "style only" in context.lower()
    assert "Warm regards," in context
    assert "private-reference" not in context
    assert writing_voice_context(config, "marketer_b") == ""


def test_invalid_voice_is_not_silently_ignored(profile_store):
    from config import Config
    from services.writing_voice import writing_voice_context

    config = Config.from_env(
        load_env_file=False, overrides={"profile_store_dir": profile_store.root}
    )
    write_style(config, "analyst_a", preferences="invalid scalar")
    with pytest.raises(ValueError, match="writing_style"):
        writing_voice_context(config, "analyst_a")


def test_loose_profile_file_does_not_inherit_a_store_candidates_voice(profile_store):
    from config import Config
    from services.writing_voice import writing_voice_context

    config = Config.from_env(
        load_env_file=False,
        overrides={
            "profile_store_dir": profile_store.root,
            "profile_path": profile_store.profile_path("analyst_a"),
        },
    )
    write_style(config, "analyst_a")
    assert writing_voice_context(config, "analyst_a") == ""


def test_voice_change_invalidates_cache_and_is_sent_only_to_letter(
    isolated_service,
    offline_service,
    stub_renderers,
    analyst_profile,
    analyst_session,
):
    from config import Config
    from services.tailor_service import tailor_documents

    config = Config.from_env(
        load_env_file=False, overrides={"project_root": isolated_service}
    )
    offline = offline_service(
        [
            analyst_session.step_text("cv_draft"),
            analyst_session.step_text("cover_letter"),
        ]
        * 2
    )
    stub_renderers([2, 2, 2])
    tailor_documents(analyst_session.job_description_text, analyst_profile)
    write_style(config, "analyst_a", tone="Distinctive synthetic voice marker")
    result = tailor_documents(analyst_session.job_description_text, analyst_profile)
    assert offline.call_count == 4
    assert result.cache_hit is False
    assert "Distinctive synthetic voice marker" not in offline.prompts[2]
    assert "Distinctive synthetic voice marker" in offline.prompts[3]
    repeated = tailor_documents(analyst_session.job_description_text, analyst_profile)
    assert repeated.cache_hit is True
    assert offline.call_count == 4
