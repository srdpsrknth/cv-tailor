"""Readable typography and explicit text spacing in the real document artifacts."""

from collections import Counter
from pathlib import Path
import re

import pytest
from docx import Document

from models.tailored_output import TailoredCV, TailoredCoverLetter
from renderers.latex_renderer import LaTeXRenderer
from renderers.docx_renderer import DocxRenderer
from renderers.upload_cv import render_upload_cv
from support import latex_available, read_json


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_cv_text_is_readable_with_two_engines(tmp_path, analyst_profile):
    import pdfplumber
    from pypdf import PdfReader

    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    path = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, analyst_profile)
    reader = PdfReader(path)
    assert len(reader.pages) <= 2
    assert reader.metadata.author == analyst_profile.identity.full_name
    with pdfplumber.open(path) as pdf:
        chars = [c for p in pdf.pages for c in p.chars if c["text"].strip()]
        common = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0]
        assert (
            common >= 10.4
        ), "Body must remain readable, not shrink to meet the page cap"
        assert not [
            c for c in chars if c["size"] < 9
        ], "No invisible delimiters or tiny metadata"
        plumber_text = " ".join(p.extract_text() or "" for p in pdf.pages)
    pypdf_text = " ".join(p.extract_text() for p in reader.pages)
    for text in (pypdf_text, plumber_text):
        normalized = " ".join(text.split())
        assert analyst_profile.identity.location in normalized
        for exp in cv.experience:
            assert exp.company in normalized
            assert exp.role in normalized
            for bullet in exp.bullets:
                assert " ".join(bullet.split()) in normalized


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
def test_letter_preserves_spaces_with_default_extraction(tmp_path, analyst_profile):
    import pdfplumber

    cl = TailoredCoverLetter.model_validate(
        read_json("content", "valid_content.json")["cover_letter"]
    )
    _, path = DocxRenderer(outputs_dir=tmp_path).render_cover_letter(
        cl, analyst_profile
    )
    with pdfplumber.open(path) as pdf:
        text = " ".join(" ".join(p.extract_text().split()) for p in pdf.pages)
    for paragraph in cl.paragraphs:
        assert " ".join(paragraph.split()) in text


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="LaTeX unavailable")
@pytest.mark.parametrize(
    "headline",
    [
        "Analytical Engineer",
        "Senior Data Analyst | Business Intelligence & Growth Analytics",
    ],
)
def test_contact_block_is_top_right_and_all_fields_remain_extractable(
    tmp_path, analyst_profile, headline
):
    import pdfplumber
    from pypdf import PdfReader

    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    cv.title = headline
    path = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, analyst_profile)
    with pdfplumber.open(path) as pdf:
        first = pdf.pages[0]
        email = first.search(re.escape(analyst_profile.identity.email))[0]
        name = first.search(analyst_profile.identity.full_name.upper())[0]
        assert email["x0"] > first.width / 2
        assert email["top"] < name["top"] + 25, "Contact block belongs beside the name"
        text = " ".join(page.extract_text() or "" for page in pdf.pages)
    texts = [text, " ".join(page.extract_text() for page in PdfReader(path).pages)]
    identity = analyst_profile.identity
    for extracted in texts:
        normalized = " ".join(extracted.split())
        assert headline in normalized, "Headline must not interleave with contact lines"
        for value in (
            identity.location,
            identity.phone,
            identity.email,
            "linkedin.com/in/example-alex-sample",
            "github.com/example-alex-sample",
            identity.visa_status,
        ):
            assert value in normalized


def test_word_cv_groups_education_and_uses_compact_contacts(tmp_path, analyst_profile):
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    paths = render_upload_cv(cv, analyst_profile, tmp_path)
    doc = Document(paths["cv_upload_docx_path"])
    contact = next(
        p for p in doc.paragraphs if analyst_profile.identity.email in p.text
    )
    assert analyst_profile.identity.phone in contact.text
    for edu in analyst_profile.education:
        index = next(i for i, p in enumerate(doc.paragraphs) if edu.degree in p.text)
        assert doc.paragraphs[index].paragraph_format.keep_with_next
        assert edu.institution in doc.paragraphs[index + 1].text
        assert str(edu.end_year) in doc.paragraphs[index + 1].text
    assert (
        Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8").rstrip()
        == "\n".join(p.text for p in doc.paragraphs).rstrip()
    )
