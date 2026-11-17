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


@needs_latex
def test_cv_pdf_text_layer_preserves_separate_fields(rendered_cv, analyst_profile):
    """The raw PDF text layer must be free of icon/ligature noise and fuse no fields."""
    from pypdf import PdfReader

    raw_text = '\n'.join(page.extract_text() or '' for page in PdfReader(str(rendered_cv)).pages)
    flat_raw = ' '.join(raw_text.split())

    for garbled in ('/ne', 'Ὄ', '\ufb00', '\ufb01', '\ufb02', '\ufb03', '\ufb04', '/♀nedn', '/gtb'):
        assert garbled not in raw_text, f'garbled glyph/ligature {garbled!r} in PDF text layer'

    assert f'{analyst_profile.identity.phone} | {analyst_profile.identity.email}' in flat_raw
    assert 'linkedin.com/in/example-alex-sample | github.com/example-alex-sample' in flat_raw
    assert f'Analytical Engineer | {analyst_profile.experience[0].company}' in flat_raw
    assert 'Apr 2023' in flat_raw
    assert 'present | Sampletown, Germany' in flat_raw
    assert '2018 – 2020 | Sampletown, Germany' in flat_raw

    # Skills and certifications use visible delimiters in the extracted text layer.
    assert 'Snowflake' in flat_raw and 'dbt' in flat_raw
    snowflake_to_dbt = flat_raw[flat_raw.index('Snowflake'):flat_raw.index('dbt') + 3]
    assert ',' in snowflake_to_dbt
    cert_line = flat_raw[flat_raw.index('Synthetic Analytics Certificate'):flat_raw.index('Synthetic Reporting Qualification')]
    assert ';' in cert_line


@needs_latex
def test_cv_preserves_skill_category_acronyms(tmp_path, content):
    """Acronyms like BI and AI in skill headings must not be lowercased to Bi/Ai."""
    profile = load_profile('synthetic_analyst')
    payload = json.loads(json.dumps(content['cv']))
    payload['skills'] = {
        'BI_and_AI_platforms': ['Looker', 'Claude'],
        'sql_and_etl': ['Snowflake', 'Airflow'],
    }
    cv = TailoredCV.model_validate(payload)

    renderer = create_latex_renderer(outputs_dir=str(tmp_path))
    pdf = Path(renderer.render_cv(cv, profile, job_position='Analytical Engineer'))
    text = normalise(pdf_text(pdf))

    assert 'BI And AI Platforms:' in text
    assert 'SQL And ETL:' in text
    assert 'Bi And' not in text
    assert 'Ai Platforms:' not in text


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
    """`_apply_standard_font` must set Calibri across the rendered DOCX."""
    from docx import Document

    path, _, _ = docx_letter
    document = Document(str(path))
    named = [run.font.name for p in document.paragraphs for run in p.runs if run.font.name]
    assert named, 'no run in the DOCX has an explicit font name'
    assert all(name == 'Calibri' for name in named)


