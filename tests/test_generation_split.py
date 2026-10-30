"""The pipeline was split along its seams; these pin what the split must preserve.

`services.generation` is now a facade over six modules. Two properties matter and
neither is visible from a behavioural test:

* the **public surface is complete** -- every name the module used to define is still
  reachable, because ~37 call sites import from it by name;
* the facade **re-exports** rather than redefines, so there is one implementation of
  each thing and the two cannot drift.

The sizes are asserted too. The split exists to stop one file from holding prompts,
schemas, parsing, validation and the generator at once, so a regression that grows any
one of them back into a monolith should be visible rather than silent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services import (
    cv_delta,
    generation,
    pipeline,
    prompts,
    response_schemas,
    schema_dialect,
    validation,
)

SERVICES = Path(generation.__file__).parent

#: Modules the split created, and the concept each owns.
SPLIT_MODULES = {
    'schema_dialect.py': schema_dialect,
    'response_schemas.py': response_schemas,
    'prompts.py': prompts,
    'cv_delta.py': cv_delta,
    'validation.py': validation,
    'pipeline.py': pipeline,
}


def test_every_split_module_exists_and_is_importable():
    for filename, module in SPLIT_MODULES.items():
        assert (SERVICES / filename).exists(), f'{filename} is missing'
        assert module.__name__ == f'services.{filename[:-3]}'


def test_the_facade_is_a_facade_and_not_a_second_implementation():
    """Each re-export must be the *same object* as its home, not an equal copy.

    Two equal definitions can drift tomorrow; one object cannot. This is the property
    that makes `services.generation` safe to keep as the public import path.
    """
    homes = {
        pipeline: ['DocumentGenerator', 'TokenCounts', 'MAX_VALIDATION_ATTEMPTS',
                   'MAX_LAYOUT_ATTEMPTS'],
        prompts: ['build_context', 'build_cv_prompt', 'EDITORIAL_REQUIREMENTS',
                  'PROMPT_CV_PATH', 'PROMPT_CL_PATH', 'layout_budget',
                  'layout_retry_instruction', 'layout_inventory', 'cv_body_words',
                  'pinned_project_clause', 'LAYOUT_RETRY_MARKER',
                  'layout_correction_instruction'],
        response_schemas: ['RESPONSE_SCHEMAS', 'response_schema_for'],
        schema_dialect: ['to_dialect', 'reshape_free_form_maps',
                         'count_optional_parameters', 'SKILLS_AS_ARRAY',
                         'DIALECT_GEMINI', 'DIALECT_STRICT',
                         'DIALECT_ANTHROPIC_VERTEX'],
        validation: ['ProfileRules', 'DEFAULT_PROFILE_RULES', 'validate_cv',
                     'validate_cover_letter', 'profile_facts_json'],
        cv_delta: ['parse_json_response', 'extract_explanation', 'apply_cv_delta',
                   'looks_like_cv_delta'],
    }

    for home, names in homes.items():
        for name in names:
            assert hasattr(generation, name), f'generation.{name} was lost in the split'
            assert getattr(generation, name) is getattr(home, name), (
                f'generation.{name} is a copy, not an alias of {home.__name__}.{name}'
            )


def test_the_facade_holds_no_logic_of_its_own():
    """The facade must contain only imports, a logger and `__all__`.

    A helper that quietly lives here would be a seventh home for pipeline logic -- the
    exact shape the split removed.
    """
    import ast

    tree = ast.parse(Path(generation.__file__).read_text(encoding='utf-8'))
    offenders = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Assign):
            # `logger = logging.getLogger(__name__)` and `__all__` are allowed.
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets <= {'logger', '__all__'}:
                continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        offenders.append(type(node).__name__)

    assert offenders == [], (
        f'the facade defines something beyond imports/logger/__all__: {offenders}'
    )


@pytest.mark.parametrize('filename', sorted(SPLIT_MODULES))
def test_no_split_module_grew_back_into_a_monolith(filename):
    """A ceiling per module, so the next feature is added to the right place.

    Not a style rule: `generation.py` reached 1,281 lines by accumulating five
    unrelated concerns, and nothing failed while it did. These ceilings sit above the
    current sizes with room to grow, and below the point where a module is again
    holding several concepts.
    """
    lines = len((SERVICES / filename).read_text(encoding='utf-8').splitlines())
    assert lines <= 420, f'{filename} is {lines} lines; it is becoming a monolith again'


def test_the_response_schemas_are_unchanged_by_the_split():
    """The schemas are a cache-key ingredient (ADR 0015), so their bytes are pinned.

    Measured at `ac1c902`, before any module was moved. A split that altered what the
    model is asked would silently invalidate every cached generation.
    """
    import hashlib
    import json

    digests = {
        kind: hashlib.sha256(json.dumps(s, sort_keys=True).encode('utf-8')).hexdigest()
        for kind, s in generation.RESPONSE_SCHEMAS.items()
    }
    assert digests == {
        'cv': 'd08062c622fb9321c73d628854a453955400d7778ef130eaa7b900b8f40654cb',
        'cover_letter': 'e259b8d12006eda91cabe6beae70e8d4b8f8ecfd3081a307677092379241f844',
    }, f'the split changed the shipped response schemas: {digests}'


def test_the_prompt_files_are_still_where_prompts_says_they_are():
    """`PROMPT_CV_PATH` is read and hashed per call, so a broken path fails loudly here."""
    assert prompts.PROMPT_CV_PATH.exists(), prompts.PROMPT_CV_PATH
    assert prompts.PROMPT_CL_PATH.exists(), prompts.PROMPT_CL_PATH
