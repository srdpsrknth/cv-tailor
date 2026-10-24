# 0011 — The private store is a sibling directory; real data is untracked, history is not rewritten

**Status:** Approved (2026-10-24) — owner confirmed the three open choices before implementation
**Related:** [0002](0002-privacy-model.md), [0003](0003-profile-identity.md), [0004](0004-storage.md), [0006](0006-remote-profile-access.md)

## Context

[0002](0002-privacy-model.md) decided *that* real candidate data leaves the public repository, and
[0004](0004-storage.md) decided the on-disk layout, but it deliberately left two things open:

1. **where `<store>` physically lives** (a sibling directory, or a second private repo);
2. **how to stop the already-committed data being public**, given that removing a file from the
   working tree does not remove it from history, and that `AGENTS.md` forbids rewriting shared
   history or changing repository visibility without explicit approval.

Phase 2 makes both urgent, because it introduces the mechanism for a second candidate. Verified at
`e190156`: `storage/profile/profile.yaml` is **tracked** (`git ls-files` lists it) and contains the
owner's real name, personal email, mobile number, home city, **immigration status**, six employers
and two degrees. 64 application files and 4 output artifacts are tracked alongside it.

## Decision

The owner confirmed all three choices on 2026-10-24, before any code was written.

### 1. Location — a sibling directory containing its own private Git repository

```
D:\coding\cv-tailor-data\           <- private store root, outside the public repo
    profiles\
        <profile_id>\
            profile.yaml
    outputs\
        <profile_id>\
            <job_id>\
                source\content.json   ...
    applications\                   <- migrated application archives
```

`<store>` stays **configuration**, never code (`CVTAILOR_STORE` / `Config.profile_store_dir`), so the
layout is unchanged when the remote store of [0006](0006-remote-profile-access.md) arrives and a
migration remains a copy. The store is its own repository so profile edits stay versioned and
diffable without any of it reaching the public remote.

### 2. Untrack now, do not rewrite history

The real data is removed from the public repository's **index** with `git rm --cached`, and the paths
are added to `.gitignore`. The files themselves are **not deleted** — they are moved into the private
store, and the working copies stay on disk.

History is **explicitly not rewritten**. The data therefore remains reachable in past commits of the
public remote. This is a known, accepted, recorded limitation, not an oversight: a rewrite needs a
force-push on shared history, which is a separate decision with its own approval.

### 3. Real data moves to the store; the public tree keeps code and synthetic examples

Per [0002](0002-privacy-model.md): profiles, `applications/` and `outputs/` leave the public repo.
Synthetic fixtures under `tests/fixtures/` are the only committed sample data.

## Consequences

- **A second real candidate may now be added** — the condition [0002](0002-privacy-model.md) placed on
  Phase 2 ("adding a second real candidate waits until this is implemented") is satisfied for *new*
  data, which lands in the private store from the start.
- **The exposure already published is not undone.** Until a history rewrite is separately approved,
  `storage/profile/profile.yaml` and the 64 application files remain in the public repository's past
  commits. Anyone who has cloned it keeps that data. This must be stated plainly to the owner rather
  than implied as resolved.
- `git rm --cached` is not a deletion: `git status` shows the data as untracked afterwards, and a
  careless `git add -A` would re-add it. `.gitignore` is the guard, and a test asserts the real
  profile is not tracked.
- The existing single-path call sites (`scripts/render_application.py:32`, the CLI) hardcode
  `storage/profile/profile.yaml`. They must resolve the profile through the store instead, or the
  deterministic re-render path breaks the moment the file moves.
- Deleting the private store directory loses every profile; it is not recoverable from the public
  repo. Backup is the owner's responsibility and is why the store is a Git repository.

## Alternatives considered

| Option | Why not |
|---|---|
| Second private GitHub repo, cloned as a sibling | Chosen layout works identically; hosting is additive and can be done later without moving anything. Keeps this increment offline and within the sandbox. |
| Local directory that is not a Git repo | Loses versioning: a bad profile edit becomes unrecoverable, and `git diff` review of profile changes disappears. |
| Keep the profile in the repo but encrypt it | Breaks the plaintext editing workflow and grep-ability that [0004](0004-storage.md) relies on. |
| Rewrite history now | Needs a force-push on shared history; `AGENTS.md` requires explicit approval and a separate rollback plan. |
| Change the repository to private | Same approval class, and it does not help the second candidate, whose data must not be in *this* repo at all. |
