# Rules — Recursive Knowledge Graph

Boundaries for any AI (or human) working on this codebase. If a change requires breaking one of these rules, update this file and Architecture.md in the same change — don't silently drift.

## 1. Approved libraries per layer (do not swap without updating Architecture.md)

| Layer | Approved | Do not substitute with |
|---|---|---|
| Graph store | Neo4j | Kùzu (archived), ArangoDB, Memgraph, TerminusDB, NebulaGraph, RDF stores — unless Architecture.md is updated with a reason |
| Agent substrate | LangGraph (core engine only) | CrewAI, AutoGen/AG2, OpenAI Agents SDK, Claude Agent SDK |
| LLM adapter | Instructor's `from_provider()` + each provider's native SDK (google-genai, groq, cerebras_cloud_sdk) | `litellm` (tried first — its `instructor.from_litellm()` path hardcodes `provider=OPENAI` internally and hits unpredictable mode-registry errors regardless of the actual model; see docs/Memory.md) |
| LLM provider | `GROUND_MODEL_CHAIN` / `MASTER_MODEL_CHAIN` (Gemini/Groq/Cerebras/Cohere, `backend/questions/llm_config.py`) | Claude/OpenAI (no usable free tier — see Implimentation-Research/Free-LLM-APIs.md); do not hardcode a single model everywhere — respect the tier and the fallback chain |
| Structured output | Instructor | Raw prompt-and-parse JSON, LangChain structured output |
| Vector search | LanceDB | Chroma, Weaviate, FAISS-as-a-database |
| Task queue/state/bus | asyncio + SQLite (`aiosqlite`) | Celery, Redis/RQ (license risk + unneeded infra at this stage) |
| Backend API | FastAPI | Flask, Django |
| Frontend graph viz | Cytoscape.js (`react-cytoscapejs`) | D3 from scratch, Sigma.js, react-force-graph |

## 2. Architectural boundaries

