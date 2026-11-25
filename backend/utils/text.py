"""Small shared text helpers.

These were duplicated across the renderers and the tailoring service (D-12):
two near-identical ``_escape_latex`` implementations and three ``_slugify``
implementations with subtly different behaviour. One definition each keeps
filenames and escaping consistent across every renderer.
"""
from __future__ import annotations

import logging
import re
import unicodedata

__all__ = ["slugify", "escape_latex", "latex_url", "format_skill_category"]

_WHITESPACE_RUN = re.compile(r"[^a-z0-9]+")

#: Acronyms kept upper-case in a skill category heading. Domain-neutral on purpose: data,
#: software, marketing, health and regulatory terms sit side by side so no one field is
#: privileged. Lower-case tool names ("dbt") are handled separately.
_UPPERCASE_ACRONYMS = frozenset({
    # data and software
    "AI", "BI", "SQL", "ETL", "ELT", "LLM", "LLMS", "MCP", "CI", "CD", "CI/CD", "AWS",
    "GCP", "API", "APIS", "ML", "NLP", "UX", "UI", "SDK", "ERP",
    # marketing and analytics
    "GA4", "CRM", "KPI", "KPIS", "SEO", "SEM", "ROAS", "CAC", "LTV",
    # health, clinical and regulatory
    "EHR", "EMR", "OMOP", "FHIR", "HL7", "CDISC", "SDTM", "GXP", "MDR", "IVDR",
    "ISO", "QMS", "SOP", "SOPS", "CAPA", "GDPR", "HIPAA", "ICD", "SNOMED", "LOINC",
    "CRO", "EDC", "CTMS", "GMP", "GLP", "FDA", "EMA",
})

#: Characters with a special meaning in LaTeX, escaped in one pass (``str.translate``) so that
#: the replacement text is never itself re-escaped (e.g. the backslash in ``\\&``).
_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

#: Typographic characters pdflatex (inputenc utf8 + T1) cannot typeset on its own, mapped to
#: LaTeX equivalents. ``None`` means "drop". Accented Latin letters, en/em dashes, curly
#: quotes and the euro sign are handled natively by inputenc and are not listed here.
_LATEX_UNICODE = {
    "\u2192": r"$\rightarrow$", "\u2190": r"$\leftarrow$", "\u2194": r"$\leftrightarrow$",
    "\u21d2": r"$\Rightarrow$", "\u2191": r"$\uparrow$", "\u2193": r"$\downarrow$",
    "\u2265": r"$\geq$", "\u2264": r"$\leq$", "\u2260": r"$\neq$", "\u2248": r"$\approx$",
    "\u00b1": r"$\pm$", "\u00d7": r"$\times$", "\u00f7": r"$\div$", "\u2212": r"$-$",
    "\u221e": r"$\infty$", "\u2022": r"\textbullet{}", "\u25cf": r"\textbullet{}",
    "\u00b7": r"\textperiodcentered{}", "\u22c5": r"\textperiodcentered{}",
    "\u2023": r"\textbullet{}", "\u25aa": r"\textbullet{}",
    "\u2122": r"\texttrademark{}", "\u00ae": r"\textregistered{}", "\u00a9": r"\textcopyright{}",
    "\u2032": r"$'$", "\u2033": r"$''$",
    "\u00a0": "~", "\u202f": "~", "\u2007": "~", "\u2009": r"\,", "\u200a": r"\,",
    "\u2000": " ", "\u2001": " ", "\u205f": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ", "\u2005": " ", "\u2006": " ", "\u2008": " ",
    "\u3000": " ", "\u2028": " ", "\u2029": " ",
    "\u2010": "-", "\u2011": "-", "\u2012": "--", "\u2015": "---", "\u00ad": None,
    "\u200b": None, "\u200c": None, "\u200d": None, "\u2060": None, "\ufeff": None,
    "\u200e": None, "\u200f": None, "\u2061": None, "\u2062": None, "\u2063": None,
    "\ufe0f": None, "\ufe0e": None,
}

#: Unicode ranges pdflatex (inputenc utf8 + T1) typesets without help: Latin-1 Supplement
#: through Latin Extended-A (minus the few T1 gaps handled above) and common punctuation.
_NATIVE_PUNCTUATION = frozenset("\u2013\u2014\u2018\u2019\u201a\u201c\u201d\u201e\u2020\u2021\u2026\u2030\u2039\u203a\u20ac")

