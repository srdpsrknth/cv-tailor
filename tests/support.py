"""Shared helpers for the characterization suite.

Nothing in here touches the network, the real LLM or the repository's `outputs/`
directory. Paths are derived from this file so the suite is portable.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"
PROFILES = FIXTURES / "profiles"
JOB_DESCRIPTIONS = FIXTURES / "job_descriptions"
LLM_RESPONSES = FIXTURES / "llm_responses"
CONTENT = FIXTURES / "content"

sys.path.insert(0, str(ROOT / "backend"))

# --- LaTeX availability -------------------------------------------------------------

def latex_available() -> bool:
    """True when a `pdflatex` the renderer can actually resolve exists."""
    from renderers.latex_renderer import LaTeXRenderer

    try:
        LaTeXRenderer(outputs_dir=str(ROOT / ".runtime-probe"))._resolve_pdflatex_path()
    except Exception:
        return False
    return True


# --- fixture loading ----------------------------------------------------------------

def fixture_path(*parts: str) -> Path:
    path = FIXTURES.joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"Missing fixture: {path}")
    return path


def read_text(*parts: str) -> str:
    return fixture_path(*parts).read_text(encoding="utf-8")


def read_json(*parts: str) -> dict:
    return json.loads(read_text(*parts))


def job_description(name: str) -> str:
    return (JOB_DESCRIPTIONS / f"{name}.txt").read_text(encoding="utf-8")


def load_profile(name: str = "synthetic_analyst"):
    """Load one of the synthetic profiles through the production loader."""
    from services.profile_loader import load_profile as _load

    return _load(str(PROFILES / f"{name}.yaml"))


def recorded_session(name: str = "analyst_nordwind") -> "RecordedSession":
    return RecordedSession(LLM_RESPONSES / name)


class RecordedSession:
    """A recorded provider transcript for one synthetic application.

    ``responses`` and ``fenced`` are returned in the order the manifest lists them,
    which is the order ``tailor_documents`` consumes them.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.manifest = json.loads((directory / "responses.json").read_text(encoding="utf-8"))

    @property
    def steps(self) -> list[dict]:
        return self.manifest["steps"]

    def step_text(self, attempt: str) -> str:
        for step in self.steps:
            if step["attempt"] == attempt:
                return (self.directory / step["file"]).read_text(encoding="utf-8")
        raise KeyError(f"No recorded step {attempt!r} in {self.directory.name}")

    def step_payload(self, attempt: str) -> dict:
        return json.loads(self.step_text(attempt))

    def texts(self) -> list[str]:
        return [self.step_text(step["attempt"]) for step in self.steps]

    @property
    def profile(self):
        return load_profile(Path(self.manifest["profile"]).stem)

    @property
    def job_description_text(self) -> str:
        return (FIXTURES / self.manifest["job_description"]).read_text(encoding="utf-8")


# --- offline LLM double -------------------------------------------------------------

class OfflineGemini:
    """Stands in for :class:`GeminiService` without any network access.

    Replays recorded responses in order. Every call is recorded so tests can assert on
    the prompt that was actually sent — which is how profile/JD/country context
    propagation is checked. If the caller exhausts the transcript, the last response is
    replayed and :attr:`exhausted` becomes true, so an unexpected extra call shows up as
    an assertion failure rather than a hang or a real request.
    """

    def __init__(self, texts, inputs_per_call: int = 100, outputs_per_call: int = 20):
        self.texts = list(texts)
        self.inputs_per_call = inputs_per_call
        self.outputs_per_call = outputs_per_call
        self.prompts: list[str] = []
        self.exhausted = False

    def _call_gemini(self, prompt, *args, **kwargs):
        self.prompts.append(prompt)
        index = len(self.prompts) - 1
        if index >= len(self.texts):
            self.exhausted = True
            index = len(self.texts) - 1
        return self.texts[index], self.inputs_per_call, self.outputs_per_call

    def calculate_token_usage(self, **kwargs):
        from models.requests import TokenUsage

        cv_in = kwargs.get('cv_input_tokens', 0)
        cv_out = kwargs.get('cv_output_tokens', 0)
        cl_in = kwargs.get('cl_input_tokens', 0)
        cl_out = kwargs.get('cl_output_tokens', 0)
        return TokenUsage(
            **kwargs,
            total_tokens=cv_in + cv_out + cl_in + cl_out,
            model_name='offline-fixture',
        )

    # Convenience for assertions.
    @property
    def call_count(self) -> int:
        return len(self.prompts)

    @property
    def last_prompt(self) -> str:
        return self.prompts[-1]

    def prompts_containing(self, needle: str) -> list[str]:
        return [p for p in self.prompts if needle in p]


# --- rendering helpers --------------------------------------------------------------

def page_count(pdf_path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_path)).pages)


def pdf_text(pdf_path: Path) -> str:
    """Extract all text from a PDF, page by page, joined with newlines."""
    return "\n".join(pdf_pages_text(pdf_path))


def pdf_pages_text(pdf_path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [de_ligature(page.extract_text() or "") for page in reader.pages]


def pdf_page_height(pdf_path: Path) -> float:
    from pypdf import PdfReader

    return float(PdfReader(str(pdf_path)).pages[0].mediabox.height)


def text_is_within_bounds(pdf_path: Path) -> bool:
    """True when every glyph in the PDF sits inside its page box.

    Catches content that overflows the bottom or right edge — the "clipping" failure
    mode called out in AGENTS.md. Requires the optional `pypdf` visitor API.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    ok = True
    for page in reader.pages:
        box = page.mediabox
        left, bottom = float(box.left), float(box.bottom)
        right, top = float(box.right), float(box.top)
        pending: list = []

        def visitor(text, cm, tm, font_dict, font_size, _page=page):
            if not text.strip():
                return
            # Text-space origin transformed by the current matrices.
            if cm:
                x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
                y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
            else:
                x, y = tm[4], tm[5]
            if x < left - 1 or x > right + 1 or y < bottom - 1 or y > top + 1:
                pending.append((x, y))

        page.extract_text(visitor_text=visitor)
        if pending:
            ok = False
    return ok


def docx_text(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    return "\n".join(parts)


def make_blank_pdf(path: Path, pages: int) -> str:
    """A synthetic blank PDF, used only where real rendering is irrelevant."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)
    return str(path)


def copy_content_json(destination: Path, name: str = "valid_content.json") -> Path:
    """Install a `content.json` in the ``<app>/source/`` layout the renderer expects."""
    source_dir = destination / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    target = source_dir / "content.json"
    shutil.copy2(CONTENT / name, target)
    return target


#: Ligature and typographic characters that pdflatex output introduces during text
#: extraction. Normalising them keeps assertions on plain ASCII needles reliable.
_LIGATURES = {
    '\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl', '\ufb03': 'ffi',
    '\ufb04': 'ffl', '\ufb05': 'ft', '\ufb06': 'st',
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '-', '\u00a0': ' ', '\u2026': '...',
}


def de_ligature(text: str) -> str:
    for source, replacement in _LIGATURES.items():
        text = text.replace(source, replacement)
    return text


def normalise(text: str) -> str:
    """Collapse whitespace and ligatures so PDF extraction quirks do not break assertions."""
    return " ".join(de_ligature(text).split())


def contains_all(haystack: str, needles) -> Optional[str]:
    """Return the first missing needle, or None when all are present."""
    flat = normalise(haystack)
    for needle in needles:
        if normalise(needle) not in flat:
            return needle
    return None
