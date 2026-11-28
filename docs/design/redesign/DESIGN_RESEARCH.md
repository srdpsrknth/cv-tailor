# CV Tailor UI redesign: design research (Nov 2026)

Method note: web search in standard mode plus a few page fetches. Many sources are practitioner blogs, not standards bodies. Items marked (opinion) are heuristics, not settled practice. Items marked (verify) were taken from search snippets and should be confirmed against the full page before being relied on. Palette hex values and font pairings in section 3 are my design proposals, not findings from sources. Contrast ratios have not been computed; run them with the contrast skill before adopting.

## 1. What the sources say

### 1.1 "AI slop" UI and how to avoid it
- Slop is design with no author: the average of many interfaces, shipped without anyone asking whether it should look that way. Flows are correct but have no identity. https://builtin.com/articles/ai-design-slop-era
- Commonly named tells (opinion): Inter everywhere, purple-to-blue gradients, centered hero, three equal cards, symmetric grids, placeholder names such as "John Smith", bland headlines, generic fade-in motion. https://world.hey.com/kostac/spot-the-slop-a-ui-designer-s-guide-to-fixing-ai-defaults-4c448c9c and https://github.com/Laith0003/ux-skill/wiki/Anti-AI-slop-ban-list
- Recurring fixes: write real copy first and let it drive layout; add less decoration; make motion reflect product character; curate your own references; start from the user journey, since a checklist only treats symptoms. https://builtin.com/articles/ai-design-slop-era
- Caveat: "never use Inter" style rules are opinion. Several font guides still recommend Inter for body. The point is to make deliberate choices, not to ban one font.

### 1.2 AI suggestions: provenance, accept/reject
- NN/g: people rarely click citations and can over-trust output because citations exist. Style sources differently from the body, put them next to the claim they support, link to the exact supporting passage, use descriptive labels (not "Source"), avoid presenting reasoning as certain, keep disclaimers near the input and actionable, avoid first-person human-like phrasing. https://www.nngroup.com/articles/explainable-ai/
- Human-in-the-loop (accept, edit, reject) is a standard 2026 pattern. https://www.lazarev.agency/articles/ai-ux-patterns
- Scale the accept path to confidence: high confidence focuses Accept, medium shows the rationale first, low requires an edit before commit. https://www.computer.org/publications/tech-news/community-voices/copilot-ergonomics-ui-patterns
- Acceptance is not proof of correctness; users accept when reviewing is hard. Reduce verification cost. (same IEEE piece, partially verified)
- Light, in-flow provenance (small source count expanding to snippet, hover card distinguishing sourced from generated text) beats audit-console UIs. https://www.telerik.com/blogs/ai-ux-patterns-user-trust

