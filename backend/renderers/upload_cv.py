"""Sequential Word/text companions for resume autofill. No model or office calls."""

from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from models.profile import Profile
from models.tailored_output import TailoredCV
from utils.text import format_skill_category, slugify


def _use_unicode_bullets(doc: Document, font_name: str = 'Arial') -> None:
    """Use a Unicode bullet in the body font instead of Symbol PUA (U+F0B7)."""
    try:
        numbering = doc.part.numbering_part.element
    except (NotImplementedError, KeyError, AttributeError):
        return
    for lvl in numbering.iter(qn('w:lvl')):
        text = lvl.find(qn('w:lvlText'))
        if text is not None and text.get(qn('w:val')) in ('\uf0b7', 'o', '\uf0a7'):
            text.set(qn('w:val'), '\u2022')
        for fonts in lvl.iter(qn('w:rFonts')):
            for attr in ('ascii', 'hAnsi', 'cs', 'eastAsia'):
                fonts.set(qn(f'w:{attr}'), font_name)
            fonts.attrib.pop(qn('w:hint'), None)


def readable_date(value: str) -> str:
    """Expand unambiguous ISO months; preserve other source dates verbatim."""
    if value.lower() == 'present':
        return 'Present'
    if re.fullmatch(r'\d{4}-\d{2}', value):
        months = ('January February March April May June July August September '
                  'October November December').split()
        month = int(value[5:])
        if 1 <= month <= 12:
            return f'{months[month - 1]} {value[:4]}'
    return value


def render_upload_cv(cv: TailoredCV, profile: Profile, outputs_dir, job_position=None) -> dict:
    """Render the accepted CV wording into one-column body paragraphs.

    The text companion is the exact paragraph text of the DOCX. No facts are
    shortened to fit; callers must review pagination separately from the PDF.
    """
    folder = Path(outputs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    identity = profile.identity
    year = datetime.now(ZoneInfo('Europe/Berlin')).year
    stem = f'{year}_CV_{slugify(identity.full_name)}_{slugify(job_position or cv.title or "role")}_upload'
    paths = {'cv_upload_docx_path': str(folder / f'{stem}.docx'),
             'cv_upload_text_path': str(folder / f'{stem}.txt')}
    doc = Document()
    doc.core_properties.author = identity.full_name or ''
    doc.core_properties.title = f"{identity.full_name} - CV - {job_position or cv.title or 'Role'}"
    _use_unicode_bullets(doc)
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.5)
    section.left_margin = section.right_margin = Cm(1.7)
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2', 'List Bullet'):
        style = doc.styles[name]
        style.font.name = 'Arial'
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt(10.5 if name in ('Normal', 'List Bullet') else 11)
        style.paragraph_format.space_after = Pt(2)
        style.paragraph_format.space_before = Pt(0)
    for name in ('Heading 1', 'Heading 2'):
        doc.styles[name].font.color.rgb = RGBColor.from_string('00004D')
        doc.styles[name].font.bold = True
        doc.styles[name].paragraph_format.space_before = Pt(5 if name == 'Heading 1' else 3)
    doc.styles['Title'].font.size = Pt(21)
    doc.styles['Title'].font.bold = True
    doc.styles['Title'].font.color.rgb = RGBColor.from_string('00004D')
    doc.styles['Normal'].paragraph_format.line_spacing = 1.0
    # Built-in Title can inherit a decorative bottom border from the Word theme.
    for style in (doc.styles['Title'],):
        ppr = style.element.find(qn('w:pPr'))
        if ppr is not None:
            border = ppr.find(qn('w:pBdr'))
            if border is not None:
                ppr.remove(border)

    def add(value, style=None, keep=False):
        if value:
            paragraph = doc.add_paragraph(value, style)
            paragraph.paragraph_format.widow_control = True
            paragraph.paragraph_format.keep_with_next = keep
            return paragraph

    add(identity.full_name, 'Title')
    add(cv.title or identity.tagline)
    contact = [identity.location, identity.phone, identity.email]
    add(' | '.join(value for value in contact if value))
    links = [identity.linkedin, identity.github]
    add(' | '.join(value for value in links if value))
    authorization = cv.work_authorization if cv.work_authorization is not None else identity.visa_status
    if authorization:
        add(f'Work authorization: {authorization}')
    if cv.summary:
        add('Summary', 'Heading 1')
        add(' '.join(cv.summary))
    if cv.experience:
        add('Work Experience', 'Heading 1')
    for exp in cv.experience:
        add(exp.role, 'Heading 2', keep=True)
        # Exact identity avoids borrowing location/tools from another role at
        # the same employer. Ambiguous matches contribute no inferred metadata.
        matches = [row for row in profile.experience if
                   (row.company, row.role, row.start_date, row.end_date) ==
                   (exp.company, exp.role, exp.start_date, exp.end_date)]
        if not matches:
            company_matches = [row for row in profile.experience if row.company == exp.company]
            matches = company_matches if len(company_matches) == 1 else []
        original = matches[0] if len(matches) == 1 else None
        dates = ' - '.join(readable_date(d) for d in (exp.start_date, exp.end_date) if d)
        metadata = [exp.company, dates, original.location if original else None]
        p = doc.add_paragraph(' | '.join(value for value in metadata if value))
        p.paragraph_format.keep_with_next = bool(exp.bullets or exp.projects or (original and original.location))
        for bullet in exp.bullets:
            add(bullet, 'List Bullet')
        for project in exp.projects:
            add(f'Project: {project.name} ({exp.company})', 'Heading 2', keep=True)
            for bullet in project.bullets:
                add(bullet, 'List Bullet')
        if original and original.technologies:
            add('Technologies: ' + ', '.join(original.technologies))
    if cv.include_education and profile.education:
        add('Education', 'Heading 1')
        for edu in profile.education:
            add(edu.degree, 'Heading 2', keep=True)
            add(' | '.join(value for value in (
                edu.institution, f'{edu.start_year} - {edu.end_year}', edu.location
            ) if value))
    if cv.include_certifications and profile.certifications:
        add('Certifications', 'Heading 1')
        for cert in profile.certifications:
            add(cert, 'List Bullet')
    if cv.skills:
        add('Skills', 'Heading 1')
        for category, skills in cv.skills.items():
            add(format_skill_category(category) + ': ' + ', '.join(skills))
    if profile.languages:
        add('Languages', 'Heading 1')
        for language in profile.languages:
            add(f'{language.name}: {language.proficiency}')
    doc.save(paths['cv_upload_docx_path'])
    Path(paths['cv_upload_text_path']).write_text(
        '\n'.join(p.text for p in doc.paragraphs) + '\n', encoding='utf-8')
    return paths
