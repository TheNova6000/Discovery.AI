# Design — Recursive Knowledge Graph (placeholder)

**[VISION] — entirely.** No UI code exists yet (Phase 6 in Phases.md, itself [VISION] — not started). This file is a placeholder to be fleshed out properly once the Cytoscape.js frontend is built, so decisions here are provisional defaults, not final commitments. Nothing below should be read as [BUILT] or [VERIFIED] under any circumstance.

## Provisional direction

- **Theme**: dark-first, since this is a graph-exploration tool likely used for long focused sessions (similar to Obsidian/Roam graph views).
- **Node encoding**: node color/size should encode graph-structural properties, not be arbitrary — e.g. abstraction/domain nodes visually distinct from entity nodes; node size could reflect connectivity (per Section 46 of the Agentic Architecture spec: importance ≠ size, but visually surfacing centrality is still useful).
- **Compound nodes**: abstractions render as Cytoscape.js compound (nested) nodes so "zoom in" is a literal expand interaction, not a page navigation — matches the Zoom operation in PRD.md directly.
- **Typography**: a monospace or semi-monospace UI font fits the "system/graph" feel and keeps node labels compact; not yet chosen.
- **Color palette**: not yet chosen — defer to whatever the dataviz/artifact-design guidance recommends at build time for accessible categorical + sequential palettes (dimension types, confidence levels, etc. will need distinct encodings).

## To be filled in at Phase 6

- Full color palette (categorical for domains/dimensions, sequential for confidence scores).
- Font choices (UI text vs. node labels).
- Layout algorithm choice within Cytoscape.js (e.g. cola, fcose, breadthfirst) per graph size/shape.
- Interaction spec: hover states, click-to-expand vs. double-click, question/resource panel layout.

## Learning Portal extension (PRD.md §9, Architecture.md §6) [VISION — provisional, filled in properly at Phase 12]

This is a **second, distinct surface** from the graph-exploration UI above, with a different usage context — reading prose and writing code in focused sessions, not exploring a node graph — so it doesn't need to inherit the graph UI's dark-first, node-encoding-driven direction wholesale. Same caveat as above: nothing here is [BUILT]; these are provisional defaults, not commitments.

- **Theme**: light-first default with a dark-mode toggle (unlike the graph UI's dark-first default) — matches the reading/coding context this surface lives in (documentation sites, code editors), where users commonly toggle rather than have one mode imposed. Respect `prefers-color-scheme`.
- **Typography**: a humanist sans (system UI stack — avoids a webfont dependency this project hasn't needed anywhere else) for lesson prose; a monospace code font (matching whatever Monaco defaults to, e.g. a `ui-monospace` stack) for code blocks and the editor — a real pairing, not one font doing both jobs.
- **Code editor**: Monaco (Rules.md §1 addition), themed to match the page's light/dark state rather than defaulting to Monaco's own built-in themes unmodified.
- **Layout patterns**:
  - Course overview: a **path/tree course map** (Duolingo-shaped — Architecture.md §0.38.3), not a plain list and not the free-explore Cytoscape graph. It's the same `requires`-edge topological order the Curriculum Compiler already produces (PRD.md §9.3), rendered as a game map (nodes along a path, branches where the prerequisite graph actually branches) instead of a flat progress bar — visually distinct from the knowledge-graph exploration surface, but built from the same real ordering, not decorative invention.
  - Lesson page: prose + inline runnable example, split from or above the exercise rather than mixed into one scroll — mirrors the existing "explanation, then try it" shape freeCodeCamp-style sites use, not novel for its own sake.
  - Exercise page: editor + a distinct test-results panel (pass/fail per test, not just an aggregate score) with hint disclosure that's opt-in per attempt, not shown by default — matches PRD.md §9.5's "fail a hidden edge case, get a hint" flow.
- **Confidence/provenance surfacing**: a lesson sentence sourced from a specific `Claim` should be able to show that source on demand (hover/click), the same honesty principle the graph UI's "bounded view, never implies completeness" rule already commits to (README) — a course should not read as more authoritative than its underlying evidence actually is.
- **Gamification surface (Architecture.md §0.38.3, Rules.md rule 22)**:
  - **Streak**: a flame/counter in the persistent header, with a visible "freeze" state (a missed day that doesn't reset it, Duolingo's forgiveness pattern [research, 2026-09-16]) rather than punishing every lapse — this is a UI treatment of a real event in the Learner Model's log, not a UI-only trick.
  - **Per-concept rank**: a small kyu-like badge (Codewars-shaped) on each course-map node, reflecting that concept's real recorded pass rate — never shown on an untouched concept (no rank until there's a real attempt to derive one from).
  - **XP and pass/fail feedback**: an immediate, fluid animation on passing an exercise (confetti/particle burst — dependency-free CSS/JS) or on a module completing (a course-map node visually "lighting up") — reuses `frontend/wasm-fluid`'s existing compiled asset for the underlying motion where a background/ambient effect is wanted, rather than a new animation library.
  - **No leaderboard/league UI in v1** (PRD.md §9.8) — a "personal best" stat (fastest solve, longest streak) is the only comparative element, and it compares the learner only against their own history.
- **Color palette**: not yet chosen — defer to dataviz/artifact-design guidance at Phase 12 build time, same as the graph UI section above; the one constraint already decided is that mastery/progress indicators (Learner Model, PRD.md §9.6.6) need a sequential encoding distinct from the graph UI's confidence-score sequential encoding, since they measure different things and appearing on the same page (if ever) must not be visually confusable. Rank badges (Codewars-shaped) should read as a categorical/ordinal scale, not reuse the confidence sequential scale either — three different things (evidence confidence, learner mastery, concept rank) need three visually distinguishable encodings.

## To be filled in at Phase 12

- Full color palette for the Learning Portal surface (progress/mastery sequential scale, pass/fail states, hint-disclosure states).
- Exact font stack (verify humanist-sans + monospace pairing renders consistently across the same browsers the graph UI already targets).
- Monaco theme tokens mapped to this project's light/dark tokens.
- Interaction spec: hint disclosure, remedial-step framing (how a learner is told "this is a remedial step" without it reading as a penalty), test-results panel layout.
