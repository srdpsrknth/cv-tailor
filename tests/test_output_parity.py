"""PDF / DOCX / TXT parity, locale-free dates, letter timezone and letter preferences.

Synthetic data only.
"""
from datetime import date, datetime, timezone
import locale
from pathlib import Path

from docx import Document
from pydantic import ValidationError
from pypdf import PdfReader
import pytest

from models.profile import LetterPreferences, Profile
from models.tailored_output import TailoredCoverLetter, TailoredCV
from renderers import docx_renderer
from renderers.cv_sections import LABELS, SECTION_TITLES, format_month_year
from renderers.docx_renderer import DocxRenderer
from renderers.latex_renderer import LaTeXRenderer
from renderers.upload_cv import render_upload_cv
from support import latex_available, load_profile, read_json
from utils.calendar import calendar_today, configured_timezone_name

ROOT = Path(__file__).resolve().parents[1]


def _cv():
    return TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])


# --- dates ------------------------------------------------------------------------

@pytest.mark.parametrize("raw,short,full", [
    ("2025-08", "Aug 2025", "August 2025"),
    ("2023-04", "Apr 2023", "April 2023"),
    ("present", "Present", "Present"),
    ("PRESENT", "Present", "Present"),
    ("", "Present", "Present"),
    ("2025-13", "2025-13", "2025-13"),
    ("Spring 2020", "Spring 2020", "Spring 2020"),
])
def test_month_names_come_from_a_fixed_english_table(raw, short, full):
    assert format_month_year(raw) == short
    assert format_month_year(raw, short=False) == full


def test_dates_do_not_follow_the_os_locale():
    original = locale.setlocale(locale.LC_TIME)
    for name in ("de_DE.UTF-8", "fr_FR.UTF-8", "de_DE", "German_Germany.1252"):
        try:
            locale.setlocale(locale.LC_TIME, name)
            break
        except locale.Error:
            continue
    else:
        pytest.skip("no non-English locale is installed")
    try:
        assert LaTeXRenderer._format_date("2025-03") == "Mar 2025"
        assert LaTeXRenderer._format_date("2025-05") == "May 2025"
        assert docx_renderer.MONTHS[2] == "March"
    finally:
        locale.setlocale(locale.LC_TIME, original)


# --- one source of titles and labels ---------------------------------------------------

def test_pdf_and_upload_copy_use_the_same_section_titles_and_date_words(tmp_path, analyst_profile):
    cv = _cv()
    paths = render_upload_cv(cv, analyst_profile, tmp_path)
    paragraphs = [p.text for p in Document(paths["cv_upload_docx_path"]).paragraphs]
    text = Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8")
    assert text.splitlines() == paragraphs
    for key in ("experience", "education", "skills", "languages", "certifications"):
        assert SECTION_TITLES[key] in paragraphs
    assert "Work Experience" not in paragraphs
    # Date ranges: capitalised Present, en dash, never a hyphen or a double hyphen.
    ranges = [p for p in paragraphs if " | " in p and ("Present" in p or "20" in p) and "–" in p]
    assert ranges and all(" - " not in p and " -- " not in p for p in ranges)
    assert any("Present" in p for p in ranges)
    # The Summary heading is deliberately kept for ATS parsers (the PDF has none).
    assert "Summary" in paragraphs


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_pdf_uses_the_shared_titles_and_present(tmp_path, analyst_profile):
    pdf = LaTeXRenderer(outputs_dir=tmp_path).render_cv(_cv(), analyst_profile)
    text = " ".join((page.extract_text() or "") for page in PdfReader(pdf).pages)
    assert SECTION_TITLES["experience"].upper() in text
    assert "–" in text and "Present" in text
    assert "present" not in text.replace("Present", "")


def test_template_has_no_hardcoded_labels():
    source = (ROOT / "templates" / "cv" / "main.tex.jinja2").read_text(encoding="utf-8")
    for label in (value for value in LABELS.values() if value.endswith(":")):
        assert label not in source, f"{label!r} is hardcoded in the template"
    assert "(continued)" not in source


def test_template_receives_every_label(analyst_profile, tmp_path):
    data = LaTeXRenderer(outputs_dir=tmp_path)._prepare_template_data(_cv(), analyst_profile)
    assert set(LABELS) <= set(data["labels"])
    assert data["section_titles"]["experience"] == "Professional Experience"


def test_docx_headings_keep_with_next(tmp_path, analyst_profile):
    paths = render_upload_cv(_cv(), analyst_profile, tmp_path)
    document = Document(paths["cv_upload_docx_path"])
    headings = [p for p in document.paragraphs if p.style.name in ("Heading 1", "Heading 2")]
    assert headings
    assert all(p.paragraph_format.keep_with_next for p in headings)
    for style in ("Heading 1", "Heading 2"):
        assert document.styles[style].paragraph_format.keep_with_next


# --- cover-letter date -------------------------------------------------------------------

def test_calendar_today_follows_the_zone():
    moment = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert calendar_today("UTC", now=moment) == date(2026, 12, 31)
    assert calendar_today("Pacific/Auckland", now=moment) == date(2027, 1, 1)
    assert calendar_today("America/Los_Angeles", now=moment) == date(2026, 12, 31)
    assert calendar_today(None, now=datetime(2026, 5, 5, 8, 0)) == date(2026, 5, 5)


