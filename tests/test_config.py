"""Tests for the single config object (A-5).

The point of ``Config`` is that configuration is read at *call* time, not at
import time. These tests import the modules with hostile environment values and
then show that a later change is still honoured -- which is exactly what the old
module-level ``os.getenv`` reads made impossible.

No test here touches the network; ``has_api_key`` is a presence check only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from config import DEFAULT_MODEL, PROJECT_ROOT, Config  # noqa: E402


# --- defaults -------------------------------------------------------------------------

def test_config_resolves_defaults_without_any_environment(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_MODEL', raising=False)
    monkeypatch.delenv('OUTPUTS_DIR', raising=False)
    monkeypatch.delenv('GEMINI_TEMPERATURE', raising=False)
    monkeypatch.delenv('GEMINI_MAX_OUTPUT_TOKENS', raising=False)

    config = Config.from_env(load_env_file=False)

    assert config.model == DEFAULT_MODEL
    assert config.temperature == 0.3
    assert config.max_output_tokens == 8000
    assert config.api_key is None
    assert config.has_api_key is False
    assert config.outputs_dir == (PROJECT_ROOT / 'outputs').resolve()
    assert config.is_mirroring is False


def test_default_model_is_always_priced():
    """The pricing fallback relies on this; see the pricing tests.

    Checked against the **single pricing table**, on the default *route*. This used to
    check ``llm_service.PRICING``, which is the Gemini-route view only, so it passed
    while Gemini was the default and fails now that the default is an OpenRouter model --
    even though that model is correctly priced. The invariant is "the fallback target
    exists in the table", which is what this asserts.
    """
    from services import pricing

    assert pricing.is_priced(DEFAULT_MODEL, pricing.DEFAULT_PROVIDER), (
        f'{DEFAULT_MODEL} is the fallback target on {pricing.DEFAULT_PROVIDER} and must '
        f'have a price row, or every unpriced call is priced from a missing key'
    )
    # And config and pricing must agree on which route is default.
    assert DEFAULT_MODEL == pricing.DEFAULT_MODEL


# --- call-time reads ------------------------------------------------------------------

def test_environment_is_read_at_call_time_not_import_time(monkeypatch):
    """Two configs built at different moments must observe different environments.

    The provider is pinned to Gemini, because this exercises the **call-time read** and
    ``GEMINI_MODEL`` is Gemini-specific by design: with OpenRouter as the default
    provider, a Gemini model variable is deliberately ignored (see
    ``test_a_provider_specific_model_variable_does_not_leak_across_providers``).
    """
    monkeypatch.setenv('CVTAILOR_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_MODEL', 'first-model')
    first = Config.from_env(load_env_file=False)
    assert first.model == 'first-model'

    monkeypatch.setenv('GEMINI_MODEL', 'second-model')
    second = Config.from_env(load_env_file=False)
    assert second.model == 'second-model'
    # The earlier object is unaffected: configs are immutable snapshots.
    assert first.model == 'first-model'


def test_a_provider_specific_model_variable_does_not_leak_across_providers(monkeypatch):
    """A Gemini setting must not decide the model for another provider.

    This is a real regression guard, not a hypothetical. On 2026-10-27 the default
    provider moved to OpenRouter while the owner's `.env` still carried
    ``GEMINI_MODEL=gemini-3.8-flash``. Because that variable was read for *any* provider,
    it silently overrode the new default and the tool ran the previous, roughly 30x more
    expensive model -- through a route where the bare name is not even a priced id.

    Nothing failed: OpenRouter resolved the bare name and returned a document. That is
    what made it worth a test rather than a note.
    """
    monkeypatch.setenv('CVTAILOR_PROVIDER', 'openrouter')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-3.8-flash')
    monkeypatch.delenv('OPENROUTER_MODEL', raising=False)
    monkeypatch.delenv('CVTAILOR_MODEL', raising=False)

    config = Config.from_env(load_env_file=False)

    assert config.provider_name == 'openrouter'
    assert config.model == DEFAULT_MODEL, (
        'a Gemini model variable decided the OpenRouter model, silently undoing the '
        'switch to the measured winner'
    )

    # The Gemini route still honours it, so nothing was lost.
    monkeypatch.setenv('CVTAILOR_PROVIDER', 'gemini')
    assert Config.from_env(load_env_file=False).model == 'gemini-3.8-flash'

    # And the provider-neutral variable applies to whichever is selected.
    monkeypatch.setenv('CVTAILOR_MODEL', 'vendor/neutral-model')
    assert Config.from_env(load_env_file=False).model == 'vendor/neutral-model'


def test_outputs_dir_relative_value_is_project_relative(monkeypatch, tmp_path):
    monkeypatch.setenv('OUTPUTS_DIR', 'mirror-out')
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})

    assert config.outputs_dir == (tmp_path / 'mirror-out').resolve()
    assert config.is_mirroring is True


def test_outputs_dir_absolute_value_is_used_as_given(monkeypatch, tmp_path):
    target = tmp_path / 'elsewhere'
    monkeypatch.setenv('OUTPUTS_DIR', str(target))
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})

    assert config.outputs_dir == target.resolve()


def test_blank_outputs_dir_falls_back_to_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv('OUTPUTS_DIR', '   ')
    config = Config.from_env(load_env_file=False, overrides={'project_root': tmp_path})

    assert config.outputs_dir == (tmp_path / 'outputs').resolve()
    assert config.is_mirroring is False


# --- api key handling -----------------------------------------------------------------

def test_placeholder_api_key_is_not_treated_as_configured(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'your_gemini_api_key_here')
    config = Config.from_env(load_env_file=False)

    assert config.has_api_key is False
    with pytest.raises(Exception):
        config.require_api_key()


def test_a_real_looking_key_is_reported_as_present_without_network_use(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-not-a-real-credential')
    config = Config.from_env(load_env_file=False)

    assert config.has_api_key is True
    assert config.require_api_key() == 'test-key-not-a-real-credential'


def test_missing_key_error_names_the_fix(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    config = Config.from_env(load_env_file=False)

    with pytest.raises(Exception) as error:
        config.require_api_key()

    message = str(error.value)
    assert 'GEMINI_API_KEY' in message
    assert '.env' in message


# --- immutability and overrides -------------------------------------------------------

def test_config_is_frozen():
    config = Config.from_env(load_env_file=False)

    with pytest.raises(Exception):
        config.model = 'something-else'


def test_with_overrides_returns_a_new_object(monkeypatch):
    """An override derives a new config without mutating the original.

    The model is pinned explicitly. This test previously read whatever the environment
    happened to hold, and passed alone while failing in the full run: an earlier test
    sets ``GEMINI_MODEL``, ``Config.from_env`` reads it, and the assertion compared that
    leftover against ``DEFAULT_MODEL``. Pinning the value tests the *override behaviour*,
    which is what this is named for, rather than the ambient environment.
    """
    monkeypatch.setenv('GEMINI_MODEL', DEFAULT_MODEL)
    original = Config.from_env(load_env_file=False)
    changed = original.with_overrides(model='other-model')

    assert changed.model == 'other-model'
    assert original.model == DEFAULT_MODEL


def test_unknown_override_is_rejected():
    """A typo in an override must fail loudly rather than be silently ignored."""
    with pytest.raises(TypeError):
        Config.from_env(load_env_file=False, overrides={'modle': 'typo'})


# --- no import-time reads -------------------------------------------------------------

def test_importing_the_backend_modules_does_not_read_the_environment(monkeypatch):
    """Import in a fresh interpreter with a hostile environment.

    A module-level ``os.getenv`` would bake these values in. Instead the modules
    must import cleanly and expose no cached configuration.
    """
    import importlib

    monkeypatch.setenv('GEMINI_MODEL', 'hostile-model')
    monkeypatch.setenv('OUTPUTS_DIR', 'hostile-dir')

    from services import llm_service

    importlib.reload(llm_service)

    assert not hasattr(llm_service, 'GEMINI_MODEL')
    assert not hasattr(llm_service, 'GEMINI_API_KEY')
    # Importing must not have created the hostile directory as a side effect.
    assert not (PROJECT_ROOT / 'hostile-dir').exists()
