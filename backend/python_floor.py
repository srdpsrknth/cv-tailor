"""The minimum Python version, shared by ``scripts/setup.py`` and ``cvtailor doctor``.

Standard library only, so the setup script can load it before any dependency exists.
"""
MIN_PYTHON = (3, 12)


def min_python_text() -> str:
    return ".".join(str(part) for part in MIN_PYTHON)
