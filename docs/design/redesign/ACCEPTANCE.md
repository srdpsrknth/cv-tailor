# Build acceptance criteria from the Bench mock-up review (for Phase 2)

These came from the read-only UX/accessibility review and the responsive sweep of [`bench-mockup.html`](bench-mockup.html) on 28 Nov 2026. The visual and layout items were fixed in the mock-up itself. The items below concern behaviour, so they belong to the real Svelte build: each needs a Playwright or component test before a screen counts as done.

## Keyboard and focus (WCAG 2.1.1, 2.4.3, 2.4.7, 2.4.11)
- Editable CV and letter bullets are reachable by keyboard: tabindex 0, role button, name "Edit bullet: …". Enter edits, Esc cancels and restores the original, and the counter is announced politely. Focus rings inside the page use the page's own signal colour (`--sheet-signal`), because the dark-theme focus colour is 1.27:1 on the paper.
- A skip link goes to `main`, and in the workspace a second one goes to "claims". `main` has an id and tabindex -1.
- On a route change: set `document.title` to "<Screen> · <candidate> · CV Tailor", then move focus to the screen h1 (tabindex -1) or announce the screen in a status region.
- Tabs follow the ARIA tabs pattern: roving tabindex, arrows, Home/End and aria-controls. The portal-answers question list becomes a real listbox or tablist.
- Library and Desk rows: the company cell is a real link. No tabindex or aria-selected on a plain `tr`.
- Paid-run start, cancel and finish move focus to the progress heading or the next action, and announce the result.
- Esc cancels any confirm or edit state.

## Announcements and errors (WCAG 3.3.1, 4.1.3)
- The confirm, edit and CV-wording states each announce what appeared and how to reach the confirm button.
- When wording is empty or over the limit, show a visible message ("Over by 12 characters. Shorten to 320.") with aria-invalid and aria-describedby. The primary button stays enabled and explains itself on press, rather than failing silently.
- All character counters share one component: text "over by N", aria-invalid, and a debounced polite status. Portal answers today use colour only.
- The page-fit readout announces only when the pass/fail state changes.
- The candidate-switch banner is role=status. If unsaved edits exist, switching asks first (ADR 0022 clears editors).
- New application: inline validation for the 50-character minimum and pasted-command rule. The work-authorization rule text is aria-live polite. The Draft button is disabled with a stated reason.

## Shortcuts (WCAG 2.1.4)
- A/E/D/U act only on a focused claim, and J/K only when the claim list has focus. Settings has "Turn off single-key shortcuts".
- The command palette is a proper combobox (aria-autocomplete=list, a result count in a live region, the empty message outside the listbox) with a visible input focus style. It includes "Go to" entries for every screen, "Previous claim", "Dismiss" and "Verify key".

## Landmarks and semantics
- Use `<header>` for the banner. The status line is not contentinfo: use a labelled region with aria-live off.
- Check-list items lead with their status text ("Warning: …").
- The visible label is contained in the accessible name (palette button "Command palette, ⌘K"; the theme button when its label is hidden).

## Honesty and safety (product invariants 3, 11, 12)
- Undo on an accepted claim names what it rolls back ("restores the backup from 10:12") and confirms if other profile edits happened since.
- The status-line spend values are labelled by scope and update after each run.
- Review progress counts saved and dismissed separately ("1 saved, 1 dismissed, 2 to review").

## States still to design (none exist in the mock-up)
Run failed or cost cap reached; key invalid; offline; answer-sheet save conflict (diverged history, sync-conflict file); copy failed; key verification failed; empty profile (first run).

## Naming (decided by the owner, 28 Nov 2026)
- In the UI, "claims" are **Suggested additions**: the panel heading is "Suggested additions", the tab is "Additions", items are "suggestions", and the ids are S1, S2 … (previously C1 …). The code, the services and the ADRs keep the term "claim" (ADR 0028); only the UI labels change.
- "Freshness" is now **Profile changes**.
- "Run details" is now **Cost and model**.
- The old "Changes" tab (how the CV differs from the profile) became **Tailoring**, so it doesn't clash with "Profile changes".
- Still open, lower priority: show tool names (pdflatex, OpenRouter) only under "Technical details", and move the provenance line under the title into Cost and model.
