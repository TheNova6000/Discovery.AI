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

## 9. Extension — Learning Portal (Course Compiler + Coding Challenges) [VISION — all of §9]

Everything below is a scope extension decided 2026-09-16, not yet started. It does not replace §1-§8 above — the recursive investigation engine (Master/Ground agents, Question Engine, Evidence Engine, Graph Interface) is the load-bearing foundation this extension builds *on top of*, unchanged. Status tags follow the same discipline as §5/§8: [VISION] until a real run demonstrates it.

### 9.1 Purpose

The Roadmap (§4a) already turns a graph into something *readable* — an ordered (Question → Resource → summary) sequence. This extension turns a graph into something **followable and checkable**: a course with lessons a person reads, exercises a person writes code against, and tests that actually run that code — the freeCodeCamp/GeeksforGeeks-style learning loop, but compiled from the same investigation the rest of this project already does, not hand-authored and not generated from a bare LLM prompt.

Concretely: `Topic → research (existing engine) → knowledge graph (existing engine) → ordered curriculum (new) → lessons with sourced explanations (new) → coding exercises with independently-validated tests (new) → learner progress that feeds back into what gets taught next (new)`.

### 9.2 Target users

Widens §2's "solo developer/researcher" scope: this extension is explicitly for **learners**, who may or may not be the same person operating the investigation engine. v1 stays single-tenant/local-first like the rest of the project (Rules.md §4 — no auth/multi-user before Phases.md calls for it); the deployed Google-login session model already built for the chat interface is the natural place multi-learner support would eventually attach, but that's not this extension's problem to solve first.

### 9.3 Relationship to the existing model — reuse, don't reinvent

- **The Curriculum is the Roadmap's successor, not a parallel structure.** Where the Roadmap orders *questions* (master-before-ground, then zoom-chain position), the Curriculum orders *concepts* by prerequisite, and attaches a lesson + exercise to each — same "pure function reading an already-built graph" shape as `generate_roadmap` (PRD.md §4a, Rules.md rule 14), extended rather than replaced.
- **No new relation family.** `backend/questions/relation_types.py` already has a `DEPENDENCY` family (§0.25/§0.36's precedent for when a new family is and isn't justified). Prerequisite ordering (`requires`/`prerequisite_of`) is a `DEPENDENCY`-family relation type, added the same architecture-first/implementation-second/verification-third way `HISTORICAL` was (Architecture.md §0.36, Memory.md 2026-09-03) — not a reason to invent an eighth family.
- **No parallel "three graphs."** An earlier framing of this idea (see chat history) proposed separate Research/Curriculum/Learner graphs. That contradicts this project's core, already-verified design: **one world model, multiple projections** (README, Architecture.md §0). The Curriculum is a **view** over the same canonical Neo4j graph the investigation engine already writes, exactly like a Roadmap or a network-projection is a view — not a second store. Per-learner progress is the one genuinely new kind of state (§9.6.5) and is scoped as narrowly as the epistemic layer was (Architecture.md §0.3-§0.5): a standalone store, not a rewrite of the world model's meaning.
- **Evidence/confidence/provenance carries over unchanged.** A lesson's explanatory text is a claim like any other (Rules.md rule 4) — it must trace to retrieved evidence, using the same `Claim` model and the same content-provenance tooling already built (`backend.questions.audit_synthesis`, Architecture.md §2), not a separate "trust the LLM" path for course content specifically.

### 9.3a Learning Research Mode — research completeness is not the same objective as dependency discovery [VISION, decided 2026-09-16]

§9.3 above says the existing engine's investigation feeds the Curriculum unchanged. That assumption doesn't survive contact with what §4a's Roadmap actually looks like once run against a real investigation (Architecture.md §0.39.2, §0.40): the base engine's default investigation stops once it has built a **dependency/structure graph** — one question per entity, one evidence pass, decomposition bounded unless a user explicitly asks to "go deeper" — because that's the right default for *exploratory chat* (bounded latency, token cost, retrieval cost, graph growth, free-tier key budget). A course built directly from that default would just be a polished-looking shallow course: correct as far as it goes, but not researched deeply enough to responsibly teach from.

