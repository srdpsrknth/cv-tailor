"""Deterministic measurements and preferences for the primary CV PDF.

These are local layout heuristics, not ATS scores. Occupied height measures the
last glyph within 15mm printable bounds; it does not measure ink coverage. No
extracted personal text is returned or persisted in a report.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import math
import re
from typing import Iterable

PRESETS = (
    dict(name="comfortable", body_size=11, leading=13.2,
         item_spacing=1.5, section_spacing=8),
    dict(name="standard", body_size=10.5, leading=12.6,
         item_spacing=1.5, section_spacing=8),
    dict(name="compact", body_size=10.5, leading=12.2,
         item_spacing=1.5, section_spacing=8),
)

_MARGIN_PT = 15 / 25.4 * 72
_SECTIONS = {
    "professional experience", "education", "certifications", "skills",
    "languages",
}


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _largest_gap(chars: list[dict]) -> float:
    """Merge vertical glyph intervals, including the paired contact block."""
    intervals = sorted((float(c["top"]), float(c["bottom"])) for c in chars)
    end = intervals[0][1]
    gap = 0.0
    for top, bottom in intervals[1:]:
        gap = max(gap, top - end)
        end = max(end, bottom)
    return max(0.0, gap)


def _quality_score(pages: list[dict], splits: int) -> float:
    # A genuine short CV does not need to fill a second page or meet a minimum.
    fullness = 0.0
    imbalance = 0.0
    if len(pages) == 2:
        fractions = [p["used_height_fraction"] for p in pages]
        fullness = sum(
            max(0, 0.75 - value) * 100 + max(0, value - 0.95) * 100
            for value in fractions
        )
        imbalance = abs(fractions[0] - fractions[1]) * 20
    gaps = sum(max(0, p["largest_gap_pt"] - 36) / 12 for p in pages)
    return round(fullness + imbalance + gaps + splits * 3, 6)


def measure_layout(
    path: str | Path,
    *,
    employer_names: Iterable[str] = (),
    project_names: Iterable[tuple[str, str]] = (),
) -> dict:
    """Inspect geometry, page endings and employer/project separation.

    ``project_names`` contains ``(employer_name, project_name)`` pairs. Repeated
    employer names in a project's parenthetical label are not mistaken for role
    headings. Missing, unreadable and text-free PDFs raise instead of passing.
    """
    import pdfplumber

    employer_order = [_normalized(name) for name in employer_names]
    employers = {name for name in employer_order if name}
    employer_counts = Counter(employer_order)
    projects = [(_normalized(employer), _normalized(project))
                for employer, project in project_names if project]
    employer_pages: dict[str, int] = {}
    project_pages: dict[tuple[str, str], int] = {}
    pages = []
    clipping = False
    orphan_headings = False
    with pdfplumber.open(Path(path)) as document:
        if not document.pages:
            raise ValueError("CV PDF contains no pages")
        for index, page in enumerate(document.pages):
            chars = [c for c in page.chars if c["text"].strip()]
            if not chars:
                raise ValueError("CV PDF contains a page without extractable text")
            top = min(float(c["top"]) for c in chars)
            bottom = max(float(c["bottom"]) for c in chars)
            page_clipping = any(
                float(c["x0"]) < -1 or float(c["x1"]) > page.width + 1
                or float(c["top"]) < -1 or float(c["bottom"]) > page.height + 1
                for c in chars
            )
            clipping = clipping or page_clipping
            lines = page.extract_text_lines()
            normalized_lines = [_normalized(line["text"]) for line in lines]
            text = " ".join(normalized_lines)
            # Match complete employer heading lines, not project labels/prose.
            for employer in employers:
                if employer in normalized_lines:
                    employer_pages.setdefault(employer, index)
            for employer, project in projects:
                if project in text:
                    project_pages.setdefault((employer, project), index)
            last = normalized_lines[-1] if normalized_lines else ""
            page_orphan = last in _SECTIONS or last in employers
            if last.startswith("selected projects"):
                page_orphan = True
            orphan_headings = orphan_headings or page_orphan
            printable_height = page.height - 2 * _MARGIN_PT
            pages.append({
                "page": index + 1,
                "top_pt": round(top, 4),
                "bottom_pt": round(bottom, 4),
                "used_height_fraction": round(
                    max(0.0, (bottom - _MARGIN_PT) / printable_height), 6
                ),
                "blank_tail_mm": round(
                    max(0, page.height - _MARGIN_PT - bottom) / 72 * 25.4, 4
                ),
                "largest_gap_pt": round(_largest_gap(chars), 4),
                "line_count": len(lines),
                "word_count": len(page.extract_words()),
                "clipping": page_clipping,
                "orphan_heading": page_orphan,
            })
    split_employers = [
        employer for (employer, _), page in project_pages.items()
        if employer in employer_pages and employer_pages[employer] != page
    ]
    splits = len(split_employers)
    warnings = []
    if len(pages) > 2:
        warnings.append("CV exceeds the two-page limit.")
    if clipping:
        warnings.append("Some text extends outside the physical page.")
    if orphan_headings:
        warnings.append("A page ends with a stranded heading.")
    if len(pages) == 2:
        if any(p["used_height_fraction"] < 0.75 for p in pages):
            warnings.append("A page uses less than 75% of its printable height.")
        if any(p["used_height_fraction"] > 0.95 for p in pages):
            warnings.append("A page uses more than 95% of its printable height.")
    if any(p["largest_gap_pt"] > 36 for p in pages):
        warnings.append("A page contains an internal text gap larger than 36pt.")
    if splits:
        warnings.append("A selected project continues on a different page from its employer heading.")
    return {
        "schema_version": 1,
        "page_count": len(pages),
        "pages": pages,
        "clipping": clipping,
        "orphan_headings": orphan_headings,
        "employer_project_splits": int(splits),
        "split_employer_indices": [
            index for index, employer in enumerate(employer_order)
            if employer in split_employers
        ],
        "second_page_employer_indices": [
            index for index, employer in enumerate(employer_order)
            if employer_pages.get(employer) == 1 and employer_counts[employer] == 1
        ],
        "warnings": warnings,
        "quality_score": _quality_score(pages, int(splits)),
    }


def preview_breaks(report: dict, role_sizes: list[tuple[int, int]]):
    """Try two bounded splits near the natural break of a two-page layout."""
    if report["page_count"] != 2:
        return
    next_roles = report["second_page_employer_indices"]
    split_roles = report["split_employer_indices"]
    # A moving role can provide both a complete bullet and a complete project
    # boundary. If only its projects moved, try a neighboring project boundary.
    if split_roles:
        role_index, project_index = split_roles[0], 1
    elif next_roles:
        role_index, project_index = next_roles[0], 0
    else:
        return
    bullets, projects = role_sizes[role_index]
    if bullets > 1:
        yield role_index, "bullet", 1
    if bullets and projects > project_index:
        yield role_index, "project", project_index


def preview_quality_score(report: dict, *, continued: bool = False) -> float:
    """Add advisory penalties for long tails and explicit role continuations."""
    pages = report["pages"]
    long_tail = max(0, max(page["blank_tail_mm"] for page in pages) - 40) / 4 if len(pages) == 2 else 0
    return round(report["quality_score"] + long_tail + (2 if continued else 0), 6)


def rank_layout(report: dict, preset_index: int = 0) -> tuple:
    """Sortable rank, lower is better; stable input order resolves exact ties.

    A safe <=2-page result always beats overflow or defective output. When every
    result overflows, fewest pages wins so the existing shortening retry receives
    the smallest real page count. Genuine one-page fits beat unnecessary two-page
    alternatives. The preset preference is deliberately weaker than a substantial
    improvement in balance.
    """
    count = report["page_count"]
    if count < 1:
        raise ValueError("Cannot rank a CV with no pages")
    defects = int(bool(report["clipping"])) + int(bool(report["orphan_headings"]))
    # A clean overflow can be shortened by the existing pipeline. A clipped or
    # stranded-heading result cannot be accepted merely because it has 2 pages.
    category = 2 if defects else int(count > 2)
    return (
        category,
        max(0, count - 2),
        defects,
        count if count <= 2 else 2,
        round(float(report["quality_score"]) + preset_index * 0.5, 6),
        preset_index,
    )


def read_layout_metadata(path: str | Path) -> dict | None:
    """Read validated advisory metadata; legacy/malformed files remain unknown.

    Metadata never establishes freshness on its own. The provenance record still
    hashes the actual PDF. Do not expose parser errors, which can contain private
    input text or paths, to the caller or the UI.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(Path(path))
        raw = (reader.metadata or {}).get("/CVLayout")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1_000_000:
            return None
        result = json.loads(raw)
        if not isinstance(result, dict):
            return None
        if type(result.get("schema_version")) is not int or result["schema_version"] != 1:
            return None
        if result.get("preset") not in {p["name"] for p in PRESETS} | {"custom"}:
            return None
        count = result.get("page_count")
        pages = result.get("pages")
        if type(count) is not int or count < 1 or count != len(reader.pages):
            return None
        if not isinstance(pages, list) or len(pages) != count:
            return None
        warnings = result.get("warnings", [])
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            return None
        for key in ("body_size", "leading"):
            value = result.get(key)
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            ):
                return None
        for index, page in enumerate(pages):
            if not isinstance(page, dict):
                return None
            if type(page.get("page")) is not int or page["page"] != index + 1:
                return None
            for key in ("used_height_fraction", "blank_tail_mm", "largest_gap_pt"):
                value = page.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    return None
        return result
    except Exception:
        return None
