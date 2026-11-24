"""Convert a verified v1 private capture into a scoped guidance sidecar.

Use --check for a read-only preview. The archive is data, never executable code.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import yaml

from models.profile import Profile
from services.candidate_guidance import parse_candidate_guidance
from services.profile_store import validate_profile_id
from services.validation import ProfileRules

# These digests identify the original public v1 briefs whose clause boundaries
# were reviewed. Unknown source versions require a new reviewed converter.
CV_SHA256 = "b2151dd15fb228ff568222b28367946e331699568e99c1b2b4d5b0e3e9a197b8"
CL_SHA256 = "3efbbd1b3f957f56982da3489928b4daff28c209de490c7a91acdcf02fb33f0b"
# One-based inclusive ranges, spanning complete clauses in those exact briefs.
CV_RANGES = ((33, 44), (51, 66), (78, 92))
CL_RANGES = ((28, 43), (61, 76), (104, 113))


def _sections(text, expected_hash, ranges):
    if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_hash:
        raise ValueError("Unrecognized archived prompt; manual review is required")
    lines = text.splitlines()
    return ["\n".join(lines[start - 1:end]).strip() for start, end in ranges]


def convert(archive, profile):
    """Return scoped data only; do not interpret any archived source code."""
    if not isinstance(archive, dict) or type(archive.get("version")) is not int or archive["version"] != 1:
        raise ValueError("Expected a version 1 guidance archive")
    effective_rules = json.loads(json.dumps(dataclasses.asdict(ProfileRules.from_profile(profile))))
    if archive.get("effective_validation_rules") != effective_rules:
        raise ValueError("Profile rules no longer match the captured rules")
    try:
        cv = _sections(archive["cv"]["shared_prompt"], CV_SHA256, CV_RANGES)
        letter = _sections(archive["cover_letter"]["shared_prompt"], CL_SHA256, CL_RANGES)
        layout = archive["layout"]["effective_pinned_project_clause"]
        example = archive["layout"]["effective_correction_example"]
    except (KeyError, TypeError) as error:
        raise ValueError("Incomplete guidance archive") from error
    if not isinstance(layout, str) or not isinstance(example, str) or (layout and example.count(layout) != 1):
        raise ValueError("Invalid archived layout clause")
    result = {"version": 1, "cv": cv, "cover_letter": letter,
              "layout": [layout.strip()] if layout.strip() else []}
    parse_candidate_guidance(result)
    return result


def migrate(store: Path, profile_id: str, *, check: bool = False) -> str:
    candidate = validate_profile_id(profile_id)
    store_root = store.resolve()
    profiles = (store / "profiles").resolve()
    if profiles.parent != store_root:
        raise ValueError("Profiles directory must remain inside the selected store")
    directory = profiles / candidate
    if directory.resolve() != directory:
        raise ValueError("Profile directory must not alias another directory")
    profile_path = directory / "profile.yaml"
    archive_path = directory / "candidate_guidance_snapshot.json"
    target = directory / "candidate_guidance.json"
    for path in (profile_path, archive_path, target):
        if path.is_symlink():
            raise ValueError("Profile and guidance files must not be symlinks")
    original_profile = profile_path.read_bytes()
    original_archive = archive_path.read_bytes()
    if len(original_archive) > 1_048_576:
        raise ValueError("Guidance archive is too large")
    raw = yaml.safe_load(original_profile)
    required = {"employers", "banned_tools", "summary_forbidden_verbs", "visa_label",
                "home_countries", "local_permit_countries"}
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), dict) or not required <= raw["rules"].keys():
        raise ValueError("Profile must explicitly declare its captured rules")
    result = convert(json.loads(original_archive), Profile.model_validate(raw))
    content = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() == content:
            return "already installed"
        raise FileExistsError("Different candidate guidance already exists; preserve it")
    if check:
        return "ready"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".candidate-guidance-", suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            out.write(content)
        if temporary.read_bytes() != content:
            raise RuntimeError("Guidance write verification failed")
        if profile_path.read_bytes() != original_profile or archive_path.read_bytes() != original_archive:
            raise RuntimeError("Profile or archive changed during migration")
        try:
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != content:
                raise
            return "already installed"
        return "installed"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print("Candidate guidance " + migrate(args.store, args.profile_id, check=args.check) + ".")


if __name__ == "__main__":
    main()
