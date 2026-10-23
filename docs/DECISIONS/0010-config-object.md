# 0010 — One explicit `Config` object; no import-time environment reads

**Status:** Approved (2026-10-23) — implemented in Phase 1
**Related:** [ROADMAP.md](../ROADMAP.md) Phase 1, [ASSESSMENT.md](../ASSESSMENT.md) A-5

## Context

`gemini_service.py:21-24` read `os.getenv` at module import, and `main.py:22` read
`OUTPUTS_DIR` the same way. Three problems followed:

1. The model, key and output path were fixed for the process lifetime, so per-task model
   selection (Phase 3) was impossible without editing environment variables and restarting.
2. Tests could not vary configuration between cases — a `monkeypatch.setenv` after import had
   no effect on the already-captured globals.
3. Importing a module performed I/O (reading `.env`) and had side effects as a side effect of
   being imported.

## Decision

Introduce `backend/config.py` with a **frozen dataclass `Config`** and exactly one
environment-reading entry point, `Config.from_env()`:

- Called at the **point of use**, never at import time.
- Accepts `env_file`, `load_env_file=False` and an `overrides` mapping, so the CLI can pass
  `--project`/`--profile` and tests can construct a config without touching process state.
- `project_root` is a field, so "relative to the project" is explicit and testable rather than
  inferred from `__file__` in several modules.
- Unknown override keys raise `TypeError`: a typo in an override fails loudly instead of being
  silently ignored.
- There is one `DEFAULT_MODEL` constant, in `config.py`, and `PRICING` must always contain it
  (asserted by a test) because the cost fallback resolves through it.
- Helpers that were previously ad-hoc `os.getenv` idioms become named properties:
  `has_api_key`, `is_mirroring`, `require_api_key()`.

`Config` is **frozen**; variation is expressed with `with_overrides()`, so a value cannot be
mutated halfway through a generation run.

## Consequences

- **Phase 3 is unblocked:** a model can be chosen per task or per profile by constructing a
  config, with no global state.
- Tests become order-independent: two configs built at different moments observe different
  environments, and the first is unaffected by a later change.
- Editing `.env` takes effect without restarting the API process.
- **Compatibility constraint:** `tailor_documents` constructs `GeminiService()` **with no
  arguments** when no config is supplied. The pre-existing test suite injects a double via
  `monkeypatch.setattr(service, 'GeminiService', lambda: fake)`; passing a keyword argument
  would break that contract. Keep that branch if the constructor signature changes.
- A guard test asserts that importing the backend modules performs no environment read. It was
  verified to fail when a module-level `os.getenv` is reintroduced, so the invariant is
  enforced rather than merely documented.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep module globals, add `reload()` helpers | Preserves the ordering problem; tests stay order-dependent |
| `pydantic-settings` `BaseSettings` | Adds a dependency for a handful of fields; also resolves at instantiation time, which a dataclass already does |
| A global singleton `get_config()` | Reintroduces the shared mutable state the change exists to remove |
| Read env inside each service | Scatters the reads again; there would be no single place to override |
