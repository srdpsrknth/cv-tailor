"""Sequential Word/text companions for resume autofill. No model or office calls."""

from pathlib import Path
import re

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from models.profile import Profile, certification_label, entry_bullets, entry_text
from renderers.cv_sections import (
    DATE_RANGE_SEPARATOR, LABELS, SECTION_TITLES, education_highlights_line,
    find_profile_project, format_month_year, project_as_subheading, project_heading,
    project_meta, project_technologies_line, role_company_label,
)
from models.tailored_output import TailoredCV
from utils.calendar import calendar_year
from utils.text import format_skill_category, slugify


#: Word list style for detail bullets under a publication or activity entry, and the
#: matching indent in the plain-text copy.
NESTED_BULLET_STYLE = 'List Bullet 2'
TEXT_NESTED_PREFIX = '  - '


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
    """Expand unambiguous ISO months (locale independent); preserve other dates verbatim."""
    return format_month_year(value)


def render_upload_cv(cv: TailoredCV, profile: Profile, outputs_dir, job_position=None, *, timezone_name="UTC", extra_acronyms=()) -> dict:
    """Render the accepted CV wording into one-column body paragraphs.

    The text companion is the exact paragraph text of the DOCX. No facts are
    shortened to fit; callers must review pagination separately from the PDF.
    """
    folder = Path(outputs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    identity = profile.identity
    year = calendar_year(timezone_name)
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
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2', 'List Bullet', 'List Bullet 2'):
        style = doc.styles[name]
        style.font.name = 'Arial'
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt(10.5 if name in ('Normal', 'List Bullet', 'List Bullet 2') else 11)
        style.paragraph_format.space_after = Pt(2)
        style.paragraph_format.space_before = Pt(0)
    for name in ('Heading 1', 'Heading 2'):
        # Word keeps a heading on the page of what follows it, so no heading is stranded.
        doc.styles[name].paragraph_format.keep_with_next = True
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

    def add_heading(value, style='Heading 1'):
        return add(value, style, keep=True)

    add(identity.full_name, 'Title')
    add(cv.title or identity.tagline)
    contact = [identity.location, identity.phone, identity.email]
    add(' | '.join(value for value in contact if value))
    links = [identity.linkedin, identity.github]
    add(' | '.join(value for value in links if value))
    authorization = cv.work_authorization if cv.work_authorization is not None else identity.visa_status
    if authorization:
        add(f"{LABELS['work_authorization']} {authorization}")
    if cv.summary and "summary" not in profile.cv_hidden_sections:
        # The PDF prints the summary as an unlabelled paragraph. The Word/text copy keeps
        # an explicit heading on purpose: ATS parsers locate the summary by its heading.
        add_heading(SECTION_TITLES['summary'])
        add(' '.join(cv.summary))
    for section in profile.visible_cv_sections():
        if section == 'experience':
            if cv.experience:
                add_heading(SECTION_TITLES['experience'])
            for exp in cv.experience:
                add_heading(exp.role, 'Heading 2')
                # Exact identity avoids borrowing location/tools from another role at
                # the same employer. Ambiguous matches contribute no inferred metadata.
                matches = [row for row in profile.experience if
                           (row.company, row.role, row.start_date, row.end_date) ==
                           (exp.company, exp.role, exp.start_date, exp.end_date)]
                if not matches:
                    company_matches = [row for row in profile.experience if row.company == exp.company]
                    matches = company_matches if len(company_matches) == 1 else []
                original = matches[0] if len(matches) == 1 else None
                dates = DATE_RANGE_SEPARATOR.join(readable_date(d) for d in (exp.start_date, exp.end_date) if d)
                metadata = [exp.company, dates, original.location if original else None]
                p = doc.add_paragraph(' | '.join(value for value in metadata if value))
                employer_projects = exp.projects if "employer_projects" not in profile.cv_hidden_sections else []
                p.paragraph_format.keep_with_next = bool(exp.bullets or employer_projects or (original and original.location))
                for bullet in exp.bullets:
                    add(bullet, 'List Bullet')
                company_label = role_company_label(original, exp.company)
                subheading = project_as_subheading(exp, show_projects=bool(employer_projects))
                for project in employer_projects:
                    extras = find_profile_project(original, project.name)
                    if subheading:
                        heading = add(project.name, keep=True)
                        for run in heading.runs:
                            run.italic = True
                    else:
                        add_heading(f"{LABELS['project']} {project.name} ({company_label})", 'Heading 2')
                    if extras is not None and project_meta(extras):
                        add(project_meta(extras), keep=True)
                    for bullet in project.bullets:
                        add(bullet, 'List Bullet')
                    if extras is not None:
                        add(project_technologies_line(extras))
                if original and original.technologies:
                    add(f"{LABELS['technologies']} " + ', '.join(original.technologies))
        elif section == 'projects':
            standalone_projects = cv.resolve_standalone_projects(profile)
            if standalone_projects:
                add_heading(SECTION_TITLES['projects'])
                for project in standalone_projects:
                    add_heading(project_heading(project), 'Heading 2')
                    for bullet in project.bullets:
                        add(bullet, 'List Bullet')
                    add(project_technologies_line(project))
        elif section == 'education':
            if cv.include_education and profile.education:
                add_heading(SECTION_TITLES['education'])
                for edu in profile.education:
                    add_heading(edu.degree, 'Heading 2')
                    add(' | '.join(value for value in (
                        edu.institution, edu.date_range(DATE_RANGE_SEPARATOR), edu.location
                    ) if value))
                    add(education_highlights_line(edu))
        elif section == 'certifications':
            if cv.include_certifications and profile.certifications:
                add_heading(SECTION_TITLES['certifications'])
                for cert in profile.certifications:
                    add(certification_label(cert), 'List Bullet')
        elif section == 'skills':
            if cv.skills:
                add_heading(SECTION_TITLES['skills'])
                for category, skills in cv.skills.items():
                    add(format_skill_category(category, extra_acronyms) + ': ' + ', '.join(skills))
        elif section == 'languages':
            if profile.languages:
                add_heading(SECTION_TITLES['languages'])
                for language in profile.languages:
                    add(f'{language.name}: {language.proficiency}')
        elif section in ('publications', 'activities'):
            entries = getattr(profile, section)
            if entries:
                add_heading(SECTION_TITLES[section])
                for entry in entries:
                    add(entry_text(entry), 'List Bullet')
                    for bullet in entry_bullets(entry):
                        add(bullet, NESTED_BULLET_STYLE)
    doc.save(paths['cv_upload_docx_path'])
    # The text copy is the paragraph text of the DOCX; a second-level bullet keeps its
    # nesting as an indented plain "  - " (no symbols an ATS parser could drop or garble).
    Path(paths['cv_upload_text_path']).write_text(
        '\n'.join(TEXT_NESTED_PREFIX + p.text if p.style.name == NESTED_BULLET_STYLE else p.text
                  for p in doc.paragraphs) + '\n', encoding='utf-8')
    return paths
