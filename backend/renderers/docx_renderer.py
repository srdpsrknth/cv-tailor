"""
DOCX renderer for tailored cover letters using docxtpl.
"""
from __future__ import annotations

from datetime import date
import re
import subprocess
from pathlib import Path
from typing import Optional

from docxtpl import DocxTemplate
from docx import Document  # post-process font
from docx.shared import Pt

from models.profile import Profile
from models.tailored_output import TailoredCoverLetter


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
    ) -> str:
        """Render a tailored cover letter to DOCX.

        Args:
            tailored_cl: Tailored cover letter content
            profile: Base profile (for contact info)
            job_position: Optional job position to use in filename; defaults to tailored_cl.role_title

        Returns:
            Path to generated DOCX file as string
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

        # Generate PDF version as well
        pdf_path: Optional[Path] = None
        try:
            pdf_path = self._export_pdf(output_path)
        except Exception:
            # Non-fatal; DOCX is the primary output
            pass

        return str(output_path)

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

    def _export_pdf(self, docx_path: Path) -> Path:
        """
        Convert DOCX to PDF using LibreOffice (if available).
        Returns PDF path if successful; raises exception otherwise.
        """
        try:
            pdf_path = docx_path.with_suffix(".pdf")
            
            # Try LibreOffice CLI
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
                return pdf_path
            else:
                raise Exception(f"LibreOffice conversion failed: {result.stderr}")
                
        except FileNotFoundError:
            # LibreOffice not installed; fallback: skip PDF generation
            raise DocxRendererError("LibreOffice not found. DOCX export only.")
        except Exception as e:
            raise DocxRendererError(f"PDF export failed: {e}")


def create_docx_renderer(
    templates_dir: Optional[str] = None,
    outputs_dir: Optional[str] = None,
) -> DocxRenderer:
    """Factory for DocxRenderer."""
    return DocxRenderer(templates_dir=templates_dir, outputs_dir=outputs_dir)
