"""Render saved application content using cv-tailor's existing templates.

Thin wrapper: delegates to the repository's root ``scripts/render_application.py`` so
there is one implementation. Arguments are identical, including the required
``--profile-id`` (or ``CVTAILOR_PROFILE_ID``); there is no implicit profile (ADR 0003).
``--project`` is optional here and defaults to the repository root.

    python .agents/skills/cv-tailor-application/scripts/render_application.py \
        --profile-id <id> --content <store>/outputs/<id>/<job_id>/source/content.json
"""
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def main():
    argv = sys.argv[1:]
    if not any(a == '--project' or a.startswith('--project=') for a in argv):
        argv = ['--project', str(REPO_ROOT)] + argv
    root_script = REPO_ROOT / 'scripts' / 'render_application.py'
    sys.argv = [str(root_script)] + argv
    runpy.run_path(str(root_script), run_name='__main__')


if __name__ == '__main__':
    main()
