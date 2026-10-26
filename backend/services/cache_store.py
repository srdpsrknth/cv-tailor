"""The validated-generation cache (Phase 3, item 5).

Re-running one profile against the same posting re-drafted the documents from
scratch and paid for them again. Rendering was already free -- ``content.json``
plus ``render_application.py`` makes a *revision* cost zero LLM calls -- so this
module extends that principle one step earlier: a generation that was **validated**
is stored, and an identical one is served from disk instead of bought twice.

Four rules make this safe, and every one of them is enforced here rather than
promised:

1. **The key is the bytes the model was shown** -- the serialized profile, the job
   description plus the company/role/country context, and the prompt and schema
   version -- not a ``job_id`` or a timestamp. Two runs that differ in any prompt
   byte cannot share an entry, so a prompt change cannot silently serve a stale
   document. ``job_id`` is deliberately *not* part of the key: it embeds a
   millisecond timestamp, so keying on it would guarantee a miss every time.
2. **Only a validated result is stored.** ``tailor_service`` writes an entry after
   the page-count gate has passed, so a draft that failed the gate can never become
   a permanent answer.
3. **It is derived data in the private store** (ADR 0011), under
   ``<store>/cache/<profile_id>/``, and it is **always safe to delete**: losing it
   costs a regeneration, never a document. Every read failure therefore falls back
   to generating rather than raising.
4. **It never carries a document's text into a log or a prompt.** The entry holds
   the accepted documents, because the accepted documents are what is being reused.

``profile_id`` is a required argument and is validated, so two candidates can never
read each other's entries (ADR 0003).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from services.profile_store import validate_profile_id

logger = logging.getLogger(__name__)

#: Schema version of the **cache file format** itself. It is separate from the
#: prompt/schema version in the key because the two answers are different: a prompt
#: edit changes what the model is asked, while this changes how an answer is stored.
#: Bumping it invalidates every entry without touching the prompts.
CACHE_FORMAT_VERSION = 1

#: Directory ``<store>/cache/<profile_id>/generations/`` holds one JSON file per key.
GENERATIONS_DIRNAME = "generations"


def serialize_profile_bytes(profile) -> str:
    """The profile exactly as it is shown to the model, as text.

    Both the prompt context and the cache key are derived from **this one string**,
    so the two cannot drift: if the bytes sent to the model ever stopped matching
    the bytes that were hashed, a prompt change could be served from cache without
    anyone noticing. One string, computed once per application, hashed and emitted.

    Phase 3, item 4 made this a single stable block per run, which is what makes it
    keyable at all; this function is that decision's shared accessor.
    """
    return profile.model_dump_json(indent=2)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(
    *,
    profile_bytes: str,
    job_description: str,
    company_name: Optional[str],
    role_title: Optional[str],
    work_country: Optional[str],
    prompt_cv: str,
    prompt_cl: str,
    prompt_version: str,
    schema_version: str,
    provider: str,
    model_cv: str,
    model_cl: str,
    rules_fingerprint: str,
    format_version: int = CACHE_FORMAT_VERSION,
) -> str:
    """The identity of one generation: everything that can change its bytes.

    Each ingredient is hashed with its **name** attached, so a value cannot be
    shifted between fields to produce the same digest. ``job_id`` and any timestamp
    are deliberately absent -- see the module docstring.

    ``model_cv``/``model_cl`` are both present because item 6 added model-per-task
    routing: one posting can be drafted by two different models, and a cache that
    knew only "the model" would serve one route's documents for the other's.
    """
    payload = {
        "format_version": format_version,
        "profile": profile_bytes,
        "job_description": job_description,
        "company_name": company_name or "",
        "role_title": role_title or "",
        "work_country": work_country or "",
        "prompt_cv": prompt_cv,
        "prompt_cl": prompt_cl,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "provider": provider,
        "model_cv": model_cv,
        "model_cl": model_cl,
        #: What the profile's *rules* resolve to, which is not part of the profile
        #: bytes: a rules edit changes validation and the retry brief without
        #: changing the profile block that was sent.
        "rules": rules_fingerprint,
    }
    return _digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def rules_fingerprint(rules) -> str:
    """A stable digest of the resolved ``ProfileRules``.

    Comparison is done here rather than in a validator because rules are data
    (A-1): two candidate profiles legitimately declare different rules, and the
    cache has to notice when one candidate's rules change.
    """
    return _digest(json.dumps({
        "special_employers": getattr(rules, "special_employers", {}) or {},
        "banned_tools": list(getattr(rules, "banned_tools", ()) or ()),
        "summary_forbidden_verbs": getattr(rules, "summary_forbidden_verbs", None),
        "visa_label": getattr(rules, "visa_label", None),
        "home_countries": list(getattr(rules, "home_countries", ()) or ()),
        "local_permit_countries": list(getattr(rules, "local_permit_countries", ()) or ()),
    }, sort_keys=True, ensure_ascii=False))


@dataclass(frozen=True)
class CacheEntry:
    """One stored generation: the accepted documents and how they were produced."""

    key: str
    cv: dict
    cover_letter: dict
    tailoring_explanation: Optional[dict]
    #: The model's responses, verbatim, in the order they were received. Restored so
    #: the job folder of a cache hit carries the same ``drafts.json`` audit trail a
    #: fresh run would have written.
    drafts: list
    usage: dict
    created_at: str
    provider: str
    models: dict

    @property
    def token_usage(self) -> dict:
        """Token usage for a **cache hit**.

        A hit makes no API call, so the honest figure is zero, not the number of
        tokens the original run spent. Reporting the original's totals would put a
        cost on a run that did not incur it.
        """
        return {
            "cv_input_tokens": 0,
            "cv_output_tokens": 0,
            "cl_input_tokens": 0,
            "cl_output_tokens": 0,
            "cv_attempts": 0,
            "cl_attempts": 0,
        }

    def to_json(self) -> dict:
        return {
            "format_version": CACHE_FORMAT_VERSION,
            "key": self.key,
            "created_at": self.created_at,
            "provider": self.provider,
            "models": self.models,
            "cv": self.cv,
            "cover_letter": self.cover_letter,
            "tailoring_explanation": self.tailoring_explanation,
            "drafts": self.drafts,
            "original_usage": self.usage,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "CacheEntry":
        """Rebuild an entry, or raise ``ValueError`` on anything unexpected.

        Every field the pipeline needs is required. A half-written entry -- a crash
        between the ``mkdir`` and the ``write_text`` is impossible because the write
        is atomic, but a hand-edited or truncated file is not -- must fail here and
        be treated as a miss by :meth:`GenerationCache.get` rather than reaching the
        pipeline as a partially restored document.
        """
        if not isinstance(payload, dict):
            raise ValueError("cache entry is not an object")
        if payload.get("format_version") != CACHE_FORMAT_VERSION:
            raise ValueError(
                f"cache entry format {payload.get('format_version')!r} is not "
                f"{CACHE_FORMAT_VERSION}"
            )
        cv = payload.get("cv")
        cover_letter = payload.get("cover_letter")
        if not isinstance(cv, dict) or not isinstance(cover_letter, dict):
            raise ValueError("cache entry is missing a document")
        return cls(
            key=payload.get("key") or "",
            cv=cv,
            cover_letter=cover_letter,
            tailoring_explanation=payload.get("tailoring_explanation"),
            drafts=payload.get("drafts") or [],
            usage=payload.get("original_usage") or {},
            created_at=payload.get("created_at") or "",
            provider=payload.get("provider") or "",
            models=payload.get("models") or {},
        )


class GenerationCache:
    """Reads and writes validated generations under one candidate's cache dir.

    Failures are a miss, never an error. The cache is an optimisation sitting on the
    generation path, so a full disk, a permission problem or a corrupt entry must
    degrade to "generate it again" -- which is what the tool did before this module
    existed -- rather than breaking a run that would otherwise have succeeded.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    @classmethod
    def at(cls, store_root: Path, profile_id) -> "GenerationCache":
        """The cache for one candidate, inside the store's ``cache/`` tree."""
        return cls(Path(store_root) / "cache" / validate_profile_id(profile_id))

    @property
    def generations_dir(self) -> Path:
        return self.root / GENERATIONS_DIRNAME

    #: A key is a SHA-256 digest: exactly this many lowercase hex characters. The
    #: length matters as much as the alphabet -- a truncated key would silently share
    #: a filename space with a short key rather than being rejected.
    KEY_LENGTH = 64

    def path_for(self, key: str) -> Path:
        if (
            not isinstance(key, str)
            or len(key) != self.KEY_LENGTH
            or any(character not in "0123456789abcdef" for character in key)
        ):
            raise ValueError(
                f"refusing to use {key!r} as a cache filename: a key is a "
                f"{self.KEY_LENGTH}-character lowercase hex digest"
            )
        return self.generations_dir / f"{key}.json"

    # --- reading ----------------------------------------------------------------------

    def get(self, key: str) -> Optional[CacheEntry]:
        """The stored entry for ``key``, or ``None``.

        ``None`` means "generate it" and covers every failure: no entry, a malformed
        entry, an entry from a different format version, an unreadable file. Nothing
        on this path raises, because a cache that can break a run is worse than no
        cache at all.
        """
        try:
            path = self.path_for(key)
        except ValueError:
            logger.warning("Ignoring an unusable cache key.")
            return None
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return CacheEntry.from_json(payload)
        except (OSError, ValueError) as error:
            logger.warning("Ignoring an unreadable cache entry %s: %s", path.name, error)
            return None

    # --- writing ----------------------------------------------------------------------

    def put(self, key: str, entry: CacheEntry) -> Optional[Path]:
        """Store ``entry``, returning its path, or ``None`` if it could not be stored.

        Written to a temporary file and then moved into place, so a crash mid-write
        cannot leave a half-written entry that a later run would read as valid.
        """
        try:
            path = self.path_for(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(entry.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(path)
            return path
        except (OSError, ValueError) as error:
            logger.warning("Could not store a cache entry: %s", error)
            return None

    # --- inspection -------------------------------------------------------------------

    def keys(self) -> list:
        """Every stored key, sorted. Empty when nothing has been cached yet."""
        if not self.generations_dir.is_dir():
            return []
        return sorted(path.stem for path in self.generations_dir.glob("*.json"))

    def count(self) -> int:
        return len(self.keys())
