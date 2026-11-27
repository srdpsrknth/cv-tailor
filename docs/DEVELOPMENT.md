# Development setup, worktrees and Git workflow

## Worktrees

| Directory | Branch | Purpose |
|---|---|---|
| `cv-tailor/` (`<projects>/cv-tailor`) | `master` | Stable, daily-use application |
| `cv-tailor-next/` (`<projects>/cv-tailor-next`) | `refactor/architecture-v2` | Refactoring, experiments, new features |

`<projects>` is wherever you keep your checkouts (for example `~/code` on macOS/Linux or
`C:\code` on Windows). *Historical note:* the original maintainer's Windows machine kept both
worktrees side by side under one parent directory. Verify at any time (bash, zsh or PowerShell):

```bash
git worktree list
git -C <projects>/cv-tailor        status --short --branch   # expect master
git -C <projects>/cv-tailor-next   status --short --branch   # expect refactor/architecture-v2
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

### Windows Python output permission error (Windows only)

macOS and Linux have no equivalent of this integrity-level problem; skip to the next section.

If `doctor` cannot write outputs even from a normal terminal, inspect the Python
executable with `icacls .venv\Scripts\python.exe`. This checkout inherited a
**Low Mandatory Level** label from an earlier agent sandbox. Windows therefore
starts the venv Python at Low integrity, which cannot write to the normal private
store even though its ordinary directory ACL grants Modify. This persists outside
the agent; it is not a harmless doctor failure.

The targeted repair restores the two Python launcher executables to Medium
integrity. Run these in **PowerShell as Administrator**, replacing `<checkout>` with
the path of the affected checkout:

```powershell
icacls "<checkout>\.venv\Scripts\python.exe" /setintegritylevel M
icacls "<checkout>\.venv\Scripts\pythonw.exe" /setintegritylevel M
```

Then run `doctor` from a **normal**, non-administrator terminal. Both commands must
report success; the repair has not been verified until doctor passes. Restart the
GUI with the stop/open shortcuts so it uses a fresh Python process. No change to
the private store's ACL, security software or profile data is needed. Recheck if
the venv is later recreated under a Low-labelled checkout.

### Windows GUI shortcuts (Windows only)

On every OS, `scripts/start.py --status` and `scripts/start.py --stop` report or stop the services that `start.py` started. They use a PID file at `.runtime/services.json` and never stop unrelated listeners on the ports. On macOS and Linux, start the GUI from a terminal with `.venv/bin/python scripts/start.py` and stop it with Ctrl+C or `--stop`; there is no
shortcut installer.

The review UI requires the added `streamlit-pdf==2.1.0` dependency for inline PDF
previews. Existing environments should install `requirements.lock.txt` after pulling
this update, then restart the GUI. Missing preview support does not remove downloads.

After installing the environment, run from the checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install_windows_shortcuts.ps1
```

This installs **CV Tailor** and **Stop CV Tailor** on the current user's desktop
and under **CV Tailor** in the Start menu. No administrator rights are needed.
Double-click **CV Tailor** to start Streamlit in the background and open the browser
after its health endpoint is ready. Reopening reuses the running GUI. Closing the
browser leaves it running; use **Stop CV Tailor** to release the port.

The launcher derives the checkout path, uses its `.venv`, reads `UI_PORT` from its
`.env`, and binds to `127.0.0.1` only. It starts the GUI alone: generation runs in
process, so FastAPI is optional. The explicit profile picker remains required.
It refuses to reuse or stop another program occupying the port. Startup failures
appear in a dialog; logs are `.runtime/logs/gui.stdout.log` and `gui.stderr.log`.
Run the installer again after moving the checkout. The shortcuts contain local
paths; they are installed on the machine, never committed.

For terminal diagnostics without opening the browser:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows_gui.ps1 -NoBrowser
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows_gui.ps1 -Stop -NoBrowser
```

Each worktree needs **its own** `.venv`, `.env`, logs and ports.

Generated documents do **not** live in either worktree: since ADR 0011 they are written to the
private store, `<store>/outputs/<profile_id>/<job_id>/`, so the two worktrees cannot collide
regardless of `OUTPUTS_DIR`.

`refactor/architecture-v2` is already set up and runnable. To create this setup from scratch on
another machine:

```powershell
# Windows
cd <checkout>
python scripts/setup.py            # creates .venv, installs requirements.lock.txt, copies .env.example
# then edit .env and set OPENROUTER_API_KEY (https://openrouter.ai/settings/keys)
.venv\Scripts\python.exe scripts/check_setup.py
.venv\Scripts\python.exe -m pytest -q
```

```bash
# macOS / Linux
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