#: Latin Extended-A letters with no glyph in the T1 encoding (verified by compiling).
_T1_GAPS = frozenset("\u0126\u0127\u0138\u013f\u0140\u0149\u0166\u0167\u017f")

_log = logging.getLogger(__name__)


def _is_native(char: str) -> bool:
    code = ord(char)
    if char in ("\n", "\t") or 0x20 <= code < 0x7F:
        return True
    return (0xA1 <= code <= 0x17F and char not in _T1_GAPS) or char in _NATIVE_PUNCTUATION


def _build_latex_table() -> dict[int, str]:
    table = {ord(c): r for c, r in _LATEX_UNICODE.items()}
    table.update({ord(c): r for c, r in _LATEX_SPECIALS.items()})
    return {k: ("" if v is None else v) for k, v in table.items()}


_LATEX_TABLE = _build_latex_table()


def slugify(text: str) -> str:
    """Return a filesystem-safe slug, falling back to ``"role"``.

    Collapses every run of non-alphanumeric characters to a single underscore and
    strips leading/trailing underscores, so ``"Nordwind Analytics GmbH"`` becomes
    ``"nordwind_analytics_gmbh"``.
    """
    return _WHITESPACE_RUN.sub("_", (text or "").strip().lower()).strip("_") or "role"


def escape_latex(value: str) -> str:
    """Make free text safe for pdflatex (inputenc utf8 + T1).

    Special characters are escaped exactly once (single-pass translation), common
    typographic symbols are mapped to LaTeX equivalents, invisible characters are removed
    and anything the font cannot render (emoji, CJK, ...) becomes ``?`` with a logged
    warning instead of aborting the compile. Non-string values are returned unchanged so
    callers can pass optional fields straight through.
    """
    if not isinstance(value, str):
        return value
    text = unicodedata.normalize("NFC", value)
    out: list[str] = []
    dropped: set[str] = set()
    for char in text:
        mapped = _LATEX_TABLE.get(ord(char))
        if mapped is not None:
            out.append(mapped)
        elif _is_native(char):
            out.append(char)
        elif unicodedata.category(char) in ("Cc", "Cf", "Mn", "Me"):
            continue
        else:
            out.append("?")
            dropped.add(char)
    if dropped:
        _log.warning(
            "Replaced %d unsupported character(s) with '?' for LaTeX: %s",
            len(dropped), ", ".join(f"U+{ord(c):04X}" for c in sorted(dropped)),
        )
    return "".join(out)


def latex_url(value: str) -> str:
    """Return ``value`` safe as the target of ``\\href{...}`` (hyperref).

    ``%`` and ``#`` must be backslash-escaped inside an ``\\href`` target; whitespace and
    characters that cannot appear in a URL (braces, backslash, non-ASCII) are percent-encoded.
    """
    if not isinstance(value, str):
        return ""
    out = []
    for char in value.strip():
        if char in "%#":
            out.append("\\" + char)
        elif char.isalnum() and ord(char) < 0x80 or char in "-._~:/?@!$&'()*+,;=[]":
            out.append(char)
        else:
            out.append("".join(f"%{b:02X}" for b in char.encode("utf-8")).replace("%", "\\%"))
    return "".join(out)


def _format_category_token(token: str, shouting: bool = False) -> str:
    if not token:
        return token
    word = token.rstrip(",;:.")
    if word != token and word:  # "sop," -> format "sop", keep the punctuation
        return _format_category_token(word, shouting) + token[len(word):]
    upper = token.upper()
    if upper in _UPPERCASE_ACRONYMS:
        return upper
    if token.lower() == "dbt":
        return "dbt"
    if len(token) >= 2 and token.isalpha() and token.isupper() and not shouting:
        return token  # an acronym the author already wrote in capitals ("DICOM", "PROMS")
    if "/" in token:
        return "/".join(_format_category_token(part, shouting) for part in token.split("/"))
    if any(ch.islower() for ch in token) and any(ch.isupper() for ch in token[1:]):
        return token
    return token.capitalize()


def format_skill_category(category: str) -> str:
    """Format a skill category heading while preserving known uppercase acronyms."""
    cleaned = " ".join((category or "").replace("_", " ").split())
    if not cleaned:
        return ""
    # A heading typed entirely in capitals is shouting, not acronyms, so it is title-cased.
    shouting = cleaned.isupper()
    return " ".join(_format_category_token(token, shouting) for token in cleaned.split(" "))
