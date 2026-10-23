"""Small shared text helpers.

These were duplicated across the renderers and the tailoring service (D-12):
two near-identical ``_escape_latex`` implementations and three ``_slugify``
implementations with subtly different behaviour. One definition each keeps
filenames and escaping consistent across every renderer.
"""
from __future__ import annotations

import re

__all__ = ["slugify", "escape_latex"]

_WHITESPACE_RUN = re.compile(r"[^a-z0-9]+")

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