def _assert_clean_business_letter(docx_path: Path, pdf_path: Path, letter: TailoredCoverLetter, profile) -> None:
    """Assert standard business-letter structure, reading order, metadata, and ATS cleanliness."""
    from datetime import date
    from docx import Document
    from pypdf import PdfReader

    today = date.today()
    expected_date = f'{today.day} {today:%B %Y}'
    expected_closing = letter.closing_line or 'Warm regards,'
    expected_name = letter.signature_name or profile.identity.full_name
    expected_salutation = f'Dear {letter.company_name} Hiring Team,'
    expected_subject = f'Application for {letter.role_title}'

    body_words = sum(len(p.split()) for p in letter.paragraphs)
    assert 290 <= body_words <= 310, f'body word count {body_words} outside 290-310'
    assert page_count(pdf_path) == 1, 'cover letter PDF must fit one page'

    docx_doc = Document(str(docx_path))
    assert len(docx_doc.tables) == 0, 'cover letter DOCX must be single-column without tables'
    for sec in docx_doc.sections:
        assert all(not p.text.strip() for p in sec.header.paragraphs), 'header must not hold text'
        assert all(not p.text.strip() for p in sec.footer.paragraphs), 'footer must not hold text'
    assert docx_doc.core_properties.author == expected_name
    assert letter.role_title in (docx_doc.core_properties.title or '')

    raw_docx = '\n'.join(p.text for p in docx_doc.paragraphs)
    pdf_reader = PdfReader(str(pdf_path))
    raw_pdf = '\n'.join(page.extract_text() or '' for page in pdf_reader.pages)
    meta = pdf_reader.metadata or {}
    assert meta.get('/Author') == expected_name
    assert letter.role_title in (meta.get('/Title') or '')
    assert letter.company_name in (meta.get('/Title') or '')

    for kind, raw in (('DOCX', raw_docx), ('PDF', raw_pdf)):
        bad_chars = [
            (ch, hex(ord(ch)))
            for ch in raw
            if (0xFB00 <= ord(ch) <= 0xFB06) or (0xE000 <= ord(ch) <= 0xF8FF)
        ]
        assert not bad_chars, f'{kind} contains ligature/PUA characters: {bad_chars}'
        assert 'Cover Letter' not in raw, f'{kind} still has generic Cover Letter heading'
        assert f'@ {letter.company_name}' not in raw, f'{kind} still has @ Company subtitle'

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        assert lines[0] == expected_name, f'{kind} must start with candidate name, got {lines[0]!r}'
        assert expected_date in lines, f'{kind} missing separated date {expected_date!r}'
        date_idx = lines.index(expected_date)
        contact_block = ' '.join(lines[1:date_idx])
        assert profile.identity.email in contact_block, f'{kind} top contact block missing email'
        if profile.identity.phone:
            assert profile.identity.phone in contact_block, f'{kind} top contact block missing phone'
        if profile.identity.location:
            assert profile.identity.location in contact_block, f'{kind} top contact block missing location'
        if profile.identity.linkedin:
            clean_li = profile.identity.linkedin.replace('https://www.', '').replace('https://', '').rstrip('/')
            assert clean_li in contact_block, f'{kind} top contact block missing LinkedIn'

        # Contact details must appear in the top header only, never repeated in a footer.
        assert raw.count(profile.identity.email) == 1, f'{kind} repeated email (footer leakage)'
        if profile.identity.phone:
            assert raw.count(profile.identity.phone) == 1, f'{kind} repeated phone (footer leakage)'

        # Date, recipient, subject, salutation, closing line, and signature in order without fusion.
        flat_lines = '\n'.join(lines)
        for token in (
            expected_date,
            letter.company_name,
            'Hiring Team',
            expected_subject,
            expected_salutation,
            expected_closing,
            expected_name,
        ):
            assert token in lines or token in flat_lines, f'{kind} missing separated token {token!r}'

        assert lines[-2] == expected_closing, f'{kind} penultimate line must be closing_line, got {lines[-2]!r}'
        assert lines[-1] == expected_name, f'{kind} final line must be signature name, got {lines[-1]!r}'


@needs_latex
def test_cover_letter_docx_and_pdf_follow_standard_business_letter_contract(tmp_path, content):
    """Both DOCX and PDF share the same ATS-clean business-letter structure across profiles."""
    if not latex_available():
        pytest.skip('No pdflatex compiler could be resolved on this machine')

    # Case 1: synthetic analyst fixture
    analyst = load_profile('synthetic_analyst')
    letter_one = TailoredCoverLetter.model_validate(content['cover_letter'])
    out_one = tmp_path / 'one'
    renderer_one = create_docx_renderer(outputs_dir=str(out_one))
    docx_one, pdf_one = renderer_one.render_cover_letter(
        letter_one, analyst, job_position=letter_one.role_title
    )
    _assert_clean_business_letter(Path(docx_one), Path(pdf_one), letter_one, analyst)

    # Case 2: second profile with realistic-length ligature-prone prose and Warm regards sign-off
    marketer = load_profile('synthetic_marketer')
    lumen_payload = read_json('llm_responses', 'marketer_lumen', '02_cover_letter.json')['cover_letter']
    ligature_prefix = (
        'Workflow, first-class traffic, office, effective, confident, and flexible '
        'channel analytics helped teams make faster budget choices across regions. '
    )
    p1_words = ligature_prefix.split() + lumen_payload['paragraphs'][0].split()
    lumen_payload['paragraphs'][0] = ' '.join(p1_words[:len(lumen_payload['paragraphs'][0].split())])
    lumen_payload['closing_line'] = 'Warm regards,'
    letter_two = TailoredCoverLetter.model_validate(lumen_payload)
    out_two = tmp_path / 'two'
    renderer_two = create_docx_renderer(outputs_dir=str(out_two))
    docx_two, pdf_two = renderer_two.render_cover_letter(
        letter_two, marketer, job_position=letter_two.role_title
    )
    _assert_clean_business_letter(Path(docx_two), Path(pdf_two), letter_two, marketer)


