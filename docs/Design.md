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
