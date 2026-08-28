# PRD — Recursive Knowledge Graph

## 1. Purpose

A personal research and learning tool that represents knowledge as a **recursive, question-driven graph** rather than a static list of notes or bookmarks. The user picks a topic (a "boundary" over the domain network), the system helps decompose it into entities, dimensions, and level-appropriate questions, finds real resources (papers, books, documentaries, docs) that answer those questions, and lets the user navigate the resulting structure by zooming in (entity → network) and out (network → entity) indefinitely.

This implements the two design specs already written by the user (now saved in full — see docs/SystemDesign.md and docs/AgenticArchitecture.md):
- **System Design** (docs/SystemDesign.md) — the knowledge-graph data model (Domains → Networks → Abstractions → Entities → Dimensions → Questions → Resources → Knowledge → New Questions).
- **Agentic Architecture** (docs/AgenticArchitecture.md) — the recursive agent loop that operates on that graph (Observe → Abstract → Decompose → Question → Investigate → Integrate → Detect Boundary → Re-abstract), implemented as a **Master agent + recursively-spawned Ground agents** (Architecture.md §0) rather than a fixed 4-level class hierarchy — a design revision made after comparing the original spec against real-world multi-agent systems; see Architecture.md §0 for the evidence.

## 2. Target user

Solo developer/researcher (the user), for personal use. No multi-tenant, auth, or collaboration features in scope initially. Built local-first so it works with zero external infrastructure beyond a local Neo4j instance and API keys for LLM/search providers.

## 3. Core feature set — the four fundamental operations

| Operation | What it does | Example |
|---|---|---|
| **Navigate** | Move between connected nodes in the graph along existing relationships. | PayPal → Stripe → Banks → Regulators |
| **Zoom** | Change the abstraction boundary — entity unfolds into a network (zoom in) or a network of entities collapses into one node (zoom out). | PayPal → Payment Processing → Authorization → Fraud Detection |
| **Interrogate** | Apply a dimension (Scale, Perspective, Time, or a custom domain-specific dimension) to the current abstraction/entity to generate a question. | PayPal + Economic perspective → "How does PayPal create and capture value?" |
| **Learn** | Attach and consume a resource (book, paper, documentary, dataset, primary source) that answers a generated question, producing knowledge that feeds new questions. | Question → gpt-researcher-style retrieval → cited answer → follow-up questions |

## 4. Worked example — "I want to learn how money transactions work"

This is the canonical user story the whole system is built around. It's not hypothetical: the Phase 1/2 verification scripts already use this exact scenario (`Payment Platforms` abstraction, `PayPal` entity), without that being planned in advance — a good sign the layers built so far are pointed the right way.

1. **The user states an objective, not a search query.** "I want to learn how money transactions work" becomes the seed **Abstraction**: a boundary named "Money Transactions," drawn around the part of the domain network touching Economics, Technology, Law, Psychology, and Networks (SystemDesign.md §2-3).
2. **The system decomposes the abstraction into entities.** Zooming in from "Money Transactions" surfaces **Payment Platforms** (PayPal, Mastercard, Stripe, Visa, banks) as a natural sub-abstraction — Zoom In per SystemDesign.md §7: the abstraction unfolds into a network of entities.
3. **Each entity gets interrogated from multiple dimensions, at multiple levels.** For PayPal: Scale-at-ground-level asks *"How does PayPal process a single transaction?"*; Scale-at-master-level asks *"How does PayPal fit into the global payments ecosystem?"* — same dimension, different level, structurally different question (SystemDesign.md §13, §16 — this is exactly what `scripts/verify_phase2.py` checks). A different dimension (Economic, Legal, Historical — §14) on the same entity produces yet another question again.
4. **Each question is resolved by evidence, not guessed by the LLM.** *"How did PayPal emerge?"* pulls a documentary/history source; *"How does PayPal process transactions?"* pulls technical documentation; *"How does PayPal make money?"* pulls financial reports (SystemDesign.md §18 — resources attach to questions, not topics). The answer becomes Knowledge, which can spawn New Questions (§17, §19).
5. **The result is a non-linear pyramid, not a fixed tree.** PayPal sits under "Payment Platforms," but it could just as well sit under "Fintech Case Studies" or any other abstraction drawn around it later — this is the non-strict-hierarchy rule already built into the Graph Interface (Rules.md rule 13, verified in Phase 1). It's what makes the structure a pyramid that can be entered from any layer, not a single taxonomy the user is forced to descend top-down.
6. **The Roadmap is the sequenced, readable version of that pyramid** — see §4a below.

