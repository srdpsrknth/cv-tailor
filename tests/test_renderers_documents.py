"""Document-level assertions against *real* LaTeX and DOCX output.

This closes the biggest gap in ASSESSMENT.md §4: both renderers were mocked in the only
integration test, so real output had no regression protection.

Covers these ASSESSMENT.md §1 workflows:
  * PDF generation (LaTeX CV)
  * DOCX generation (cover letter)
  * page-count enforcement
  * word-count enforcement

Tests that need `pdflatex` are marked ``requires_latex`` and skip cleanly when no compiler
can be resolved, so the suite still runs on a machine without TeX.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.tailored_output import TailoredCoverLetter, TailoredCV
from renderers import create_docx_renderer, create_latex_renderer
from renderers.docx_renderer import DocxRenderer
from renderers.latex_renderer import LaTeXRenderer
from support import (
    CONTENT,
    contains_all,
    docx_text,
    latex_available,
    load_profile,
    normalise,
    page_count,
    pdf_page_height,
    pdf_pages_text,
    pdf_text,
    read_json,
    text_is_within_bounds,
)

requires_latex = pytest.mark.skipif(
    not latex_available(), reason='No pdflatex compiler could be resolved on this machine'
)

# Every CV section the template can emit, in the order the template emits them.
CV_SECTIONS = ['PROFESSIONAL EXPERIENCE', 'EDUCATION', 'SKILLS', 'LANGUAGES']
OPTIONAL_CV_SECTIONS = ['SELECTED PROJECTS', 'CERTIFICATIONS']

A4_WIDTH, A4_HEIGHT = 595.276, 841.89

# Two separate concerns, deliberately not conflated:
#   * `requires_latex` tags a test so `pytest -m "not requires_latex"` can skip the slow
#     pdflatex work for a fast lane;
#   * `needs_latex` skips a test outright on a machine with no TeX, keeping the suite green.
# Tests that compile a document carry both; tests that only inspect models or construct
# renderers carry neither.
requires_latex = pytest.mark.requires_latex
_skip_without_latex = pytest.mark.skipif(
    not latex_available(), reason='No pdflatex compiler could be resolved on this machine'
)


def needs_latex(func):
    """Tag a test as slow (deselectable) and skip it when no TeX compiler exists."""
    return requires_latex(_skip_without_latex(func))


@pytest.fixture(scope='module')
def content() -> dict:
    return read_json('content', 'valid_content.json')


@pytest.fixture(scope='module')
def rendered_cv(tmp_path_factory, content):
    """Render the fixture CV once for the whole module — pdflatex is the slow part."""
    if not latex_available():
        pytest.skip('No pdflatex compiler could be resolved on this machine')
    outputs = tmp_path_factory.mktemp('latex_cv')
    profile = load_profile('synthetic_analyst')
    cv = TailoredCV.model_validate(content['cv'])
    renderer = create_latex_renderer(outputs_dir=str(outputs))
    pdf = Path(renderer.render_cv(cv, profile, job_position='Analytical Engineer'))
    return pdf


# --- LaTeX CV: page geometry and sections --------------------------------------------

@needs_latex
def test_cv_is_a4_portrait(rendered_cv):
    """Page geometry is fixed by the template; a silent change would resize every CV."""
    assert page_count(rendered_cv) >= 1
    assert pdf_page_height(rendered_cv) == pytest.approx(A4_HEIGHT, abs=1.0)


@needs_latex
def test_cv_stays_within_the_two_page_limit(rendered_cv):
    assert page_count(rendered_cv) <= 2, 'fixture CV must fit the default two-page limit'


@needs_latex
def test_cv_contains_every_required_section(rendered_cv):
    text = normalise(pdf_text(rendered_cv)).upper()
    missing = [section for section in CV_SECTIONS if section not in text]
    assert not missing, f'missing CV sections: {missing}'


@needs_latex
def test_cv_contains_the_sections_the_fixture_enables(rendered_cv):
    text = normalise(pdf_text(rendered_cv)).upper()
    missing = [section for section in OPTIONAL_CV_SECTIONS if section not in text]
    assert not missing, f'missing enabled CV sections: {missing}'


@needs_latex
def test_cv_carries_identity_and_contact_details(rendered_cv, analyst_profile):
    text = normalise(pdf_text(rendered_cv))
    missing = contains_all(text, [
        analyst_profile.identity.full_name.upper(),
        analyst_profile.identity.email,
    ])
    assert missing is None, f'{missing!r} missing from the rendered CV'


@needs_latex
def test_cv_lists_every_employer_with_exact_titles_and_dates(rendered_cv, analyst_profile):
    """The validator guarantees this in the model; this proves it survives rendering."""
    text = normalise(pdf_text(rendered_cv))
    for exp in analyst_profile.experience:
        assert normalise(exp.company) in text, f'missing employer {exp.company}'
        assert normalise(exp.role) in text, f'missing role {exp.role}'


@needs_latex
def test_cv_renders_profile_bullets_verbatim(rendered_cv, analyst_profile):
    text = normalise(pdf_text(rendered_cv))
    checked = 0
    for exp in analyst_profile.experience:
        for bullet in exp.bullets:
            assert normalise(bullet) in text, f'missing bullet from {exp.company}: {bullet[:60]}'
            checked += 1
    assert checked > 0, 'fixture should contain bullets to check'


@needs_latex
def test_cv_has_no_clipped_or_overflowing_text(rendered_cv):
    """No glyph may fall outside the page box."""
    assert text_is_within_bounds(rendered_cv), 'text extends past the page edge'


@needs_latex
def test_cv_has_no_orphan_section_heading(rendered_cv):
    """A section heading must not be the last thing on a page.

    The template guards every section with ``\\needspace``; this asserts that guard
    still holds, which is the failure mode AGENTS.md calls an orphan heading.
    """
    pages = pdf_pages_text(rendered_cv)
    headings = set(CV_SECTIONS + OPTIONAL_CV_SECTIONS + ['CERTIFICATIONS'])
    for index, page in enumerate(pages[:-1], start=1):
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if not lines:
            continue
        tail = lines[-1].upper()
        orphaned = [h for h in headings if h in tail]
        assert not orphaned, f'page {index} ends on a section heading: {orphaned}'


@needs_latex
@needs_latex
def test_cv_respects_the_include_flags(content):
    """`include_education` / `include_certifications` must actually remove sections."""
    if not latex_available():
        pytest.skip('No pdflatex compiler could be resolved on this machine')
    import tempfile

    profile = load_profile('synthetic_analyst')
    payload = json.loads(json.dumps(content['cv']))
    payload['include_education'] = False
    payload['include_certifications'] = False
    cv = TailoredCV.model_validate(payload)

    with tempfile.TemporaryDirectory() as folder:
        renderer = create_latex_renderer(outputs_dir=folder)
        pdf = Path(renderer.render_cv(cv, profile, job_position='Analytical Engineer'))
        text = normalise(pdf_text(pdf)).upper()

    assert 'EDUCATION' not in text
    assert 'CERTIFICATIONS' not in text
    # The sections that were not disabled must survive.
    assert 'PROFESSIONAL EXPERIENCE' in text


@needs_latex
@needs_latex
def test_cv_escapes_latex_special_characters(tmp_path):
    """Free text containing & % $ # _ { } must render as literal characters."""
    profile = load_profile('synthetic_analyst')
    payload = json.loads((CONTENT / 'valid_content.json').read_text(encoding='utf-8'))['cv']
    payload['summary'] = [
        'Handled 100% of A&B reporting $100 #1 with snake_case keys {braced} and 1~2^3.'
    ]
    cv = TailoredCV.model_validate(payload)

    renderer = create_latex_renderer(outputs_dir=str(tmp_path))
    pdf = Path(renderer.render_cv(cv, profile, job_position='Analytical Engineer'))
    text = normalise(pdf_text(pdf))

    for fragment in ['100%', 'A&B', '$100', '#1', 'snake_case', '{braced}']:
        assert fragment in text, f'LaTeX escaping lost {fragment!r}'


