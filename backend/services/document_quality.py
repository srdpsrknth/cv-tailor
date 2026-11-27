"""Read-only PDF extraction diagnostics, not an ATS score or upload guarantee.

Both engines use their normal extraction settings independently. Word retention
uses a case-insensitive NFKC token multiset, so missing repeated words and merged
words reduce retention. Paragraph order is checked only when every supplied
paragraph survives as a contiguous token sequence. No OCR or layout inference is
attempted for extraction retention. The separate CV bullet check uses PDF
positions and includes short excerpts so reviewers can find flagged bullets.
"""

from collections import Counter
from pathlib import Path
import re
from typing import Mapping, Sequence
import unicodedata


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def _position(tokens: list[str], phrase: list[str], start: int = 0) -> int:
    if not phrase:
        return -1
    for index in range(start, len(tokens) - len(phrase) + 1):
        if tokens[index : index + len(phrase)] == phrase:
            return index
    return -1


def _compare_text(
    text: str, paragraphs: Sequence[str], fields: Mapping[str, str]
) -> dict:
    tokens = _tokens(text)
    expected = Counter(word for paragraph in paragraphs for word in _tokens(paragraph))
    total = sum(expected.values())
    retained = sum((Counter(tokens) & expected).values())
    # Empty source fields are uncheckable, rather than automatically present.
    missing = [
        label
        for label, value in fields.items()
        if not _tokens(value) or _position(tokens, _tokens(value)) < 0
    ]
    suspicious = sorted(
        {
            f"U+{ord(char):04X}"
            for char in text
            if char == "\ufffd"
            or unicodedata.category(char) in {"Co", "Cs"}
            or (unicodedata.category(char) == "Cf" and char != "\u00ad")
        }
    )
    warnings = []
    if total and retained < total:
        warnings.append(
            "Some normalized source words are missing or merged in extraction."
        )
    if missing:
        warnings.append("Some expected fields are missing or fragmented in extraction.")
    if suspicious:
        warnings.append(
            "Unexpected replacement, private-use or invisible glyphs were extracted."
        )
    if not tokens:
        warnings.append(
            "No extractable words were found; image-only PDFs require separate review."
        )
    phrases = [_tokens(paragraph) for paragraph in paragraphs if _tokens(paragraph)]
    order = None
    if phrases:
        if all(_position(tokens, phrase) >= 0 for phrase in phrases):
            cursor = 0
            order = True
            for phrase in phrases:
                position = _position(tokens, phrase, cursor)
                if position < 0:
                    order = False
                    break
                cursor = position + len(phrase)
            if not order:
                warnings.append("Source paragraph order differs from extraction.")
        else:
            warnings.append(
                "Paragraph order could not be checked because source phrases are missing."
            )
    return {
        "word_retention": retained / total if total else None,
        "expected_word_count": total if total else None,
        "retained_word_count": retained if total else None,
        "missing_fields": missing if fields else None,
        "suspicious_glyphs": suspicious,
        "reading_order": order,
        "warnings": warnings,
    }


def _extract_pypdf(path: Path) -> tuple[int, str]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return len(reader.pages), "\n".join(
        page.extract_text() or "" for page in reader.pages
    )


def _extract_pdfplumber(path: Path) -> tuple[int, str]:
    import pdfplumber

    with pdfplumber.open(path) as document:
        return len(document.pages), "\n".join(
            page.extract_text() or "" for page in document.pages
        )


def inspect_cv_bullets(path: str | Path) -> dict:
    """Find bullets of three or more drawn lines in the single-column CV PDF."""
    bullets = []
    current = None
    try:
        import pdfplumber

        with pdfplumber.open(path) as document:
            for page in document.pages:
                for line in page.extract_text_lines():
                    chars = [char for char in line["chars"] if char["text"].strip()]
                    if not chars:
                        continue
                    if chars[0]["text"] == "\u2022" and len(chars) > 1:
                        # Wrapped lines align with the text, while the marker and
                        # unindented headings are further left. Allow rounding
                        # and small font-position differences in PDF coordinates.
                        body_x = chars[1]["x0"]
                        excerpt = line["text"].lstrip("\u2022 ").strip()
                        if len(excerpt) > 80:
                            excerpt = excerpt[:77].rstrip() + "..."
                        current = {
                            "page": page.page_number,
                            "end_page": page.page_number,
                            "lines": 1,
                            "excerpt": excerpt,
                        }
                        bullets.append(current)
                    elif current is not None and abs(chars[0]["x0"] - body_x) <= 0.75:
                        current["lines"] += 1
                        current["end_page"] = page.page_number
                    else:
                        current = None
    except Exception as exc:
        return {
            "checked": None,
            "long_bullets": [],
            "warning": f"CV bullet lines could not be checked ({type(exc).__name__}).",
        }
    return {
        "checked": len(bullets),
        "long_bullets": [bullet for bullet in bullets if bullet["lines"] >= 3],
    }


def inspect_document(
    path: str | Path,
    *,
    expected_paragraphs: Sequence[str] | None = None,
    expected_fields: Mapping[str, str] | None = None,
) -> dict:
    """Return JSON-ready advisory metrics; unavailable checks remain null.

    Pass source body paragraphs in their intended reading order, and a mapping
    from field labels to exact expected values (for example email, title, dates).
    Fields are checked independently; the mapping's insertion order is ignored.
    A missing dependency or unreadable PDF never becomes a successful check.
    DOCX pagination needs a separately rendered PDF and is not inferred here.
    """
    path = Path(path)
    paragraphs = list(expected_paragraphs or [])
    fields = dict(expected_fields or {})
    report = {"page_count": None, "engines": {}, "warnings": []}
    if not any(_tokens(paragraph) for paragraph in paragraphs):
        report["warnings"].append(
            "No source paragraphs supplied; body word retention is unchecked."
        )
    if not fields:
        report["warnings"].append(
            "No expected fields supplied; required-field retention is unchecked."
        )
    for name, extractor in [
        ("pypdf", _extract_pypdf),
        ("pdfplumber", _extract_pdfplumber),
    ]:
        result = {
            "status": "error",
            "settings": {"extract_text": "defaults"},
            "page_count": None,
            "word_retention": None,
            "expected_word_count": None,
            "retained_word_count": None,
            "missing_fields": None,
            "suspicious_glyphs": None,
            "reading_order": None,
            "warnings": [],
        }
        report["engines"][name] = result
        if path.suffix.lower() != ".pdf":
            result["status"] = "unsupported"
            result["warnings"].append(
                "Only PDF extraction is supported; render other formats separately."
            )
        else:
            try:
                count, text = extractor(path)
                result.update(_compare_text(text, paragraphs, fields))
                result.update(status="ok", page_count=count)
                if count == 0:
                    result["warnings"].append("PDF has no pages.")
            except ImportError:
                result["status"] = "unavailable"
                result["warnings"].append("Extraction dependency is unavailable.")
            except Exception as exc:
                # Parser messages can include private document text or paths.
                result["warnings"].append(
                    f"PDF extraction failed ({type(exc).__name__})."
                )
        report["warnings"].extend(
            f"{name}: {warning}" for warning in result["warnings"]
        )
    counts = [
        result["page_count"]
        for result in report["engines"].values()
        if result["page_count"] is not None
    ]
    if counts:
        report["page_count"] = counts[0]
        if len(set(counts)) > 1:
            report["warnings"].append("Extraction engines disagree on page count.")
    return report