### 4a. The Roadmap (a distinct output, not just free browsing)

The graph alone is something to *explore*; the Roadmap is something to *read*. Once enough of the graph exists under an abstraction (entities + attached questions + evidence), the system assembles an ordered **learning path** through it, rather than leaving the user to wander:

- **Input:** the sub-graph reachable from the seed abstraction — entities, their attached questions, and each question's evidence/confidence.
- **Output:** an ordered sequence of (Question → Resource → short summary) steps that reads coherently start to finish, ending wherever the user's original objective is actually answered.
- **Ordering rule (v1, kept deliberately simple):** master-level questions before ground-level questions within each branch — orient broad before drilling into specifics, mirroring SystemDesign.md §16's own worked example (individual → organization → society is already a broad-to-specific reading order, not an arbitrary one). Within a level, order by position in the zoom chain: parent-abstraction questions before child-entity questions.
- **Architecturally, this is a pure function over an existing graph** (`generate_roadmap(abstraction) -> list[Question]`), not a new agent tier and not new agent behavior — consistent with Rules.md's "keep the graph mechanically dumb, put reasoning in the layer above it" rule. It runs once enough of the graph exists to be worth sequencing, not continuously.
- Scheduled as a Phase 6 deliverable (docs/Phases.md) — it's what the visualization UI actually renders as a "start here" reading list alongside the free-explore graph view.

## 5. Functional requirements (v1 scope)

Status tags below follow Architecture.md §0.1's discipline — [BUILT] the code exists, [VERIFIED] a real run has demonstrated it, [VISION] not started. See Architecture.md §0 for the full theory (this list only tags the original requirements; it doesn't restate the reasoning behind them).

