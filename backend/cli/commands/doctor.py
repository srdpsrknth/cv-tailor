"""``cvtailor doctor`` -- check the local setup and say exactly what to fix.

Extends the checks that used to live in ``scripts/check_setup.py``. Every check
reports a name, a status and -- when it fails -- the command or edit that fixes
it. Nothing here calls a paid API: the API key is checked for *presence*, and
network verification is opt-in via ``--verify-key``.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from cli.context import CliError, Console

#: (name, status) where status is one of "ok", "warn", "fail".
OK = "ok"
WARN = "warn"
FAIL = "fail"


class Check:
    def __init__(self, name: str, status: str, detail: str = "", fix: str = ""):
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix

    def as_dict(self) -> dict:
        return {"check": self.name, "status": self.status,
                "detail": self.detail, "fix": self.fix}


def check_python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < (3, 10):
        return Check("python", FAIL, version, "Use Python 3.10 or newer.")
    return Check("python", OK, version)


def check_venv(root: Path) -> Check:
    """Report whether the interpreter running this is the project's venv."""
    venv_markers = [root / ".venv", root / "venv"]
    existing = [p for p in venv_markers if p.is_dir()]
    if not existing:
        return Check(
            "virtualenv", WARN, "no .venv in the project",
            "Create one: python -m venv .venv",
        )
    # sys.prefix points inside the venv when it is active.
    inside = any(str(sys.prefix).startswith(str(p)) for p in existing)
    if inside:
        return Check("virtualenv", OK, str(existing[0]))
    return Check(
        "virtualenv", WARN, f"running outside {existing[0]}",
        r"Use the project interpreter: .venv\Scripts\python.exe -m cvtailor ...",
    )


def check_profile(config) -> Check:
    from services.profile_loader import load_profile

    path = Path(config.profile_path)
    if not path.exists():
        return Check(
            "profile", FAIL, f"missing {path}",
            "Create storage/profile/profile.yaml (see docs/DEVELOPMENT.md).",
        )
    try:
        profile = load_profile(str(path))
    except ValueError as error:
        return Check("profile", FAIL, str(error), "Fix the YAML at the path above.")
    return Check("profile", OK, f"{profile.identity.full_name} ({len(profile.experience)} roles)")


def check_outputs(config) -> Check:
    directory = Path(config.outputs_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return Check("outputs", FAIL, f"{directory}: {error}", "Check directory permissions.")
    scope = "mirror configured" if config.is_mirroring else "default"
    return Check("outputs", OK, f"{directory} ({scope})")


def check_timezone() -> Check:
    try:
        ZoneInfo("Europe/Berlin")
    except Exception as error:  # missing tzdata on a bare Windows install
        return Check(
            "timezone", FAIL, str(error),
            "Install the timezone data: pip install tzdata",
        )
    return Check("timezone", OK, "Europe/Berlin")


def check_templates(root: Path) -> Check:
    cv_template = root / "templates" / "cv" / "main.tex.jinja2"
    cl_template = root / "cover_letter_latex_template" / "setup" / "preamble.tex"
    missing = [str(p) for p in (cv_template, cl_template) if not p.exists()]
    if missing:
        return Check("templates", FAIL, "missing: " + ", ".join(missing),
                     "Restore the template files from version control.")
    return Check("templates", OK, "CV and cover-letter templates present")


def check_pdflatex() -> Check:
    try:
        from renderers.latex_renderer import LaTeXRenderer

        compiler = LaTeXRenderer(outputs_dir=str(Path.cwd()))._resolve_pdflatex_path()
    except Exception as error:
        return Check(
            "pdflatex", FAIL, str(error),
            "Install MiKTeX or TeX Live, or set LATEX_COMPILER to the binary.",
        )
    return Check("pdflatex", OK, str(compiler))


def check_api_key(config, verify: bool = False) -> Check:
    if not config.has_api_key:
        return Check(
            "api key", FAIL, "GEMINI_API_KEY is not set",
            f"Add GEMINI_API_KEY to {config.project_root / '.env'} (never commit it).",
        )
    if not verify:
        return Check("api key", OK, f"present; model={config.model} (not verified)")
    # Opt-in live check. This is the only code path that may contact Google.
    try:
        from google import genai

        client = genai.Client(api_key=config.api_key)
        client.models.generate_content(model=config.model, contents="ping")
    except Exception as error:
        return Check("api key", FAIL, f"rejected by Google: {error}",
                     "Check the key and GEMINI_MODEL in .env.")
    return Check("api key", OK, f"verified against Google; model={config.model}")


def run(args, console: Console, config) -> int:
    """Run every check and report. Returns 0 only when nothing failed."""
    root = config.project_root
    checks = [
        check_python(),
        check_venv(root),
        check_profile(config),
        check_timezone(),
        check_templates(root),
        check_pdflatex(),
        check_outputs(config),
        check_api_key(config, verify=getattr(args, "verify_key", False)),
    ]

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]

    if console.as_json:
        console.json({
            "ok": not failed,
            "failed": len(failed),
            "warnings": len(warned),
            "checks": [c.as_dict() for c in checks],
        })
        return 1 if failed else 0

    symbols = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}
    for check in checks:
        console.out(f"[{symbols[check.status]}] {check.name:<12} {check.detail}")
        if check.fix and check.status != OK:
            console.out(f"         -> {check.fix}")

    console.out("")
    if failed:
        console.out(f"{len(failed)} check(s) failed. Fix the items marked FAIL above.")
        return 1
    if warned:
        console.out(f"All required checks passed ({len(warned)} warning(s)).")
        return 0
    console.out("Everything looks good.")
    return 0
