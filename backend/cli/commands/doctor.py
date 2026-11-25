"""``cvtailor doctor`` -- check the local setup and say exactly what to fix.

Extends the checks that used to live in ``scripts/check_setup.py``. Every check
reports a name, a status and -- when it fails -- the command or edit that fixes
it. Nothing here calls a paid API: the API key is checked for *presence*, and
network verification is opt-in via ``--verify-key``.
"""
from __future__ import annotations

import math
import shutil
import sys
from pathlib import Path
from utils.calendar import calendar_zone

from cli.context import CliError, Console
from python_floor import MIN_PYTHON, min_python_text

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
    if tuple(sys.version_info[:2]) < MIN_PYTHON:
        return Check("python", FAIL, version, f"Use Python {min_python_text()} or newer.")
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
    # The interpreter path differs by platform: .venv/bin/python on macOS and
    # Linux, .venv\Scripts\python.exe on Windows. Naming only the Windows one told
    # a Mac user to run a command that cannot exist there.
    interpreter = (r".venv\Scripts\python.exe" if sys.platform == "win32"
                   else ".venv/bin/python")
    return Check(
        "virtualenv", WARN, f"running outside {existing[0]}",
        f"Use the project interpreter: {interpreter} -m cvtailor ...",
    )


def check_store(config) -> Check:
    """Report the private profile store and which profiles it holds.

    A missing ``--profile-id`` is a warning rather than a failure: ``doctor`` is the
    command a caller runs *before* choosing, so refusing to run without an id would
    make the tool unusable exactly when it is needed.
    """
    store = config.store
    ids = store.list_ids()
    scope = "ok" if config.profile_id else "no --profile-id set"
    if not ids:
        return Check(
            "store", WARN, f"{store.root} (empty; {scope})",
            "Create one: cvtailor profile new <id>  "
            "|  migrate: cvtailor profile import <path> --profile-id <id>",
        )
    return Check("store", OK, f"{store.root} ({len(ids)}: {', '.join(ids)}; {scope})")


def check_profile(config) -> Check:
    """Report whether the selected profile loads. Fails closed on a bad id."""
    from services.profile_store import InvalidProfileIdError, UnknownProfileError

    if getattr(config, "profile_path", None):
        path = Path(config.profile_path)
        try:
            profile = config.load_profile()
        except ValueError as error:
            return Check("profile", FAIL, str(error), "Fix the YAML at the path above.")
        except FileNotFoundError:
            return Check("profile", FAIL, f"missing {path}",
                         "Point --profile at an existing profile.yaml.")
        return Check("profile", OK, f"{profile.identity.full_name} (--profile {path.name})")

    try:
        profile = config.load_profile()
    except InvalidProfileIdError as error:
        return Check("profile", WARN, "no profile selected",
                     f"{error} Then run `cvtailor profile list`.")
    except UnknownProfileError as error:
        return Check("profile", FAIL, str(error),
                     "Run `cvtailor profile list` to see the available ids.")
    except ValueError as error:
        return Check("profile", FAIL, str(error), "Fix the YAML at the path above.")
    return Check(
        "profile", OK,
        f"{config.profile_id}: {profile.identity.full_name} ({len(profile.experience)} roles)",
    )


def check_outputs(config) -> Check:
    """Check the writable output locations.

    Since ADR 0011 documents are written into the store, so the *primary* location is
    ``<store>/outputs/<profile_id>``. ``config.outputs_dir`` remains the optional
    mirror. Both are probed, and the message names them, because a failing mirror
    alone should not read as "generation is broken".
    """
    profile_id = getattr(config, "profile_id", None)
    primary = (
        config.store.outputs_dir(profile_id)
        if profile_id
        else config.store.root / "outputs"
    )
    targets = [primary]
    if config.is_mirroring:
        targets.append(Path(config.outputs_dir))

    for directory in targets:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".doctor-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            return Check(
                "outputs", FAIL, f"{directory}: {error}", "Check directory permissions."
            )

    detail = f"store: {primary}"
    if config.is_mirroring:
        detail += f"; mirror: {config.outputs_dir}"
    return Check("outputs", OK, detail)


