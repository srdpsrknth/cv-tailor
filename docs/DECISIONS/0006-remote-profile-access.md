# 0006 — Local-first store, remote profile access later

**Status:** Approved in principle (2026-10-23) — implementation deferred to a later phase
**Related:** [0002](0002-privacy-model.md), [0004](0004-storage.md)

## Context

The owner wants to reach their profiles from **any machine** where cv-tailor can be installed,
provided there is internet access — without publishing candidate data in the public repo.

That is a remote-storage requirement, not a reason to keep data in Git. It also introduces
real obligations: authentication, transport security, and a threat model for hosting
someone's CV and immigration status.

The owner explicitly prefers to **start local and add internet access later**.

## Decision

Build the store behind a **storage interface** from the start, with two implementations:

1. **`LocalStore` (Phase 2, first)** — files under a configurable directory outside the repo.
   Fully functional offline. This is the only implementation built initially.
2. **`RemoteStore` (later phase)** — a small backend serving the *same* layout and the same
   interface, plus a local cache so offline use still works.

Design rules that must hold now so the later step stays cheap:

- All storage access goes through the interface — no direct filesystem calls in services.
- The store is selected by configuration (`CV_TAILOR_STORE`, `--store local|remote`).
- The on-disk layout is identical local and remote ([0004](0004-storage.md)), so migrating is
  a copy, not a transformation.
- Every record carries `profile_id` ([0003](0003-profile-identity.md)).

### Requirements the remote store must meet before it ships

- **Authentication** — the store holds PII; anonymous access is not acceptable.
- **Encryption in transit** (HTTPS) and at rest on the host.
- **No default profile**, and tenant-scoped keys so one account cannot read another's data.
- **Retention and deletion** endpoints (export and erase a profile).
- **Client-side caching** with an explicit offline mode.
- Never log profile contents or prompts.

## Consequences

- Phase 2 is not blocked on hosting decisions, and the local product stays usable offline.
- A small amount of interface indirection is accepted now to avoid a later rewrite.
- Hosting, auth and cost remain **open** and must be decided before this phase begins.
- If the remote store is never built, nothing is lost — the interface has one implementation,
  which is a normal, defensible design.
- The owner should re-confirm scope when this phase is reached.