**These are two different objectives, and they need two different stopping conditions, not one investigation policy stretched to cover both:**

- **Exploratory mode** (§1-§8's existing, unchanged, default behavior): stop once a dependency/structure graph exists. Right for free chat exploration; wrong as the sole gate before compiling a course.
- **Learning research mode** (new, this section): stop only once a concept is *researched and verified enough to teach*, not merely once it's been named and linked to its neighbors.

Both modes reuse the exact same underlying machinery — `GroundAgent`, the Evidence Engine, the Graph Interface, the LLM key-pool (Rules.md rule 21) — nothing here forks the engine. What differs is the **orchestration policy layered on top**: how many passes an entity gets, what fields must be filled before a concept counts as done, and what triggers a stop. Concretely, a concept is not "researched" for learning purposes until each of the following either holds or is explicitly recorded as unresolved (never silently absent — an empty field must be distinguishable from a checked-and-genuinely-unknown one, same honesty bar Rules.md rule 9 already sets for claims):

- a definition
- its prerequisite concepts (feeds the same `DEPENDENCY`-family `requires` edges §9.3 already uses)
- the mechanism (how it actually works, not just what it's called)
- at least one worked example
- common misconceptions, for concepts where getting it wrong is the normal failure mode
- evidence meeting a minimum confidence bar (reusing the existing `Claim`/confidence model unchanged — no new trust mechanism, per §9.3's "reuse, don't reinvent" principle, which this section narrows rather than contradicts)

This is a genuinely stronger stopping condition than "a dependency edge exists," and it's *policy*, not a single hardcoded `deep=True` flag — different research objectives (a quick chat exploration vs. compiling a real course vs. a deliberately thorough research pass) need different thresholds on the same knobs. A future `ResearchPolicy` (implementation detail, not specified further here — Phase 8.1) would carry fields like `max_concept_depth`, `min_evidence_items`, `require_prerequisites`, `require_examples`, `require_misconceptions`, `confidence_threshold`, and `max_research_cost`, with at minimum an `exploratory` preset (today's existing default, literally unchanged) and a `learning` preset (the stronger bar above).

**Research completeness is also not the same thing as learning completeness, and the two must stay separate concerns:** research completeness asks "have we sufficiently understood and evidenced this concept" (the bullet list above); learning completeness asks "can this become an effective lesson" (sequencing, what to teach first, what misconception to preempt, what exercise actually tests understanding). Keeping them separate means:

```
Learning research mode (new)
      -> a research-complete world model (still just Neo4j -- one world model, multiple projections, §9.3's principle unchanged)
      -> Curriculum Compiler (existing, §9.4/Phase 9 -- unchanged in shape, now consumes a research-complete subgraph instead of a bare exploratory one)
      -> a learning-complete course
```

The research engine is never made directly responsible for producing the final course — that stays the Curriculum Compiler's job, exactly as already scoped. This section only changes what the Curriculum Compiler is allowed to assume about its input's depth before it runs.

**Explicitly not decided or built by this section:** the concrete `ResearchPolicy`/research-planner/coverage-model implementation, the async job lifecycle a multi-minute deep-research pass would need (distinct from and layered on top of the existing job-lifecycle groundwork already scoped for Post-Phase-6, above), and exactly which fields are mandatory vs. optional per concept type. Those are Phase 8.1-8.6's job (Phases.md), not this PRD section's — this section exists so Phase 8 starts from an agreed objective instead of retrievers being built against an unstated one.

### 9.4 New feature set

| Component | What it does | Builds on |
|---|---|---|
| **Learning Research Mode** (§9.3a) | Orchestration policy that keeps investigating a concept until it's research-complete (definition/prerequisites/mechanism/example/misconceptions/evidence-confidence), not merely until a dependency edge exists | Same `GroundAgent`/Evidence Engine/Graph Interface as exploratory mode — a policy layered on top, not a fork |
| **Curriculum Compiler** | Orders a topic's concept graph into modules/lessons by `DEPENDENCY` edges (prerequisite-before-dependent) | `generate_roadmap` (Phase 6), now fed a research-complete subgraph (§9.3a) instead of a bare exploratory one |
| **Curriculum-source retrievers** | New `Retriever` implementations (GeeksforGeeks, freeCodeCamp curriculum, GitHub tutorial/exercise repos) feeding the existing Evidence Engine, invoked as part of Learning Research Mode's deeper per-concept evidence pass (§9.3a, Phase 8.4) | `backend/evidence/retrievers/base.py`'s existing ABC |
| **Lesson Authoring** | Produces sourced explanation + examples per concept, audited for traceability | `Claim` model, `audit_synthesis` |
| **Challenge Engine** | Coding exercises with starter code, hidden tests, hints, and a sandboxed grader | New — deliberately outside the graph/agent trust boundary (Rules.md §9.x below) |
| **Learner Model** | Per-concept mastery/attempt/mistake tracking, feeding remedial lesson/exercise selection | New — narrow, additive store |
| **Gamification layer** | XP, streak (with freeze/repair), per-concept kyu-like rank, badges, a path/tree course map — all derived from real Learner Model data (Architecture.md §0.38.3, §6.3) | Duolingo (streaks, XP, skill-tree path), Codewars (per-kata rank) [research, 2026-09-16] |

### 9.5 Worked example — "Learn B+ Trees in C++"

1. User names the topic. It becomes a seed **Abstraction** exactly as in §4 — no new entry point.
2. The existing Master/Ground agents decompose and investigate it (pages, buffer pools, node splitting, search/insert/delete) via the existing Evidence Engine, now also drawing on the new curriculum-source retrievers for worked implementations and exercises, not just papers/docs/video.
3. The Curriculum Compiler reads the resulting subgraph, orders concepts by `requires` edges (e.g. `Node Splitting` requires `Page Layout`), and groups them into modules.
4. Lesson Authoring produces a sourced explanation + a runnable example per concept.
5. The Challenge Engine attaches a coding exercise per concept ("implement `insert()` for a B+ Tree node") with independently-validated tests.
6. The learner reads, writes code, runs it, fails a hidden edge case, gets a hint, passes. The Learner Model records the attempt; a concept failed twice in a row surfaces a remedial step (a narrower lesson/exercise) before the main path continues.
7. Passing the exercise awards XP and advances the concept's node on the course's path/tree map (visually, a Duolingo-shaped skill tree, not the free-explore knowledge graph); the concept's own rank ticks up a kyu-like tier the way a Codewars kata does. The day's streak counter updates. None of this is separate bookkeeping — all of it reads back from the same attempt the Learner Model just recorded (Rules.md rule 22).

### 9.6 Functional requirements (all [VISION])

1. Curriculum Compiler orders a topic's already-investigated concept subgraph by prerequisite (`DEPENDENCY`-family edges), producing modules/lessons — a pure read over the Graph Interface, no LLM/retriever call of its own (same constraint as Rules.md rule 14).
2. At least one working curriculum-source retriever (GeeksforGeeks, freeCodeCamp, or a GitHub tutorial/exercise corpus) exists behind the existing `Retriever` ABC and degrades gracefully on failure (Rules.md §3).
3. Lesson text for a concept is composed of claims each traceable to retrieved evidence — verified the same way `audit_synthesis` already verifies synthesized answers (Architecture.md §0.4), not a new trust mechanism.
4. A coding exercise has: prompt, starter code, visible + hidden tests, hints, and a reference solution that is verified (not assumed) to pass its own test suite before the exercise is served to a learner.
5. Learner-submitted code is executed only inside an isolated, resource/time-limited, network-disabled sandbox; grading never trusts an LLM's "this looks correct" judgment as the pass/fail signal — the tests are the signal.
6. A per-concept Learner Model (attempts, pass/fail, time) persists across sessions (same "must survive a restart" bar as Rules.md rule 7 sets for agent state).
7. A learner who fails the same concept's exercise repeatedly is offered a remedial step before the main path resumes — the simplest possible version of the adaptive loop, not a general tutoring system.
8. XP, streak (with a freeze/grace mechanic), and a per-concept rank are shown to the learner, computed live from the Learner Model's attempt log — never a value that can drift from what was actually recorded (Rules.md rule 22, Architecture.md §0.38.3).
9. The course map renders as a path/tree (prerequisite order, made visual — Architecture.md §0.38.3), distinct from the free-explore knowledge graph the rest of this project already builds toward (Phase 6).
10. The whole extension runs from one laptop with no cloud dependency: the existing `docker compose up` (Neo4j + sandbox Docker daemon) plus `uvicorn backend.api.app:app`, with the Learning Portal's own pages served by the same FastAPI static mount the chat/docs frontend already uses — no separate frontend build step, dev server, or hosted service required for v1 (Architecture.md §0.38.2).
11. The Curriculum Compiler refuses to compile a concept that hasn't met Learning Research Mode's completeness bar (§9.3a) rather than silently compiling a course module from a bare, unresearched dependency edge — an incomplete concept is surfaced as incomplete (same "empty must be distinguishable from unknown" honesty bar as Rules.md rule 9), not papered over with a thin auto-generated paragraph.

### 9.7 Non-functional requirements

- Sandbox isolation is a security requirement, not a performance one — no learner-submitted code may reach the network, the host filesystem, or another learner's container, regardless of how unlikely a specific submission looks.
- Content-generation cost stays bounded the same way §6 already requires for the investigation engine — tiered model usage, no eager generation of lessons/exercises for concepts nobody has reached yet (mirrors Rules.md rule 11's laziness requirement, applied to curriculum content instead of questions).
- New node types (`Course`, `Lesson`, `Exercise`) and new relation types (`prerequisite_of`, `taught_by`, `exercises`) require this PRD update to exist first (satisfied by this section) before any code adds them, per Rules.md rule 6.
- **Runs entirely on one laptop for v1** (Architecture.md §0.38.2), mirroring §6's existing local-first commitment for the base engine: `docker compose up` + `uvicorn`, frontend served by the same FastAPI process, no cloud account required to use it.
- Any new keyed integration (e.g. a GitHub API token for the tutorial/exercise retriever) follows the existing comma-separated multi-key rotation pattern already built for LLM providers (`backend/questions/llm_config.py`'s `_collect_keys`/`PROVIDER_KEY_POOLS`, Architecture.md §0.38.1) — not a new single-key config convention.

### 9.8 Out of scope (v1 of this extension)

- Arbitrary-language sandboxing hardened against a determined adversary — v1 supports a small fixed set of languages behind a well-understood container-based sandbox, not a general-purpose secure code execution platform.
- Plagiarism/cheating detection.
- Real-time multi-learner features (leaderboards, pairing, live classes) — the gamification layer (§9.4) is deliberately local-only: XP/streak/rank are real, but there is no online leaderboard/league to compare against in v1.
- A general tutoring dialogue — the adaptive loop (§9.6.7) is remedial-step insertion, not a conversational tutor.

### 9.9 Success criteria

Given a topic with an already-investigated graph (per §8's existing criteria), the extension should, end-to-end:
1. **[VISION]** Produce an ordered curriculum (modules → lessons) that a person could read start to finish, distinct from and building on the Roadmap (§8.7).
2. **[VISION]** Serve at least one coding exercise per module whose hidden tests correctly distinguish a working reference solution from at least one deliberately broken variant.
3. **[VISION]** Contain a deliberately hostile submission (infinite loop, fork bomb, network call) without it affecting the host process or any other learner's session.
4. **[VISION]** Trace every sentence of a sampled lesson back to a real retrieved source, the same way `audit_synthesis` already does for synthesized answers.
5. **[VISION]** Demonstrate the remedial loop: a simulated learner who fails one concept's exercise twice is routed through a remedial step before the main curriculum resumes.