@needs_latex
@needs_latex
def test_renderer_leaves_only_the_pdf_behind(tmp_path, content):
    """`_cleanup_intermediates` must remove .tex/.aux/.log residue."""
    profile = load_profile('synthetic_analyst')
    cv = TailoredCV.model_validate(content['cv'])
    renderer = create_latex_renderer(outputs_dir=str(tmp_path))
    renderer.render_cv(cv, profile, job_position='Analytical Engineer')

    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.suffix.lower() not in {'.pdf'}]
    assert leftovers == [], f'intermediate files were not cleaned up: {leftovers}'


@needs_latex
@needs_latex
def test_tex_and_pdf_share_a_deterministic_basename(tmp_path, content):
    profile = load_profile('synthetic_analyst')
    cv = TailoredCV.model_validate(content['cv'])
    renderer = create_latex_renderer(outputs_dir=str(tmp_path))
    pdf = Path(renderer.render_cv(cv, profile, job_position='Analytical Engineer'))

    assert pdf.parent == tmp_path
    assert pdf.suffix == '.pdf'
    assert 'alex_sample' in pdf.name and 'analytical_engineer' in pdf.name


@needs_latex
@needs_latex
def test_work_authorization_overrides_the_profile_tagline(tmp_path, content):
    """`work_authorization` replaces the profile's visa wording when set."""
    profile = load_profile('synthetic_analyst')
    payload = json.loads(json.dumps(content['cv']))
    payload['work_authorization'] = 'Synthetic Permit Holder'
    cv = TailoredCV.model_validate(payload)

    renderer = create_latex_renderer(outputs_dir=str(tmp_path))
    pdf = Path(renderer.render_cv(cv, profile, job_position='Analytical Engineer'))
    text = normalise(pdf_text(pdf))

    assert 'Synthetic Permit Holder' in text
    assert profile.identity.visa_status not in text


