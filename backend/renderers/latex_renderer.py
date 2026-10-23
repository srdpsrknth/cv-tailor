"""
LaTeX renderer service for generating PDF CVs.
Handles Jinja2 template rendering and pdflatex compilation.
"""
import os
import re
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from models.tailored_output import TailoredCV
from models.profile import Profile
from utils.text import escape_latex, slugify


class LaTeXRendererError(Exception):
    """Custom exception for LaTeX rendering errors."""
    pass


class LaTeXRenderer:
    """Service for rendering CV to PDF using LaTeX."""

    def __init__(
        self,
        templates_dir: Optional[str] = None,
        outputs_dir: Optional[str] = None
    ):
        """
        Initialize LaTeX renderer.

        Args:
            templates_dir: Path to templates directory
            outputs_dir: Path to outputs directory
        """
        if templates_dir is None:
            templates_dir = Path(__file__).parent.parent.parent / "templates" / "cv"
        if outputs_dir is None:
            outputs_dir = Path(__file__).parent.parent.parent / "outputs"

        self.templates_dir = Path(templates_dir)
        self.outputs_dir = Path(outputs_dir)

        # Remember a possible MiKTeX default path for pdflatex
        local_app_data = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        self._pdflatex_candidates = [
            "pdflatex",
            str(Path(os.getenv("ProgramFiles", "C:/Program Files")) / "MiKTeX/miktex/bin/x64/pdflatex.exe"),
            str(Path(os.getenv("ProgramFiles(x86)", "C:/Program Files (x86)")) / "MiKTeX/miktex/bin/x64/pdflatex.exe"),
            str(local_app_data / "Programs/MiKTeX/miktex/bin/x64/pdflatex.exe"),
        ]

        # Ensure directories exist
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # Set up Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )

    def render_cv(
        self,
        tailored_cv: TailoredCV,
        profile: Profile,
        job_position: Optional[str] = None
    ) -> str:
        """
        Render CV to PDF.

        Args:
            tailored_cv: Tailored CV content
            profile: Base profile (for identity info)
            job_position: Optional job position for filename; defaults to tailored_cv.title

        Returns:
            Path to generated PDF file

        Raises:
            LaTeXRendererError: If rendering fails
        """
        job_pos = job_position or tailored_cv.title or "role"
        safe_job = self._slugify(job_pos)
        year = datetime.now().year

        try:
            # Load template
            template = self.jinja_env.get_template("main.tex.jinja2")
        except TemplateNotFound:
            raise LaTeXRendererError(
                f"Template not found: main.tex.jinja2 in {self.templates_dir}"
            )

        # Prepare template data
        template_data = self._prepare_template_data(tailored_cv, profile)

        # Render LaTeX content
        try:
            latex_content = template.render(**template_data)
        except Exception as e:
            raise LaTeXRendererError(f"Template rendering failed: {e}")

        # Save .tex file
        name_slug = self._slugify(profile.identity.full_name or "applicant")
        base_name = f"{year}_CV_{name_slug}_{safe_job}"
        tex_path = self.outputs_dir / f"{base_name}.tex"
        try:
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_content)
        except Exception as e:
            raise LaTeXRendererError(f"Failed to write .tex file: {e}")

        # Compile to PDF
        pdf_path = self._compile_pdf(tex_path, base_name)

        return str(pdf_path)

    def _prepare_template_data(
        self,
        tailored_cv: TailoredCV,
        profile: Profile
    ) -> Dict[str, Any]:
        """
        Prepare data for template rendering.

        Args:
            tailored_cv: Tailored CV content
            profile: Base profile

        Returns:
            Dictionary of template variables
        """
        # Extract identity from profile
        identity = profile.identity

        # Prepare experience data
        experiences = []
        for exp in tailored_cv.experience:
            exp_data = {
                "company": self._escape_latex(exp.company),
                "role": self._escape_latex(exp.role),
                "start_date": self._format_date(exp.start_date),
                "end_date": self._format_date(exp.end_date),
                "location": self._escape_latex(self._get_location_for_company(exp.company, profile)),
                "bullets": [self._escape_latex(b) for b in exp.bullets],
                "technologies": [self._escape_latex(t) for t in self._get_technologies_for_company(exp.company, profile)]
            }

            # Handle new projects structure
            if exp.projects:
                exp_data["projects"] = [
                    {
                        "name": self._escape_latex(proj.name),
                        "bullets": [self._escape_latex(b) for b in proj.bullets]
                    }
                    for proj in exp.projects
                ]
            else:
                exp_data["projects"] = []

            experiences.append(exp_data)

        # Build tagline with visa status
        tagline_base = tailored_cv.title or identity.tagline or ""
        # If there's a visa status and it's not already in the tagline, append it
        visa_status = tailored_cv.work_authorization if tailored_cv.work_authorization is not None else identity.visa_status
        if visa_status and visa_status not in tagline_base:
            tagline = f"{tagline_base} | {visa_status}" if tagline_base else visa_status
        else:
            tagline = tagline_base

        return {
            "name": self._escape_latex(identity.full_name),
            "tagline": self._escape_latex(tagline),
            "email": identity.email,
            "phone": identity.phone or "",
            "linkedin": identity.linkedin or "",
            "github": identity.github or "",
            "summary": [self._escape_latex(s) for s in tailored_cv.summary],
            "experience": experiences,
            "education": [
                {
                    "degree": self._escape_latex(edu.degree),
                    "institution": self._escape_latex(edu.institution),
                    "location": self._escape_latex(edu.location or ""),
                    "start_year": edu.start_year,
                    "end_year": edu.end_year
                }
                for edu in profile.education
            ] if tailored_cv.include_education else [],
            "certifications": [self._escape_latex(c) for c in profile.certifications] if tailored_cv.include_certifications else [],
            "skills": {
                self._escape_latex(category): [self._escape_latex(s) for s in skills]
                for category, skills in tailored_cv.skills.items()
            },
            "languages": [
                {
                    "name": self._escape_latex(lang.name),
                    "proficiency": self._escape_latex(lang.proficiency)
                }
                for lang in profile.languages
            ]
        }

    def _get_location_for_company(self, company: str, profile: Profile) -> str:
        """Get location for a specific company from profile."""
        for exp in profile.experience:
            if exp.company == company:
                return exp.location or ""
        return ""

    def _get_technologies_for_company(self, company: str, profile: Profile) -> list:
        """Get technologies for a specific company from profile."""
        for exp in profile.experience:
            if exp.company == company:
                return exp.technologies
        return []

    def _compile_pdf(self, tex_path: Path, base_name: str) -> Path:
        """
        Compile .tex file to PDF using pdflatex.

        Args:
            tex_path: Path to .tex file
            job_id: Job ID

        Returns:
            Path to generated PDF

        Raises:
            LaTeXRendererError: If compilation fails
        """
        pdf_path = self.outputs_dir / f"{base_name}.pdf"
        pdf_path = self._compile_pdf_pdflatex(tex_path, pdf_path)
        self._cleanup_intermediates(base_name=tex_path.stem)
        return pdf_path

    def _compile_pdf_pdflatex(self, tex_path: Path, pdf_path: Path) -> Path:
        """
        Compile LaTeX to PDF using pdflatex (fallback if tectonic unavailable).

        Args:
            tex_path: Path to .tex file
            pdf_path: Expected path to output .pdf file

        Returns:
            Path to generated PDF file

        Raises:
            LaTeXRendererError: If compilation fails
        """
        try:
            pdflatex_path = self._resolve_pdflatex_path()
            env = os.environ.copy()
            # Prepend common MiKTeX paths for this subprocess invocation
            env["PATH"] = os.pathsep.join([str(Path(pdflatex_path).parent), env.get("PATH", "")])
            env["TEXINPUTS"] = str(self.templates_dir) + os.pathsep + env.get("TEXINPUTS", "")

            # Run pdflatex twice for references
            for run in range(2):
                result = subprocess.run(
                    [
                        pdflatex_path,
                        "-interaction=nonstopmode",
                        "-output-directory", str(self.outputs_dir),
                        str(tex_path)
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env
                )

                if result.returncode != 0:
                    # Capture full error details
                    error_details = f"pdflatex compilation failed (run {run+1})\n"
                    error_details += f"Return code: {result.returncode}\n"
                    error_details += f"STDOUT:\n{result.stdout}\n"
                    error_details += f"STDERR:\n{result.stderr}\n"

                    # Also check for log file
                    log_path = self.outputs_dir / f"{tex_path.stem}.log"
                    if log_path.exists():
                        try:
                            log_content = log_path.read_text(encoding='utf-8', errors='ignore')
                            # Get last 100 lines of log
                            log_lines = log_content.split('\n')[-100:]
                            error_details += f"\nLast 100 lines of log:\n" + '\n'.join(log_lines)
                        except:
                            pass

                    raise LaTeXRendererError(error_details)

            # Verify PDF was created
            if not pdf_path.exists():
                raise LaTeXRendererError(
                    "PDF not generated by pdflatex. Check LaTeX errors above."
                )

            return pdf_path

        except FileNotFoundError:
            raise LaTeXRendererError(
                "pdflatex not found. Install MiKTeX or TeX Live:\n"
                "  - MiKTeX: https://miktex.org/download\n"
                "  - TeX Live: https://www.tug.org/texlive/"
            )
        except subprocess.TimeoutExpired:
            raise LaTeXRendererError("pdflatex compilation timed out")
        except Exception as e:
            raise LaTeXRendererError(f"pdflatex compilation error: {e}")

    def _cleanup_intermediates(self, base_name: str) -> None:
        """Remove LaTeX aux files, leaving only the PDF."""
        keep_extensions = {".pdf"}
        for path in self.outputs_dir.glob(f"{base_name}.*"):
            if path.suffix.lower() not in keep_extensions:
                try:
                    path.unlink()
                except OSError:
                    pass

    def _resolve_pdflatex_path(self) -> str:
        """Find a usable pdflatex executable path."""
        # 1) User override via LATEX_COMPILER path
        env_override = os.getenv("LATEX_COMPILER")
        if env_override:
            return env_override

        # 2) Look for known candidates
        for candidate in self._pdflatex_candidates:
            if shutil.which(candidate):
                return candidate
            if Path(candidate).exists():
                return candidate

        # 3) Last resort: system which
        which_path = shutil.which("pdflatex")
        if which_path:
            return which_path
        raise FileNotFoundError("pdflatex not found in PATH or default locations")

    @staticmethod
    def _slugify(text: str) -> str:
        """Create filesystem-safe slug for filenames."""
        return slugify(text)

    @staticmethod
    def _escape_latex(value: str) -> str:
        """Escape LaTeX special characters in free text."""
        return escape_latex(value)

    @staticmethod
    def _format_date(date_str: str) -> str:
        """
        Format date from YYYY-MM to 'Aug 2025' format.
        Handles 'present' as-is.

        Args:
            date_str: Date in YYYY-MM format or 'present'

        Returns:
            Formatted date string like 'Aug 2025' or 'present'
        """
        if not date_str or date_str.lower() == 'present':
            return 'present'

        try:
            # Parse YYYY-MM format
            date_obj = datetime.strptime(date_str, '%Y-%m')
            # Format as 'Aug 2025'
            return date_obj.strftime('%b %Y')
        except ValueError:
            # If parsing fails, return original string
            return date_str


def create_latex_renderer(
    templates_dir: Optional[str] = None,
    outputs_dir: Optional[str] = None
) -> LaTeXRenderer:
    """
    Create and return a LaTeXRenderer instance.

    Args:
        templates_dir: Optional templates directory path
        outputs_dir: Optional outputs directory path

    Returns:
        Initialized LaTeXRenderer
    """
    return LaTeXRenderer(templates_dir=templates_dir, outputs_dir=outputs_dir)
