"""The Gemini SDK is optional: OpenRouter (the default) must work without it."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = textwrap.dedent(
    """
    import sys

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "google" or name.startswith("google."):
                raise ImportError("google is blocked for this test")
            return None

    sys.meta_path.insert(0, _Block())
    sys.path.insert(0, {backend!r})

    from services import provider
    from services.provider import OpenRouterProvider, build_provider, ProviderError
    import requests

    class _Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {{"choices": [{{"message": {{"content": "ok"}}}}],
                    "usage": {{"prompt_tokens": 1, "completion_tokens": 2}}}}

    requests.post = lambda *a, **k: _Response()

    class Cfg:
        provider = None  # falls back to the configured default (openrouter)
        openrouter_api_key = "k"
        model = "vendor/model"

    built = build_provider(Cfg())
    assert isinstance(built, OpenRouterProvider), type(built)
    assert built.generate("hi").text == "ok"

    Cfg.provider = "gemini"
    Cfg.api_key = "g"
    try:
        build_provider(Cfg())
    except ProviderError as error:
        assert "google-genai" in str(error)
    else:
        raise SystemExit("gemini should fail clearly without google-genai")
    print("OK")
    """
)


def test_openrouter_path_works_when_google_is_not_importable():
    script = _SCRIPT.format(backend=str(ROOT / "backend"))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("OK")


def test_unset_provider_uses_the_configured_default(monkeypatch):
    from config import DEFAULT_PROVIDER
    from services.provider import OpenRouterProvider, build_provider

    assert DEFAULT_PROVIDER == "openrouter"
    config = SimpleNamespace(provider=None, openrouter_api_key="k", model="vendor/model")
    assert isinstance(build_provider(config), OpenRouterProvider)


def test_load_profile_requires_an_explicit_path():
    import pytest
    from services.profile_loader import load_profile

    with pytest.raises(ValueError, match="explicit profile path"):
        load_profile(None)
    with pytest.raises(TypeError):
        load_profile()  # type: ignore[call-arg]
