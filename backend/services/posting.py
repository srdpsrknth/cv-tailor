"""Shared preflight validation, before any provider or filesystem work."""

import re

MIN_JOB_DESCRIPTION = 50
_COMMAND_START = re.compile(
    r"^(?:(?:[^\s]*[/\\])?python(?:\d+(?:\.\d+)*)?(?:\.exe)?\s+"
    r"(?:[^\s]*[/\\])?cvtailor\.py(?:\s|$)"
    r"|cvtailor(?:\.py)?\s+(?:--\S+|generate\b))",
    re.I,
)


def validate_posting(text: str, min_length: int = MIN_JOB_DESCRIPTION) -> str:
    text = (text or "").strip()
    first = next(
        (
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("```")
        ),
        "",
    )
    if _COMMAND_START.match(first):
        raise ValueError(
            "The job description starts with a CV Tailor command. "
            "The clipboard may contain the command instead of the posting."
        )
    if len(text) < min_length:
        raise ValueError(
            f"Job description is too short ({len(text)} characters). "
            f"Paste the full posting; at least {min_length} characters."
        )
    return text