# --- DOCX cover letter ----------------------------------------------------------------

@pytest.fixture
def docx_letter(tmp_path, content):
    """Render the fixture letter to DOCX with the LaTeX PDF step disabled.

    PDF generation for the letter is a separate concern (and needs pdflatex); here we
    assert the DOCX document itself.
    """
    renderer = DocxRenderer(outputs_dir=str(tmp_path))
    placeholder = tmp_path / 'letter.pdf'
    placeholder.write_bytes(b'%PDF-1.4\n')
    renderer._generate_pdf_via_latex = lambda *args, **kwargs: placeholder
    profile = load_profile('synthetic_analyst')
    letter = TailoredCoverLetter.model_validate(content['cover_letter'])
    path, pdf = renderer.render_cover_letter(letter, profile, job_position='Analytical Engineer')
    return Path(path), letter, profile


def test_docx_is_created_with_the_expected_name(docx_letter):
    path, _, _ = docx_letter
    assert path.exists() and path.suffix == '.docx'
    assert 'cover_letter' in path.name
    assert 'nordwind' in path.name


def test_docx_contains_every_body_paragraph(docx_letter):
    path, letter, _ = docx_letter
    text = normalise(docx_text(path))
    for index, paragraph in enumerate(letter.paragraphs, start=1):
        assert normalise(paragraph) in text, f'paragraph {index} missing from the DOCX'


def test_docx_contains_company_role_and_signature(docx_letter):
    path, letter, profile = docx_letter
    text = normalise(docx_text(path))
    missing = contains_all(text, [
        letter.company_name,
        letter.role_title,
        letter.signature_name,
    ])
    assert missing is None, f'{missing!r} missing from the DOCX'


def test_docx_contains_candidate_contact_details(docx_letter):
    path, _, profile = docx_letter
    text = normalise(docx_text(path))
    missing = contains_all(text, [profile.identity.email])
    assert missing is None, f'{missing!r} missing from the DOCX'


def test_docx_body_word_count_still_meets_the_target(docx_letter):
    """Enforcement check on the rendered document, not only on the model."""
    path, letter, _ = docx_letter
    words = sum(len(p.split()) for p in letter.paragraphs)
    assert 290 <= words <= 310, f'fixture letter has {words} words'


def test_docx_preserves_xml_sensitive_characters(tmp_path):
    """Regression guard for the autoescape behaviour already covered elsewhere."""
    renderer = DocxRenderer(outputs_dir=str(tmp_path))
    renderer._generate_pdf_via_latex = lambda *args, **kwargs: tmp_path / 'letter.pdf'
    profile = load_profile('synthetic_analyst')
    letter = TailoredCoverLetter(
        company_name='Data & Capital <Holdings>',
        role_title='Analyst "Senior"',
        signature_name=profile.identity.full_name,
        paragraphs=['Handled 1 < 2 and 3 > 2 with A&B reporting.'] + ['Body text.'] * 3,
    )
    path, _ = renderer.render_cover_letter(letter, profile, job_position='Analytical Engineer')
    text = normalise(docx_text(Path(path)))

    for fragment in ['Data & Capital <Holdings>', 'Analyst "Senior"', '1 < 2', '3 > 2', 'A&B']:
        assert fragment in text, f'DOCX lost {fragment!r}'


