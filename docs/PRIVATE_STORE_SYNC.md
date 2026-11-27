# Private store sync pilot (synthetic data only)

## Current status

This document is a test plan, not approval to sync a real profile store. Use disposable synthetic
profiles and outputs only. The automated test simulates two local stores; it does not establish
that transport between Windows and macOS works. The latest recorded live observation below is
from 2026-11-24 and did **not** complete a two-peer transport test. Re-check both peers and record
the result before treating the pilot as complete. Do not place profile facts, real application
content, credentials, or machine-specific store paths in this repository.

Run this pilot against disposable synthetic stores on Windows and macOS. Use the same
CV Tailor revision and working local TeX on both peers. Test the full round trip and a
restore before connecting either real store.

## Store and share setup

| Path | Use |
| --- | --- |
| `<pilot-store>/profiles/` | Dedicated Syncthing share for synthetic profiles |
| `<pilot-store>/outputs/` | Dedicated Syncthing share for synthetic applications |
| `<store>/applications/` | Optional archive share after the pilot |
| `<checkout>/outputs/`, `OUTPUTS_DIR` | Checkout output and optional export mirrors, kept local |

1. Choose a new empty pilot directory on each peer, outside the code checkout and every
   existing share. Create `profiles/` and `outputs/` beneath it. Use purpose-specific
   folder IDs for the two shares and the same IDs on both devices. Use the Windows pilot
   as the initial seed. Pair the peers through their own Syncthing dashboards and share
   only these pilot folders. Use send/receive on both peers and enable staggered file
   versioning on both pilot shares. Keep a backup outside the synced folders. Syncthing
   archives incoming replacements and deletions, so a separate backup also covers local
   mistakes. [Syncthing folder modes](https://docs.syncthing.net/users/foldertypes.html) ·
   [File versioning](https://docs.syncthing.net/users/versioning.html)
2. Launch CV Tailor from a dedicated shell with `CVTAILOR_STORE` set to the local pilot
   root and `CVTAILOR_PROFILE_ID` set to `analyst_a`. On Windows use PowerShell
   `$env:CVTAILOR_STORE = '<absolute pilot path>'` and on macOS use
   `export CVTAILOR_STORE='<absolute pilot path>'`. Keep `.env`, `.git`, private Git
   backups, caches, logs, preferences, mirrors and the emulator and Obsidian shares
   outside the pilot.

## Render and transfer in both directions

1. On Windows, import the synthetic profile with
   `.\.venv\Scripts\python.exe cvtailor.py profile import tests/fixtures/profiles/synthetic_analyst.yaml --profile-id analyst_a`.
   Create `<pilot-store>/outputs/analyst_a/pilot-windows/source/`, copy
   `tests/fixtures/content/valid_content.json` into it as `content.json` and copy
   `tests/fixtures/job_descriptions/nordwind_analytics_engineer.txt` as
   `job_description.txt`. From the code checkout, save a profile snapshot and render
   locally with the repository's Windows Python. The render uses the existing editable
   content and needs no provider call.

   ```powershell
   $pilotSource = "$env:CVTAILOR_STORE/outputs/analyst_a/pilot-windows/source"
   $pilotProfile = .\.venv\Scripts\python.exe cvtailor.py --json --profile-id analyst_a profile show | ConvertFrom-Json
   $pilotProfile.profile | ConvertTo-Json -Depth 100 | Set-Content "$pilotSource/profile_snapshot.json" -Encoding utf8NoBOM
   .\.venv\Scripts\python.exe scripts/render_application.py --project . --profile-id analyst_a --content "$pilotSource/content.json"
   ```

2. Wait for both shares to show **Up to Date** on both devices. On macOS open
   `pilot-windows` under Applications, open the saved posting and open the CV and
   cover letter from **Application folder**. Compare SHA-256 hashes of the profile,
   profile snapshot, posting, editable content, manifest and each local artifact
   against the Windows originals. Use
   `Get-FileHash -Algorithm SHA256 <path>` on Windows and `shasum -a 256 <path>` on macOS.
   Record the application IDs, relative paths and matching hashes.
3. On macOS, change the synthetic profile tagline, then repeat in a new `pilot-mac`
   folder using the same fixture posting and editable content. Render with the
   repository's Mac Python, then open and compare files from Windows. Confirm the updated
   tagline is in the synced profile and `pilot-mac` snapshot, and `pilot-windows` still
   carries its original snapshot. Compare the transferred bytes with each original file.
   Local renders by two different toolchains can produce different bytes.

   ```bash
   pilot_source="$CVTAILOR_STORE/outputs/analyst_a/pilot-mac/source"
   .venv/bin/python cvtailor.py --json --profile-id analyst_a profile show \
     | .venv/bin/python -c 'import json, sys; json.dump(json.load(sys.stdin)["profile"], sys.stdout)' \
     > "$pilot_source/profile_snapshot.json"
   .venv/bin/python scripts/render_application.py --project . --profile-id analyst_a --content "$pilot_source/content.json"
   ```

## Conflict and restore

1. With both devices current, copy a complete pilot application outside the shares and
   record its file hashes. Temporarily pause the pilot output share on both peers. Edit
   `source/content.json` differently on each peer, using valid JSON and a distinct
   synthetic CV summary on each. Retain a copy and hash of both edits before resuming
   both shares. Wait for both peers to settle. Verify that the canonical file and its
   `content.sync-conflict-*.json` sibling hold the two edited versions. Syncthing can
   propagate the conflict copy to both peers. [Syncthing conflict handling](https://docs.syncthing.net/users/syncing.html)
2. Preserve both versions outside the share. Paste the known-good `content.json` from
   the backup over the canonical file on one peer. Keep the other peer idle until it
   receives the restoration. Compare the restored bytes with the backup and check the
   application and its local PDFs still open correctly on both peers. Record both edit
   hashes and the restored hash. Use the retained backup to restore the full synthetic
   folder if more than one file changed.
3. Deliberately stage a fresh synthetic application by copying `source/` and one PDF
   into a new pilot application first, followed by the remaining artifacts. On the
   receiving device, verify that the available PDF opens before the other files
   arrive and that the complete package works afterwards. A saved success manifest can
   arrive before its artifacts. Check actual files and hashes before editing or relying
   on a synced application.

## Readiness for real data

The local regression suite simulates two store locations, file-by-file arrival and a
conflict copy. Run `python -m pytest -q tests/test_private_store_sync.py` with the
repository venv. The live pilot above checks real peer transport and each operating
system's rendering path separately.

On 2026-11-24 the Windows desktop browser reached the local Syncthing health endpoint.
The dashboard requires sign-in and the macOS peer was unavailable for verification.
The isolated Windows profile import and snapshot export completed. A separate test
rendered real PDFs with a portable MiKTeX configuration, copied the output to a second
local store, matched all ten file hashes and reopened the application there. The
two-peer transport remains to be tested.

Before migrating, inventory both existing stores by profile ID and application folder,
take independent backups, preserve the private Git history outside Syncthing and
reconcile different files. Choose an authoritative store layout before enabling
two-way sync. Until CV Tailor can report incomplete revisions and guard edits against
conflicts, finish syncing between devices before editing the same profile or application.
