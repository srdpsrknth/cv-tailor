"""Render saved application content using cv-tailor's existing templates."""
import argparse
import json
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--content', required=True, type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--cv-only', action='store_true')
    group.add_argument('--cover-letter-only', action='store_true')
    parser.add_argument('--mirror-configured', action='store_true')
    args = parser.parse_args()
    root = args.project.resolve()
    content_path = args.content.resolve()
    folder = content_path.parent.parent
    if content_path.parent.name != 'source':
        parser.error('Keep editable content at <application-folder>/source/content.json')
    sys.path.insert(0, str(root / 'backend'))
    from dotenv import dotenv_values, load_dotenv
    load_dotenv(root / '.env', override=True)
    from services.profile_loader import load_profile
    from models.tailored_output import TailoredCV, TailoredCoverLetter
    from renderers import create_latex_renderer, create_docx_renderer
    from pypdf import PdfReader

    data = json.loads(content_path.read_text(encoding='utf-8-sig'))
    profile = load_profile(str(root / 'storage/profile/profile.yaml'))
    cv = TailoredCV.model_validate(data['cv'])
    cl = TailoredCoverLetter.model_validate(data['cover_letter'])
    role = data.get('role_title') or cl.role_title
    manifest_path = content_path.parent / 'generation_result.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig')) if manifest_path.exists() else {}
    manifest.update(company_name=cl.company_name, role_title=role, job_id=folder.name)
    generated = []
    if not args.cover_letter_only:
        renderer = create_latex_renderer(outputs_dir=str(folder))
        pdf = Path(renderer.render_cv(cv, profile, job_position=role))
        # The renderer deletes intermediate TEX. Reconstruct it before adjusting
        # project-heading pagination, without modifying the shared template.
        tex = renderer.jinja_env.get_template('main.tex.jinja2').render(
            **renderer._prepare_template_data(cv, profile))
        heading = r'{\small\textbf{\textcolor{accent}{Selected Projects:}}}'
        tex = tex.replace(heading, r'\needspace{1.8cm}' + '\n' + heading)
        tex_path = pdf.with_suffix('.tex')
        tex_path.write_text(tex, encoding='utf-8')
        renderer._compile_pdf(tex_path, tex_path.stem)
        pages = len(PdfReader(pdf).pages)
        manifest.update(cv_path=str(pdf), cv_pages=pages)
        generated.append(pdf)
        print(f'CV: {pages} pages; {pdf}')
        if pages > 2:
            print('REVIEW REQUIRED: shorten content and rerender to reach the two-page target.')
    if not args.cv_only:
        docx, pdf = create_docx_renderer(outputs_dir=str(folder)).render_cover_letter(cl, profile, job_position=role)
        manifest.update(cover_letter_path=docx, cl_pdf_path=pdf,
                        cover_letter_body_words=sum(len(p.split()) for p in cl.paragraphs))
        generated.append(Path(docx))
        if pdf:
            generated.append(Path(pdf))
            manifest['cover_letter_pdf_pages'] = len(PdfReader(pdf).pages)
        print(f'Cover letter: {len(cl.paragraphs)} paragraphs; {manifest["cover_letter_body_words"]} words')
        if len(cl.paragraphs) != 4 or not 290 <= manifest['cover_letter_body_words'] <= 310:
            print('REVIEW REQUIRED: default cover-letter target is four paragraphs and 290-310 words.')
    if args.mirror_configured:
        configured = dotenv_values(root / '.env').get('OUTPUTS_DIR')
        if configured:
            external = Path(configured)
            if not external.is_absolute():
                external = root / external
            destination = external.resolve() / folder.name
            if destination != folder:
                destination.mkdir(parents=True, exist_ok=True)
                for artifact in generated:
                    shutil.copy2(artifact, destination / artifact.name)
                manifest['mirror_folder'] = str(destination)
    # Preserve explicit user filenames stored during application migration.
    for key, preferred in manifest.get('artifact_filenames', {}).items():
        if key not in ('cv_path', 'cover_letter_path', 'cl_pdf_path') or not manifest.get(key):
            continue
        if Path(preferred).name != preferred:
            raise ValueError('artifact_filenames must contain filenames, not paths')
        original = Path(manifest[key])
        target = folder / preferred
        if original in generated and original != target:
            shutil.copy2(original, target)
            original.unlink()
            manifest[key] = str(target)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Keep compilation residue out of the deliverable folder.
    tex_path = next(iter(folder.glob('*_CV_*.tex')), None)
    if tex_path:
        tex_path.unlink()


if __name__ == '__main__':
    main()
