"""LaTeX escaping, unicode sanitising and contact-link safety (WP2)."""
import logging
from datetime import datetime, timezone
import subprocess
import tempfile
from pathlib import Path

import pytest
from pypdf import PdfReader

from models.profile import Profile
from models.tailored_output import TailoredCV
from renderers.latex_renderer import LaTeXRenderer
from support import latex_available, read_json
from utils.text import escape_latex, latex_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\\b", r"a\textbackslash{}b"),
        ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
        ("{x}", r"\{x\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
        ("\\{", r"\textbackslash{}\{"),
        ("100% of R&D_#1", r"100\% of R\&D\_\#1"),
        ("plain text", "plain text"),
    ],
)
def test_each_special_character_is_escaped_exactly_once(raw, expected):
    assert escape_latex(raw) == expected


def test_non_strings_pass_through():
    assert escape_latex(None) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a \u2192 b", r"a $\rightarrow$ b"),
        ("\u2265 \u2264", r"$\geq$ $\leq$"),
        ("\u2022 item", r"\textbullet{} item"),
        ("3\u00d74", r"3$\times$4"),
        ("a\u00a0b\u202fc", "a~b~c"),
        ("zero\u200bwidth\ufeff", "zerowidth"),
        ("non\u2011breaking", "non-breaking"),
    ],
)
def test_typographic_characters_map_to_latex(raw, expected):
    assert escape_latex(raw) == expected


def test_keeps_accents_dashes_quotes_and_euro():
    text = "Café Zoë – Ñandú — “quoted” ‘x’ €5 Łódź"
    assert escape_latex(text) == text


def test_unrenderable_characters_become_question_marks_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        out = escape_latex("go \U0001f680 \u6f22\u5b57 now")
    assert out == "go ? ?? now"
    assert "U+1F680" in caplog.text


def test_latex_url_escapes_percent_hash_and_encodes_unsafe_characters():
    assert latex_url("https://x.io/a_b#c") == r"https://x.io/a_b\#c"
    assert latex_url("https://x.io/a%20b") == r"https://x.io/a\%20b"
    assert latex_url("https://x.io/a b{c}") == r"https://x.io/a\%20b\%7Bc\%7D"


needs_latex = pytest.mark.skipif(not latex_available(), reason="pdflatex not available")


def _compile(body: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        tex = Path(tmp) / "t.tex"
        tex.write_text(
            "\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage[T1]{fontenc}\n"
            "\\IfFileExists{carlito.sty}{\\usepackage[sfdefault]{carlito}}{\\usepackage[default]{lato}}\n"
            "\\begin{document}\n" + body + "\n\\end{document}\n",
            encoding="utf-8",
        )
        resolved = LaTeXRenderer(outputs_dir=tmp)._resolve_pdflatex_path()
        return subprocess.run(
            [resolved, "-interaction=nonstopmode", "-halt-on-error", "-output-directory", tmp, str(tex)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )


@needs_latex
def test_sanitised_text_compiles():
    samples = [
        "arrows \u2192 \u2190 \u2265 \u2264 \u2022 \u00d7 emoji \U0001f680 CJK \u6f22\u5b57",
        "nbsp\u00a0narrow\u202fnbsp zw\u200bsp hy\u2011phen \u2212 \u00b1 \u2260",
        "Caf\u00e9 \u2013 \u2014 \u201cq\u201d \u2018x\u2019 \u20ac \u0141\u00f3d\u017a \u0126 \u017f",
        "special \\ & % $ # _ { } ~ ^ end",
    ]
    result = _compile("\n\n".join(escape_latex(s) for s in samples))
    assert result.returncode == 0, result.stdout[-1500:]


@needs_latex
def test_cv_with_special_characters_in_contact_fields_compiles(analyst_profile, tmp_path):
    identity = analyst_profile.identity.model_copy(update={
        "email": "jane_doe+cv@example.com",
        "linkedin": "https://www.linkedin.com/in/jane_doe-1%20x",
        "github": "https://github.com/jane_doe#readme",
        "phone": "+44 (0)20 7946_0000 #1",
    })
    profile = Profile.model_validate({**analyst_profile.model_dump(), "identity": identity.model_dump()})
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    pdf = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, profile)
    text = "".join(page.extract_text() for page in PdfReader(pdf).pages)
    assert "jane_doe+cv@example.com" in text
    assert "linkedin.com/in/jane_doe-1%20x" in text
    assert "github.com/jane_doe#readme" in text


@needs_latex
@pytest.mark.parametrize(("zone", "year"), [("UTC", "2026"), ("Pacific/Auckland", "2027")])
def test_cv_file_name_year_follows_the_configured_timezone(monkeypatch, analyst_profile, tmp_path, zone, year):
    """23:30 UTC on 31 Dec 2026 is already 2027 in Auckland."""
    import utils.calendar as calendar

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(calendar, "datetime", FixedClock)
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    pdf = LaTeXRenderer(outputs_dir=tmp_path, timezone_name=zone).render_cv(cv, analyst_profile)
    assert Path(pdf).name.startswith(f"{year}_CV_")


@pytest.mark.parametrize("mark", ["\u2713", "\u2714"])
def test_check_marks_map_to_checkmark_not_a_question_mark(mark):
    escaped = escape_latex(f"done {mark}")
    assert r"\checkmark" in escaped and "?" not in escaped.replace(r"\else?\fi", "")


@needs_latex
def test_check_mark_in_a_template_without_amssymb_still_compiles():
    """An older custom preamble that never loads amssymb must not break on a check mark."""
    result = _compile(escape_latex("ok \u2713 \u2714 end"))
    assert result.returncode == 0, result.stdout[-1500:]


@needs_latex
def test_check_mark_typesets_in_the_cv_and_the_cover_letter_preambles(analyst_profile, tmp_path):
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    cv.experience[0].bullets[0] = "Reduced manual checks \u2713 across reports."
    pdf = LaTeXRenderer(outputs_dir=tmp_path).render_cv(cv, analyst_profile)
    assert "Reduced manual checks" in "".join(p.extract_text() for p in PdfReader(pdf).pages)

    import shutil
    root = Path(__file__).resolve().parents[1] / "cover_letter_latex_template"
    work = tmp_path / "letter"
    shutil.copytree(root / "setup", work / "setup")
    (work / "main.tex").write_text(
        "\\input{setup/preamble.tex}\n\\input{setup/macros.tex}\n\\begin{document}\n"
        + escape_latex("Checked \u2713 \u2714 done.") + "\n\\end{document}\n", encoding="utf-8")
    compiler = LaTeXRenderer(outputs_dir=tmp_path)._resolve_pdflatex_path()
    result = subprocess.run([compiler, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                            cwd=work, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=120)
    assert result.returncode == 0, result.stdout[-1500:]
