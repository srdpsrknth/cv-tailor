"""``cvtailor render`` -- re-render a saved ``content.json`` with no LLM call.

This is the deterministic, zero-cost revision path. It reproduces what
``scripts/render_application.py`` does, exposed as a subcommand.
"""
from __future__ import annotations

import json
from pathlib import Path

from cli.context import CliError, Console, EXIT_NOT_FOUND, EXIT_USAGE, human_pages
from services.profile_store import resolve_profile_id


def _load_file(path: Path):
    from services.profile_loader import load_profile

    return load_profile(str(path))


def find_content(explicit, config) -> Path:
    """Resolve the ``content.json`` to render, or explain how to point at it."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise CliError(f"content.json not found: {path}", EXIT_NOT_FOUND)
        if path.parent.name != "source":
            raise CliError(
                f"Keep editable content at <application>/source/content.json, not {path}",
                EXIT_NOT_FOUND,
            )
        return path

    # Fall back to the most recently modified saved application for this candidate.
    # Since ADR 0011 the documents live in the store, under a candidate segment, so a
    # single ``*/source`` glob against the repository's outputs/ finds nothing.
    profile_id = resolve_profile_id(config)
    candidates = sorted(
        config.store.outputs_dir(profile_id).glob("*/source/content.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise CliError(
            f"No saved applications for {profile_id!r} under "
            f"{config.store.outputs_dir(profile_id)}",
            EXIT_NOT_FOUND,
            hint=(
                "Pass --content <application>/source/content.json. Note that a job "
                "folder without source/content.json (a partial or pre-Phase-2 folder) "
                "has no editable text to render."
            ),
        )
    return candidates[0]


def run(args, console: Console, config) -> int:
    from models.tailored_output import TailoredCV, TailoredCoverLetter
    from renderers import create_latex_renderer, create_docx_renderer
    from services.profile_store import (
        InvalidProfileIdError,
        UnknownProfileError,
    )

    content_path = find_content(getattr(args, "content", None), config)
    folder = content_path.parent.parent

    # The profile comes from the store (or from an explicit --profile file), never
    # from a hardcoded path: the real profile no longer lives in the repository.
    explicit = getattr(args, "profile_path", None)
    profile_id = None
    if explicit:
        profile_path = Path(explicit)
        if not profile_path.exists():
            raise CliError(f"Profile not found: {profile_path}", EXIT_NOT_FOUND)
        loader = lambda: _load_file(profile_path)  # noqa: E731
    else:
        try:
            profile_id = config.require_profile_id()
        except InvalidProfileIdError as error:
            raise CliError(str(error), EXIT_USAGE,
                           hint="Pass --profile-id <id>, or --profile <path>.")
        loader = lambda: config.store.load(profile_id)  # noqa: E731

    try:
        data = json.loads(content_path.read_text(encoding="utf-8-sig"))
        profile = loader()
        cv = TailoredCV.model_validate(data["cv"])
        cl = TailoredCoverLetter.model_validate(data["cover_letter"])
    except UnknownProfileError as error:
        raise CliError(str(error), EXIT_NOT_FOUND,
                       hint="Run `cvtailor profile list` to see the available ids.")
    except KeyError as error:
        raise CliError(f"content.json is missing the {error} document", EXIT_NOT_FOUND)
    except (ValueError, OSError) as error:
        raise CliError(f"Could not read {content_path}: {error}", EXIT_NOT_FOUND)

    role = data.get("role_title") or cl.role_title
    only = getattr(args, "only", None)
    result = {"content": str(content_path), "folder": str(folder), "job_id": folder.name}
    generated = []

    if only != "cover-letter":
        renderer = create_latex_renderer(outputs_dir=str(folder))
        pdf = Path(renderer.render_cv(cv, profile, job_position=role))
        pages = _count(pdf)
        result.update(cv_path=str(pdf), cv_pages=pages)
        generated.append(pdf)
        console.out(f"CV:            {human_pages(pages)}  {pdf}")
        if pages > 2:
            console.warn(
                f"CV is {pages} pages; the target is two. "
                "Shorten content in content.json and render again."
            )

    if only != "cv":
        docx, pdf = create_docx_renderer(outputs_dir=str(folder)).render_cover_letter(
            cl, profile, job_position=role
        )
        words = sum(len(p.split()) for p in cl.paragraphs)
        result.update(cover_letter_path=str(docx), cover_letter_body_words=words)
        generated.append(Path(docx))
        console.out(f"Cover letter:  {len(cl.paragraphs)} paragraphs, {words} words  {docx}")
        if pdf:
            pages = _count(Path(pdf))
            result.update(cl_pdf_path=str(pdf), cover_letter_pdf_pages=pages)
            generated.append(Path(pdf))
            console.out(f"Cover PDF:     {human_pages(pages)}  {pdf}")
            if pages != 1:
                console.warn(f"Cover letter is {pages} pages; the target is one.")
        if len(cl.paragraphs) != 4 or not 290 <= words <= 310:
            console.warn("Cover letter target is four paragraphs of 290-310 words.")

    _update_manifest(content_path.parent / "generation_result.json", result, folder)

    if getattr(args, "mirror_configured", False):
        _mirror(console, config, folder, generated)

    if console.as_json:
        console.json(result)
    return 0


def _count(pdf_path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_path)).pages)


def _update_manifest(path: Path, result: dict, folder: Path) -> None:
    """Refresh the manifest the same way the render script does."""
    manifest = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    manifest.update({k: v for k, v in result.items() if k not in ("content", "folder")})
    manifest.setdefault("job_id", folder.name)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _mirror(console: Console, config, folder: Path, generated: list) -> None:
    """Copy artifacts to the configured mirror directory (A-10)."""
    import shutil

    if not config.is_mirroring:
        console.warn("--mirror-configured was given but OUTPUTS_DIR is not set.")
        return
    destination = Path(config.outputs_dir) / folder.name
    if destination.resolve() == folder.resolve():
        return

    console.out("")
    console.out(f"Mirroring to {destination}")
    console.out(f"  source: OUTPUTS_DIR in {config.project_root / '.env'}")
    # ADR 0007 rule 6: confirm before anything that writes outside the job folder,
    # showing the resolved path. Skipped automatically in scripts and --json use.
    if _is_interactive() and not getattr(_mirror, "_assume_yes", False):
        answer = input("  Copy there? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            console.warn("Mirroring skipped.")
            return
    destination.mkdir(parents=True, exist_ok=True)
    for artifact in generated:
        shutil.copy2(artifact, destination / artifact.name)
    manifest = folder / "generation_result.json"
    if manifest.exists():
        shutil.copy2(manifest, destination / manifest.name)


def _is_interactive() -> bool:
    import sys

    return sys.stdin is not None and sys.stdin.isatty()
