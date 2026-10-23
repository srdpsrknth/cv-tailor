"""Determinism tests for `scripts/render_application.py`.

This is the most-used revision route — re-render a saved `content.json` with no LLM call —
and it was entirely untested (ASSESSMENT.md §4). The contract under test:

    identical `content.json`  ->  identical page count

The script needs a whole project root (`.env`, `storage/profile/profile.yaml`, `backend/`),
so the fixture builds a synthetic one in a temp directory and runs the real script as a
subprocess. No network, no API key, no repository `outputs/` directory is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from support import ROOT, latex_available, page_count, pdf_text, normalise, read_json

# Every test here runs the real script, which compiles LaTeX. Marked so the fast lane
# (`-m "not requires_latex"`) can skip the slow path, and skipped outright without TeX.
pytestmark = [
    pytest.mark.requires_latex,
    pytest.mark.skipif(
        not latex_available(),
        reason='No pdflatex compiler could be resolved on this machine',
    ),
]

SCRIPT = ROOT / 'scripts' / 'render_application.py'


@pytest.fixture(scope='module')
def project(tmp_path_factory):
    """A throwaway project root containing only what the render script reads."""
    root = tmp_path_factory.mktemp('render_project')

    # The script does `sys.path.insert(root/'backend')` and imports from it, so the real
    # backend, templates and LaTeX cover-letter template must exist under the fake root.
    shutil.copytree(ROOT / 'backend', root / 'backend')
    shutil.copytree(ROOT / 'templates', root / 'templates')
    letter_template = ROOT / 'cover_letter_latex_template'
    if letter_template.exists():
        shutil.copytree(letter_template, root / 'cover_letter_latex_template')

    profile_dir = root / 'storage' / 'profile'
    profile_dir.mkdir(parents=True)
    shutil.copy2(
        ROOT / 'tests' / 'fixtures' / 'profiles' / 'synthetic_analyst.yaml',
        profile_dir / 'profile.yaml',
    )

    # A minimal .env. Deliberately no GEMINI_API_KEY: re-rendering must never need one.
    (root / '.env').write_text('GEMINI_MODEL=offline-fixture\n', encoding='utf-8')
    return root


def install_content(project: Path, name: str = 'application') -> Path:
    """Create `<project>/<name>/source/content.json` from the valid fixture."""
    folder = project / name
    source = folder / 'source'
    source.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'tests' / 'fixtures' / 'content' / 'valid_content.json',
                 source / 'content.json')
    return folder


def run_render(project: Path, folder: Path, *extra: str) -> subprocess.CompletedProcess:
    command = [
        sys.executable, str(SCRIPT),
        '--project', str(project),
        '--content', str(folder / 'source' / 'content.json'),
        *extra,
    ]
    environment = dict(os.environ)
    # A blank key proves the render path is offline; nothing may read it.
    environment.pop('GEMINI_API_KEY', None)
    environment['PYTHONIOENCODING'] = 'utf-8'
    return subprocess.run(
        command, capture_output=True, text=True, cwd=str(project),
        env=environment, timeout=300,
    )


def cv_pdf(folder: Path) -> Path:
    pdfs = [p for p in folder.glob('*.pdf') if 'cover_letter' not in p.name.lower()]
    assert pdfs, f'no CV PDF produced in {folder}'
    return pdfs[0]


def letter_pdf(folder: Path) -> Path:
    pdfs = [p for p in folder.glob('*.pdf') if 'cover_letter' in p.name.lower()]
    assert pdfs, f'no cover-letter PDF produced in {folder}'
    return pdfs[0]


# --- determinism ----------------------------------------------------------------------

def test_identical_content_produces_an_identical_page_count(project):
    """The headline determinism guarantee for the re-render path."""
    first = install_content(project, 'first')
    second = install_content(project, 'second')

    one = run_render(project, first, '--cv-only')
    two = run_render(project, second, '--cv-only')

    assert one.returncode == 0, one.stdout + one.stderr
    assert two.returncode == 0, two.stdout + two.stderr

    pages_one = page_count(cv_pdf(first))
    pages_two = page_count(cv_pdf(second))
    assert pages_one == pages_two, (
        f'identical content.json rendered to {pages_one} and {pages_two} pages'
    )


def test_identical_content_produces_identical_text(project):
    """Stronger than page count: the extracted text must match exactly."""
    first = install_content(project, 'text_first')
    second = install_content(project, 'text_second')

    assert run_render(project, first, '--cv-only').returncode == 0
    assert run_render(project, second, '--cv-only').returncode == 0

    assert normalise(pdf_text(cv_pdf(first))) == normalise(pdf_text(cv_pdf(second)))


def test_rerunning_in_place_is_stable(project):
    """Re-rendering the *same* folder must not drift the page count."""
    folder = install_content(project, 'in_place')

    assert run_render(project, folder, '--cv-only').returncode == 0
    first = page_count(cv_pdf(folder))

    assert run_render(project, folder, '--cv-only').returncode == 0
    second = page_count(cv_pdf(folder))

    assert first == second


# --- cover letter ---------------------------------------------------------------------

def test_cover_letter_renders_docx_and_pdf(project):
    folder = install_content(project, 'letter')
    result = run_render(project, folder, '--cover-letter-only')

    assert result.returncode == 0, result.stdout + result.stderr
    docx = list(folder.glob('*.docx'))
    assert docx, 'no DOCX produced'
    assert page_count(letter_pdf(folder)) == 1, 'fixture letter must fit one page'


def test_cover_letter_body_word_count_is_reported_and_enforced(project):
    folder = install_content(project, 'letter_words')
    result = run_render(project, folder, '--cover-letter-only')

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((folder / 'source' / 'generation_result.json').read_text(encoding='utf-8'))
    words = manifest['cover_letter_body_words']
    assert 290 <= words <= 310
    assert 'REVIEW REQUIRED' not in result.stdout, 'valid fixture letter was flagged for review'


# --- manifest behaviour ---------------------------------------------------------------

def test_manifest_records_paths_pages_and_words(project):
    folder = install_content(project, 'manifest')
    assert run_render(project, folder).returncode == 0

    manifest = json.loads((folder / 'source' / 'generation_result.json').read_text(encoding='utf-8'))
    assert manifest['job_id'] == folder.name
    assert manifest['company_name'] == 'Nordwind Analytics GmbH'
    assert manifest['role_title'] == 'Analytical Engineer'
    assert manifest['cv_pages'] == page_count(cv_pdf(folder))
    assert manifest['cover_letter_pdf_pages'] == 1
    assert Path(manifest['cv_path']).exists()
    assert Path(manifest['cover_letter_path']).exists()


def test_manifest_is_preserved_across_a_rerender(project):
    folder = install_content(project, 'manifest_twice')
    assert run_render(project, folder, '--cv-only').returncode == 0
    assert run_render(project, folder, '--cover-letter-only').returncode == 0

    manifest = json.loads((folder / 'source' / 'generation_result.json').read_text(encoding='utf-8'))
    assert manifest.get('cv_pages') == page_count(cv_pdf(folder))
    assert manifest.get('cover_letter_pdf_pages') == 1


def test_compilation_residue_is_cleaned_up(project):
    """The script must leave no .tex/.aux/.log in the deliverable folder."""
    folder = install_content(project, 'cleanup')
    assert run_render(project, folder).returncode == 0

    residue = [p.name for p in folder.iterdir()
               if p.suffix.lower() in {'.tex', '.aux', '.log', '.out', '.pdf.tmp'}]
    assert residue == [], f'compilation residue left behind: {residue}'


def test_three_page_content_is_flagged_for_review(project):
    """A CV over two pages must still render, but print an explicit warning."""
    folder = install_content(project, 'too_long')
    content_path = folder / 'source' / 'content.json'
    data = json.loads(content_path.read_text(encoding='utf-8'))

    # Inflate the CV well past two pages without touching factual fields.
    filler = ('Reporting and modelling work spanning warehouse layers, '
              'quality checks and stakeholder delivery across several teams. ')
    for experience in data['cv']['experience']:
        base = experience['bullets'] or ['Analytical delivery across reporting domains.']
        experience['bullets'] = [base[0] + ' ' + filler * 12 for _ in range(6)]
    content_path.write_text(json.dumps(data, indent=2), encoding='utf-8')

    result = run_render(project, folder, '--cv-only')

    assert result.returncode == 0, result.stdout + result.stderr
    assert page_count(cv_pdf(folder)) > 2
    assert 'REVIEW REQUIRED' in result.stdout


# --- failure paths --------------------------------------------------------------------

def test_content_outside_a_source_folder_is_rejected(project):
    folder = install_content(project, 'misplaced')
    moved = folder / 'content.json'
    shutil.move(str(folder / 'source' / 'content.json'), moved)

    command = [sys.executable, str(SCRIPT), '--project', str(project), '--content', str(moved)]
    result = subprocess.run(command, capture_output=True, text=True,
                            cwd=str(project), timeout=120)

    assert result.returncode != 0
    assert 'source/content.json' in (result.stderr + result.stdout)


def test_invalid_content_json_fails_without_writing_documents(project):
    folder = install_content(project, 'invalid')
    shutil.copy2(ROOT / 'tests' / 'fixtures' / 'content' / 'invalid_content.json',
                 folder / 'source' / 'content.json')

    result = run_render(project, folder, '--cv-only')

    assert result.returncode != 0
    assert not list(folder.glob('*.pdf')), 'documents were written from invalid content'
