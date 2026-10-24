# 0002 — Separate public code from private candidate data

**Status:** Approved (2026-10-23) — **implemented in Phase 2**; see [0011](0011-private-store-location.md)
for the store's location and the history question
**Related:** [ASSESSMENT.md](../ASSESSMENT.md) §6, [0004](0004-storage.md), [0006](0006-remote-profile-access.md), [0011](0011-private-store-location.md)

## Context

The repository is **public**. Verified contents include:

- `storage/profile/profile.yaml` — legal name, personal email, mobile number, home city,
  **immigration status**, full employment history, education;
- **64 of 112 tracked files** under `applications/` — job postings, LLM drafts, review notes,
  `profile_snapshot.json` (a full profile copy per application) and
  `application_answers.json` (free-text answers plus two eligibility attestations);
- three generated PDFs/DOCX tracked in `outputs/` despite `.gitignore`;
- `applications/.../booking.../source/initial_generation_result.json:4-6` — absolute local
  paths including a third-party first name.

No credential was ever committed (verified across all refs), so this is a privacy issue,
not a credential leak.

The roadmap adds **more candidates**. Committing a second person's profile and application
answers to a public repository is not acceptable.

## Decision

Split storage by sensitivity. **All real candidate data moves to a private store; the public
repository keeps code and synthetic examples only.**

| Public repo (code only) | Private store (never public) |
|---|---|
| `backend/`, renderers, `prompts/`, `templates/`, `tests/`, `scripts/`, `docs/`, `.env.example`, a **synthetic** `example.yaml` | all real profiles, `applications/`, `outputs/`, mirrors, form answers, snapshots, drafts, generated documents |

### Owner requirement: access from any machine

The owner wants to reach their profiles from any machine where cv-tailor can be installed and
the internet is available. That requirement is satisfied by the **remote profile store**
described in [0006](0006-remote-profile-access.md), which is layered on top of this split —
not by keeping data in the public repo.

## Consequences

- Phase 2 includes migrating existing profiles and applications into the private store.
- Synthetic fixtures become the only committed sample data — safe to share and test with.
- The local-first path stays fully functional without internet; remote access is additive.
- Existing `applications/` history remains in the public repo unless history is rewritten.
- **Do not** rewrite Git history, delete data, or change repository visibility without
  explicit owner approval.
- Adding a second real candidate waits until this is implemented.

## Implementation note (2026-10-24)

Implemented as decided, with the three open choices settled in
[0011](0011-private-store-location.md). The honest summary of the outcome:

- **Stopped:** real profiles, `applications/` and `outputs/` are no longer tracked. New data for
  any candidate lands in the private store, so the "adding a second candidate" condition above is
  satisfied **for new data**.
- **Not undone:** the files already published remain in the public repository's past commits.
  Untracking is not un-disclosure. Purging them needs a history rewrite and a force-push, which
  [0011](0011-private-store-location.md) records as a separate, unapproved decision.