def test_configured_timezone_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("CVTAILOR_TIMEZONE", raising=False)
    assert configured_timezone_name() is None
    monkeypatch.setenv("CVTAILOR_TIMEZONE", " Pacific/Auckland ")
    assert configured_timezone_name() == "Pacific/Auckland"


def test_letter_date_and_file_year_use_the_configured_timezone(tmp_path, monkeypatch):
    seen = []

    def fake_today(name, *, now=None):
        seen.append(name)
        return date(2027, 1, 1)

    monkeypatch.setattr(docx_renderer, "calendar_today", fake_today)
    renderer = DocxRenderer(outputs_dir=str(tmp_path), timezone_name="Pacific/Auckland")
    assert renderer._format_render_date() == "1 January 2027"
    assert renderer._format_filename("Example Co", "Analyst").startswith("2027_")
    assert seen == ["Pacific/Auckland", "Pacific/Auckland"]


def test_letter_timezone_defaults_to_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CVTAILOR_TIMEZONE", "Pacific/Auckland")
    assert DocxRenderer(outputs_dir=str(tmp_path)).timezone_name == "Pacific/Auckland"
    monkeypatch.delenv("CVTAILOR_TIMEZONE")
    assert DocxRenderer(outputs_dir=str(tmp_path)).timezone_name is None


def test_an_unknown_timezone_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="CVTAILOR_TIMEZONE"):
        DocxRenderer(outputs_dir=str(tmp_path), timezone_name="Not/AZone")._format_render_date()


# --- optional letter preferences -------------------------------------------------------------

def _letter(**overrides):
    payload = {"company_name": "Example Co", "role_title": "Analyst", "signature_name": "Alex Sample",
               "paragraphs": ["Opening.", "Body one.", "Body two.", "Closing."],
               "closing_line": "Kind regards,"}
    return TailoredCoverLetter.model_validate({**payload, **overrides})


def _with_letter(profile, **prefs):
    return Profile.model_validate({**profile.model_dump(), "letter": prefs})


def test_default_letter_wording_is_unchanged(tmp_path, analyst_profile):
    assert analyst_profile.letter is None
    assert "letter" not in analyst_profile.model_dump()
    renderer = DocxRenderer(outputs_dir=str(tmp_path))
    context = renderer._build_context(_letter(), analyst_profile)
    assert context["salutation_line"] == "Dear Example Co Hiring Team,"
    assert context["closing_line"] == "Kind regards,"
    assert context["recipient_line"] == "Hiring Team"
    assert renderer._build_context(_letter(closing_line=""), analyst_profile)["closing_line"] == "Warm regards,"


def test_profile_letter_preferences_override_the_model_wording(tmp_path, analyst_profile):
    profile = _with_letter(analyst_profile, salutation="Dear {company} recruiting team,",
                           sign_off="With best wishes,")
    renderer = DocxRenderer(outputs_dir=str(tmp_path))
    letter = _letter(paragraphs=["Dear Someone Else,\nOpening.", "Body one.", "Body two.", "Closing."])
    context = renderer._build_context(letter, profile)
    assert context["salutation_line"] == "Dear Example Co recruiting team,"
    assert context["closing_line"] == "With best wishes,"
    assert context["opening_paragraph"] == "Opening."
    assert renderer._resolve_closing_line(letter, profile) == "With best wishes,"
    # Only the sign-off set: the salutation keeps its default.
    only = _with_letter(analyst_profile, sign_off="Sincerely,")
    context = renderer._build_context(_letter(), only)
    assert context["salutation_line"] == "Dear Example Co Hiring Team,"
    assert context["closing_line"] == "Sincerely,"


def test_company_placeholder_without_a_company_collapses():
    prefs = LetterPreferences(salutation="Dear {company} Hiring Team,")
    assert prefs.salutation_for("") == "Dear Hiring Team,"
    assert prefs.salutation_for(" Example Co ") == "Dear Example Co Hiring Team,"
    assert LetterPreferences().salutation_for("Example Co") is None


@pytest.mark.parametrize("prefs", [
    {"salutation": "Dear {name},"}, {"salutation": "Dear\nteam"}, {"sign_off": " "}, {"unknown": "x"},
])
def test_invalid_letter_preferences_are_rejected(prefs):
    with pytest.raises(ValidationError):
        LetterPreferences.model_validate(prefs)


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_docx_and_pdf_letters_show_the_same_preferred_wording(tmp_path):
    profile = _with_letter(load_profile("synthetic_analyst"),
                           salutation="Dear {company} recruiting team,", sign_off="With best wishes,")
    letter = TailoredCoverLetter.model_validate(
        read_json("llm_responses", "analyst_nordwind", "02_cover_letter.json")["cover_letter"])
    docx_path, pdf_path = DocxRenderer(outputs_dir=str(tmp_path)).render_cover_letter(letter, profile)
    docx_text = "\n".join(p.text for p in Document(docx_path).paragraphs)
    pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(pdf_path).pages)
    for text in (docx_text, pdf_text):
        assert f"Dear {letter.company_name} recruiting team," in " ".join(text.split())
        assert "With best wishes," in text
        assert "Hiring Team" in text
