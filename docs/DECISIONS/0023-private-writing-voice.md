# 0023 — Per-profile cover-letter voice is private style guidance, not candidate facts

**Status:** Approved and implemented (2026-11-17), following the owner's request
to improve cover-letter purpose, naturalness and fidelity to their nominated letters.

## Decision

The shared cover-letter brief now asks for a specific reason for the actual work,
one or two explained examples, practical meaning for users and a concise closing.
It discourages CV compression, keyword inventories, repeated fit claims and generic
flattery. Four paragraphs, 290–310 body words, one page, factual ownership,
ongoing-work status and overseas-support requirements are unchanged.

Optional `<store>/profiles/<profile_id>/writing_style.json` contains version 1
preferences: `tone`, `preferences`, `avoid` and `sign_off`. Reference paths and
provenance may be kept alongside these as private audit metadata, but only the
distilled preference fields are sent to the model. Old letters are never a source
of new facts, results, tools or personal motivations. A loose `--profile <path>`
does not inherit a store profile's preferences.

The effective preference context is appended to the cover-letter brief only. The
same bytes are included in its existing cache-key input. Changing a voice brief
invalidates the paired generation cache; changing audit-only source paths does not.
An absent file uses the shared brief; an existing malformed/oversized file fails
before paid calls rather than silently dropping the requested voice.

The owner's personal reference excerpts, analysis and actual style file stay in
the private store. The public repository contains only generic rules, code and
synthetic tests. Existing applications are not overwritten or regenerated.

Candidate policy uses a separate optional `candidate_guidance.json` with version 1
`cv`, `cover_letter`, and `layout` lists. Each list is used only for its matching
provider call. The cache key covers the effective instructions, and factual rules
and country overrides retain precedence. The migration command reads the archived
sources as data, verifies the current profile rules, and installs only the selected
clauses. Generation reads the scoped sidecar directly.

*Amended 2026-11-27 (PR #1).* The version 1 file also accepts an optional `acronyms` list (up to
100 single words, at most 32 characters each) naming acronyms that keep their upper case in that
candidate's skill headings. It is a render-only setting, threaded to the renderers as
`extra_acronyms`, with no global state; unknown keys are still rejected. The `cv`, `cover_letter`
and `layout` lists are used in the matching prompts (see ADR 0026 for what belongs there). Syntax
and examples: [HOW_TO_GENERATE.md](../HOW_TO_GENERATE.md#candidate-guidance-optional).

## Verification boundary

Tone cannot be certified by word counts, phrase tests or an AI detector. Use human
review and concrete examples. Offline tests prove scope, isolation, validation and
cache behaviour, not the quality of new live prose. No additional model-review pass
or paid evaluation has been introduced. Future drafts still need the owner's reading.
