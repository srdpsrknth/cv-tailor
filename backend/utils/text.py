"""Small shared text helpers.

These were duplicated across the renderers and the tailoring service (D-12):
two near-identical ``_escape_latex`` implementations and three ``_slugify``
implementations with subtly different behaviour. One definition each keeps
filenames and escaping consistent across every renderer.
"""
from __future__ import annotations

import re

__all__ = ["slugify", "escape_latex", "format_skill_category"]

_WHITESPACE_RUN = re.compile(r"[^a-z0-9]+")

_UPPERCASE_ACRONYMS = frozenset({
    "AI", "BI", "SQL", "ETL", "ELT", "LLM", "LLMS", "MCP", "CI", "CD", "CI/CD",
    "GA4", "CRM", "KPI", "KPIS", "AWS", "GCP", "API", "APIS", "ML", "NLP",
    "SEO", "SEM", "ROAS", "CAC", "LTV", "GDPR",
})

#: Order matters: the backslash must be replaced before anything that introduces one,
#: otherwise the replacement text would itself be escaped.
_LATEX_REPLACEMENTS = (
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
)


def slugify(text: str) -> str:
    """Return a filesystem-safe slug, falling back to ``"role"``.

    Collapses every run of non-alphanumeric characters to a single underscore and
    strips leading/trailing underscores, so ``"Nordwind Analytics GmbH"`` becomes
    ``"nordwind_analytics_gmbh"``.
    """
    return _WHITESPACE_RUN.sub("_", (text or "").strip().lower()).strip("_") or "role"


def escape_latex(value: str) -> str:
    """Escape LaTeX special characters in free text.

    Non-string values are returned unchanged so callers can pass optional fields
    straight through.
    """
    if not isinstance(value, str):
        return value
    escaped = value
    for char, replacement in _LATEX_REPLACEMENTS:
        escaped = escaped.replace(char, replacement)
    return escaped


def _format_category_token(token: str) -> str:
    if not token:
        return token
    upper = token.upper()
    if upper in _UPPERCASE_ACRONYMS:
        return upper
    if token.lower() == "dbt":
        return "dbt"
    if "/" in token:
        return "/".join(_format_category_token(part) for part in token.split("/"))
    if any(ch.islower() for ch in token) and any(ch.isupper() for ch in token[1:]):
        return token
    return token.capitalize()


def format_skill_category(category: str) -> str:
    """Format a skill category heading while preserving known uppercase acronyms."""
    cleaned = " ".join((category or "").replace("_", " ").split())
    if not cleaned:
        return ""
    return " ".join(_format_category_token(token) for token in cleaned.split(" "))