### 1.3 Long-running tasks
- Nielsen: show a progress indicator past about 10 seconds, ideally percent-done; never stall or reset a bar; long-running agents need progress visibility, checkpoints and clear cancellation, and must serve users who walked away. https://www.uxtigers.com/post/2026-predictions-halfway and https://jakobnielsenphd.substack.com/p/2025-review
- The appearance of progress matters nearly as much as real progress (Myers 1985, cited in https://uxdesign.cc/the-waiting-problem-in-ai-products-e7c11fd5a825).
- NN/g State of UX 2026 notes growing fatigue with AI experiences that feel rushed or disconnected from real needs. https://www.nngroup.com/articles/state-of-ux-2026/

### 1.4 Exemplars
- iA Writer: strips interface to the text, custom typeface, "hands on the keyboard, mind in the text"; Apple Design Award finalist 2025. Lesson: the document is the hero, chrome recedes. https://ia.net/topics/ia-writer-5-from-raw-to-cooked-to-sushi
- Linear March 2026 refresh: fewer, smaller icons; lighter borders and fewer separators; warmer, less saturated greys replacing cool blue; dimmer sidebars so content stands out; choice of Enter vs Ctrl+Enter to send. Lesson: calm comes from removing, not adding. https://linear.app/now/behind-the-latest-design-refresh and https://linear.app/changelog/2026-03-12-ui-refresh (verify details; from snippets)
- Job tools (Teal, Huntr, Kickresume): sources are mostly vendor comparisons, no independent UI teardown found. Teal is described as tracker-first with a secondary resume builder; Huntr favours speed and visibility; Kickresume is design-led but lacks DOCX export and tracker. Many AI features are paywalled. Inference (mine): this category defaults to template-gallery marketing visuals and score badges; a local review tool can differentiate by looking like a workbench for documents. https://huntr.co/blog/huntr-vs-teal , https://enhancv.com/blog/teal-review/
- GitHub PR review, Figma comments, Bear, Craft, Lex were not researched in this pass. Known conventions I would draw on without citation: side-by-side/inline diff with per-hunk actions, anchored comment threads, resolved/unresolved states. Treat as prior knowledge.

### 1.5 Keyboard-first
- Palette (Cmd/Ctrl+K) for long-tail actions with shortcuts shown beside results; searchable cheat sheet on `?`; consistent keys across screens; OS-aware labels; fuzzy search; introduce accelerators after the user has done the action the standard way (NN/g). https://developer.dynatrace.com/develop/keyboard-shortcuts/plan-keyboard-shortcuts/ , https://blog.superhuman.com/how-to-build-a-remarkable-command-palette/ , https://www.nngroup.com/articles/ui-accelerators/
- Single-character shortcuts must be remappable/disableable or only active when focus is not in a text field (WCAG 2.1.4).

### 1.6 Typography
- Sources recommend serif options for editorial feel: Fraunces (expressive display), Newsreader (open-source, commissioned by Google Fonts for on-screen long reading), Instrument Serif (display), Source Serif 4 (calm reading). Sans partners: Geist, Source Sans 3, DM Sans. https://muz.li/blog/best-free-google-fonts-for-2026/ , https://www.productiontype.com/news/new_fonts_from_production_type_newsreader , https://fontalternatives.com/best-fonts-for/news-editorial/
- Vendor-driven lists; test any pairing at real sizes. Check licences (all above are OFL on Google Fonts, to my knowledge; confirm).

### 1.7 Accessibility baseline
- WCAG 2.2 AA remains the compliance baseline. WCAG 3.0 is still a Working Draft (update 10 Sep 2026), will change before finalisation, does not replace WCAG 2; AbilityNet estimated finalisation not before 2028. https://www.w3.org/TR/2026/DNOTE-wcag-3.0-explainer-20260910/ , https://www.w3.org/WAI/news/2026-03-03/wcag3 , https://abilitynet.org.uk/resources/digital-accessibility/what-expect-wcag-30-web-content-accessibility-guidelines
- APCA is not established as part of any conformance model; still under discussion. Use WCAG 2 ratios (4.5:1 body, 3:1 large text and UI components) for compliance; APCA may be used as a secondary sanity check only.
- WCAG 2.2 additions to honour: focus not obscured (2.4.11), target size minimum 24px (2.5.8), dragging alternatives (2.5.7), consistent help (3.2.6), redundant entry (3.3.7), accessible authentication. Prior knowledge, not re-fetched.

## 2. Trends worth adopting (and why they fit)

1. Document as hero, chrome recedes (iA Writer, Linear). The app is a reading/editing tool; paper, text and diff should take roughly 70 percent of the screen.
2. Calm, warm, low-saturation neutrals and fewer separators (Linear 2026). Long review sessions; reduces fatigue; reads as human rather than SaaS.
3. Provenance inline and quiet. Each claim carries a small source marker that expands to the exact profile fact; unsourced or inferred claims are visibly different in style (NN/g). This is the core of confirm-first.
4. Confidence-scaled review. Claims that match profile facts exactly: one-key accept. Inferred or reworded claims: show rationale and source side by side first. Anything with a number or authorisation wording: require edit or explicit tick.
5. Checkpointed, honest progress. Named stages (reading posting, matching profile, drafting CV, drafting letter, fit check) with elapsed time, per-stage cost so far, cancel at any point, and result preserved on leaving. Percent bars only where truly measurable.
6. Cost as a quiet ledger, not a warning. Estimate before running, actual after, per-run and running total in a fixed place; ask before spending (matches project rule).
7. Keyboard-first with a visible palette and `?` cheat sheet. J/K move between claims, A accept, E edit, R reject, Cmd+Enter run.
8. Real typographic craft: a reading serif for documents and headings, a restrained sans for controls, tabular figures for cost, hanging punctuation and proper quotes.
9. Purposeful, minimal motion; honour prefers-reduced-motion.
10. Designed empty states that use the user's own next step (for example "Paste a posting to begin"), no illustrations.

## 3. Trends to avoid
- Glassmorphism, blur, aurora or mesh gradients, purple/indigo accents, glowing borders.
- Default shadcn/Tailwind look: rounded-xl cards on grey-50, Inter, pill badges everywhere, lucide icon on every row, "Get started" hero.
- Emoji or sparkle icons as the AI marker. Use a neutral typographic mark.
- Chat-bubble framing for what is a document workflow; first-person AI voice ("I've drafted...").
- Match-score gauges and gamified percentages (job-tool cliche) unless backed by a real, explainable computation.
- Decorative skeletons and spinners for multi-minute tasks; indeterminate bars that stall.
- Confetti and celebration animations.
- Placeholder-as-label inputs; icon-only controls without tooltips.
- Card-in-card nesting and equal three-column feature grids.

## 4. Three candidate visual directions

### A. "Proof Desk" (editorial, print proofing)
- Mood: a copy editor's desk; warm paper, ink, one red-pencil accent. Quiet, literate, confident.
- Type: headings and document text Newsreader (variable, OFL); UI labels Source Sans 3 or Geist; figures and keys in Geist Mono or JetBrains Mono. Optional Fraunces for the single app title only.
- Palette: paper #F6F2E9, surface #FBF8F1, ink #1F1B16, muted ink #6B6358, rule #DDD5C4, accent proof-red #B3261E (suggestions, active), confirm green #2F6B4F, caution ochre #9A6A12, source-highlight wash #F1E3B5.
- Dark: #17140F paper, #E9E2D3 ink, accent #E0725F.
- Layout: three columns at desktop. Left: slim rail of stages (Profile, Job, Review, Documents, Questions, Applications) as typeset list, no icons. Centre: the document as a literal page on a slightly darker desk. Right: margin notes column, like marginalia, holding claims with provenance, anchored to lines.
- Signature details: suggestions appear as a red-pencil underline with margin note; accepted text turns ink; page-fit shown as a ruler down the page edge.
- References: iA Writer, Linear's calm neutrals, Bear's warmth, print proof marks.

### B. "Bench" (precise, tool-like, Swiss)
- Mood: a well-made instrument; dense, exact, grid-driven, monochrome with one signal colour.
- Type: Geist or Instrument Sans for UI; Source Serif 4 for document previews; Geist Mono for IDs, cost, shortcuts.
- Palette: chalk #F2F2EE, panel #FFFFFF, graphite #16181A, mid #5D6368, hairline #D9DBD6, signal teal-green #0F766E replaced by a more distinct cobalt-ink #1D3FD8 only for focus and primary; accept #1E7A46; reject #B42318; pending amber #A15C07.
- Layout: strict 8px grid, two-pane split (source on left, output on right) with a diff gutter; top bar with breadcrumb and cost ledger; bottom status line like an editor (stage, tokens, cost, page count).
- Signature details: numbered claims (C1, C2) cross-referenced between source and output; hairline rules instead of cards; tabular figures.
- Risk: closest to generic developer-tool look if cobalt and Geist are used without personality. Needs custom numbering and ruled-line details to avoid it.
- References: Linear, GitHub PR review, Figma comments, Dynatrace-style density.

### C. "Atelier" (warm, tactile, folio)
- Mood: a tailor's workroom; muted greens and clay, cloth-and-thread metaphors used lightly (never illustrated). Friendlier and more approachable for a job seeker under stress.
- Type: Fraunces (soft, opsz axis) for headings; Newsreader or Source Serif 4 for documents; DM Sans or Figtree for controls.
- Palette: linen #F3EEE6, bone #FAF7F1, bottle green #1F3D36, thread clay #B5532F, chalk-line #CFC7B8, ink #22201C, mend-blue #3B5B7A for info, confirm #3E7B52.
- Layout: top stage "tape measure" strip showing the pipeline as a horizontal measure with ticks; workspace is a single main column with a collapsible provenance drawer; applications page is a folio list rather than a kanban.
- Signature details: stitched-line dashed rule for pending items; page-fit as a tape measure showing 2.0 of 2 pages.
- Risk: whimsy can age; keep metaphor in naming and rules only.
- References: Craft, Bear, Are.na, Kickresume's approachability without its template-gallery look.

Recommendation (mine): A as the base, borrowing B's numbered claims and bottom status line. It best serves a document-review tool and is least likely to look templated.

## 5. Interaction patterns by screen

1. Profile pick. If one usable profile, restore silently and show it in the header; if several with no valid memory, a plain typeset list with last-used dates. No avatars or cards. Switch via palette.
2. Job intake (paste or search). One large paste area with visible label; detect title, company, country; show parsed fields as editable inline text for correction before spending. Search results as a ruled list with source and date. Show estimated cost and "Generate" with the verb stated ("Draft CV and cover letter, about X").
3. Generation progress. Named stages list with elapsed time and cost so far; cancel always available; safe to navigate away; completion notice in-page and in tab title. Errors state what failed, what was kept, and next action.
4. Claim review (confirm-first). Source-vs-output: left the job requirement or profile fact, right the proposed claim. Each claim row: claim text, provenance chip with fact name that expands to the exact profile excerpt, status (confirmed, needs edit, unsupported). Keys: J/K, A accept, E edit, R reject, U undo. Bulk accept only for exact-match claims. Unsupported claims cannot be accepted without edit. Show remaining count and keep a visible "n of m reviewed". Toast-free: state changes inline with undo.
5. Document edit and revise. WYSIWYG-ish page with inline editing of bullets; changes since last generation tracked as a visible diff toggle; revision history saved as named versions; "revise" input scoped to a selection with cost estimate; regenerate never overwrites manual edits without a diff and confirmation.
6. Preview and page-fit. PDF and DOCX tabs on same page frame; fit meter ("CV 2 of 2 pages, 3 lines spare"; letter "4 paragraphs, 301 words of 290 to 310"); overflow lines highlighted on the page; one-click jump to the offending bullet. Review both formats before marking final.
7. Portal questions. Question list on left, answer editor on right with character limit counter, provenance chips, copy button with confirmation state, and per-question regenerate with cost.
8. Applications tracker. Dense ruled table (company, role, date, status, files) with filter and keyboard navigation; row opens the saved application; no kanban unless needed. Status as text with a small coloured marker, not pills.
9. Empty states. One sentence, one action, no illustration (for example "No applications saved. Generate one from a job posting.").
10. Global. Cmd/Ctrl+K palette, `?` cheat sheet, persistent cost ledger (this run, today, store total), visible save state, light and dark themes, prefers-reduced-motion respected.

## 6. Anti-generic checklist
- [ ] Typefaces chosen on purpose, not framework defaults; at least one serif for documents; mono or tabular figures for numbers.
- [ ] No purple/indigo, no gradients, no blur, no glow, no glass.
- [ ] Neutrals are tinted (warm paper or chalk), never pure white on grey-50 plus slate.
- [ ] One accent colour, used for state and action only; semantic colours never carry meaning alone.
- [ ] No card-in-card, no equal three-card rows, no hero blocks.
- [ ] Rules and whitespace do the grouping; shadows only for true overlays.
- [ ] No emoji; icons only where text is worse; every icon-only control has a tooltip and name.
- [ ] Real copy in every state, written before layout; verb-first buttons; no "AI magic" language.
- [ ] AI output marked with a typographic convention, not a sparkle.
- [ ] Every claim shows provenance; unsupported claims look different.
- [ ] Signature detail exists (margin notes, numbered claims, page ruler) that could not be swapped into another product.
- [ ] Motion limited to state changes, under 200ms, reduced-motion honoured.
- [ ] Test with real, long, messy content (long job titles, 40-line postings), not lorem ipsum or "John Smith".
- [ ] Squint test: the document, not the chrome, is the most prominent thing.
- [ ] Screenshot swap test: remove the logo; would it be mistaken for any other SaaS dashboard? If yes, iterate.

## 7. Accessibility acceptance (WCAG 2.2 AA)
- Contrast 4.5:1 body, 3:1 large text, icons, focus rings, input borders; check both themes. Compute with a tool, do not eyeball.
- Visible focus on every interactive element, not obscured by sticky bars (2.4.11).
- Targets at least 24px (2.5.8); prefer 32px in dense lists.
- Keyboard: every action reachable; single-key shortcuts disabled in text fields and remappable (2.1.4); no keyboard traps in editor.
- Live regions for generation stage changes and fit results; do not rely on colour alone for accept/reject/pending.
- Text resizes to 200 percent and reflows at 320 CSS px for non-document panes (document page may scroll).
- Respect prefers-reduced-motion and prefers-color-scheme.