1. **Only `/backend/graph` talks to Neo4j.** No Cypher outside the Graph Interface functions. Agents, the Question Engine, and the Evidence Engine call Graph Interface functions, never the driver directly.
2. **Only `/backend/evidence` and `/backend/questions` call external LLM/search APIs**, and only through the shared Instructor/retriever wrappers — never a raw `requests`/SDK call embedded inside an agent class. This keeps provider swaps and rate-limit/retry logic centralized.
3. **Ground agents use the `GROUND_MODEL_CHAIN` (free-tier Gemini/Groq/Cerebras) by default.** Escalating to the `MASTER_MODEL_CHAIN` requires an explicit reason (synthesis across many children, or a Master-level structural decision) — don't default to the more expensive/rate-limited tier "to be safe."
4. **Every claim/answer must carry `evidence`, `confidence`, and `provenance`.** No function may return a bare answer string from an LLM call without wrapping it in the typed Claim model — this is a correctness requirement of the design spec (Section 30 of the Agentic Architecture), not a style preference. **`provenance` as a first-class concept now has real, verified tooling** (`backend.agents.trace_claim` for structural provenance, `backend.questions.audit_synthesis` for content provenance — Architecture.md §0.3-§0.4) — but neither is wired into the default `GroundResult`/`Claim` path automatically yet; they are standalone, independently-callable tools, not (yet) an enforced property of every answer. Don't assume `provenance` is automatically populated on a `Claim` just because these tools exist — check whether the specific code path actually calls them.
5. **The `BOUNDARY_HIT → EXPANSION_REQUEST → MASTER DECISION` escalation protocol must never be skipped or short-circuited.** An agent that needs information outside its current abstraction escalates vertically toward Master — it does not silently fetch out-of-scope data itself, and it does not hop laterally to a peer to get it (see rule 9).
6. **Don't invent new node/abstraction/dimension types outside PRD.md's model without updating PRD.md first.** The graph's core vocabulary — as actually implemented through Phase 5 (`backend/graph/schema.py`) — is: `GraphNode` (type=`domain`|`entity`), `Abstraction`, `Question`, `Claim`, connected by `RELATES_TO` (generic, semantic label in a `relationship_type` property — e.g. `"decomposes_into"`, `"competes_with"`), `MEMBER_OF` (entity→abstraction, non-strict), `HAS_QUESTION` (entity→question), `ANSWERED_BY` (question→claim), `SUPERSEDES` (claim→claim, temporal). `Network` is intentionally never materialized as its own node — it's just "entities connected by `RELATES_TO`," queried, not stored. **`Resource` (from the original SystemDesign.md/PRD.md vocabulary) was never built as a separate node** — a `Claim`'s source (title/url/type) is a property of the `Claim` itself, not a standalone reusable node, since nothing has yet needed one paper/page cited by multiple independent claims to be deduplicated. Extending this vocabulary (e.g. reifying `Resource` as its own node) is a product decision requiring a PRD.md update first, same as any other addition.
7. **Agent state must be persisted, not held only in memory.** Any agent that can be paused/resumed per Phases.md must checkpoint its state to the SQLite state store, not rely on process lifetime.
8. **Agent hierarchy depth is dynamic — do not pre-declare fixed `DomainAgent`/`SubdomainAgent` classes.** Implement `MasterAgent` and `GroundAgent` only; a Ground agent that needs to decompose further spawns child Ground agents (which functionally behave like a "Domain/Subdomain" layer) — this is a runtime recursion outcome, not a fixed 4-class schema. Rationale: no production multi-agent system surveyed (including Anthropic's own) uses more than ~2 fixed agent tiers — see Architecture.md §0.
9. **No lateral (peer-to-peer) agent messaging.** All coordination is vertical: a message goes to a parent or a child, never sideways to a sibling/cousin agent. If two branches need to share information, it goes up to their common ancestor and back down.
10. **The Master must enforce a hard spawn budget before spawning any agents**, sized to query complexity (e.g. default to a small fixed number of Ground agents for a simple lookup; only scale up for queries that are demonstrably broad/complex). This is not an optional cost optimization — implement it in Phase 4 from the start, not after observing runaway spawning in practice (see Architecture.md §0 — Anthropic had to retrofit this after their own orchestrator over-spawned).
11. **Question Engine calls are lazy, never eager/batch.** Do not write code that precomputes questions for every (entity × dimension × level) combination in an abstraction upfront. Generate a question only when a Ground agent is actively investigating that specific (entity, dimension, level), or when the user interacts with a node in the UI.
12. **Entities are canonical, not duplicated per abstraction.** When an agent discovers what might be the same real-world entity under a different name/context, it must attempt `merge_entity` (dedup by precedence rule) rather than creating a second node for the same thing. An "abstraction" is a boundary/view referencing existing canonical entities, never a copy of them.
13. **The graph schema must allow one entity to belong to multiple abstractions simultaneously (non-strict hierarchy).** Do not model abstraction membership as a single `parent_id` field on an entity — use a many-to-many relationship from day one (Phase 1), since retrofitting this after entities assume single-parent membership is expensive.
14. **The Roadmap Generator (PRD.md §4a) only reads from the Graph Interface — it must never call an LLM or a retriever API itself.** It sequences questions/evidence that already exist; if a question hasn't been generated or answered yet, the Roadmap Generator surfaces that gap, it doesn't fill it by making its own calls. Filling gaps is the Question Engine's/Evidence Engine's job, triggered separately (and lazily, per rule 11).

## 3. Error handling conventions

- Each layer defines its own typed exception (e.g. `GraphInterfaceError`, `QuestionEngineError`, `EvidenceRetrievalError`, `BoundaryHitError`) — don't let raw driver/HTTP exceptions leak upward uncaught.
- External API failures (Tavily/Semantic Scholar/arXiv/etc.) degrade gracefully: a failed retriever returns zero results for that source, not a crash — the Evidence Engine should still return whatever other sources succeeded.
- LLM structured-output validation failures (Instructor) should retry once with the validation error fed back to the model before surfacing an error upward — Instructor supports this natively, use it.
- Boundary-hit escalation failures (e.g. Master unreachable) must be logged and retried, never dropped silently — a missed escalation is a silent correctness bug in this system, since it means an investigation stalls without anyone knowing.

## 4. What the AI should NOT do

- Do not add authentication, multi-user support, or hosting/deployment infrastructure before Phases.md reaches a phase that calls for it.
- Do not reach for Celery/Redis/Kubernetes/microservices "for scalability" in a solo local-first prototype — that's premature per Architecture.md's local-first-now philosophy.
- Do not adopt Graphiti, GraphRAG, or LightRAG as hard dependencies — their patterns are reference material only (see Architecture.md §1); the graph data model in this project is custom.
- Do not silently change which LLM model tier an agent level uses — that's a cost and behavior decision, surface it.
- Do not skip writing the Memory.md progress log once implementation starts (Phases.md Phase 1 onward) — future sessions depend on it to avoid re-deriving context.
- Do not build a fixed 4-level `MasterAgent`/`DomainAgent`/`SubdomainAgent`/`GroundAgent` class hierarchy — see rule 8. This was the original design; it was revised after research (Architecture.md §0) found no production precedent for more than ~2 fixed tiers.
- Do not add agent-to-agent lateral messaging "for efficiency" — see rule 9. It's unvalidated coordination surface with no real-world precedent, not a missing feature.
- Do not eagerly generate the full dimension×level×entity question tree for an abstraction "so it's ready" — see rule 11. This is the exact cost mistake Microsoft's GraphRAG made before building LazyGraphRAG to undo it.
