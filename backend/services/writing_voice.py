"""Optional private, per-profile prose preferences; never a source of CV facts."""

import json

from services.profile_store import validate_profile_id


def writing_voice_context(config, profile_id):
    if config.profile_path is not None:
        return ""
    candidate = validate_profile_id(profile_id)
    if not config.store.exists(candidate):
        raise ValueError("Writing voice requires a known profile id.")
    path = config.store.profile_path(candidate).with_name("writing_style.json")
    if not path.exists():
        return ""
    try:
        if path.stat().st_size > 16_384 or not path.resolve().is_relative_to(
            config.store.root.resolve()
        ):
            raise ValueError("style file is too large or outside the store")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("expected an object with version 1")
        effective = {}
        for key in ("tone", "sign_off"):
            value = data.get(key, "")
            if not isinstance(value, str) or len(value) > 1000:
                raise ValueError(f"{key} must be short text")
            if value.strip():
                effective[key] = value.strip()
        for key in ("preferences", "avoid"):
            values = data.get(key, [])
            if (
                not isinstance(values, list)
                or len(values) > 20
                or any(not isinstance(v, str) or len(v) > 700 for v in values)
            ):
                raise ValueError(f"{key} must be a list of short text preferences")
            if values:
                effective[key] = values
        if not effective:
            raise ValueError("no prose preferences supplied")
    except (OSError, ValueError) as error:
        raise ValueError(
            f"Cannot load writing_style.json for {candidate}: {error}"
        ) from error
    # Source paths/old letters are audit metadata only. They are not sent to a provider.
    return (
        "\nCANDIDATE WRITING VOICE (style only, not evidence of facts or personal motivations):\n"
        + json.dumps(effective, ensure_ascii=False, sort_keys=True, indent=2)
        + "\nApply these preferences to the cover letter only. Historical reference letters "
        "never override the current BASE PROFILE, factual rules, country requirements or body limits.\n"
    )
