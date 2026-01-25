"""
DOCX renderer for tailored cover letters using docxtpl.
"""
from __future__ import annotations

from datetime import date
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

from docxtpl import DocxTemplate
from docx import Document  # post-process font
from docx.shared import Pt

from models.profile import Profile
from models.tailored_output import TailoredCoverLetter


logger = logging.getLogger(__name__)


class DocxRendererError(Exception):
    """Raised when DOCX rendering fails."""
    pass


class DocxRenderer:
    """Render tailored cover letters to DOCX."""

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
        """Render a tailored cover letter to DOCX and optionally PDF.

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
            doc.render(context)
            doc.save(output_path)
        except Exception as e:  # pragma: no cover - render/save issues
            raise DocxRendererError(f"Failed to render DOCX: {e}")

        # Enforce Aptos font across the document
        try:
            self._apply_aptos_font(output_path)
        except Exception:
            # Non-fatal; keep the rendered file even if font post-processing fails
            pass

        # Tidy signature block: ensure no empty lines between name, phone, email
        try:
            self._tidy_signature_block(
                docx_path=output_path,
                name=context.get("candidate_name", ""),
                phone=context.get("candidate_phone", ""),
                email=context.get("candidate_email", ""),
            )
        except Exception:
            pass

        # Generate PDF version (required)
        pdf_path: Optional[str] = None
        try:
            pdf_file = self._export_pdf(output_path, tailored_cl, profile)
            pdf_path = str(pdf_file)
            logger.info(f"Generated cover letter PDF: {pdf_path}")
        except Exception as e:
            logger.error(f"Failed to generate cover letter PDF: {e}")
            raise DocxRendererError(f"PDF generation failed (required): {e}")

        return str(output_path), pdf_path

    def _build_context(self, tailored_cl: TailoredCoverLetter, profile: Profile) -> dict:
        paragraphs = tailored_cl.paragraphs or []
        return {
            "company_name": tailored_cl.company_name,
            "role_title": tailored_cl.role_title,
            "current_date": date.today().strftime("%B %d, %Y"),
            "hiring_manager": "Hiring Manager",
            "opening_paragraph": paragraphs[0] if len(paragraphs) > 0 else "",
            "body_paragraph_1": paragraphs[1] if len(paragraphs) > 1 else "",
            "body_paragraph_2": paragraphs[2] if len(paragraphs) > 2 else "",
            "closing_paragraph": paragraphs[3] if len(paragraphs) > 3 else "",
            "closing_line": tailored_cl.closing_line or "Sincerely,",
            "candidate_name": (tailored_cl.signature_name or profile.identity.full_name),
            "candidate_phone": profile.identity.phone or "",
            "candidate_email": profile.identity.email,
        }

    @staticmethod
    def _slugify(text: str) -> str:
        text = text.strip().lower()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text or "role"

    def _format_filename(self, company: str, job_position: str) -> str:
        year = date.today().year
        safe_company = self._slugify(company)
        safe_job = self._slugify(job_position)
        return f"{year}_cover_letter_{safe_company}_{safe_job}.docx"

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape LaTeX special characters in text."""
        # Order matters: backslash must be first
        replacements = [
            ("\\", r"\textbackslash{}"),
            ("&", r"\&"),
            ("%", r"\%"),
            ("$", r"\$"),
            ("#", r"\#"),
            ("_", r"\_"),
            ("{", r"\{"),
            ("}", r"\}"),
            ("~", r"\textasciitilde{}"),
            ("^", r"\textasciicircum{}"),
        ]
        for char, replacement in replacements:
            text = text.replace(char, replacement)
        return text

    def _apply_aptos_font(self, docx_path: Path) -> None:
        """Set Aptos font for all paragraphs and the Normal style."""
        docx = Document(str(docx_path))
        # Update Normal style
        try:
            normal = docx.styles["Normal"]
            font = normal.font
            font.name = "Aptos"
            # Optional: set size if desired; leaving as template default
            # font.size = Pt(12)
        except Exception:
            pass

        # Update all runs
        for para in docx.paragraphs:
            for run in para.runs:
                run.font.name = "Aptos"

        # Also update table text if present
        for table in docx.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.name = "Aptos"

        docx.save(str(docx_path))

    def _tidy_signature_block(self, docx_path: Path, name: str, phone: str, email: str) -> None:
        """Remove blank paragraphs between name, phone, and email at the end."""
        docx = Document(str(docx_path))

        # Helper: delete paragraph by element
        def _delete_paragraph(paragraph):
            p = paragraph._element
            p.getparent().remove(p)

        # Locate indices of signature lines (first match for each)
        indices = {}
        targets = {"name": name.strip(), "phone": phone.strip(), "email": email.strip()}
        for key, text in targets.items():
            if not text:
                continue
            for i, para in enumerate(docx.paragraphs):
                if para.text.strip() == text:
                    indices[key] = i
                    break

        ordered_keys = [k for k in ["name", "phone", "email"] if k in indices]
        if len(ordered_keys) >= 2:
            # Remove empty paragraphs between consecutive signature lines
            for a_key, b_key in zip(ordered_keys[:-1], ordered_keys[1:]):
                a_idx, b_idx = indices[a_key], indices[b_key]
                if b_idx > a_idx:
                    # Collect empties between
                    to_remove = []
                    for j in range(a_idx + 1, b_idx):
                        if docx.paragraphs[j].text.strip() == "":
                            to_remove.append(docx.paragraphs[j])
                    for para in to_remove:
                        _delete_paragraph(para)

        # Remove trailing empty paragraphs at the end of document
        changed = True
        while changed and len(docx.paragraphs) > 0:
            last = docx.paragraphs[-1]
            if last.text.strip() == "":
                _delete_paragraph(last)
            else:
                changed = False

        docx.save(str(docx_path))

    def _export_pdf(self, docx_path: Path, tailored_cl: TailoredCoverLetter, profile: Profile) -> Path:
        """
        Convert DOCX to PDF using LibreOffice (preferred) or LaTeX fallback.
        Raises exception if both methods fail.
        
        Args:
            docx_path: Path to DOCX file
            tailored_cl: Tailored cover letter data
            profile: Base profile for contact info
        
        Returns:
            Path to generated PDF file
            
        Raises:
            DocxRendererError: If PDF generation fails with all methods
        """
        pdf_path = docx_path.with_suffix(".pdf")
        
        # Method 1: Try LibreOffice
        try:
            logger.info(f"Attempting LibreOffice PDF conversion for {docx_path.name}")
            result = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(self.outputs_dir),
                    str(docx_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and pdf_path.exists():
                logger.info(f"✅ LibreOffice PDF generated: {pdf_path}")
                return pdf_path
        except FileNotFoundError:
            logger.warning("LibreOffice not found, trying LaTeX fallback...")
        except subprocess.TimeoutExpired:
            logger.warning("LibreOffice timeout, trying LaTeX fallback...")
        except Exception as e:
            logger.warning(f"LibreOffice failed ({e}), trying LaTeX fallback...")
        
        # Method 2: LaTeX fallback - generate simple LaTeX from cover letter text
        try:
            logger.info(f"Attempting LaTeX PDF generation for {docx_path.name}")
            pdf_path = self._generate_pdf_via_latex(docx_path, tailored_cl, profile)
            logger.info(f"✅ LaTeX PDF generated: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"LaTeX PDF generation also failed: {e}")
            raise DocxRendererError(f"PDF generation failed (both LibreOffice and LaTeX): {e}")

    def _generate_pdf_via_latex(self, docx_path: Path, tailored_cl: TailoredCoverLetter, profile: Profile) -> Path:
        """
        Generate PDF from cover letter using professional LaTeX template.
        Uses structured data from TailoredCoverLetter for accurate, complete rendering.
        
        Args:
            docx_path: Path to DOCX file (used for output naming only)
            tailored_cl: Tailored cover letter data with all paragraphs
            profile: Base profile for contact information
            
        Returns:
            Path to generated PDF file
            
        Raises:
            Exception: If LaTeX generation fails
        """
        import shutil
        
        # Extract structured data from TailoredCoverLetter and Profile
        candidate_name = profile.identity.full_name or "Applicant"
        role_title = tailored_cl.role_title or ""
        company_name = tailored_cl.company_name or "Hiring Manager"
        phone = profile.identity.phone or "+1 (555) 000-0000"
        email = profile.identity.email or "applicant@example.com"
        
        # Use all paragraphs from the tailored cover letter (not limited to 3)
        body_paras = tailored_cl.paragraphs or []
        
        # Create temporary working directory for LaTeX compilation
        work_dir = docx_path.parent / "latex_work"
        work_dir.mkdir(exist_ok=True)
        
        # Copy template files to working directory
        template_root = Path(__file__).resolve().parents[2] / "cover_letter_latex_template"
        setup_dir = work_dir / "setup"
        setup_dir.mkdir(exist_ok=True)
        
        try:
            # Copy template files
            if (template_root / "setup" / "preamble.tex").exists():
                shutil.copy(template_root / "setup" / "preamble.tex", setup_dir / "preamble.tex")
            if (template_root / "setup" / "macros.tex").exists():
                shutil.copy(template_root / "setup" / "macros.tex", setup_dir / "macros.tex")
        except Exception as e:
            logger.warning(f"Failed to copy template files: {e}. Will attempt inline compilation.")
        
        # Create LaTeX content using the template structure
        latex_content = r"""\input{setup/preamble.tex}
\input{setup/macros.tex}

\begin{document}

    """
        
        # Add title and job role (use "Cover Letter" as title, role as subtitle)
        escaped_role = self._escape_latex(role_title)
        latex_content += f"\\name{{Cover Letter}}{{{escaped_role}}}\n"
        
        # Add receiver/company
        escaped_company = self._escape_latex(company_name)
        latex_content += f"\\receiver{{{escaped_company}}}\n\n"
        
        # Add all body paragraphs with smaller font size
        for para in body_paras:
            # Escape LaTeX special characters
            escaped_para = self._escape_latex(para)
            # Paragraphs handled by \para macro which includes left-justify
            latex_content += f"\\para{{{escaped_para}}}\n"
        
        # Add closing signature using the signature macro
        closing_line = tailored_cl.closing_line or "Best regards,"
        signature_name = tailored_cl.signature_name or candidate_name
        escaped_closing = self._escape_latex(closing_line)
        escaped_signature = self._escape_latex(signature_name)
        latex_content += f"\n\\signature{{{escaped_closing}}}{{{escaped_signature}}}\n"
        
        # Add footer with contact info - NO LOCATION (empty string for first param)
        escaped_email = self._escape_latex(email)
        latex_content += f"\n\\bottom{{}}{{{phone}}}{{{escaped_email}}}\n"
        latex_content += r"""\end{document}"""
        
        # Write LaTeX file to working directory
        tex_path = work_dir / "main.tex"
        
        try:
            tex_path.write_text(latex_content, encoding="utf-8")
            logger.info(f"Created LaTeX file: {tex_path}")
        except Exception as e:
            raise Exception(f"Failed to write LaTeX file: {e}")
        
        # Compile with pdflatex
        try:
            result = subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-output-directory", str(work_dir),
                    str(tex_path)
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(work_dir)
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
            
            # Copy PDF to outputs directory
            shutil.copy(pdf_src, pdf_dst)
            logger.info(f"Generated professional template PDF: {pdf_dst}")
            
            # Clean up working directory
            try:
                shutil.rmtree(work_dir)
            except:
                pass
            
            return pdf_dst
            
        except FileNotFoundError:
            raise Exception("pdflatex not found. Install MiKTeX or TeX Live.")
        except subprocess.TimeoutExpired:
            raise Exception("pdflatex compilation timed out")
        except Exception as e:
            logger.error(f"LaTeX compilation error: {e}")
            raise Exception(f"LaTeX compilation error: {e}")


def create_docx_renderer(
    templates_dir: Optional[str] = None,
    outputs_dir: Optional[str] = None,
) -> DocxRenderer:
    """Factory for DocxRenderer."""
    return DocxRenderer(templates_dir=templates_dir, outputs_dir=outputs_dir)