1. **[VERIFIED]** User can define an **abstraction** (a named, cheap-to-revise boundary/view over a set of domains/entities) as a starting point — not a permanent structural commitment (Architecture.md §0).
2. **[VERIFIED]** System can **decompose** an abstraction into entities and sub-domains automatically, via a Master agent recursively spawning Ground agents (not a fixed multi-level class hierarchy — Architecture.md §0), under an enforced spawn budget so a simple query doesn't trigger runaway agent creation.
3. **[VERIFIED]** System applies **dimensions** (starting with the 3 universal ones: Scale, Perspective, Time, plus custom ones the agents discover) to generate **level-aware questions on demand** — the same dimension must produce different questions depending on the current abstraction/agent level, and questions are generated lazily (only for what's actually being investigated or viewed), never precomputed for a whole abstraction upfront. Since v1 was scoped: dimensions now also **compose** (multiple lenses jointly framing one investigation, not concatenated) and, when none is given, the system names the **implicit** lens it used anyway rather than applying one silently — Architecture.md §0.2.
4. **[VERIFIED]** Questions decompose recursively into sub-questions (a question graph), and propagate upward (parent chain only, no lateral agent-to-agent messaging) when an agent hits a **boundary** (missing context needed to answer).
5. **[VERIFIED]** System retrieves real **resources** per question from live APIs (web search, academic papers, books, video) and attaches them to the question node. (Tavily/YouTube require API keys not yet configured — Wikipedia/arXiv/Semantic Scholar/Open Library work keyless and are what's actually been exercised under real use so far.)
6. **[BUILT, UI not started]** User can **navigate and zoom** the resulting graph visually (nodes = entities/abstractions, edges = relationships), see attached questions/resources per node. **An entity may belong to more than one abstraction at once** (non-strict hierarchy) — the UI must not assume every node has exactly one parent. The graph operations this needs (`zoom_in`, `explain_entity`, `get_decomposition`) are built and verified server-side (Architecture.md §2); no visual frontend exists yet (Phase 6, [VISION]).
7. **[PARTIAL]** Every claim/answer the system produces carries **evidence, confidence, and provenance** — nothing is presented as unconditional truth. `evidence`/`confidence` are enforced today (Rules.md rule 4). `provenance` now has real, verified tooling (structural + content provenance, Architecture.md §0.3-§0.4) but is not yet wired into the default answer path — it must be explicitly invoked, it isn't automatic yet.
8. **[VERIFIED]** The graph and agent state must be **resumable** — closing and reopening the app should not lose progress.
9. **[VERIFIED]** Entities are **canonical and deduplicated** — rediscovering the same real-world thing under a different name/context merges into the existing node rather than creating a duplicate. (A real duplication bug — an older script bypassing the dedup path — was found and fixed by actually using `merge_entity` for the first time; see Memory.md.)
10. **[VISION]** Once a graph exists under an abstraction, the system can produce a **Roadmap** — an ordered (Question → Resource → summary) reading sequence through that graph, distinct from free Navigate/Zoom exploration (see §4a). Scheduled for Phase 6; not started.

**Evolved since this list was first written (not a requirements change, a deeper understanding of the same requirements — see Architecture.md §0 in full):** the system turned out to matter less as "the one correct knowledge graph" and more as a **session-scoped workspace** for constructing a useful model of whatever's being investigated — persistence is an opt-in decision (`persist_to_graph`), not automatic, and the same entity can be validly decomposed along different lenses depending on the question being asked. Three real, unscripted learning sessions (Memory.md, 2026-08-28) then surfaced a frontier this PRD didn't originally anticipate: synthesis can assert more than was actually investigated, and can flatten genuinely competing explanations into false agreement. That's the epistemic layer in Architecture.md §0.2-§0.5 — real, partial progress, not yet a v1 requirement, but likely to become one.

## 6. Non-functional requirements

- Runs entirely on the user's machine for v1 (local Neo4j via Docker, local SQLite for agent/task state).
- Architecture must not block a later move to a hosted/cloud deployment (see Architecture.md — every chosen local tool has a documented cloud upgrade path).
- LLM/search API costs should stay low for solo/prototype use — tiered model usage (cheap models for high-volume ground-level calls, expensive models reserved for rare master-level structural decisions) and free-tier APIs are used wherever they meet the need (see Architecture.md).

## 7. Out of scope (v1)

- Multi-user accounts, sharing, permissions.
- Mobile app.
- Fully automatic "understand the entire internet" crawling — the system investigates only within the abstraction boundary the user or Master Agent has currently defined.
- Guaranteeing factual correctness — the system surfaces evidence and confidence, not verified truth.

## 8. Success criteria

Given a single topic/entity as a starting abstraction, the system should be able to, end-to-end:
1. **[VERIFIED]** Decompose it into a small network of related entities/domains.
2. **[VERIFIED]** Generate at least one meaningful, level-appropriate question per dimension per node.
3. **[VERIFIED]** Retrieve at least one real, relevant resource per question from a live external API.
4. **[VISION]** Let the user visually zoom from the top-level abstraction down into a concrete mechanism, and back out, through the Cytoscape.js graph UI — the underlying `zoom_in` operation is [VERIFIED] server-side; no UI exists.
5. **[VERIFIED]** Survive an app restart without losing the graph or in-progress questions (state is persisted, not in-memory only).
6. **[VERIFIED]** Not spawn a runaway number of agents or questions for a simple, narrow query — the spawn budget and lazy question generation (Architecture.md §0) should be visibly bounded, not just theoretically bounded.
7. **[VISION]** Produce a coherent Roadmap (§4a) for the worked example (§4) that a person could actually follow start to finish to learn how money transactions work — `generate_roadmap` is not built (Phase 6).
