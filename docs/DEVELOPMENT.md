# Development setup, worktrees and Git workflow

## Worktrees

| Directory | Branch | Purpose |
|---|---|---|
| `cv-tailor/` (`D:\coding\cv-tailor`) | `master` | Stable, daily-use application |
| `cv-tailor-next/` (`D:\coding\cv-tailor-next`) | `refactor/architecture-v2` | Refactoring, experiments, new features |

Both already exist and are clean. Verify at any time:

```powershell
git worktree list
git -C D:\coding\cv-tailor        status --short --branch   # expect master
git -C D:\coding\cv-tailor-next   status --short --branch   # expect refactor/architecture-v2
```

**Never** do substantial redesign on `master`.

### Initialising this setup on another machine

```bash
git clone https://github.com/srdpsrknth/cv-tailor.git
cd cv-tailor
git worktree add ../cv-tailor-next refactor/architecture-v2   # if the branch exists remotely
# or, first time only, to create the branch:
git worktree add -b refactor/architecture-v2 ../cv-tailor-next master
```

`git worktree add` refuses to overwrite a non-empty directory, so an existing
`cv-tailor-next` is never clobbered. Do not create a second branch for the same purpose.

---

## Environment isolation

Each worktree needs **its own** `.venv`, `.env`, logs and ports.

Generated documents do **not** live in either worktree: since ADR 0011 they are written to the
private store, `<store>/outputs/<profile_id>/<job_id>/`, so the two worktrees cannot collide
regardless of `OUTPUTS_DIR`.

`refactor/architecture-v2` is already set up and runnable. To create this setup from scratch on
another machine:

```powershell
# Windows
cd D:\coding\cv-tailor-next
python scripts/setup.py            # creates .venv, installs requirements.lock.txt, copies .env.example
# then edit .env and set GEMINI_API_KEY
.venv\Scripts\python.exe scripts/check_setup.py
.venv\Scripts\python.exe -m pytest -q
```

```bash
# macOS
python3.12 scripts/setup.py
.venv/bin/python scripts/check_setup.py
.venv/bin/python -m pytest -q
```

`scripts/setup.py` never overwrites an existing `.env`. Never copy a `.venv` between
operating systems, and never commit one.

### The private profile store

Real candidate data does **not** live in this repository (ADR 0002, ADR 0011). It lives in a
separate private store, named by `CVTAILOR_STORE`:

```
<store>/profiles/<profile_id>/profile.yaml
<store>/outputs/<profile_id>/<job_id>/
<store>/applications/<job_id>/source/
```

On this machine the store is `D:\coding\cv-tailor-data`, and it is its own Git repository.
Point a worktree at it in `.env`:

```
CVTAILOR_STORE=D:/coding/cv-tailor-data
CVTAILOR_PROFILE_ID=sreedeep
```

`profile_id` is required and fails closed: there is no default profile (ADR 0003). Use
`cvtailor profile list` to see the ids in a store, and `cvtailor profile import <path>
--profile-id <id>` to add one. The store's own `README.md` describes its layout.

A fresh clone has no store; `CVTAILOR_STORE` then defaults to `./storage`, which is gitignored
for exactly that reason — do not commit what ends up there.

### Known issue: `pip install` hangs on a stale HTTP cache

On this machine, `pip install -r requirements.lock.txt` hung indefinitely — high CPU,
zero packages installed after 30+ minutes — because of a corrupt/contended pip HTTP cache.
`pyyaml` alone reproduced it, so it is not the dependency set.

**Workaround — bypass the cache:**

```powershell
.venv\Scripts\python.exe -m pip install --only-binary=:all: --no-cache-dir `
    --progress-bar off -r requirements.lock.txt
```

That installed all 91 locked packages successfully. If pip ever hangs again with no output,
suspect the cache first (`--no-cache-dir`), not the network — PyPI was reachable in 0.1 s
while pip was stuck.

`scripts/setup.py` does not yet pass `--no-cache-dir`; consider fixing it if this recurs.

### Current state of this worktree

Runnable: `.venv` with all locked dependencies, `.env` created from `.env.example`, ports set
to 8001/8502. `scripts/check_setup.py` reports profile/timezone/LaTeX/templates OK, and
`python -m pytest -q` → **282 passed** (see [`TESTING.md`](TESTING.md) for the current baseline).

The only outstanding item is `GEMINI_API_KEY`, which the owner must enter into `.env` directly
— never paste it into a chat. Set `CVTAILOR_STORE` and `CVTAILOR_PROFILE_ID` too; without them
every command that touches candidate data fails closed by design (ADR 0003).

### Running both versions at once

`scripts/start.py` reads `BACKEND_PORT` and `UI_PORT`. Give each worktree distinct ports in
its own `.env`:

| Worktree | `BACKEND_PORT` | `UI_PORT` |
|---|---|---|
| `cv-tailor` (master) | 8000 | 8501 |
| `cv-tailor-next` (dev) | 8001 | 8502 |

If you change `BACKEND_PORT`, set `BACKEND_URL` to match, because `ui/app.py` reads it
separately.

### Portability rules

- Derive paths from the clone; never hardcode a machine-specific absolute path.
- Use `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS/Linux.
- TeX: MiKTeX on Windows, MacTeX on macOS, TeX Live on Linux. Tectonic is **not** used.
  Set `LATEX_COMPILER` if `pdflatex` is not on `PATH`.
- Never commit credentials, virtual environments, logs or generated PDFs/DOCX.

---

## Git workflow

- `master` stays stable and is never force-pushed.
- `refactor/architecture-v2` is the development integration branch.
- Short-lived feature branches are fine when they aid isolation or review; base them on
  development needs, **not** on conversation boundaries.
- Commit focused, validated increments. Do not combine unrelated changes.
- Documentation changes ship in the same commit as the code they describe.
- Check for remote changes before pushing.
- Never silently overwrite uncommitted work.

### Commit message conventions

```
test:  establish baseline for CV rendering
refactor: separate profile rules from tailoring logic
feat:  add multi-profile storage
fix:   isolate application outputs by profile
docs:  record provider architecture decision
```

### Merging to master

Do **not** merge development into `master` until: required functionality is complete,
behaviour is verified, regression and integration tests pass, existing profile and
application data migrate or read safely, document output quality is reviewed, performance is
acceptable, breaking changes are documented, a rollback path exists, **and the owner
approves**. Use a pull request for the final review.

---

## Cross-machine synchronisation

1. Commit and push on machine A (development branch only).
2. On machine B: `git fetch`, then `git -C cv-tailor-next pull --ff-only`.
3. Re-run `scripts/setup.py` if `requirements.lock.txt` changed.
4. Re-run the test baseline before continuing.
5. Never copy `.venv`, `.env`, `outputs/` or `.runtime/` between machines.
