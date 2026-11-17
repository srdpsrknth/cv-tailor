"""Opt-in LibreOffice pagination estimates for Word artifacts.

Call only during explicit rendering/inspection, never a passive GUI read. The
original file is copied into a disposable directory and a separate Office user
profile prevents attaching to a running desktop session. All converted PDFs are
removed. LibreOffice pagination is not a Microsoft Word layout guarantee.
"""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        executable = shutil.which(name)
        if executable:
            return executable
    candidates = [
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice",
        Path("/usr/bin/soffice"),
        Path("/usr/local/bin/soffice"),
        Path("/opt/libreoffice/program/soffice"),
    ]
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if os.environ.get(variable):
            candidates.append(
                Path(os.environ[variable]) / "LibreOffice/program/soffice.exe"
            )
    return next((str(path) for path in candidates if path.is_file()), None)


def inspect_word_layout(
    path: str | Path, *, page_limit: int = 2, timeout: float = 60
) -> dict:
    """Return advisory DOCX page count, artifact hash and explicit unchecked state.

    ``page_limit`` applies to this Word artifact's converted PDF, independently of
    the primary LaTeX PDF. Use one for a letter. Missing Office, failed conversion
    and unavailable PDF parsing leave the count and limit result null. No source
    text, subprocess output or filesystem paths are included in warnings.
    """
    path = Path(path)
    report = {
        "page_count": None,
        "engine": None,
        "warnings": [],
        "artifact_sha256": None,
        "page_limit": page_limit,
        "exceeds_page_limit": None,
        "status": "unchecked",
    }
    try:
        source = path.read_bytes()
        report["artifact_sha256"] = hashlib.sha256(source).hexdigest()
    except OSError:
        report["warnings"].append(
            "Word layout unchecked: source artifact could not be read."
        )
        return report
    if path.suffix.lower() != ".docx":
        report["warnings"].append(
            "Word layout unchecked: only DOCX artifacts are supported."
        )
        return report
    executable = _find_soffice()
    if not executable:
        report["warnings"].append("Word layout unchecked: LibreOffice is unavailable.")
        return report
    report["engine"] = "LibreOffice"
    try:
        with TemporaryDirectory(prefix="cvtailor-word-layout-") as temporary:
            work = Path(temporary)
            input_dir = work / "input"
            output_dir = work / "converted"
            input_dir.mkdir()
            output_dir.mkdir()
            local_source = input_dir / path.name
            local_source.write_bytes(source)
            command = [
                executable,
                f'-env:UserInstallation={(work / "office-profile").as_uri()}',
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(local_source),
            ]
            process = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                shell=False,
            )
            if process.returncode:
                report["status"] = "error"
                report["warnings"].append(
                    "Word layout unchecked: LibreOffice conversion failed."
                )
                return report
            converted = output_dir / (path.stem + ".pdf")
            if not converted.is_file():
                report["status"] = "error"
                report["warnings"].append(
                    "Word layout unchecked: conversion produced no PDF."
                )
                return report
            from pypdf import PdfReader

            count = len(PdfReader(converted).pages)
            if not count:
                report["status"] = "error"
                report["warnings"].append(
                    "Word layout unchecked: converted PDF has no pages."
                )
                return report
            report.update(
                page_count=count,
                exceeds_page_limit=count > page_limit,
                status="checked",
            )
    except subprocess.TimeoutExpired:
        report["status"] = "error"
        report["warnings"].append(
            "Word layout unchecked: LibreOffice conversion timed out."
        )
        return report
    except Exception as exc:
        report["status"] = "error"
        report["warnings"].append(
            f"Word layout unchecked: conversion or PDF inspection failed ({type(exc).__name__})."
        )
        return report
    report["warnings"].append(
        "Pagination is a LibreOffice estimate; inspect the intended Word/PDF upload visually."
    )
    if report["exceeds_page_limit"]:
        report["warnings"].append(
            f"Converted Word artifact exceeds its {page_limit}-page limit."
        )
    return report
