"""Offline extraction checks with synthetic documents, never candidate fixtures."""

import json
import sys

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _pdf(path, lines, *, positioned=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(
        (
            "BT /F1 12 Tf 40 740 Td 18 TL\n"
            + "\n".join(lines if positioned else [f"({line}) Tj T*" for line in lines])
            + "\nET"
        ).encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    return path


def test_cv_bullet_check_uses_drawn_lines_and_stops_at_headings(tmp_path):
    from services.document_quality import inspect_cv_bullets

    path = _pdf(tmp_path / "cv.pdf", [
        r"1 0 0 1 40 740 Tm (\225) Tj 1 0 0 1 52 740 Tm (A three-line bullet) Tj",
        "1 0 0 1 52 726 Tm (that wraps once) Tj",
        "1 0 0 1 52 712 Tm (and wraps again.) Tj",
        r"1 0 0 1 40 696 Tm (\225) Tj 1 0 0 1 52 696 Tm (A two-line bullet) Tj",
        "1 0 0 1 52 682 Tm (with one wrap.) Tj",
        "1 0 0 1 40 668 Tm (TECHNOLOGIES) Tj",
        "1 0 0 1 40 654 Tm (A long unbulleted passage follows.) Tj",
        "1 0 0 1 40 640 Tm (Second unbulleted line.) Tj",
        "1 0 0 1 40 626 Tm (Third unbulleted line.) Tj",
    ], positioned=True)
    report = inspect_cv_bullets(path)
    assert report == {
        "checked": 2,
        "long_bullets": [
            {"page": 1, "end_page": 1, "lines": 3, "excerpt": "A three-line bullet"},
        ],
    }


def test_cv_bullet_check_distinguishes_unreadable_and_markerless_pdfs(tmp_path):
    from services.document_quality import inspect_cv_bullets

    assert inspect_cv_bullets(tmp_path / "missing.pdf")["checked"] is None
    report = inspect_cv_bullets(_pdf(tmp_path / "cv.pdf", ["Text without markers."]))
    assert report == {"checked": 0, "long_bullets": []}


def test_two_independent_default_engines_retain_words_fields_and_order(tmp_path):
    from services.document_quality import inspect_document

    path = _pdf(
        tmp_path / "synthetic.pdf",
        [
            "Avery Example",
            "avery@example.test",
            "Data Analyst 2021 - 2024",
            "Built useful reports.",
            "Reviewed useful reports.",
        ],
    )
    report = inspect_document(
        path,
        expected_paragraphs=["Built useful reports.", "Reviewed useful reports."],
        expected_fields={
            "email": "avery@example.test",
            "role_dates": "Data Analyst 2021 - 2024",
        },
    )
    assert report["page_count"] == 1
    assert set(report["engines"]) == {"pypdf", "pdfplumber"}
    for result in report["engines"].values():
        assert result["status"] == "ok"
        assert result["settings"] == {"extract_text": "defaults"}
        assert result["word_retention"] == 1.0
        assert result["missing_fields"] == []
        assert result["reading_order"] is True
        assert result["suspicious_glyphs"] == []
    # Reports can be persisted without embedding document text or source values.
    assert "avery@example.test" not in json.dumps(report)


def test_missing_words_duplicate_counts_and_field_boundaries(tmp_path):
    from services.document_quality import inspect_document

    path = _pdf(tmp_path / "synthetic.pdf", ["Built usefulreports.", "Data Analyst"])
    report = inspect_document(
        path,
        expected_paragraphs=["Built useful reports useful."],
        expected_fields={"role": "Senior Data Analyst"},
    )
    for result in report["engines"].values():
        assert result["word_retention"] == 0.25
        assert result["missing_fields"] == ["role"]
        assert result["reading_order"] is None
        assert result["warnings"]


def test_reordered_paragraphs_are_distinguished_from_retained_words(tmp_path):
    from services.document_quality import inspect_document

    path = _pdf(tmp_path / "synthetic.pdf", ["Second example.", "First example."])
    report = inspect_document(
        path, expected_paragraphs=["First example.", "Second example."]
    )
    for result in report["engines"].values():
        assert result["word_retention"] == 1.0
        assert result["reading_order"] is False
        assert "Source paragraph order differs from extraction." in result["warnings"]


def test_absent_sources_are_not_reported_as_a_pass(tmp_path):
    from services.document_quality import inspect_document

    report = inspect_document(_pdf(tmp_path / "synthetic.pdf", ["Example text."]))
    for result in report["engines"].values():
        assert result["word_retention"] is None
        assert result["missing_fields"] is None
        assert result["reading_order"] is None
    assert report["warnings"]


@pytest.mark.parametrize("kind", ["missing", "corrupt", "unsupported"])
def test_unreadable_document_is_an_advisory_failure(tmp_path, kind):
    from services.document_quality import inspect_document

    path = tmp_path / ("synthetic.docx" if kind == "unsupported" else "synthetic.pdf")
    if kind != "missing":
        path.write_bytes(b"not a PDF")
    report = inspect_document(path, expected_fields={"email": "avery@example.test"})
    assert report["page_count"] is None
    assert report["warnings"]
    for result in report["engines"].values():
        assert result["status"] != "ok"
        assert result["missing_fields"] is None
        assert result["word_retention"] is None


def test_missing_engine_does_not_prevent_independent_engine_check(
    tmp_path, monkeypatch
):
    from services.document_quality import inspect_document

    path = _pdf(tmp_path / "synthetic.pdf", ["Example text."])
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    report = inspect_document(path, expected_paragraphs=["Example text."])
    assert report["engines"]["pypdf"]["word_retention"] == 1.0
    missing = report["engines"]["pdfplumber"]
    assert missing["status"] == "unavailable"
    assert missing["word_retention"] is None
    assert report["warnings"]


def test_unicode_normalization_and_suspicious_glyphs():
    from services.document_quality import _compare_text

    result = _compare_text(
        "Office ﬁle\nAvery\ufffd \ue001", ["Office file"], {"name": "AVERY"}
    )
    assert result["word_retention"] == 1.0
    assert result["missing_fields"] == []
    assert result["suspicious_glyphs"] == ["U+E001", "U+FFFD"]
    assert result["warnings"]


def test_blank_pdf_does_not_claim_retention_or_order_success(tmp_path):
    from services.document_quality import inspect_document

    report = inspect_document(
        _pdf(tmp_path / "blank.pdf", []),
        expected_paragraphs=["Example text."],
        expected_fields={"email": "avery@example.test"},
    )
    assert report["page_count"] == 1
    for result in report["engines"].values():
        assert result["word_retention"] == 0.0
        assert result["missing_fields"] == ["email"]
        assert result["reading_order"] is None
        assert any("No extractable words" in warning for warning in result["warnings"])


def test_engine_failure_is_isolated_and_error_messages_do_not_leak_text(
    tmp_path, monkeypatch
):
    from services import document_quality

    path = _pdf(tmp_path / "synthetic.pdf", ["Example text."])

    def fail(_path):
        raise ValueError("PRIVATE CONTENT from an extractor exception")

    monkeypatch.setattr(document_quality, "_extract_pypdf", fail)
    report = document_quality.inspect_document(
        path, expected_paragraphs=["Example text."]
    )
    assert report["engines"]["pypdf"]["status"] == "error"
    assert report["engines"]["pypdf"]["word_retention"] is None
    assert report["engines"]["pdfplumber"]["word_retention"] == 1.0
    assert "PRIVATE CONTENT" not in json.dumps(report)