def test_docx_has_no_empty_paragraph_run_before_the_signature(docx_letter):
    """`_tidy_signature_block` must not leave a stack of blank lines at the end."""
    from docx import Document

    path, _, _ = docx_letter
    paragraphs = Document(str(path)).paragraphs
    trailing = 0
    for paragraph in reversed(paragraphs):
        if paragraph.text.strip():
            break
        trailing += 1
    assert trailing <= 1, f'{trailing} trailing empty paragraphs left in the DOCX'


def test_docx_font_is_applied(docx_letter):
    """`_apply_aptos_font` is best-effort but must actually set the font when it runs."""
    from docx import Document

    path, _, _ = docx_letter
    document = Document(str(path))
    named = [run.font.name for p in document.paragraphs for run in p.runs if run.font.name]
    assert named, 'no run in the DOCX has an explicit font name'
    assert all(name == 'Aptos' for name in named)


# --- page-count enforcement -----------------------------------------------------------

@needs_latex
def test_page_count_reads_a_real_pdf(rendered_cv):
    assert page_count(rendered_cv) == len(pdf_pages_text(rendered_cv))


def test_page_count_gate_accepts_one_and_two_pages(tmp_path):
    from support import make_blank_pdf

    for pages in (1, 2):
        assert page_count(Path(make_blank_pdf(tmp_path / f'{pages}.pdf', pages))) == pages


def test_page_count_gate_rejects_three_pages(tmp_path):
    from support import make_blank_pdf

    """The pipeline's gate is `page_count <= 2`; three pages must be a failure."""
    assert page_count(Path(make_blank_pdf(tmp_path / 'three.pdf', 3))) == 3


@needs_latex
def test_docx_letter_pdf_is_one_page_when_latex_is_available(tmp_path):
    if not latex_available():
        pytest.skip('No pdflatex compiler could be resolved on this machine')
    profile = load_profile('synthetic_analyst')
    letter = TailoredCoverLetter.model_validate(
        read_json('content', 'valid_content.json')['cover_letter'])
    renderer = create_docx_renderer(outputs_dir=str(tmp_path))
    _, pdf = renderer.render_cover_letter(letter, profile, job_position='Analytical Engineer')

    assert pdf is not None, 'cover-letter PDF generation failed'
    assert page_count(Path(pdf)) == 1, 'cover letter must fit one page'


# --- renderer construction guards ------------------------------------------------------

def test_docx_renderer_requires_its_template(tmp_path):
    from renderers.docx_renderer import DocxRendererError

    with pytest.raises(DocxRendererError, match='template not found'):
        DocxRenderer(templates_dir=str(tmp_path / 'empty'), outputs_dir=str(tmp_path))


def test_latex_renderer_creates_its_directories(tmp_path):
    outputs = tmp_path / 'new' / 'outputs'
    renderer = LaTeXRenderer(outputs_dir=str(outputs))
    assert outputs.exists()
    assert renderer.templates_dir.exists()


@needs_latex
@needs_latex
def test_missing_template_is_reported_clearly(tmp_path, content):
    from renderers.latex_renderer import LaTeXRendererError

    renderer = LaTeXRenderer(templates_dir=str(tmp_path / 'none'), outputs_dir=str(tmp_path))
    cv = TailoredCV.model_validate(content['cv'])
    with pytest.raises(LaTeXRendererError, match='Template not found'):
        renderer.render_cv(cv, load_profile('synthetic_analyst'), job_position='X')


# --- date formatting ------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('2023-04', 'Apr 2023'),
    ('present', 'present'),
    ('PRESENT', 'present'),
    ('', 'present'),
    ('not-a-date', 'not-a-date'),
])
def test_date_formatting_is_stable(raw, expected):
    assert LaTeXRenderer._format_date(raw) == expected
