"""
LaTeX renderer service for generating PDF CVs.
Handles Jinja2 template rendering and pdflatex compilation.
"""
import os
import re
import subprocess
import shutil
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from models.tailored_output import TailoredCV
from models.profile import Profile
from utils.text import escape_latex, format_skill_category, latex_url, slugify


def discover_texlive_pdflatex(
    windows_roots: Optional[list] = None, unix_roots: Optional[list] = None
) -> list:
    """Find ``pdflatex`` in per-year TeX Live directories, newest year first.

    TeX Live installs to ``<root>/<year>/bin/<platform>/pdflatex``:
    ``C:\\texlive\\2025\\bin\\windows`` or ``bin\\win64`` on Windows and
    ``/usr/local/texlive/2025/bin/<arch>-<os>/pdflatex`` on Linux and macOS. The year
    is a wildcard, so a new release needs no code change. The roots are parameters
    so tests can point them at a temporary directory.
    """
    if windows_roots is None:
        system_drive = os.getenv("SystemDrive", "C:")
        windows_roots = [Path(system_drive + "/texlive")]
    if unix_roots is None:
        unix_roots = [Path("/usr/local/texlive")]

    found: list = []
    for root in windows_roots:
        for pattern in ("*/bin/windows/pdflatex.exe", "*/bin/win64/pdflatex.exe"):
            found.extend(Path(root).glob(pattern))
    for root in unix_roots:
        found.extend(Path(root).glob("*/bin/*/pdflatex"))
    # Year directories are four digits, so a reverse string sort is newest first.
    return [str(path) for path in sorted(found, key=lambda path: str(path), reverse=True)]


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
        self.last_layout = None

        # Candidate pdflatex locations, most specific first. An explicit
        # LATEX_COMPILER always wins (see _resolve_pdflatex_path); these are the
        # conventional install locations per platform, and the final fallback is
        # PATH, so an unusual install still works if the binary is on PATH.
        #
        # macOS is listed explicitly because MacTeX does NOT put pdflatex on PATH by
        # default: it installs to /Library/TeX/texbin, which the TeX installer adds to
        # PATH only for login shells. A non-login shell -- which is what a script, an
        # IDE or a CI runner gets -- therefore finds nothing, and the failure looks
        # like "pdflatex not found" on a machine where LaTeX is correctly installed.
        # Homebrew's TeX is at /opt/homebrew/bin (Apple Silicon) or /usr/local/bin
        # (Intel); both are checked so neither architecture is assumed.
        local_app_data = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        self._pdflatex_candidates = [
            "pdflatex",
            # macOS -- MacTeX and the TeX Live installer both use this prefix.
            "/Library/TeX/texbin/pdflatex",
            "/usr/local/bin/pdflatex",
            "/opt/homebrew/bin/pdflatex",
            # Linux conventions.
            "/usr/bin/pdflatex",
            # Windows -- MiKTeX and TeX Live.
            str(Path(os.getenv("ProgramFiles", "C:/Program Files")) / "MiKTeX/miktex/bin/x64/pdflatex.exe"),
            str(Path(os.getenv("ProgramFiles(x86)", "C:/Program Files (x86)")) / "MiKTeX/miktex/bin/x64/pdflatex.exe"),
            str(local_app_data / "Programs/MiKTeX/miktex/bin/x64/pdflatex.exe"),
            # TeX Live installs into a per-year directory (newest year first).
            *discover_texlive_pdflatex(),
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

    def preview_cv_layout(
        self,
        tailored_cv: TailoredCV,
        profile: Profile,
        job_position: Optional[str] = None,
        *,
        layout_preset: str = "auto",
    ) -> tuple[bytes, dict]:
        """Compare experimental page breaks against the existing selector in scratch.

        The caller supplies the saved CV revision and matching profile snapshot.
        All rendered files are disposable, and the returned report contains no
        source prose. The returned PDF is a preview, with no save side effect.
        """
        with tempfile.TemporaryDirectory(prefix="cvtailor-layout-preview-") as scratch:
            renderer = LaTeXRenderer(templates_dir=self.templates_dir, outputs_dir=scratch)
            path = renderer._render_cv(
                tailored_cv, profile, job_position, layout_preset=layout_preset,
                explore_breaks=True,
            )
            report = renderer.last_layout
            if report["page_count"] > 2:
                raise LaTeXRendererError("No CV layout preview fit within two pages.")
            return Path(path).read_bytes(), report

    def render_cv(
        self,
        tailored_cv: TailoredCV,
        profile: Profile,
        job_position: Optional[str] = None,
        *,
        layout_preset: str = "auto",
        balance_cv_pages: bool = False,
    ) -> str:
        """
        Render CV to PDF.

        Args:
            tailored_cv: Tailored CV content
            profile: Base profile (for identity info)
            job_position: Optional job position for filename; defaults to tailored_cv.title
            layout_preset: Auto-select readable typography, or force a named preset.
            balance_cv_pages: Compare additional page breaks for more even pages.

        Returns:
            Path to generated PDF file

        Raises:
            LaTeXRendererError: If rendering fails
        """
        return self._render_cv(
            tailored_cv, profile, job_position, layout_preset=layout_preset,
            explore_breaks=balance_cv_pages,
        )

    def _render_cv(
        self, tailored_cv: TailoredCV, profile: Profile, job_position: Optional[str], *,
        layout_preset: str, explore_breaks: bool,
    ) -> str:
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

        from renderers.cv_layout import (
            PRESETS, measure_layout, preview_breaks, preview_quality_score, rank_layout,
        )
        from services.document_quality import inspect_document
        from pypdf import PdfWriter

        presets = [p for p in PRESETS if layout_preset in ("auto", p["name"])]
        if not presets:
            raise ValueError(f"Unknown CV layout preset: {layout_preset}")
        self.last_layout = None
        template_source = self.jinja_env.loader.get_source(self.jinja_env, "main.tex.jinja2")[0]
        configurable = "for section in cv_section_order" in template_source
        if not configurable and (profile.cv_hidden_sections or profile.cv_section_order):
            profile = profile.model_copy(update={"cv_section_order": [], "cv_hidden_sections": []})
        unsupported = [section for section in ("publications", "activities")
                       if f"section == '{section}'" not in template_source]
        if unsupported:
            profile = profile.model_copy(update={"cv_hidden_sections": [*profile.cv_hidden_sections, *unsupported]})
        template_data = self._prepare_template_data(tailored_cv, profile)
        name_slug = self._slugify(profile.identity.full_name or "applicant")
        base_name = f"{year}_CV_{name_slug}_{safe_job}"
        paragraphs, fields = self._extraction_contract(tailored_cv, profile)
        has_prose = any(re.search(r"\w", paragraph) for paragraph in paragraphs)
        visible_experience = tailored_cv.experience if "experience" in profile.visible_cv_sections() else []
        show_employer_projects = "employer_projects" not in profile.cv_hidden_sections
        employers = [exp.company for exp in visible_experience]
        projects = [(exp.company, project.name) for exp in visible_experience
                    for project in (exp.projects if show_employer_projects else [])]
        attempts = []
        candidates = []
        # Historical application-specific templates remain fixed rather than
        # pretending that they support the shared typography presets.
        adaptive = "layout.body_size" in template_source
        if not adaptive:
            presets = [next(p for p in PRESETS if p["name"] == "compact")]
        # Every trial and failure is disposable; never overwrite an existing CV
        # until a complete candidate has been checked and selected.
        with tempfile.TemporaryDirectory(prefix="cvtailor-layout-") as scratch:
            def trial(preset, break_before=None, split_before=None):
                directory = Path(scratch) / str(len(attempts))
                directory.mkdir()
                data = {**template_data, "layout": preset,
                        "break_before_employer_index": break_before,
                        "split_before": split_before}
                try:
                    latex_content = template.render(**data)
                except Exception as exc:
                    raise LaTeXRendererError(f"Template rendering failed: {exc}") from exc
                tex = directory / f"{base_name}.tex"
                tex.write_text(latex_content, encoding="utf-8")
                compiler = LaTeXRenderer(templates_dir=self.templates_dir, outputs_dir=directory)
                pdf = compiler._compile_pdf(tex, base_name)
                metrics = measure_layout(pdf, employer_names=employers, project_names=projects)
                # Both parsers must retain the supplied prose/fields in order.
                # Layout scoring cannot trade away content to improve fullness.
                extraction = inspect_document(pdf, expected_paragraphs=paragraphs,
                                              expected_fields=fields)
                text_ok = all(
                    check["status"] == "ok"
                    and check["page_count"] == metrics["page_count"]
                    and (not has_prose or check["word_retention"] == 1.0)
                    and (not has_prose or check["reading_order"] is True)
                    and not check["missing_fields"]
                    and not check["suspicious_glyphs"]
                    for check in extraction["engines"].values()
                )
                report = {**metrics, "schema_version": 1,
                          "preset": preset["name"] if adaptive else "custom",
                          "body_size": preset["body_size"] if adaptive else None,
                          "leading": preset["leading"] if adaptive else None,
                          "break_before_employer_index": break_before,
                          "extraction": extraction,
                          "text_preserved": text_ok}
                attempts.append({key: report[key] for key in (
                    "preset", "break_before_employer_index", "page_count",
                    "quality_score", "clipping", "orphan_headings", "text_preserved")})
                if explore_breaks:
                    report.update(
                        split_before={"role_index": split_before[0], "kind": split_before[1],
                                      "index": split_before[2]} if split_before else None,
                        blank_tails_mm=[page["blank_tail_mm"] for page in metrics["pages"]],
                        preview_score=preview_quality_score(metrics, continued=split_before is not None),
                    )
                    attempts[-1].update({key: report[key] for key in (
                        "split_before", "blank_tails_mm", "preview_score")})
                if text_ok:
                    index = next(i for i, p in enumerate(PRESETS) if p["name"] == preset["name"])
                    candidates.append((rank_layout(metrics, index), len(attempts), pdf, report))
                return report

            role_sizes = [(len(exp.bullets), len(exp.projects) if show_employer_projects else 0)
                          for exp in visible_experience]
            for preset in presets:
                report = trial(preset)
                # One semantic alternative per preset is enough to compare a
                # natural break with a clean boundary, without combinatorial search.
                splits = report.get("split_employer_indices", [])
                if adaptive and report["page_count"] == 2 and splits:
                    boundary = next((i for i in splits if i > 0), None)
                    if boundary is not None:
                        trial(preset, boundary)
                if explore_breaks and adaptive and "split_before" in template_source:
                    for split_before in preview_breaks(report, role_sizes):
                        trial(preset, split_before=split_before)
            if not candidates:
                raise LaTeXRendererError("No CV layout preserved the source text in both PDF parsers.")
            if explore_breaks:
                _, _, _, baseline = min(
                    (row for row in candidates if row[3]["split_before"] is None),
                    key=lambda row: (row[0], row[1]), default=(None, None, None, None),
                )
                # The exact same content, page-count and geometry gates apply to
                # every preview candidate, with only preferences changed.
                _, _, selected_pdf, selected = min(candidates, key=lambda row: (
                    rank_layout({**row[3], "quality_score": row[3]["preview_score"]}, row[0][-1]),
                    row[1],
                ))
                selected["baseline"] = None if baseline is None else {
                    key: baseline[key] for key in (
                        "preset", "break_before_employer_index", "page_count", "blank_tails_mm",
                        "clipping", "orphan_headings", "text_preserved", "preview_score",
                    )
                }
            else:
                _, _, selected_pdf, selected = min(candidates, key=lambda row: (row[0], row[1]))
            if selected["page_count"] <= 2 and (selected["clipping"] or selected["orphan_headings"]):
                raise LaTeXRendererError("No CV layout passed clipping and heading checks; review the editable content.")
            selected["attempts"] = attempts
            selected["section_order"] = list(template_data["cv_section_order"])
            selected["summary_visible"] = "summary" not in profile.cv_hidden_sections
            selected["employer_projects_visible"] = show_employer_projects
            if selected["page_count"] > 2:
                selected["warnings"].append("All readable presets exceed two pages; content shortening is required.")
            # Embed metrics in the artifact itself so every generation, CLI,
            # alias and mirror path can record the exact selected layout.
            writer = PdfWriter(clone_from=str(selected_pdf))
            writer.add_metadata({"/CVLayout": json.dumps(selected, sort_keys=True)})
            ready = Path(scratch) / "selected.pdf"
            with ready.open("wb") as stream:
                writer.write(stream)
            destination = self.outputs_dir / f"{base_name}.pdf"
            # Copy into this filesystem before the atomic replacement.
            with tempfile.NamedTemporaryFile(dir=self.outputs_dir, suffix=".pdf.tmp", delete=False) as staged:
                staged_path = Path(staged.name)
            try:
                shutil.copyfile(ready, staged_path)
                staged_path.replace(destination)
            finally:
                staged_path.unlink(missing_ok=True)
            self.last_layout = selected
        return str(destination)

    def _extraction_contract(self, cv, profile):
        """Source-backed prose and independently checked visible fields."""
        experience_paragraphs = []
        identity = profile.identity
        fields = {"Candidate name": identity.full_name, "Email": identity.email}
        for key, value in (("Headline", cv.title or identity.tagline),
                           ("Location", identity.location), ("Phone", identity.phone),
                           ("LinkedIn", identity.linkedin), ("GitHub", identity.github),
                           ("Authorization", cv.work_authorization if cv.work_authorization is not None else identity.visa_status)):
            if value:
                fields[key] = value.replace("https://www.", "").replace("https://", "") if key in ("LinkedIn", "GitHub") else value
        sections = profile.visible_cv_sections()
        for index, exp in enumerate(cv.experience if "experience" in sections else []):
            fields[f"Employer {index}"] = exp.company
            fields[f"Role {index}"] = exp.role
            fields[f"Start {index}"] = self._format_date(exp.start_date)
            fields[f"End {index}"] = self._format_date(exp.end_date)
            experience_paragraphs.extend(exp.bullets)
            for project in (exp.projects if "employer_projects" not in profile.cv_hidden_sections else []):
                experience_paragraphs.append(project.name)
                experience_paragraphs.extend(project.bullets)
            for item_index, item in enumerate(self._get_technologies_for_company(exp.company, profile)):
                fields[f"Technology {index}/{item_index}"] = item
        prose_by_section = {
            "experience": experience_paragraphs,
            "projects": [
                line for project in (cv.resolve_standalone_projects(profile) if "projects" in sections else [])
                for line in (project.name, *project.bullets)
            ],
        }
        paragraphs = list(cv.summary) if "summary" not in profile.cv_hidden_sections else []
        for section in sections:
            paragraphs.extend(prose_by_section.get(section, ()))
        for category, items in (cv.skills.items() if "skills" in sections else ()):
            fields[f"Skill category {category}"] = format_skill_category(category)
            for index, item in enumerate(items):
                fields[f"Skill {category}/{index}"] = item
        if cv.include_education and "education" in sections:
            for index, edu in enumerate(profile.education):
                fields[f"Degree {index}"] = edu.degree
                fields[f"Institution {index}"] = edu.institution
                fields[f"Education dates {index}"] = edu.date_range(" -- ")
                if edu.location:
                    fields[f"Education location {index}"] = edu.location
        if cv.include_certifications and "certifications" in sections:
            for index, item in enumerate(profile.certifications):
                fields[f"Certification {index}"] = item
        for index, language in enumerate(profile.languages if "languages" in sections else []):
            fields[f"Language {index}"] = f"{language.name}: {language.proficiency}"
        for section in ("publications", "activities"):
            if section in sections:
                for index, entry in enumerate(getattr(profile, section)):
                    fields[f"{section.title()} {index}"] = entry
        return paragraphs, fields

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
            if exp.projects and "employer_projects" not in profile.cv_hidden_sections:
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

        # Keep the professional headline separate from factual authorization.
        tagline_base = tailored_cv.title or identity.tagline or ""
        # If there's a visa status and it's not already in the tagline, append it
        visa_status = tailored_cv.work_authorization if tailored_cv.work_authorization is not None else identity.visa_status
        tagline = tagline_base

        return {
            "name": self._escape_latex(identity.full_name),
            "tagline": self._escape_latex(tagline),
            "location": self._escape_latex(identity.location or ""),
            "work_authorization": self._escape_latex(visa_status or ""),
            "email": identity.email,
            "phone": identity.phone or "",
            "linkedin": identity.linkedin or "",
            "github": identity.github or "",
            **self._contact_context(identity),
            "summary": [self._escape_latex(s) for s in tailored_cv.summary]
            if "summary" not in profile.cv_hidden_sections else [],
            "experience": experiences,
            "cv_section_order": profile.visible_cv_sections(),
            "publications": [self._escape_latex(entry) for entry in profile.publications],
            "activities": [self._escape_latex(entry) for entry in profile.activities],
            "standalone_projects": [
                {"name": self._escape_latex(project.name),
                 "bullets": [self._escape_latex(bullet) for bullet in project.bullets]}
                for project in tailored_cv.resolve_standalone_projects(profile)
            ],
            "education": [
                {
                    "degree": self._escape_latex(edu.degree),
                    "institution": self._escape_latex(edu.institution),
                    "location": self._escape_latex(edu.location or ""),
                    "dates": edu.date_range(" -- "),
                    # Keep these keys for historical/custom templates.
                    "start_year": edu.start_year,
                    "end_year": edu.end_date_label() if edu.ongoing else edu.end_year,
                }
                for edu in profile.education
            ] if tailored_cv.include_education else [],
            "certifications": [self._escape_latex(c) for c in profile.certifications] if tailored_cv.include_certifications else [],
            "skills": {
                self._escape_latex(format_skill_category(category)): [self._escape_latex(s) for s in skills]
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

    @staticmethod
    def _contact_context(identity) -> Dict[str, str]:
        """LaTeX-safe display text and ``\\href`` targets for the contact fields.

        ``*_display`` is escaped body text; ``*_url`` is safe inside ``\\href{...}``.
        """
        email = (identity.email or "").strip()
        phone = (identity.phone or "").strip()
        linkedin = (identity.linkedin or "").strip()
        github = (identity.github or "").strip()

        def short(url: str) -> str:
            return re.sub(r"^https?://(?:www\.)?", "", url)

        return {
            "email_display": escape_latex(email),
            "email_url": latex_url("mailto:" + email) if email else "",
            "phone_display": escape_latex(phone),
            "phone_url": latex_url("tel:" + re.sub(r"\s+", "", phone)) if phone else "",
            "linkedin_display": escape_latex(short(linkedin)),
            "linkedin_url": latex_url(linkedin),
            "github_display": escape_latex(short(github)),
            "github_url": latex_url(github),
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
        Compile LaTeX to PDF using pdflatex.

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

            # Project continuation labels use shipped page references. Repeat
            # until auxiliary references settle (normally two passes), allowing
            # another pass if a continuation label itself changes wrapping.
            aux_path = self.outputs_dir / f"{tex_path.stem}.aux"
            for run in range(4):
                previous_aux = aux_path.read_bytes() if aux_path.exists() else None
                result = subprocess.run(
                    [
                        pdflatex_path,
                        "-interaction=nonstopmode",
                        "-output-directory", str(self.outputs_dir),
                        str(tex_path)
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
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

                current_aux = aux_path.read_bytes() if aux_path.exists() else None
                if run >= 1 and current_aux == previous_aux:
                    break
            else:
                raise LaTeXRendererError("PDF page references did not stabilize after four passes.")

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