Point a worktree at a private store in `.env`. Paths relative to the worktree
are portable when both directories share a parent.

```
CVTAILOR_STORE=../cv-tailor-data
CVTAILOR_PROFILE_ID=<profile_id>
```

`profile_id` is required and fails closed: there is no default profile (ADR 0003). Use
`cvtailor profile list` to see the ids in a store, and `cvtailor profile import <path>
--profile-id <id>` to add one. The store's own `README.md` describes its layout.

A fresh clone has no store; `CVTAILOR_STORE` then defaults to `./storage`, which is gitignored
for exactly that reason — do not commit what ends up there.

### Known issue: `pip install` hangs on a stale HTTP cache

*Historical note (observed on the original Windows development machine):* `pip install -r requirements.lock.txt` hung indefinitely — high CPU,
zero packages installed after 30+ minutes — because of a corrupt/contended pip HTTP cache.
`pyyaml` alone reproduced it, so it is not the dependency set.

**Workaround — bypass the cache:**

```powershell
# Windows
.venv\Scripts\python.exe -m pip install --only-binary=:all: --no-cache-dir `
    --progress-bar off -r requirements.lock.txt
```

```bash
# macOS / Linux
.venv/bin/python -m pip install --only-binary=:all: --no-cache-dir \
    --progress-bar off -r requirements.lock.txt
```

That installed all 91 locked packages successfully. If pip ever hangs again with no output,
suspect the cache first (`--no-cache-dir`), not the network — PyPI was reachable in 0.1 s
while pip was stuck.

`scripts/setup.py` does not yet pass `--no-cache-dir`; consider fixing it if this recurs.

### Current state of this worktree

*Historical note (snapshot from the original development worktree; see `PROJECT_STATE.md` for the live baseline):* runnable: `.venv` with all locked dependencies, `.env` created from `.env.example`, ports set
to 8001/8502. `scripts/check_setup.py` reports profile/timezone/LaTeX/templates OK, and
`python -m pytest -q` → **1142 passed, 3 skipped** (see [`TESTING.md`](TESTING.md) for the
current baseline).

The only outstanding item is `OPENROUTER_API_KEY`, which the owner must enter into `.env`
directly (the user, not an agent) — never paste it into a chat. Set `CVTAILOR_STORE` and `CVTAILOR_PROFILE_ID` too;
without them every command that touches candidate data fails closed by design (ADR 0003).

> **Run the suite with `TEMP`/`TMP` pointed inside the worktree**, or the LaTeX tests can
> fail with a spurious `pdflatex compilation failed` even with nothing else running:
>
> ```powershell
> # Windows
> $env:TEMP = "$PWD\.tmp"; $env:TMP = $env:TEMP
> ```
>
> ```bash
> # macOS / Linux
> mkdir -p .tmp && export TMPDIR="$PWD/.tmp"
> ```

### Running both versions at once

`scripts/start.py` reads `BACKEND_PORT` and `UI_PORT`. Give each worktree distinct ports in
its own `.env`:

| Worktree | `BACKEND_PORT` | `UI_PORT` |
|---|---|---|
| `cv-tailor` (master) | 8000 | 8501 |
| `cv-tailor-next` (dev) | 8001 | 8502 |

`BACKEND_URL` is still read by the API's own clients, but **since Phase 6 the UI no longer
uses it**: `ui/app.py` calls the services in process rather than talking to the backend over
HTTP, so the UI works whether or not uvicorn is running. Keep `BACKEND_URL` matching
`BACKEND_PORT` for anything that does call the API.

### Portability rules

- Derive paths from the clone; never hardcode a machine-specific absolute path.
- Use `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS/Linux.
- TeX: MiKTeX on Windows, MacTeX on macOS, TeX Live on Linux. Tectonic is **not** used.
  Set `LATEX_COMPILER` if `pdflatex` is not on `PATH`.
- Never commit credentials, virtual environments, logs or generated PDFs/DOCX.

The [private store sync pilot](PRIVATE_STORE_SYNC.md) uses disposable profiles and
outputs to check both directions, staggered arrivals and conflict recovery.

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