def check_timezone(name: str = "UTC") -> Check:
    try:
        calendar_zone(name)
    except Exception as error:  # missing tzdata on a bare Windows install
        return Check(
            "timezone", FAIL, str(error),
            "Set CVTAILOR_TIMEZONE to an IANA timezone and install tzdata if needed.",
        )
    return Check("timezone", OK, name)


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
            "Install a TeX distribution (macOS: MacTeX; Windows: MiKTeX or TeX Live; "
            "Linux: TeX Live), or set LATEX_COMPILER to the pdflatex binary.",
        )
    return Check("pdflatex", OK, str(compiler))


def check_fonts(which=shutil.which, run=None) -> "Check | None":
    """Warn (never fail) when the templates' font package is missing from the TeX install.

    Both templates use Carlito (``carlito.sty``) and fall back to Lato. ``kpsewhich``
    reports whether a file is installed; when it is not on PATH the check is skipped.
    """
    import subprocess

    kpsewhich = which("kpsewhich")
    if not kpsewhich:
        return None
    run = run or subprocess.run

    def installed(name: str) -> bool:
        try:
            result = run([kpsewhich, name], capture_output=True, text=True,
                         encoding="utf-8", timeout=30)
        except (OSError, subprocess.SubprocessError):
            return True  # cannot tell; do not warn
        return result.returncode == 0 and bool(result.stdout.strip())

    if installed("carlito.sty"):
        return Check("fonts", OK, "Carlito available")
    fix = "Install the TeX package 'carlito' (tlmgr install carlito, or the MiKTeX package manager)."
    if installed("lato.sty"):
        return Check("fonts", WARN, "Carlito missing; documents fall back to Lato", fix)
    return Check("fonts", WARN, "neither Carlito nor Lato found; documents may fail to compile", fix)


def check_api_key(config, verify: bool = False) -> Check:
    provider = config.provider_name
    env_var = config.provider_key_env
    if not config.has_api_key:
        return Check(
            "api key", FAIL, f"{env_var} is not set",
            f"Add {env_var} to {config.project_root / '.env'} (never commit it).",
        )
    if not verify:
        return Check("api key", OK, f"{provider} key present; model={config.model} (not verified)")

    key = config.require_provider_key()
    fix = f"Check {env_var} in .env and confirm the provider is reachable."
    if provider == "openrouter":
        return _check_openrouter_key(key, fix)

    try:
        from google import genai

        client = genai.Client(api_key=key)
        try:
            client.models.get(model=config.model)
        finally:
            client.close()
    except Exception:
        # Provider exceptions can include credentials or request metadata.
        return Check("api key", FAIL, "Gemini model metadata verification failed",
                     f"{fix} Check the configured Gemini model name.")
    return Check("api key", OK, f"verified with Gemini model metadata; model={config.model}")


def _check_openrouter_key(key: str, fix: str) -> Check:
    from requests import RequestException, get

    try:
        response = get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code != 200:
            return Check("api key", FAIL, f"OpenRouter key check returned HTTP {response.status_code}", fix)
        payload = response.json()
    except (RequestException, ValueError):
        return Check("api key", FAIL, "OpenRouter key metadata verification failed", fix)

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return Check("api key", FAIL, "OpenRouter returned invalid key metadata", fix)

    detail = "verified with OpenRouter key metadata"
    remaining = data.get("limit_remaining")
    if type(remaining) in (int, float) and math.isfinite(remaining):
        detail += f"; key limit remaining: ${remaining:.2f}"
    elif "limit_remaining" in data and remaining is None:
        detail += "; no per-key limit reported"
    return Check("api key", OK, detail)


def run(args, console: Console, config) -> int:
    """Run every check and report. Returns 0 only when nothing failed."""
    root = config.project_root
    checks = [
        check_python(),
        check_venv(root),
        check_store(config),
        check_profile(config),
        check_timezone(config.timezone_name),
        check_templates(root),
        check_pdflatex(),
        check_fonts(),
        check_outputs(config),
        check_api_key(config, verify=getattr(args, "verify_key", False)),
    ]
    checks = [c for c in checks if c is not None]  # a skipped check returns None

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
