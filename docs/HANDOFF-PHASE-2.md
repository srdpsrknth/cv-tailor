# Handoff — start of Phase 2

**Written:** 2026-10-24, at the end of Phase 1.
**Branch:** `refactor/architecture-v2` (worktree `D:\coding\cv-tailor-next`), at `3e779f5`.
**Stable branch:** `master` (`D:\coding\cv-tailor`) at `1416177` — untouched, still usable.

This file exists so a **new chat** can begin Phase 2 without the Phase 1 conversation. Read
[`PROJECT_STATE.md`](PROJECT_STATE.md) first; this only adds the Phase 2 entry conditions.

---

## 1. Entry conditions (confirm before writing code)

1. `git -C D:\coding\cv-tailor-next status --short` → clean.
2. `git rev-parse --abbrev-ref HEAD` → `refactor/architecture-v2`.
3. `.venv\Scripts\python.exe -m pytest -q` → **190 passed** in ~110 s (fully offline).
4. Fast lane while iterating: `-m "not requires_latex"` → 160 passed in ~5 s.
5. `git log --oneline -1` → `3e779f5` or later.

If the suite is not 190 green, **stop and find out why** before changing anything. The whole
point of Phase 1 was to make the suite a reliable safety net.

## 2. What Phase 1 changed that Phase 2 depends on

| Surface | Now | Consequence for Phase 2 |
|---|---|---|
| `backend/config.py` | One `Config`, resolved at call time | `profile_id` belongs here, not in `os.getenv` |
| `backend/services/generation.py` | `ProfileRules.from_profile(profile)` | Already reads per-profile rules; a second profile needs no validator change |
| `backend/services/application_store.py` | `ApplicationStore(project_root, job_id)` | Add `profile_id` to the path and to `make_job_id` |
| `backend/cli/` | `doctor`, `profile show`, `generate`, `render` | `profile list/new/import/export` slot in beside `show` |
| `storage/profile/profile.yaml` | Declares a `rules:` block | Must survive migration byte-for-byte |

## 3. Read these before deciding anything

- [`DECISIONS/0002-privacy-model.md`](DECISIONS/0002-privacy-model.md) — **not yet implemented**
- [`DECISIONS/0003-profile-identity.md`](DECISIONS/0003-profile-identity.md) — the core of Phase 2
- [`DECISIONS/0004-storage.md`](DECISIONS/0004-storage.md) — files keyed by `profile_id`
- [`ASSESSMENT.md`](ASSESSMENT.md) §6 — the privacy analysis and path-traversal findings

## 4. The privacy problem is now the critical path

Phase 1's `PROJECT_STATE.md` records this as a blocker, and Phase 2 is what makes it dangerous.

`storage/profile/profile.yaml` contains real personal data — name, personal email, mobile,
home city, **immigration status**, full employment history — and it is committed to a **public**
repository, alongside ~64 application files. Today there is **one** candidate, so the exposure
is the owner's own and deliberate.

**Phase 2 adds a second candidate.** Adding another person's PII to a public repo is not
acceptable, and [ADR 0002](DECISIONS/0002-privacy-model.md) already decided the split:

| Public repo (code only) | Private store (never public) |
|---|---|
| `backend/`, renderers, `prompts/`, `templates/`, `tests/`, `scripts/`, `docs/`, `.env.example`, a **synthetic** example | all real profiles, `applications/`, `outputs/`, mirrors, form answers, snapshots, drafts, documents |

**Therefore: implement the private-store split before, or in the same increment as, the first
second profile.** A migration that copies the existing profile into a private store is the
natural vehicle. Do not rewrite git history or change repository visibility without explicit
approval — both are on the "ask first" list in `AGENTS.md`.

## 5. Suggested order

1. **Confirm ADR 0002/0003/0004** with the owner, and settle where the private store lives
   (a sibling directory, or a second private repo — [ADR 0006](DECISIONS/0006-remote-profile-access.md)
   covers remote access later).
2. `ProfileStore` keyed by `profile_id`; `storage/profiles/<profile_id>/profile.yaml`.
3. Thread `profile_id` through `Config`, `tailor_documents`, `ApplicationStore` and the CLI.
   **Fail closed** when it is absent or unknown (ADR 0003) — never default.
4. `outputs/<profile_id>/<job_id>/`; put the candidate segment into `make_job_id` so the
   A-9 collision cannot recur.
5. Migrate the existing profile; assert manual edits, titles, dates, ownership and
   ongoing-project status survive, and that its `rules:` block is unchanged.
6. Isolation tests: A generates → B's files are untouched; no cross-contamination in prompts
   or `profile_snapshot.json` (the Phase 1 fixtures already support two divergent profiles).
7. `cvtailor profile list|new|import|export`.

## 6. Hazards specific to this worktree

- **Pushing and committing** need unconfined access: this worktree's git metadata lives in
  `D:\coding\cv-tailor\.git`, outside the sandbox.
- **pytest `tmp_path`** errors under the `workspace-write` sandbox (ACL operations). Run the
  suite unconfined.
- **The venv Python may be denied writes** under `outputs/` and `storage/profile/` while
  PowerShell is allowed. This bit Phase 1 when editing `profile.yaml`; the workaround is a
  .NET append, and it is worth verifying byte-preservation afterwards if you must rewrite a
  file in place.
- `outputs/2026_adjoe_senior_data_analyst_1769343142/` has **no `source/content.json`** — the
  D-14 partial-folder case. Do not assume `outputs/*/source/` exists.
- A broad `git add -A` will sweep `pytest-of-*/` temp trees into a commit. They are gitignored
  now, but stage explicit paths anyway.

## 7. Carry-over debt Phase 2 will touch

- **A-6** dates are unvalidated strings — a real multi-profile integrity risk; fix while
  adding the store.
- **A-9** `job_id` has no candidate segment — fix in step 4.
- **D-11** saved applications have inconsistent schemas — migrate in Phase 2 per ADR 0009.
- **D-4** the UI duplicates the pricing table — one source of truth.

## 8. Definition of done for Phase 2

- Two profiles generate independently with no cross-contamination, proved by tests.
- `profile_id` is explicit and fails closed; no code path defaults to a profile.
- The existing profile migrates with its facts, titles, dates and `rules:` block intact.
- The real profile is **not** in the public repo.
- `python -m pytest -q` green and offline; `PROJECT_STATE.md`, `ROADMAP.md`, `TESTING.md` and
  any new decision record updated in the same commits.
