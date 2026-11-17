"""Local GUI selection memory. Service/CLI identity resolution remains fail-closed."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from services.profile_store import validate_profile_id


def _path(config):
    return Path(config.store.root) / "preferences" / "gui.json"


def _read(config):
    path = _path(config)
    try:
        if path.stat().st_size > 16_384:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def initial_profile(config, available_ids):
    remembered = _read(config).get("last_profile_id")
    if remembered in available_ids and config.store.exists(remembered):
        return remembered
    if len(available_ids) == 1 and config.store.exists(available_ids[0]):
        return available_ids[0]
    return None


def remember_profile(config, profile_id):
    profile_id = validate_profile_id(profile_id)
    if not config.store.exists(profile_id):
        raise ValueError("Cannot remember an unknown profile.")
    if _read(config).get("last_profile_id") == profile_id:
        return True
    path = _path(config)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump({"last_profile_id": profile_id}, handle)
        temporary.replace(path)
        return True
    except OSError:
        return False
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)