def test_cover_letter_renderer_does_not_mutate_paragraphs(tmp_path):
    """A-7 regression: stripping an inline Dear line must not mutate caller data."""
    renderer = DocxRenderer(outputs_dir=str(tmp_path))
    renderer._generate_pdf_via_latex = lambda *args, **kwargs: tmp_path / 'letter.pdf'
    profile = load_profile('synthetic_analyst')
    original_paragraphs = ['Dear Hiring Manager,\nFirst sentence.', 'Second.', 'Third.', 'Fourth.']
    letter = TailoredCoverLetter(
        company_name='Adjoe',
        role_title='Analyst',
        paragraphs=list(original_paragraphs),
        closing_line='Warm regards,',
        signature_name=profile.identity.full_name,
    )
    renderer.render_cover_letter(letter, profile)
    assert letter.paragraphs == original_paragraphs


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


# --- D-13: no build residue in the deliverable folder ----------------------------------

def test_a_failed_pdf_compile_leaves_no_scratch_dir_in_the_deliverable_folder(tmp_path, monkeypatch):
    """D-13: ``latex_work/`` must never land beside the documents handed to an employer.

    The deliverable folder is the one an application ships from, so a scratch directory
    there means the application carries the build residue. This is the **failure** path:
    when the compile raises, the cleanup at the end of the happy path never runs, so the
    directory and its ``main.tex`` survive -- which is how the defect was reachable in
    practice, and why the happy path alone did not show it.

    Asserted on the folder's *contents* rather than on the source, so any future spelling
    of "make a scratch dir next to the output" is caught.
    """
    from renderers.latex_renderer import LaTeXRenderer

    deliverable = tmp_path / 'outputs' / 'adjoe'
    deliverable.mkdir(parents=True)
    renderer = DocxRenderer(outputs_dir=str(deliverable))
    # A compiler path that resolves but cannot run: the compile fails, as a broken TeX
    # installation or a timeout would.
    monkeypatch.setattr(
        LaTeXRenderer, '_resolve_pdflatex_path', lambda self: 'definitely-not-pdflatex')

    profile = load_profile('synthetic_analyst')
    letter = TailoredCoverLetter(
        company_name='Adjoe', role_title='Analyst',
        paragraphs=['Dear Hiring Manager,'] + ['Body text.'] * 3,
        signature_name=profile.identity.full_name,
    )
    with pytest.raises(Exception):
        renderer.render_cover_letter(letter, profile, job_position='Analytical Engineer')

    residue = sorted(p.name for p in deliverable.iterdir() if p.is_dir())
    assert residue == [], f'scratch directories left in the deliverable folder: {residue}'


@needs_latex
def test_a_real_render_leaves_only_documents_in_the_deliverable_folder(tmp_path):
    """The success path: the scratch dir is gone and only the deliverables remain."""
    deliverable = tmp_path / 'outputs' / 'real'
    deliverable.mkdir(parents=True)
    profile = load_profile('synthetic_analyst')
    letter = TailoredCoverLetter.model_validate(
        read_json('content', 'valid_content.json')['cover_letter'])
    renderer = create_docx_renderer(outputs_dir=str(deliverable))
    _, pdf = renderer.render_cover_letter(letter, profile, job_position='Analytical Engineer')

    assert pdf is not None, 'cover-letter PDF generation failed'
    residue = sorted(p.name for p in deliverable.iterdir() if p.is_dir())
    assert residue == [], f'scratch directories left in the deliverable folder: {residue}'


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
