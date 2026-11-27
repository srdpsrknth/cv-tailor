"""Load optional, private drafting guidance for one selected store profile.

This loader is intentionally separate from writing voice: guidance may describe
candidate-specific factual constraints and must not be inferred from old letters.
Generation uses the cv, cover_letter and layout lists in the matching prompts,
and the optional acronyms list in rendering and validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from services.profile_store import validate_profile_id


@dataclass(frozen=True)
class CandidateGuidance:
    """Version 1 guidance, separated by the call on which it may be used."""

    cv: tuple[str, ...] = ()
    cover_letter: tuple[str, ...] = ()
    layout: tuple[str, ...] = ()
    #: Extra upper-case acronyms for this candidate's skill headings (render only).
    acronyms: tuple[str, ...] = ()


def parse_candidate_guidance(data) -> CandidateGuidance:
    """Validate a decoded versioned sidecar for loading or migration."""
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("expected an object with version 1")
    keys = {"version", "cv", "cover_letter", "layout", "acronyms"}
    if data.keys() - keys:
        raise ValueError("unknown guidance fields")
    fields = {}
    for key in ("cv", "cover_letter", "layout"):
        values = data.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 20
            or any(not isinstance(value, str) or not value.strip() or len(value) > 2000 for value in values)
        ):
            raise ValueError(f"{key} must be a list of up to 20 non-empty short strings")
        fields[key] = tuple(value.strip() for value in values)
    acronyms = data.get("acronyms", [])
    if (
        not isinstance(acronyms, list)
        or len(acronyms) > 100
        or any(not isinstance(value, str) or not value.strip() or len(value.strip()) > 32
               or len(value.split()) != 1 for value in acronyms)
    ):
        raise ValueError("acronyms must be a list of up to 100 single words of at most 32 characters")
    fields["acronyms"] = tuple(dict.fromkeys(value.strip() for value in acronyms))
    return CandidateGuidance(**fields)


def load_candidate_guidance(config, profile_id) -> CandidateGuidance:
    """Read guidance for the selected store profile, failing closed if invalid.

    A loose profile has no store-scoped sidecar, even when the path happens to
    point into a store. An absent sidecar represents no additional guidance.
    """
    if config.profile_path is not None:
        return CandidateGuidance()
    candidate = validate_profile_id(profile_id)
    if not config.store.exists(candidate):
        raise ValueError("Candidate guidance requires a known profile id.")
    directory = config.store.profile_path(candidate).parent
    path = directory / "candidate_guidance.json"
    if not path.exists() and not path.is_symlink():
        return CandidateGuidance()
    try:
        if (
            path.is_symlink()
            or directory.resolve() != (config.store.root / "profiles").resolve() / candidate
            or path.resolve().parent != directory.resolve()
            or path.stat().st_size > 65_536
        ):
            raise ValueError("guidance file is too large or outside the selected profile")
        data = json.loads(path.read_text(encoding="utf-8"))
        return parse_candidate_guidance(data)
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"Cannot load candidate_guidance.json for {candidate}: {error}") from error


def load_candidate_acronyms(config, profile_id) -> tuple[str, ...]:
    """The candidate's extra skill-heading acronyms for a render.

    Re-rendering a saved application works from its profile snapshot, so a profile that
    is no longer in the store simply has no extra acronyms; a malformed guidance file
    still fails closed.
    """
    if config.profile_path is None and not config.store.exists(validate_profile_id(profile_id)):
        return ()
    return load_candidate_guidance(config, profile_id).acronyms
