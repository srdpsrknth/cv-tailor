# CV Tailor design system

This is the visual and interaction system for the web UI ([ADR 0031](../DECISIONS/0031-web-ui.md)). The tokens are in [`tokens.css`](tokens.css). The reference mock-up is [`redesign/bench-mockup.html`](redesign/bench-mockup.html), which uses synthetic data only; open it in a browser. When this document and the mock-up disagree, this document wins.

## Idea

CV Tailor is an instrument for checking a document against its sources. The document is the hero. The interface around it is calm, exact and quiet, and it measures what matters to this product: pages, lines spare, letter words, and cost.

**Signature details** (no other product has these, so keep them):
- **Suggestion balloons with leader lines.** Each suggested addition (S1, S2 …) is drawn as a technical-drawing balloon, joined by a line to the exact place in the CV it would change. The line is dashed while pending and solid once approved into a revision.
- **A page-fit scale ruled in document lines** along the page edge, with spare lines hatched and a readout such as "2 of 2 pages · 2 lines spare".
- **An editor-style status line** at the bottom: stage, CV pages, lines spare, letter words, the cost of this run, and spend this month.

## Colour

Proof Desk palette: galley-proof neutrals with one signal colour, proof blue. Semantic colours (ok, warn, bad) never carry meaning alone; they always come with a text label or a shape. The document page stays paper in dark mode, so the document reads true.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--desk` | #E3E7E6 | #131719 | App background |
| `--chrome` | #EEF1F0 | #191E20 | Header, status line |
| `--panel` | #F7F9F8 | #1F2528 | Panels, cards, inputs |
| `--sheet` | #FDFDFB | #D8DDDA | Document paper |
| `--ink` | #1B2023 | #E3E8E6 | Text |
| `--muted` | #4E585E | #A2ACB0 | Secondary text |
| `--ctl` | #717B80 | #6E797E | Every control edge |
| `--line` | #C3CACB | #343C40 | Decorative separators only |
| `--signal` | #1C5E86 | #8FCDE6 | Focus, primary action, balloons, leader lines |
| `--ok` / `--warn` / `--bad` | #24693F / #7E5400 / #A3291D | #7DC598 / #E2B65A / #F28E80 | State, always with text |

**Computed contrast (WCAG 2.x)**, measured against desk / chrome / panel / sheet:

| Light | desk | chrome | panel | sheet |
|---|---|---|---|---|
| ink | 13.18 | 14.46 | 15.55 | 16.14 |
| muted | 5.84 | 6.41 | 6.89 | |
| signal | 5.62 | 6.17 | 6.63 | 6.89 |
| ctl (non-text) | 3.47 | 3.81 | 4.10 | 4.25 |

| Dark | desk | chrome | panel |
|---|---|---|---|
| ink | 14.56 | 13.58 | 12.52 |
| muted | 7.79 | | 6.70 |
| signal | 10.34 | | 8.90 |
| ctl (non-text) | 4.04 | | 3.47 |

On the dark-mode paper, the page ink is 11.96 and the page blue (#1C5E86) is 5.10. The dark focus colour on the paper is only 1.27, so **focus inside the page uses `--sheet-signal`**.

## Type

- **Archivo** for the interface: body 14px/1.5; headings use its width axis (`font-stretch` 112–125%) for a compact, engineered look.
- **Martian Mono** only for ids (S1), figures, costs and keyboard keys, always with tabular numerals. Never use it for prose.
- **Source Serif 4** only inside document previews (CV, letter), never in the interface chrome.
- Scale: 12, 13, 14, 16, 20, 28. Meaningful labels (balloon ids, the manual-edit marker, counts) are at least 12px.
- Fonts are self-hosted in the build. The app makes no runtime request to a font CDN.

## Space and shape

- An 8px grid (4px for optical alignment only). Radius 2px everywhere.
- Hairlines and whitespace do the grouping. Shadows are only for true overlays: the command palette, dialogs and menus.
- No card-in-card, and no rows of three equal cards.

## Layout

Layout is driven by **container queries on the workspace**, not just the viewport, so it adapts to the real space available.

| Workspace width | Zones |
|---|---|
| < 720px | One column: suggestions above the document |
| 720–1023px | Suggestions panel and document (no leader lines; balloon ids still cross-reference) |
| ≥ 1024px, and only if the suggestions column can be ≥ 340px | Suggestions, a 56px leader gutter, and the document |
| ≥ 1600px | The above plus a right **Inspector** (max 480px, one column) showing Checks, Tailoring, Profile changes and Cost and model together, with no tabs |
| Pages fit at ≥ 520px each | Spread view: CV page 1 and 2 side by side; at ≥ 3000px, CV + letter |

Rules:
- **Pages scale as a whole sheet** (fixed internal layout, scaled to fit). Line breaks and "lines spare" are identical at every width.
- **Page width tops out at 820px.** Extra width becomes more pages side by side, never longer lines or empty margins. All content is capped at 3600px and centred.
- **Header:** one row when it fits. When the nav does not fit beside the candidate switcher, a script measures that and moves the nav to its own full-width row. Links are never hidden or scrolled away. On phones (≤ 560px) the header is not sticky, "New application" shows as "New", and the brand shrinks to its mark. Sticky offsets read the measured `--top-h`.
- **Tab rows never scroll to hide items:** they become a 2×2 grid when narrow. Status-line segments drop by priority; "? shortcuts" always stays.
- **No horizontal page scroll from 360px to 5120px.** Wide tables scroll inside their own frame with an edge shadow, and hide low-value columns below 1000px.

## Components (reference: the mock-up)

| Component | Notes |
|---|---|
| Header | Brand, main nav (Desk, New application, Jobs, Library, Profile, Settings), candidate switcher, ⌘K, theme. The **active candidate's full name and id are always visible** (ADR 0022). |
| Candidate switcher | Name and id; on phones they wrap to two lines. Switching clears drafts and editors, and asks first if anything is unsaved. |
| Segmented control | Document (CV, Cover letter, Portal answers, Cost and model), Render (PDF, Word), Density. 2×2 grid on phones. |
| Tabs | Additions · Checks · Tailoring · Profile changes. ARIA tabs pattern. |
| Suggestion card | Balloon id, the posting requirement, proposed wording, where it goes, why, what the profile has. Status as text plus mark. Dismissed cards collapse to "S3 dismissed · Restore". |
| Confirm group | Inline, never a modal. It shows the exact profile change as a diff and says a backup is written first. Focus lands on the group, not on the action button. |
| Sheet | Paper page, folio, page-fit ruler, balloon markers, editable bullets with a character counter, and a manual-edit marker. |
| Readout | "2 of 2 pages · 2 lines spare on page 2". Announced only when pass/fail changes. |
| Inspector section | Checks (status first), Tailoring, Profile changes (with "Regenerate (paid, about $0.20)"), Cost and model. |
| Estimate and run panel | Estimate range, cache result, cap, and what is sent to which provider. Paid confirm, then named stages with elapsed time, spend so far and Cancel. |
| Table | Library: a sortable, filterable table whose company cell is a real link. A preview pane appears at ≥ 1600px. |
| Status line | Stage, pages, lines spare, letter words, this run's cost, the month's spend, "? shortcuts". |
| Command palette | ⌘K / Ctrl+K: Go to each screen, suggestion actions, view options, Verify key. |
| Banner | Warn-wash background for profile changed, candidate switched, and errors. Every banner names its next action. |

## Interaction rules

- **Confirm-first, two approvals.** "Mark true and add to profile" writes the profile, after a backup. "Approve wording and save CV revision" writes a new revision. These are never merged, and never pre-ticked (ADR 0028).
- **Every paid action states its price on the trigger** ("Draft CV and cover letter (paid, about $0.20)"). Its confirmation names the provider, the model, the data sent, the estimate, the cap, and whether the cache can serve it.
- **Reads are free and look free.** Opening, comparing, checking and re-rendering are never styled like paid actions.
- **Undo:**
  - Restore a dismissed suggestion with U, or "Restore" on the collapsed card.
  - Undoing "add to profile" names the backup it restores.
  - Esc backs out of any confirm or edit step.
- **Keyboard.** J/K move between suggestions when the list has focus. A/E/D/U act on the focused card. ⌘K opens the palette, `?` the shortcut sheet. Single-key shortcuts can be turned off in Settings.
- **Motion** is under 200ms, only for state changes, and none under `prefers-reduced-motion`.

## Copy

- Write from the user's side, in plain words. Buttons start with a verb, and never say "OK", "Submit" or "Proceed".
- AI output is marked typographically ("Suggested wording, not yet confirmed"), never with a sparkle icon or a first-person voice.
- Tool names (pdflatex, OpenRouter, model ids) belong under "Cost and model" or "Technical details", not in headings.
- An error says what happened, what was kept, and the next action. Never blame the user.

## Accessibility baseline

WCAG 2.2 AA: contrast as above in both themes, visible focus that is never obscured, targets ≥ 24px (32px on dense desktop lists, 44px for phone primaries), keyboard access to everything including editable bullets, and live regions for stage changes and confirm steps. The full build checklist is in [`redesign/ACCEPTANCE.md`](redesign/ACCEPTANCE.md).

## Anti-generic checklist (review every screen)

- No purple or indigo, gradients, glass, glow or blur. No emoji, and no sparkle "AI" icon.
- No Inter, Geist or default component-library look. No pill badges everywhere, no `rounded-lg` on everything.
- One accent colour, used only for state and action.
- Real, long, messy synthetic content in every state, never lorem ipsum.
- The squint test: the document, not the chrome, is the most prominent thing.
- The swap test: with the logo removed, the screen could not be mistaken for a generic SaaS dashboard.
