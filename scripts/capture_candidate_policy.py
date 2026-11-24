"""Privately capture the current candidate policy before shared-default removal.

Run from the checkout: python scripts/capture_candidate_policy.py --store PATH --profile-id ID
The sidecar is an archive for a later migration; the generator does not read it.
"""
from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import yaml
from models.profile import Profile
from services.profile_store import validate_profile_id
from services import prompts
from services.validation import ProfileRules


def capture(store: Path, profile_id: str) -> None:
    candidate = validate_profile_id(profile_id)
    directory = (store / "profiles" / candidate).resolve()
    if not directory.is_relative_to(store.resolve() / "profiles"):
        raise ValueError("Profile directory is outside the store")
    profile_path = directory / "profile.yaml"
    voice_path = directory / "writing_style.json"
    sidecar_path = directory / "candidate_guidance_snapshot.json"
    if sidecar_path.exists():
        raise FileExistsError("Guidance snapshot already exists; preserve and review it")
    original = profile_path.read_bytes()
    voice_original = voice_path.read_bytes() if voice_path.is_file() else None
    raw = yaml.safe_load(original)
    profile = Profile.model_validate(raw)
    rules = ProfileRules.from_profile(profile)
    # Prevent a later schema default change from silently changing current rules.
    required = {"employers", "banned_tools", "summary_forbidden_verbs", "visa_label",
                "home_countries", "local_permit_countries"}
    if not isinstance(raw.get("rules"), dict) or not required <= raw["rules"].keys():
        raise ValueError("Profile does not explicitly declare all required rules; manual migration needed")
    guidance = {
        "version": 1,
        "purpose": "Archive of current effective inputs; not read by generation",
        "effective_validation_rules": dataclasses.asdict(rules),
        "cv": {"shared_prompt": prompts.PROMPT_CV_PATH.read_text(encoding="utf-8"),
               "editorial_requirements": prompts.EDITORIAL_REQUIREMENTS},
        "cover_letter": {"shared_prompt": prompts.PROMPT_CL_PATH.read_text(encoding="utf-8"),
                         "voice_file_present": voice_original is not None},
        "shared_context": {"build_context_function": inspect.getsource(prompts.build_context)},
        "layout": {"correction_function": inspect.getsource(prompts.layout_correction_instruction),
                   "pinned_project_function": inspect.getsource(prompts.pinned_project_clause),
                   "effective_pinned_project_clause": prompts.pinned_project_clause(rules),
                   "effective_correction_example": prompts.layout_correction_instruction(3, 650, rules),
                   "retry_function": inspect.getsource(prompts.layout_retry_instruction)},
    }
    guidance = json.loads(json.dumps(guidance, ensure_ascii=False))
    # A new directory provides a no-overwrite backup of both existing private files.
    backup = directory / ("before-candidate-isolation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir()
    shutil.copy2(profile_path, backup / profile_path.name)
    if voice_original is not None:
        shutil.copy2(voice_path, backup / voice_path.name)
    if (backup / profile_path.name).read_bytes() != original:
        raise RuntimeError("Profile backup verification failed")
    if voice_original is not None and (backup / voice_path.name).read_bytes() != voice_original:
        raise RuntimeError("Voice backup verification failed")
    # Publish only a completely written and verified snapshot, without overwriting a
    # concurrent capture. A failed attempt removes only its own temporary file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=directory, prefix=".candidate-guidance-",
                                         suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            json.dump(guidance, out, ensure_ascii=False, indent=2)
            out.write("\n")
        if json.loads(temporary.read_text(encoding="utf-8")) != guidance:
            raise RuntimeError("Guidance verification failed")
        current_voice = voice_path.read_bytes() if voice_path.is_file() else None
        if profile_path.read_bytes() != original or current_voice != voice_original:
            raise RuntimeError("Profile or voice changed during capture")
        if os.name == "nt":
            os.rename(temporary, sidecar_path)
        else:
            os.link(temporary, sidecar_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    args = parser.parse_args()
    capture(args.store, args.profile_id)
    print("Private profile and voice backed up; guidance captured and verified.")


if __name__ == "__main__":
    main()
