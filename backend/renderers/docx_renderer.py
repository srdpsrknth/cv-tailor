"""
DOCX renderer for tailored cover letters using docxtpl.
"""
from __future__ import annotations

from datetime import date
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from docxtpl import DocxTemplate
from docx import Document  # post-process font & properties
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from models.profile import Profile
from models.tailored_output import TailoredCoverLetter
from utils.text import escape_latex, slugify


logger = logging.getLogger(__name__)


class DocxRendererError(Exception):
    """Raised when DOCX rendering fails."""
    pass


class DocxRenderer:
    """Render tailored cover letters to DOCX and PDF."""

    def __init__(
        self,
        templates_dir: Optional[str] = None,
        outputs_dir: Optional[str] = None,
    ) -> None:
        base_dir = Path(__file__).parent.parent.parent
        self.templates_dir = Path(templates_dir) if templates_dir else base_dir / "templates" / "cover_letter"
        self.outputs_dir = Path(outputs_dir) if outputs_dir else base_dir / "outputs"

        self.template_path = self.templates_dir / "cover_letter.docx"
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        if not self.template_path.exists():
            raise DocxRendererError(
                f"Cover letter template not found at {self.template_path}"
            )

    def render_cover_letter(
        self,
        tailored_cl: TailoredCoverLetter,
        profile: Profile,
        job_position: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Render a tailored cover letter to DOCX and PDF.

        Args:
            tailored_cl: Tailored cover letter content
            profile: Base profile (for contact info)
            job_position: Optional job position to use in filename; defaults to tailored_cl.role_title

        Returns:
            Tuple of (docx_path, pdf_path_or_none) as strings
        """
        job_pos = job_position or tailored_cl.role_title
        company = tailored_cl.company_name
        output_path = self.outputs_dir / self._format_filename(company, job_pos)

        try:
            doc = DocxTemplate(str(self.template_path))
        except Exception as e:  # pragma: no cover - template load issues
            raise DocxRendererError(f"Failed to load template: {e}")

        context = self._build_context(tailored_cl, profile)

        try:
            # Preserve XML-sensitive characters in company names and prose.
            doc.render(context, autoescape=True)
            doc.save(output_path)
        except Exception as e:  # pragma: no cover - render/save issues
            raise DocxRendererError(f"Failed to render DOCX: {e}")

        # Enforce standard Calibri font, document properties, and clean paragraphs.
        try:
            self._apply_standard_font(
                output_path,
                font_name="Calibri",
                candidate_name=context.get("candidate_name", ""),
                role_title=context.get("role_title", ""),
                company_name=context.get("company_name", ""),
            )
        except Exception as e:  # pragma: no cover - non-fatal post-process guard
            logger.warning(f"Failed to apply DOCX font/metadata post-processing: {e}")

        try:
            self._tidy_signature_block(docx_path=output_path)
        except Exception as e:  # pragma: no cover - non-fatal post-process guard
            logger.warning(f"Failed to tidy DOCX paragraphs: {e}")

        # Generate PDF version using LaTeX (required)
        pdf_path: Optional[str] = None
        try:
            pdf_file = self._generate_pdf_via_latex(output_path, tailored_cl, profile)
            pdf_path = str(pdf_file)
            logger.info(f"Generated cover letter PDF: {pdf_path}")
        except Exception as e:
            logger.error(f"Failed to generate cover letter PDF: {e}")
            raise DocxRendererError(f"PDF generation failed: {e}")

        return str(output_path), pdf_path

    @staticmethod
    def _format_render_date() -> str:
        """Return today's date for the letter header.

        Render-time ``date.today()`` is intentional: generating or re-rendering an
        application on the day of submission stamps that submission date into both the
        DOCX and the PDF (e.g. ``17 November 2026``). Re-rendering an older folder on a
        later date updates the letter date accordingly.
        """
        today = date.today()
        return f"{today.day} {today:%B %Y}"

    @staticmethod
    def _format_sender_contact_line(profile: Profile) -> str:
        """Build a plain-text single-line contact header from non-empty profile fields."""
        identity = profile.identity
        parts = []
        for value in (identity.location, identity.phone, identity.email):
            cleaned = (value or "").strip()
            if cleaned:
                parts.append(cleaned)
        linkedin = (identity.linkedin or "").strip()
        if linkedin:
            clean_linkedin = re.sub(r"^https?://(?:www\.)?", "", linkedin).rstrip("/")
            if clean_linkedin:
                parts.append(clean_linkedin)
        return " | ".join(parts)

    @staticmethod
    def _extract_salutation_and_paragraphs(
        tailored_cl: TailoredCoverLetter,
    ) -> tuple[str, list[str]]:
        """Derive the salutation and body paragraphs without mutating ``tailored_cl``."""
        company_name = (tailored_cl.company_name or "").strip()
        salutation = (
            f"Dear {company_name} Hiring Team," if company_name else "Dear Hiring Team,"
        )
        body_paras = [p for p in (tailored_cl.paragraphs or [])]
        if body_paras and body_paras[0].lstrip().startswith("Dear"):
            lines = body_paras[0].lstrip().split("\n", 1)
            salutation = lines[0].strip()
            if len(lines) > 1 and lines[1].strip():
                body_paras[0] = lines[1].strip()
            else:
                body_paras = body_paras[1:]
        return salutation, body_paras

    def _build_context(self, tailored_cl: TailoredCoverLetter, profile: Profile) -> dict:
        salutation, paragraphs = self._extract_salutation_and_paragraphs(tailored_cl)
        company_name = (tailored_cl.company_name or "").strip()
        role_title = (tailored_cl.role_title or "").strip()
        candidate_name = (
            tailored_cl.signature_name or profile.identity.full_name or "Applicant"
        ).strip()
        closing_line = (tailored_cl.closing_line or "Warm regards,").strip()
        closing_para = (
            "\n\n".join(paragraphs[3:])
            if len(paragraphs) > 4
            else (paragraphs[3] if len(paragraphs) > 3 else "")
        )
        return {
            "company_name": company_name,
            "role_title": role_title,
            "current_date": self._format_render_date(),
            "recipient_line": "Hiring Team",
            "salutation_line": salutation,
            "hiring_manager": f"{company_name} Hiring Team" if company_name else "Hiring Team",
            "sender_contact_line": self._format_sender_contact_line(profile),
            "opening_paragraph": paragraphs[0] if len(paragraphs) > 0 else "",
            "body_paragraph_1": paragraphs[1] if len(paragraphs) > 1 else "",
            "body_paragraph_2": paragraphs[2] if len(paragraphs) > 2 else "",
            "closing_paragraph": closing_para,
            "closing_line": closing_line,
            "candidate_name": candidate_name,
            "candidate_phone": profile.identity.phone or "",
            "candidate_email": profile.identity.email or "",
        }

    @staticmethod
    def _slugify(text: str) -> str:
        return slugify(text)

    def _format_filename(self, company: str, job_position: str) -> str:
        year = date.today().year
        safe_company = self._slugify(company)
        safe_job = self._slugify(job_position)
        return f"{year}_cover_letter_{safe_company}_{safe_job}.docx"

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape LaTeX special characters in text."""
        return escape_latex(text)

    @staticmethod
    def _set_run_font_family(element, font_name: str) -> None:
        rpr = element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.insert(0, rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), font_name)

    def _apply_standard_font(
        self,
        docx_path: Path,
        font_name: str = "Calibri",
        *,
        candidate_name: str = "",
        role_title: str = "",
        company_name: str = "",
    ) -> None:
        """Set a standard sans-serif font across the document and populate metadata."""
        docx = Document(str(docx_path))
        try:
            normal = docx.styles["Normal"]
            normal.font.name = font_name
            self._set_run_font_family(normal.element, font_name)
        except Exception:
            pass

        for para in docx.paragraphs:
            for run in para.runs:
                run.font.name = font_name
                self._set_run_font_family(run._element, font_name)

        for table in docx.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.name = font_name
                            self._set_run_font_family(run._element, font_name)

        props = docx.core_properties
        if candidate_name:
            props.author = candidate_name
        title_parts = [p for p in (candidate_name, "Cover Letter", role_title, company_name) if p]
        if title_parts:
            props.title = " - ".join(title_parts)
        if role_title or company_name:
            subject_bits = [b for b in (role_title, f"at {company_name}" if company_name else "") if b]
            props.subject = f"Cover letter for {' '.join(subject_bits)}"

        docx.save(str(docx_path))

    def _apply_aptos_font(self, docx_path: Path) -> None:
        """Backwards-compatible alias for applying the standard DOCX font."""
        self._apply_standard_font(docx_path, font_name="Calibri")

    def _tidy_signature_block(
        self,
        docx_path: Path,
        name: str = "",
        phone: str = "",
        email: str = "",
    ) -> None:
        """Remove empty paragraphs left by optional fields and clean trailing blanks."""
        docx = Document(str(docx_path))

        for para in list(docx.paragraphs):
            if para.text.strip() == "":
                p = para._element
                parent = p.getparent()
                if parent is not None:
                    parent.remove(p)

        docx.save(str(docx_path))

    def _generate_pdf_via_latex(
        self,
        docx_path: Path,
        tailored_cl: TailoredCoverLetter,
        profile: Profile,
    ) -> Path:
        """Generate a standard business-letter PDF via LaTeX matching the DOCX layout."""
        candidate_name = (
            tailored_cl.signature_name or profile.identity.full_name or "Applicant"
        ).strip()
        role_title = (tailored_cl.role_title or "").strip()
        company_name = (tailored_cl.company_name or "").strip()
        contact_line = self._format_sender_contact_line(profile)
        current_date = self._format_render_date()
        closing_line = (tailored_cl.closing_line or "Warm regards,").strip()
        salutation, body_paras = self._extract_salutation_and_paragraphs(tailored_cl)

        title_parts = [p for p in (candidate_name, "Cover Letter", role_title, company_name) if p]
        pdf_title = " - ".join(title_parts)
        subject_bits = [b for b in (role_title, f"at {company_name}" if company_name else "") if b]
        pdf_subject = f"Cover letter for {' '.join(subject_bits)}".strip()

        # Scratch space for the pdflatex run, deliberately **outside** the deliverable
        # folder: `docx_path.parent` is the folder handed to an employer, so building
        # there ships `main.tex`, the setup/ copies and the .aux/.log residue with every
        # application. `tempfile` also keeps two concurrent renders from colliding.
        work_dir = Path(tempfile.mkdtemp(prefix="cvtailor_latex_"))

        # Copy template files to working directory
        template_root = Path(__file__).resolve().parents[2] / "cover_letter_latex_template"
        setup_dir = work_dir / "setup"
        setup_dir.mkdir(exist_ok=True)

        try:
            if (template_root / "setup" / "preamble.tex").exists():
                shutil.copy(template_root / "setup" / "preamble.tex", setup_dir / "preamble.tex")
            if (template_root / "setup" / "macros.tex").exists():
                shutil.copy(template_root / "setup" / "macros.tex", setup_dir / "macros.tex")
        except Exception as e:
            logger.warning(f"Failed to copy template files: {e}. Will attempt inline compilation.")

        escaped_name = self._escape_latex(candidate_name)
        escaped_contact = self._escape_latex(contact_line)
        escaped_date = self._escape_latex(current_date)
        escaped_company = self._escape_latex(company_name)
        escaped_role = self._escape_latex(role_title)
        escaped_salutation = self._escape_latex(salutation)
        escaped_closing = self._escape_latex(closing_line)
        escaped_title = self._escape_latex(pdf_title)
        escaped_subject = self._escape_latex(pdf_subject)

        lines = [
            r"\input{setup/preamble.tex}",
            r"\input{setup/macros.tex}",
            r"\hypersetup{",
            f"  pdftitle={{{escaped_title}}},",
            f"  pdfauthor={{{escaped_name}}},",
            f"  pdfsubject={{{escaped_subject}}},",
            r"  hidelinks",
            r"}",
            "",
            r"\begin{document}",
            f"\\senderblock{{{escaped_name}}}{{{escaped_contact}}}",
            f"\\letterdate{{{escaped_date}}}",
            f"\\recipientblock{{{escaped_company}}}{{Hiring Team}}",
            f"\\subjectline{{Application for {escaped_role}}}" if role_title else r"\subjectline{Application}",
            f"\\salutation{{{escaped_salutation}}}",
        ]
        for para in body_paras:
            lines.append(f"\\para{{{self._escape_latex(para)}}}")
        lines.append(f"\\signature{{{escaped_closing}}}{{{escaped_name}}}")
        lines.append(r"\end{document}")
        latex_content = "\n".join(lines)

        tex_path = work_dir / "main.tex"

        try:
            tex_path.write_text(latex_content, encoding="utf-8")
            logger.info(f"Created LaTeX file: {tex_path}")
        except Exception as e:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise Exception(f"Failed to write LaTeX file: {e}")

        # Compile with pdflatex. The scratch directory is removed on **every** exit path,
        # success or failure: a failed compile used to leave `main.tex` and `setup/`
        # behind, and while it was created inside the deliverable folder that residue
        # shipped with the application.
        try:
            from renderers.latex_renderer import LaTeXRenderer
            compiler = LaTeXRenderer()._resolve_pdflatex_path()
            env = os.environ.copy()
            env["PATH"] = os.pathsep.join([str(Path(compiler).parent), env.get("PATH", "")])
            result = subprocess.run(
                [
                    compiler,
                    "-interaction=nonstopmode",
                    "-output-directory", str(work_dir),
                    str(tex_path)
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(work_dir),
                env=env,
            )

            pdf_src = work_dir / "main.pdf"
            pdf_dst = docx_path.with_suffix(".pdf")

            if result.returncode != 0:
                logger.warning(f"pdflatex returned code {result.returncode}")
                logger.warning(f"stderr: {result.stderr[:500]}")
                if "error" in result.stderr.lower() and not pdf_src.exists():
                    raise Exception(f"pdflatex error: {result.stderr[:200]}")

            if not pdf_src.exists():
                raise Exception("PDF not generated by pdflatex")

            shutil.copy(pdf_src, pdf_dst)
            logger.info(f"Generated cover letter PDF: {pdf_dst}")

            return pdf_dst

        except FileNotFoundError:
            raise Exception("pdflatex not found. Install MiKTeX or TeX Live.")
        except subprocess.TimeoutExpired:
            raise Exception("pdflatex compilation timed out")
        except Exception as e:
            logger.error(f"LaTeX compilation error: {e}")
            raise Exception(f"LaTeX compilation error: {e}")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


def create_docx_renderer(
    templates_dir: Optional[str] = None,
    outputs_dir: Optional[str] = None,
) -> DocxRenderer:
    """Factory for DocxRenderer."""
    return DocxRenderer(templates_dir=templates_dir, outputs_dir=outputs_dir)
