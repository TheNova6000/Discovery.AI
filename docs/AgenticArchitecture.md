# Agentic System Architecture — Autonomous Exploration, Abstraction, Question Generation and System Construction

This is the original foundational spec for the agent-runtime half of the system, authored by the project owner. Saved here verbatim (condensed formatting) because Architecture.md/Rules.md/Phases.md reference it by section number, and it previously only existed in conversation history. **Important:** Architecture.md §0 revised the concrete agent hierarchy described here (fixed 4-level Master/Domain/Subdomain/Ground) after comparing it against real-world precedent (Anthropic's own production multi-agent system uses 2 tiers, not 4). Read this document for the *concepts* (boundary detection, message types, context compression, non-uniform pyramid) — read Architecture.md §0 and Rules.md rules 8-13 for what was actually kept vs. changed before implementing anything.

## 1. Purpose

The Knowledge Graph (docs/SystemDesign.md) defines **what the system represents**. The Agentic Architecture defines **how an autonomous system operates over that graph**. The agents are not the knowledge graph — they are the reasoning, exploration, decomposition, coordination and boundary-management layer operating on top of it.

$$
\boxed{\text{Observe} \rightarrow \text{Abstract} \rightarrow \text{Decompose} \rightarrow \text{Question} \rightarrow \text{Investigate} \rightarrow \text{Integrate} \rightarrow \text{Detect Boundary} \rightarrow \text{Re-abstract}}
$$

The architecture is recursive and non-uniform — it must not assume reality forms a clean balanced tree.

## 2. Core Architectural Principle

$$
\boxed{\text{Knowledge Graph} + \text{Agent Runtime} + \text{Abstraction Controller} + \text{Question Engine} + \text{Evidence Engine}}
$$

The Knowledge Graph represents the world. Agents construct temporary **working views** of that world. **Agents manage abstractions; they do not define reality.**

## 3-8. Agent Hierarchy (original spec — see Architecture.md §0 for what was revised)

The original spec described four roles — Master Agent (largest abstraction, thinks outward: what larger system contains this? what's missing? should we expand/contract/restructure?), Domain Agent (owns a region of the abstraction, discovers nodes/entities, creates subdomains), Subdomain Agent (deeper mechanism decomposition), Ground Agent (concrete claims/mechanisms/evidence, expands until the question is answered, evidence is unavailable, the boundary is reached, another domain is needed, or the abstraction is too deep) — arranged as a **three-layer working window** (Context / Current System / Mechanism) that slides as investigation moves up or down, with every agent able to recursively instantiate the same architecture below itself (a Domain Agent can become the local Master of its own region).

**As implemented:** collapsed to Master + dynamically-recursive Ground (Rules.md rule 8) — the "Domain/Subdomain" layers still conceptually exist, they just emerge as Ground agents recurse rather than being pre-declared classes, per the real-world precedent in Architecture.md §0.

## 10-11. Direction of Movement & Boundary-Hit Mechanism

**Downward expansion** = mechanistic decomposition (*what is this made of?*). **Upward expansion** = contextual expansion (*what larger system does this belong to?*).

When a Ground agent discovers it needs information outside its current abstraction (e.g. "understanding this mechanism requires banking settlement"), it sends a `BOUNDARY_HIT` up the chain as a `DEPENDENCY`, which becomes an `EXPANSION_REQUEST` at the top. **Lower agents discover boundaries; higher agents decide whether boundaries should move** (expand, create a new branch, delegate, reject, or stop).

**As implemented:** this protocol is unchanged and is Rules.md rule 5/10 — the escalation must never be skipped, and the Master's decision must respect a hard spawn budget (rule 10, added after Architecture.md §0's research — Anthropic's own orchestrator over-spawned before this was added).

## 12-14. Abstraction Manager

Controls Breadth (how many related domains?), Depth (how far down?), Resolution (how detailed?), Boundary (context), Relevance, Stopping. \(A=(B,D,R,C)\).

**The Infinite Rabbit-Hole Problem:** without this, decomposition never terminates (Money → Banking → Economics → Psychology → Neuroscience → ... → Quantum Mechanics). Every expansion needs a reason: \(U(\text{expand}) = \text{ExpectedInformationGain} - \text{Cost}\); expand only when \(U(\text{expand}) > \tau\).

**As implemented:** this is exactly why Question generation is lazy (Rules.md rule 11) rather than eager — the "expected value" gate for the *whole system* is: don't compute a question until something (the user, or an agent that already decided to investigate) actually asks for it.

## 15-18. Question Engine (shared with docs/SystemDesign.md §15-16)

$$
Q = f(A, N, E, D, L, O, K, U)
$$

where \(O\)=objective, \(K\)=known knowledge, \(U\)=unknowns (added on top of SystemDesign.md's \(Q=f(A,N,E,D,L,C)\) to make the agent's current progress state part of the question-generation input — **this is exactly the signature `backend/questions/engine.py`'s `generate_question()` implements**).

## 19-21. Agent Communication

Typed messages only: `TASK, QUESTION, DISCOVERY, EVIDENCE, HYPOTHESIS, DEPENDENCY, BOUNDARY_HIT, EXPANSION_REQUEST, NEW_ENTITY, NEW_DOMAIN, CONFLICT, ABSTRACTION_CHANGE, COMPLETION, FAILURE`. Two modes: **vertical** (supervision, escalation, delegation, synthesis) and **horizontal** (dependencies, shared entities, cross-domain coordination).

**As implemented:** horizontal/lateral messaging was dropped (Rules.md rule 9) — no production system surveyed in Architecture.md §0's research uses it. All coordination goes through the vertical chain, even for cross-branch dependencies (up to the common ancestor, back down).

## 21-22. Context Compression & Agent State

$$
\boxed{\text{Raw Information} \rightarrow \text{Local Synthesis} \rightarrow \text{Hierarchical Compression} \rightarrow \text{Global Model}}
$$

The Master never receives raw evidence — only conclusions, uncertainty, contradictions, boundary changes, and recommended actions. Every agent maintains persistent, resumable state (`AgentState`: identity, role, parent, children, abstraction, local_network, objective, active/completed questions, hypotheses, evidence, uncertainty, dependencies, boundary, resources, status).

**As implemented:** this is `backend/runtime`'s SQLite-checkpointed state store (Rules.md rule 7) — not built yet (Phase 3).

## 23. Agent Lifecycle

`CREATE → INITIALIZE CONTEXT → UNDERSTAND OBJECTIVE → MAP LOCAL NETWORK → GENERATE QUESTIONS → PRIORITIZE → DELEGATE/INVESTIGATE → INTEGRATE RESULTS → CHECK BOUNDARY → CHECK COMPLETENESS → REPORT UPWARD → REFINE/EXPAND/TERMINATE`. Reusable at every level.

## 30-33. Evidence, Confidence, Conflict, Task Allocation

Every conclusion carries `Evidence + Confidence + Provenance` (Claim, Source, Reasoning, Confidence, Contradictions, Timestamp) — **this is exactly `backend/evidence`'s planned `Claim` model, and `backend/questions/models.py`'s `Question.rationale` field is the same idea applied one layer earlier.**

Contradictory claims are never silently overwritten — both are kept with their evidence and context until a higher-level agent resolves them (Rules.md's "conflict resolution" requirement, Phase 7).

$$
Priority(Q) = Importance(Q) \times Uncertainty(Q) \times Dependency(Q) \times ExpectedInformationGain(Q)
$$

$$
ExpectedValue(\text{Branch}) > Cost(\text{Agent})
$$

— agents are only created when the expected value justifies it, producing an irregular computational pyramid matching the irregularity of the knowledge graph (not implemented yet — noted in Phases.md "Later / not yet scheduled").

## 34. Abstraction Change Protocol

`BOUNDARY_HIT → DEPENDENCY ANALYSIS → IMPACT ESTIMATION → EXPANSION REQUEST → MASTER DECISION → ABSTRACTION UPDATE → NEW AGENT BRANCH → CONTINUE INVESTIGATION`. The Master can Expand, Contract, Split, Merge, or Reframe. **The map itself can change** — learning is not merely filling an existing map.

## 44-48. Worked Example & Non-Uniform Pyramid

The spec's own worked example (Understanding Payment Platforms) is the direct ancestor of PRD.md's "Worked Example: money transactions" — Technology Agent discovers banking settlement is needed → boundary expands; Security Agent discovers fraud detection needs identity/behavioral signals → another branch; Economics Agent discovers different entities capture value at different points → PayPal/Mastercard/Visa/Stripe/banks become comparable. **The system constructs the appropriate abstraction while investigating it** — it doesn't start with a complete map.

$$
\boxed{Importance \neq Size} \qquad \boxed{Hierarchy \neq \text{Simple Depth}}
$$

A tiny node can matter more than a large one if many branches depend on it (dependency/connectivity/centrality, not size, drives priority — Phases.md "Later / not yet scheduled").

## 47-50. No Permanent Pyramid & Design Philosophy

The final architecture is not a single tree:

$$
\boxed{\text{Tree} = \text{Local Computational Representation}} \qquad \boxed{\text{Graph} = \text{Underlying Knowledge Structure}}
$$

$$
\boxed{\text{AGENT SYSTEM} = G + A + D + Q + M + E + C + R}
$$

(Knowledge Graph + Abstraction Manager + Dimension Engine + Question Engine + Agent Memory + Evidence Engine + Coordination + Recursive Agent Runtime.)

> The agents should not merely answer predefined questions. They should determine: What system are we actually studying? What boundary should define it? What domains constitute it? What entities exist inside it? What dimensions matter at this level? What questions should be asked? Which questions deserve deeper investigation? When has the current abstraction become insufficient? What should be expanded, contracted, split or merged? How should discoveries propagate back to the larger system?

$$
\boxed{\text{Understand the system} \rightarrow \text{discover what is missing} \rightarrow \text{change the abstraction} \rightarrow \text{understand the new system}}
$$

The ultimate architecture is a **dynamic graph observed through recursively changing abstractions, operated by a hierarchy of agents whose hierarchy itself changes with the abstraction** — not a permanent pyramid. (Which is exactly why Architecture.md §0 revised the *fixed* Master/Domain/Subdomain/Ground hierarchy into a *dynamic-depth* one: a fixed hierarchy was already, on this spec's own terms, the wrong shape.)
