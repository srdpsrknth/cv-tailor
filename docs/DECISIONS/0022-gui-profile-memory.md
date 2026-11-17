# 0022 — Convenient GUI profile defaults with visible identity

**Status:** Approved (2026-11-17), explicit owner instruction after using the GUI.

The owner requested automatic selection of the only available profile, persistent
memory of the last profile used, and a clear active-profile indicator at the top.
This supersedes the empty-initial-picker requirement in ADR 0020/0021, but only
for the GUI. CLI/API/service `profile_id` requirements and isolation remain intact.

At GUI startup, restore a remembered id only when currently usable. Otherwise use
the sole usable profile. With multiple profiles and no valid memory, require a
choice rather than choosing the first or inferring from names. A user can clear
the current selection; it is not immediately reselected within that session.

Remember the id alone in `<store>/preferences/gui.json`, atomically and outside
the public repository. Memory is scoped to the local store, shared by its local
GUI sessions rather than synced as a browser account preference. Corrupt/stale
memory is ignored. A write failure leaves the selection active and shows a warning.
The header displays full active name and id. Switching profiles still clears
the previous candidate's draft, search and review state. No profile facts change.
