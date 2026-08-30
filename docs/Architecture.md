# Architecture — Recursive Knowledge Graph

Stack decisions below come from research into currently-maintained (2026) tools per layer — see the research summary preserved in the approved plan at
`C:\Users\srikr\.claude\plans\recursive-knowledge-graph-sleepy-map.md` for the full comparison and rationale behind each pick.

The **agent hierarchy and graph-generation strategy** described in §2/§4 below were revised after a second research pass compared the original design against real-world precedent (Cyc, Wikidata/Knowledge Vault, OLAP/GIS hierarchies, Palantir Ontology, Microsoft GraphRAG→LazyGraphRAG, Anthropic's own published multi-agent research system, OpenAI Deep Research, and the AutoGPT/BabyAGI failure history). §0 records what that research found and why the design changed — treat it as load-bearing context, not a changelog footnote.

## 0. Design principles & real-world precedent

**Why these principles exist:** the original design (fixed 4-level Master/Domain/Subdomain/Ground agent tree with lateral peer messaging; eagerly precomputed dimension×level×entity questions; abstractions as dynamically emergent per-viewer subgraphs) has a documented historical analog for almost every element, and each analog either failed outright or was later walked back for cost reasons. Building the ambitious version first would repeat known mistakes instead of learning from them.

| Principle | What real system validated it / warned against it |
|---|---|
| **Agent depth is dynamic, not a fixed 4-level schema.** Start with Master + Ground; Domain/Subdomain-like intermediate agents emerge only when recursion actually goes deep enough to need them. | Anthropic's own production multi-agent research system uses **two tiers** (lead + parallel subagents), not four, and explicitly recommends "start with the simplest approach, add complexity only when evidence supports it." No production deep-research system surveyed (Anthropic, OpenAI) uses more than ~2 agent tiers. |
| **No lateral peer-to-peer agent messaging by default.** All coordination is vertical (parent ↔ child). | No production system reviewed uses lateral peer messaging between agents — it's unvalidated coordination surface. Anthropic's subagents do not talk to each other; all traffic is lead↔subagent. |
| **Hard spawn/cost budgets are mandatory from day one, not an optimization added later.** The Master must apply a scaling rule (e.g. ~1 agent for a simple lookup, more only for genuinely complex/broad queries) before spawning anything. | Anthropic's orchestrator initially over-spawned up to 50 subagents for trivial queries — an AutoGPT-shaped failure — and had to bolt on hard-coded scaling rules after the fact. AutoGPT/BabyAGI's well-documented failures (infinite loops, cost explosion, low completion rates) trace directly to the absence of this. |
| **Question/abstraction generation is lazy (on zoom/access), not eager (precomputed across the whole tree).** | Microsoft's GraphRAG precomputes hierarchical summaries and it's expensive at scale; their own follow-up, LazyGraphRAG, exists specifically because deferring summarization to query time cut indexing cost to ~0.1% of GraphRAG's. Precomputing dimension × zoom-level × recursive sub-questions has the identical unbounded-cost shape. |
| **One canonical entity node per real-world thing; "abstraction" is a view/query over the canonical graph, not a separate mutated copy per viewer.** | Palantir's Ontology — the closest production system to "same entity, many perspectives" — explicitly rejects per-viewer dynamic copies. Their named anti-patterns ("System Silos," "The God Object") are exactly what happens without a canonical-entity rule; their fix is ETL-time merge via precedence rules. |
| **Hierarchies are non-strict by design — an entity may belong to more than one abstraction/parent.** Don't assume a clean tree. | OLAP/GIS literature on non-strict, non-covering hierarchies (many-to-many parent-child, asymmetric drill-down/roll-up) is decades deep precisely because real hierarchies aren't clean trees; this project's Graph Interface must support multi-parent membership from Phase 1, not retrofit it later. |
| **Keep the graph itself "mechanically dumb"; put reasoning/hierarchy logic in the agent/query layer above it.** | The knowledge graphs that scaled to production (Google Knowledge Vault, Wikidata) deliberately kept the stored graph simple (plain triples/typed edges) and pushed abstraction/hierarchy reasoning to consumers, rather than embedding rich recursive semantics into the storage layer itself. This validates keeping the Graph Interface (§2) simple and putting all "abstraction," "zoom," and "dimension" logic in the agent/Question Engine layers, never in the Neo4j schema. |
| **Context-scoped knowledge (the core "Abstraction as bounded subgraph" idea) is real but historically hard — budget for it.** | Cyc's microtheories are the closest 40-year precedent for context-bounded assertions and never solved "which microtheory applies to this query" or cross-microtheory consistency, despite $200M and 2,000 person-years invested. This doesn't mean abandon the abstraction concept — it means treat "which abstraction does this belong to" as a genuinely hard, ongoing problem, not a solved implementation detail, and keep abstractions cheap to redefine/merge rather than treating them as permanent commitments. |

### 0.1 Theoretical foundations (unified 2026-08-28, after Phase 5 + the graph-persistence pass)

This subsection consolidates a design-theory discussion that ran alongside real implementation and testing (full detail in Memory.md's dated entries) into one place. Four labels, deliberately distinct — **built ≠ verified**, code existing is not the same claim as a test having demonstrated it:
- **[THEORY]** — the research/reasoning behind a decision. Not a claim about the code at all.
- **[BUILT]** — the code exists and is wired in, but hasn't necessarily been exercised by a real test for this specific claim.
- **[VERIFIED]** — demonstrated working by an actual run, cited (script/question/phase). The strongest claim; implies BUILT.
- **[VISION]** — the direction, intentionally not yet implemented — cite where it's scheduled (a Phases.md phase, or "Later / not yet scheduled").

Absorbed from a longer exploratory write-up (`docs/system.md`, since deleted — its accurate parts live here now; see Memory.md for what was judged inaccurate and why, and for the full traceability discussion that produced this four-label scheme).

**The core loop.** The system is not `Question → Answer`; it is:

```
Abstraction → Decomposition Hypothesis → Investigation → Coupling Discovery → New Abstraction → (repeat)
```

**[VERIFIED]** `GroundAgent`'s sequential loop (`decide_next_step` called repeatedly, each call informed by everything resolved so far) implements exactly this: a question is investigated, its result is integrated, and the *next* decision — answer, decompose one more sub-question, or hit a boundary — is made with that new information, not decided in advance. Demonstrated end-to-end multiple times (PayPal, Alphabet, UN, mechanical doorbell), including the "explore-then-reassess" case for genuinely ambiguous coupling (the "why does money have value" test) — see Memory.md's structural-judgment and near-decomposability entries.

**Near-decomposability (Herbert Simon, 1962) is the operational criterion, not "independent vs. dependent."** [THEORY] A component is worth its own graph node when interactions *within* it are much stronger than interactions *between* it and its siblings — not when it's completely independent (nothing in a real system is). **[VERIFIED]** `decide_next_step`'s master-level guidance and `GroundDecision.discovered_entity_name` encode this directly; falsified the competing "business questions never decompose" hypothesis empirically (Alphabet's near-unrelated segments decomposed correctly; PayPal's tightly-coupled revenue streams answering directly is defensible under this same test, not a bug) — see Memory.md's near-decomposability research entry.

**Three interacting graphs, not one.** The **Knowledge Graph** (what exists — entities, abstractions, relationships) — **[VERIFIED]** this is what Neo4j actually stores and persists across runs (Phase 1, extended Phase 5 + graph-persistence pass). The **Question Graph** (what's still unknown — a question's own parent/child structure) — **[BUILT, not VERIFIED as an independent structure]** exists as real parent/child relationships in `AgentState.children` (SQLite) and `child_results` (`GroundResult`) during and after a run, but is not a first-class, independently queryable structure in Neo4j — you cannot currently ask the graph database "show me the question tree" the way you can ask it "show me this entity's relationships." **[VISION]** Making it one is closer to Phase 6/7 territory. The **Agent Graph** (who is currently investigating what) — **[VERIFIED, but ephemeral]** real parent-chain relationships exist and were directly tested (the multi-hop `BoundaryHitMessage` propagation check in Phase 4), but only for the duration of one run — nothing persists which agent investigated what after the process ends.

**Discovery must persist, or it didn't happen.** [THEORY] Before the graph-persistence pass, everything a Ground Agent discovered lived only in the SQLite agent-state store and vanished at the end of a run. **[VERIFIED]** `persist_to_graph` + `find_or_create_entity` + `decomposes_into` relationships close this — demonstrated live (`Internet Infrastructure Probe -[decomposes_into]-> DNS resolution / TCP+TLS Connection Establishment / Network Routing`).

**Entity discovery is a decision, not a consequence of decomposing.** **[VERIFIED]** Most sub-questions are just narrower questions about the *same* entity; a new entity is only created when the model's decompose judgment identifies something with substantial internal structure of its own. This was a real bug the first time it was implemented (the model described things as "distinct, independently-investigable" in its reasoning but left the dedicated field unset) — caught precisely *because* this was tested, not just built; fixed by stating the contradiction explicitly in the prompt, then re-verified (see Memory.md).

**The pyramid is non-uniform and importance isn't size.** [THEORY] Some branches go deep, some don't; a small, highly-connected node (a shared protocol) can matter more than a large peripheral one. **[VERIFIED, structurally]** `max_depth`/`max_sequential_steps` allow irregular per-branch depth — observed directly across runs (Q1-style questions typically produce 2-4 children, some questions produce zero). **[VISION, explicitly deferred]** The "importance" half of this claim — actual dependency/connectivity/centrality-based prioritization (AgenticArchitecture.md §46) — is Phases.md "Later / not yet scheduled." Depth is irregular in practice; priority is not yet computed by anything.

**What the system optimizes for is not answer quality alone.** [THEORY, applied as an evaluation methodology — not a system-computed objective] A perfect paragraph that flattens real structure into prose is a worse outcome than a correctly-decomposed graph, and a huge graph built from arbitrary splits ("decomposition theater") is worse than a smaller, accurate one. This principle shaped how the structural-judgment evaluations were *graded by hand* (Memory.md); there is no code anywhere that computes a "structural quality" score or optimizes for it — the judgment lives in the LLM prompt and in how a human reads the output, not in an objective function. Calling this **[BUILT]** would overstate it; it isn't a system capability at all yet, just a principle that has correctly predicted what "good" output looks like so far.

**A relationship between two claims is a function of the claims AND the question/abstraction they're being read through — not an intrinsic property of the claim pair alone.** [VERIFIED] (2026-08-28, three controlled experiments, Architecture.md §0.5 / Memory.md): the identical claim pair, in identical original wording, classified through an unchanged prompt, returned three different relationships — `sequential`, `complementary`, `alternative_explanation` — as only the target question's framing changed (from "why does X emerge" to "how is X sustained" to "which factor primarily explains X"). $R = f(A, B, Q)$. This directly extends the same principle already established for decomposition (near-decomposability is a judgment relative to a question, not a fixed property of a subject) and for framing (§0.2's implicit-framing work) to claim relationships: nothing in this architecture's epistemics is context-free. **Open question this raises, not yet answered:** is a relationship itself a claim — i.e. does "these are alternative explanations" need its own provenance/evidence the same way any other assertion does? Named at the end of the relationship-experiment arc, genuinely unresolved, the explicit starting point for the next design session on this workstream (not code, not Neo4j — see §0.5's closing note).

**What's explicitly [VISION], despite being coherent extensions of the theory above** (do not assume otherwise when reading Master/Ground code): the Master does not yet manage abstraction expansion/contraction/split/merge (it only logs an accept/reject `ExpansionRequestMessage` — acting on it is Phase 7's abstraction-change protocol); there is no conflict-resolution mechanism when two claims disagree (also Phase 7); Claims do not carry an epistemic-status field (`known`/`hypothesis`/`uncertain`/`contradictory`) beyond their numeric `confidence`; there is no persisted priority queue (see §2's Agent Runtime entry) or centrality-based scheduling.

**Traceability going forward:** every new feature this discipline applies to should be able to answer, in order, Theory → Architecture decision → PRD requirement → Phase → Implementation → Verification → Memory entry. If a claim can't point to a Memory.md entry with an actual test result, it isn't [VERIFIED] — say [BUILT] or [VISION] instead, whichever is honest.

### 0.2 Epistemic synthesis — design investigation (opened 2026-08-28, not yet implemented)

[THEORY] §0.1 already named this gap before any real session existed to prove it: "Claims do not carry an epistemic-status field... beyond their numeric confidence" and "there is no conflict-resolution mechanism when two claims disagree" (both listed there as [VISION]). Three real, non-synthetic sessions (`docs/Memory.md`, 2026-08-28: global payment systems, central bank rates, why companies dominate) then independently reproduced exactly this gap in practice, not as an edge case but as the dominant finding across 2 of 3 sessions — a predicted gap confirmed empirically is stronger evidence than either alone, and is why this is now a design investigation rather than a hypothetical.

**The gap, precisely stated.** The system is strong at `Question → Decompose → Investigate → Evidence → Claim` (all [VERIFIED] across the three sessions) and weak at the step after: `Claims → what does this collection actually justify?`. Two distinct failure shapes were observed, not one:
- **Coverage gap** (central bank session): the final synthesis asserted content (the transmission-mechanism explanation) that no child ever investigated and no evidence was gathered for, at the same confidence as content that was investigated.
- **Flattening gap** (company-dominance session): four individually well-evidenced claims (network effects, economies of scale, regulatory capture/"enshittification", organizational execution) were presented as uniformly-true complementary pillars, when at least one pair represents genuinely rival explanatory theories in real economic/antitrust discourse, not independent facts.

Both shapes point at the same missing capability: nothing today represents a relationship *between* claims (agrees-with / contradicts / is-one-of-several-competing-explanations-for), and nothing represents *how much of a synthesized answer was actually backed by investigation* versus asserted from the model's own prior. `GroundResult.confidence` is a single scalar doing the work of at least two different judgments at once.

**Real precedent surveyed, not invented from scratch:**
- **Dung's Abstract Argumentation Frameworks** (Dung, 1995, and the 30 years of CS argumentation theory built on it) — arguments as nodes, "attacks" as the formal primitive relation; **bipolar** extensions add "support" as a second primitive. This is the actual, decades-deep formal foundation for exactly "claim A conflicts with claim B" / "claim A supports claim B" as first-class typed relations, not a novel idea this project would be inventing.
- **ArgLLM** (Freedman, Dejl, Gorur, Yin, Rago, Toni — *Argumentative Large Language Models for Explainable and Contestable Claim Verification*, AAAI 2025, King's College London; code at [github.com/CLArg-group/argumentative-llms](https://github.com/CLArg-group/argumentative-llms)) — the single closest working system found. Builds a Quantitative Bipolar Argumentation Framework from LLM-generated claims and computes the final verdict/confidence via formal argumentation semantics over that graph, rather than trusting the LLM's own self-reported confidence — explicitly designed so a specific edge in the argument graph can be disputed, not just the final number. Directly relevant to both failure shapes above: it separately tracks per-claim strength AND how claims combine, which is precisely the missing middle step.
- **Toulmin's argument model** (claim/data/warrant/backing/qualifier/rebuttal) — informal, not a graph formalism, but supplies useful vocabulary already close to what's needed: a **qualifier** (scope/degree a claim holds at) and a named **rebuttal** (a specific condition under which a claim doesn't hold) are cleaner primitives than a single confidence float.
- **IPCC calibrated uncertainty language** — a real, non-technical, battle-tested precedent for splitting what this project currently conflates into one number: **confidence** (validity given evidence type/quality/amount/internal consistency AND degree of expert agreement — the "is this contested" axis) is tracked separately from **likelihood** (a probabilistic estimate of the finding itself). "Degree of agreement" as an explicit, separate factor is exactly what would have flagged the company-dominance flattening.
- **Wikidata's statement ranks** (preferred/normal/deprecated, plus qualifying properties like `P5102` "nature of statement" and `P2241` "reason for deprecated rank") — the simplest production-proven precedent: conflicting claims are allowed to **coexist** in the same graph rather than forcing resolution before storage, with lightweight metadata explaining the conflict. Maps directly onto this project's existing `Claim` nodes (already multiple per question) — the missing piece is just a typed relationship between them, not a new storage model.

**What this rules out, per explicit instruction:** building a full epistemology engine (`KNOWN`/`HYPOTHESIS`/`DISPUTED`/`INFERRED`/`CONTROVERSIAL`/`CONSENSUS`... enum soup) now, on the strength of three sessions. §0.1's own traceability discipline exists specifically to prevent naming a theoretical capability and treating it as built. This section is [THEORY] + [VISION] only — no schema change, no code, accompanies this pass.

**Direction that looks minimal enough to actually earn its way in, if/when this moves to implementation** (explicitly not decided or scheduled yet): closer to Wikidata's "let claims coexist, tag the relationship" simplicity than to ArgLLM's full formal argumentation semantics — e.g. a typed relationship between two `ClaimNode`s (`supports` / `conflicts` / `competing_explanation_for`), populated only when a synthesis step (`synthesize_answer` or the master's own decompose-time reasoning) explicitly identifies one, rather than computing it for every claim pair. ArgLLM is the deeper reference to study closely if automated synthesis-confidence computation (not just human-readable labeling) is ever actually needed — study it the way Graphiti and LightRAG were studied-not-adopted in §0's original research pass.

**Narrowing the question further (still research, no schema decided):** the two session findings that motivated this section are not the same problem, and treating them as one risks landing on exactly the "confidence += 0.1" outcome this section explicitly rejects.
- The **coverage gap** (session 2: transmission mechanisms asserted, never investigated) is a **provenance** question — did this specific piece of the final answer trace back to an actual investigated child with evidence, or was it asserted directly by the synthesizing step? The raw signal for this already exists today, for free, in `GroundResult.child_results` — a synthesized answer whose content doesn't map onto any child's Q/A pair is detectable by comparing what was asked against what was answered, without inventing a new relationship type at all.
- The **flattening gap** (session 3: rival explanations presented as uncontested pillars) is a genuine **relationship-between-claims** question — this is the one Dung/bipolar-AF/Wikidata-rank precedent actually speaks to, and it cannot be derived from data already sitting in the system; it requires a real judgment ("are these two claims complementary or competing?") made at synthesis time, most cheaply by asking the same LLM already doing the synthesis to make that judgment explicit, rather than computing it post-hoc via formal argumentation semantics.

These are two separable, independently-testable primitives, not one epistemic layer — and the coverage one is cheap enough to audit against data already collected (the three sessions' existing traces) before writing a single line of new code, the same way the revision-signal battery was run against the existing system before any collapse mechanism was designed.

**Audit result (zero new API calls — re-classified the three sessions' already-logged traces against A/directly-investigated, B/jointly-supported, C/reasonable-inference, D/uninvestigated-assertion):** the two gaps failed **independently**, confirming the split above is a real boundary, not an arbitrary one.

| Session | Provenance/coverage | Claim relationships |
|---|---|---|
| 1 (payment infra) | Clean — synthesis is 100% Category A, maps 1:1 onto the four investigated children | N/A — no competing claims present |
| 2 (central bank rates) | **Broken** — 5 of 6 substantive sections (all the transmission-channel content) are Category D, asserted with no investigating child and no evidence, at the same 0.95 confidence as the one Category-A section | N/A — nothing to relate; the D-content isn't even a claim with an origin |
| 3 (company dominance) | Clean — zero Category D; all content is A/B/C | **Broken** — well-provenanced claims (network effects, scale, regulatory capture, execution) presented as uniformly-complementary when at least one is a rival explanatory theory |

Session 2 has a coverage failure with nothing to relate (only one investigated thing existed). Session 3 has a relationship failure with perfect coverage (everything was investigated; the failure is purely in how the pieces combine). No single fix touches both — this rules out one shared mechanism and confirms two independent workstreams.

**Decision (design-only, no code yet): provenance before relationships.** A claim's relationship to another claim ("competes with," "supports") is only meaningful once the claim's own origin is established — reasoning about how two things relate before knowing where either came from repeats the exact ordering mistake this whole investigation started by avoiding. Sequencing agreed:

```
Provenance design → verify against the three existing session traces (no new API calls)
  → implement minimally → observe on real use
  → THEN claim-relationship design → implement minimally → observe on real use
```

Explicitly not an "epistemics engine" — two small, separately-earned mechanisms, in that order. Provenance's shape (traceability at the claim/concept level, not sentence-string matching — a synthesized sentence combining three children's findings into new prose is legitimate synthesis, not a provenance failure) is the next design question, not yet started. **Stopped here for this pass — the next session starts with designing the provenance mechanism, not running further experiments.**

### 0.3 Provenance — semantics defined, minimally implemented, verified (2026-08-28)

**[BUILT] + [VERIFIED].** `backend/agents/provenance.py` — `trace_claim(agent_id)` walks the persisted `AgentState` tree every run already checkpoints (Rules.md rule 7) and classifies each node structurally, by child count alone, into a `ClaimProvenance` tree: **direct** (0 children — answered without decomposing), **derived** (exactly 1 child — narrows/builds on one investigated sub-question), **synthesized** (2+ children — combines multiple investigated branches), **unresolved** (boundary hit / no result). Deliberately does NOT attempt content-level verification that an answer's text is fully backed by its `derived_from` claims — that's a harder, separate problem (claim/concept-level comparison, not sentence matching) left for later. Built against the existing SQLite state store only, per the explicit "prove the semantics before choosing storage" ordering — no Neo4j edges, no schema change to `Claim`/`Question`.

**Unit-tested** (`scripts/verify_trace_claim.py`, 11 checks, zero LLM calls, synthetic AgentState tree written directly via `save_state`) — confirms all four classifications plus `find_root_agent_id`'s "exactly one true root" invariant.

**Verified against real data — replayed against the three real sessions' already-persisted SQLite state** (`scripts/replay_provenance.py`), zero new API calls, exactly the ordering agreed on. Confirmed the hand-done A/B/C/D audit (§0.2) structurally, and surfaced a sharper, quantitative version of it that wasn't anticipated:

| Session | Root classification | Root answer length | Sum of children's answer lengths |
|---|---|---|---|
| 1 (payment infra) | synthesized (4 children) | 2,194 chars | 6,960 chars (root is a *compression* of its children — expected for clean synthesis) |
| 2 (central bank) | **derived (1 child)** | **2,350 chars** | **1,760 chars — root is LONGER than the single child it's "derived" from** |
| 3 (company dominance) | synthesized (4 children) | 1,762 chars | 6,598 chars (compression again, as in session 1) |

Session 2 inverts the pattern the other two sessions share: a "derived" node's answer should be built from investigating exactly one narrower question, so it should never need to be longer than what that one child produced. It is — by 590 characters, all of it the previously hand-identified uninvestigated transmission-mechanism content. Every other session compresses; session 2 expands. This is an incidental discovery from the replay script's own printed diagnostics, not something `trace_claim` computes or asserts as a rule — one data point, flagged as a candidate cheap heuristic (`derived`-or-`direct` node whose answer is longer than its source is suspicious) worth watching on future real sessions, not yet built into anything.

**Deliberately not done this pass:** no Neo4j storage decision, no claim-relationship work (workstream 2, untouched per the agreed ordering), no attempt to make the length-ratio observation into an actual automated check.

### 0.4 Content provenance — designed, then tested once, and it worked (2026-08-28)

**[THEORY], now with one real data point.** §0.3's `trace_claim` answers "where did this node's answer come from, structurally" but not "is this specific sentence in the answer actually backed by what was investigated." That second question — **content provenance** — was designed before any code was written, per explicit instruction:

- Unit of analysis is the **atomic proposition**, not the sentence (a sentence can bundle a supported claim and an unsupported one) and not the whole answer.
- `origin: investigated | uninvestigated` is a **traceability** judgment, not a truth judgment — "uninvestigated" does not mean false, "investigated" does not mean verified true. It means "did THIS specific investigation establish THIS specific proposition," nothing more.
- Designed as an **audit problem, not a self-report**: a separate call examines the finished answer against the known material, rather than asking the generator to grade its own output. This was a deliberate choice over the cheaper self-report pattern used for `working_framing`/`discovered_entity_name` — self-attribution of "did this come from context or from my own training" is a documented LLM weak spot, categorically harder than naming a lens one is already applying, and this project already has two documented cases of the same model failing a much easier self-report instruction.

**[BUILT] + [VERIFIED, single experiment]:** `backend/questions/audit.py` — `audit_synthesis(answer, known) -> SynthesisAudit` (`AtomicClaim{text, origin, supporting_source}`), one new LLM call, no schema family, no Neo4j, following the exact pattern already used by `synthesize_answer`/`decide_next_step`.

**The one isolated experiment, run exactly as scoped** (`scripts/audit_session2_synthesis.py`, using Session 2's real answer and known text verbatim, no new investigation): extracted 15 atomic propositions, 2 `investigated` (both from the one real child, about policy tools / interest-on-reserves mechanics), 13 `uninvestigated` (every single transmission-channel proposition — interbank markets, bank-lending pass-through, asset prices, exchange rates, forward guidance, each split into its own atomic claim, finer-grained than the original hand audit's 5-section framing). This is exactly the boundary predicted by hand weeks earlier in this same investigation, now reproduced by an independent auditor call rather than by a human reading the transcript.

**Honest limits:** n=1. This is real evidence an LLM auditor *can* do this task, not proof it reliably does. No further sessions or generalization claims should be made from one clean result — the next real step (not started, not scheduled) would be running this against session 1 (expect: everything `investigated`, since the synthesis there was 1:1 with its children) and session 3 (expect: everything `investigated`, since session 3's actual problem was in claim relationships, not provenance — the audit tool should find nothing wrong there, and that itself would be a meaningful negative-control result) before trusting the mechanism generally.

**Two negative controls run against Session 1 and Session 3's already-captured data** (`scripts/audit_negative_controls.py`), exactly as scoped: Session 1 — 35 atomic propositions, **35 investigated, 0 uninvestigated**. Session 3 — 27 atomic propositions, **27 investigated, 0 uninvestigated**, including the closing "conversely, companies fail when..." paragraph (the original hand-audit called this Category C, a reasonable inference rather than direct investigation — the auditor traced it to `investigated` instead, a minor granularity difference, not a failure of the control). Critically, **the auditor did not mark the contested regulatory-capture/"enshittification" content as uninvestigated** despite it being the most rhetorically loaded, hardest-to-reconcile claim in that session — confirming it is behaving as a traceability auditor, not a truth/consensus detector. That was the specific failure mode this control was designed to catch, and it didn't happen.

**Two real bugs found by actually running this against larger, real sessions, not by more design:**
1. **A genuine, severe fallback-chain bug in `structured_call`** (`backend/questions/llm_client.py`): when a provider's error text contained a Unicode character (a non-breaking hyphen, U+2011 — echoed back from the model's own generated content inside a JSON-parse error), the fallback handler's own `print()` statement crashed with `UnicodeEncodeError` on Windows' default console codec (cp1252) — aborting the ENTIRE fallback chain from inside the error-logging path meant to enable it. Fixed by sanitizing the logged reason (`encode("ascii", errors="backslashreplace")`) before printing. This bug pre-dates tonight's work and could have silently killed any structured call whose error text happened to contain non-ASCII characters, on Windows specifically — not caught by any earlier test because none had hit this exact character combination before.
2. **`audit_synthesis`'s first schema (with a verbose `supporting_source` field) reliably truncated on both Gemini and Groq for larger sessions** (4-child sessions 1/3, not the 1-child session 2 it was designed against) — the requested per-claim source quotes multiplied output length past what the structured-output call could return without invalid/truncated JSON. Fixed by dropping `supporting_source` entirely for now rather than fighting prompt-engineering around it; the field was a nice-to-have, not load-bearing for the core traceability judgment. **Also discovered, unrelated to this project's code:** Cerebras (the third link in `MASTER_MODEL_CHAIN`) now returns `402 Payment required` — free-tier access appears to have changed since this chain was set up. Not fixed tonight (account/billing, not code); flagged here so it isn't mistaken for a code regression later.

**Current honest state, per the four-label discipline:**
```
[VERIFIED]              Structural provenance (trace_claim)
[VERIFIED, 3 sessions]   Content provenance / synthesis auditor (audit_synthesis) —
                         1 true positive (session 2) + 2 clean negative controls
                         (sessions 1, 3), including a negative control specifically
                         against confusing "contested" with "unsupported"
[PARTIAL]               Claim relationships — first experiment run, see §0.5
[VISION]                Any Neo4j storage decision for either provenance workstream
[KNOWN ISSUE]           Cerebras returns 402 Payment required — MASTER_MODEL_CHAIN's
                        third fallback is currently dead; not yet addressed
```

### 0.5 Claim relationships — first experiment, mixed result, preserved not patched (2026-08-28)

**[BUILT] + [PARTIAL, one experiment].** `backend/questions/relationships.py` — `analyze_claim_relationships(question, claims)` classifies every pair of already-grounded claims as `complementary` / `alternative` / `conflicting` / `unrelated` with required reasoning, deliberately narrower than Dung's full attack/support formalism (§0.2) — a first vocabulary to test, not an ontology to commit to. Run once (`scripts/analyze_session3_relationships.py`) against Session 3's actual question and its 4 real claims — no Neo4j, no schema, one call, exactly as scoped.

**What it got right:** never invented a false `conflicting` label (the specific failure mode most worth avoiding, since "different" is not "contradictory"), always gave reasoning, and produced a non-trivial split (3 `complementary` / 3 `alternative`) rather than collapsing everything into one bucket.

**What it didn't do — the actual finding:** it did not surface the specific tension that motivated this workstream. Every pair involving the regulatory-capture claim came back `complementary` ("enables," "builds upon," "leverages"), when the original Session 3 critique was precisely that regulatory capture represents a *rival normative account* of dominance (extraction vs. earned value) — not just another additive lever. The `alternative` labels it did produce (network effects vs. scale, either vs. organizational execution) look driven by a shallower heuristic — "external market-structural mechanism vs. internal organizational mechanism" — not "these compete to explain the same causal outcome." **"These are different mechanisms" is not sufficient evidence for "these are competing explanations."** A sharper, truer requirement than the one this workstream started with.

**A likely confound, named before blaming the model:** the claims fed in were condensed, neutral one-sentence paraphrases of Session 3's actual answers, stripped of the original's loaded framing ("extracting rents," "enshittification"). That framing may be exactly what made the tension visible to a human reader. This means the experiment tested `paraphrase → relationship analyzer`, not `claim → relationship analyzer` — a lossy transformation introduced before the epistemic reasoning step, the same principle §0.4 already established for content provenance (compression can destroy the information a judgment depends on).

**Controlled follow-up, designed but explicitly not run** (next session): one carefully chosen pair, original unparaphrased wording, asked explicitly whether they're complementary, competing, or something else relative to a named question. Succeeding would mean tonight's result was mostly representation loss; failing would isolate a genuine, narrower capability gap. Either is informative — the finding is being preserved and documented, not immediately patched.

**Controlled follow-up, run (2026-08-28) — a genuinely split result.** Taxonomy expanded from 4 to 6 labels (`complementary`/`alternative_explanation`/`contradictory`/`conditional`/`sequential`/`unrelated`, plus a `confidence` field) and the relationship judgment made explicitly question-relative rather than judged on the claim pair alone (`backend/questions/relationships.py`). One pair only, **original Session 3 wording verbatim** (not the earlier paraphrase) — Network Effects vs. Regulatory Capture — tested under two different target questions (`scripts/analyze_controlled_relationship.py`, 2 calls):

| Target question | Relationship | Confidence |
|---|---|---|
| "Why do some companies become dominant while others fail?" (emergence-flavored) | `sequential` — pricing enables network effects, which regulatory capture then protects/sustains | 0.9 |
| "How can dominant companies sustain market power?" (persistence-flavored) | `complementary` — both stack as co-occurring sustaining mechanisms | 0.8 |

**What this confirms:** the label genuinely changed across questions for the identical claim pair in identical wording — real, direct evidence for the load-bearing principle this experiment was designed to test: **relationship is a function of (claim_a, claim_b, question), not an intrinsic property of the two claims alone.**

**What this did NOT yet confirm at the time:** `alternative_explanation` had never appeared, under either question, even with the original loaded framing ("enshittification," "extract rents") fully restored. That ruled out "paraphrasing destroyed the signal" as the *whole* story. Two live possibilities were left open: (a) this specific pair genuinely reads as causally sequential/complementary, a defensible reading, not a model failure; or (b) eliciting `alternative_explanation` needs a sharper question form — e.g. "what **primarily** explains X" — forcing single-cause framing instead of a multi-mechanism narrative.

**Third, final variant — resolved (b), cleanly (2026-08-28).** Same two claims, same original wording, one more question, only this time explicitly demanding a primary-cause pick rather than a general "why"/"how" (`scripts/analyze_causal_competition_question.py`, one new call — Question A's identical result was reused from the prior run rather than re-measured):

| Target question | Relationship | Confidence |
|---|---|---|
| "Why do some companies become dominant while others fail?" | `sequential` | 0.9 |
| "How can dominant companies sustain market power?" | `complementary` | 0.8 |
| "Which factor **primarily explains** why some companies become dominant while others fail: network effects or regulatory capture?" | **`alternative_explanation`** | 0.9 |

Reasoning quoted the question's own framing directly: "the two claims present different primary causal pathways for the outcome of dominance, **as framed by the question**." Not a leading prompt — the classification instructions were completely unchanged across all three calls; only the target question's framing changed, and the model's own stated reasoning attributed the shift to that framing.

**This closes the arc `R = f(A, B, Q)` opened by the first, confounded experiment.** Same claims, same wording, three different questions, three different relationships, each independently defensible for its specific framing. This is no longer a hypothesis under test — it's a confirmed, load-bearing empirical finding about how claim relationships need to be modeled: **question-relative, not an intrinsic property of a claim pair**, and specifically, whether a question demands a single primary cause (surfaces competition) or tolerates multiple contributing mechanisms (surfaces complementarity/sequence) is what controls which relationship gets recognized.

**The next real architectural question, raised but deliberately not decided yet:** where does a *contextual* relationship live? Not immediately `ClaimA -[ALTERNATIVE_TO]-> ClaimB` (a bare edge has nowhere to hang the question it's relative to) — closer to a `Question -> {ClaimA, ClaimB, Relationship{type, reasoning, provenance}}` shape, so the relationship's dependency on its originating question is structural, not implicit. Not designed in detail, not scheduled, not code — the next session's actual starting question if this workstream continues.

**A further evolution, named during hackathon-day live testing (2026-08-28), explicitly [THEORY]/[VISION] — not started, not scheduled:** the current graph conflates two things that don't have to be the same. `decomposes_into` is simultaneously the record of *how an investigation proceeded* (a hierarchical trace: parent question → child question) and the *displayed model of what was learned* — and those aren't guaranteed to be the same shape. A richer target: separate the **investigation graph** (how the agent explored — already exists, matches `AgentState`/`decomposes_into` today) from a **question-scoped model graph** (what the investigation concluded, with semantically-typed edges the investigation actually earned — e.g. `Generation --produces--> Transmission --feeds--> Distribution`, not a generic parent/child edge). Under this model, the *same* canonical entities could participate in multiple different model graphs depending on the question that produced them (a technical-lens model of "Generation/Transmission/Distribution" looks structurally different from an economic-lens model of the same three entities) — directly continuous with the already-`[VERIFIED]` finding that `R = f(A, B, Q)` for claim relationships (§0.1); this is that same finding applied one level up, to the graph's own edges, not just to pairwise claim comparisons.

**The genuinely open problem, not solved by wanting the idea:** when an investigation discovers that A relates to B, what exactly earns the typed edge `A --produces--> B` in the model graph, as opposed to nothing, or a generic edge? This has no answer yet — it requires the same discipline every other mechanism in this project earned before being trusted (a real experiment, not a guess), and it interacts directly with the provenance/relationship work already built (`trace_claim`, `audit_synthesis`, `analyze_claim_relationships` all currently read the investigation-graph shape directly; a model-graph split would need to define how they'd read the new structure instead). **Deliberately not attempted on hackathon night** — the working demo, built on today's `decomposes_into` hierarchy, is the actual deliverable; this is captured so the idea isn't lost, not because it's been earned yet.

**Next session starts here, explicitly not with code:** two design questions, in order — (1) what exactly is a `Relationship` object (subject claim, object claim, context/question, type, reasoning, provenance, confidence — which of these are load-bearing vs. nice-to-have?); (2) **is a relationship itself a claim?** "Network effects and regulatory capture are alternative explanations for dominance" is itself a proposition someone could ask "why do you believe that" about — if relationships need their own provenance the way any other assertion does, epistemics becomes recursive (a claim about a relationship between claims). Genuinely open, not answered by anything built so far.

**Current state, six labels, after three real experiments:**
```
Provenance                        [VERIFIED]      solid
Relationship: context-sensitivity  [VERIFIED]      3 questions, 3 different labels, same pair/wording
Relationship: difference           [PARTIAL]       detects "these differ," reliably
Relationship: complementarity      [PARTIAL]       detects real enabling/stacking/sequential relationships
Relationship: contradiction        [CONSERVATIVE]  never over-fires, not yet tested for under-firing
Relationship: alternative_explanation [VERIFIED, n=1] elicited successfully once a question demanded a single
                                     primary cause; did not appear under two broader framings of the same pair
```

### 0.6 Post-hackathon research pass: the graph/UI gap, audited before redesigning (2026-08-28)

**Trigger.** After the hackathon demo shipped (Vercel + Render + Supabase deployment, docs/Memory.md), live use surfaced a specific, repeated frustration: the graph "is just working but nowhere near what we want" — zooming re-triggers investigation instead of navigating, the visible graph is only ever the path the user happened to click through, and there is no way to see *why* an answer is true beyond the text itself. The instinct was "the graph system is totally broken, rebuild from scratch." **This section's job was to check that instinct against what actually exists before agreeing with it** — per this doc's own traceability discipline (§0.1), a rebuild decision needs the same evidence bar as any other architectural claim here.

**Finding, stated plainly: this is not mostly a wrong-decision problem. It's a dormant-feature problem.** Re-reading PRD.md/§4a, §5, §8 and Architecture.md §2 against the actual code shows most of what was just asked for was already designed — in some cases already built and verified — before the hackathon, and simply never turned on in the demo path:

| What was asked for (verbatim, 2026-08-28) | Where it already exists | Status |
|---|---|---|
| "the real problem statement was that our system was there for research of sources... answer a roadmap or a system and then down we get resources or sources" | PRD.md §3 ("Learn" operation), §4a ("The Roadmap — a distinct output, not just free browsing"), §8 success criterion 7 | **[VISION]**, unchanged — PRD.md already specifies this exact shape (roadmap on top, resources underneath) and already schedules it for "Phase 6." It was never built, but it was never forgotten by the design either — it fell off during the pivot to shipping a live demo fast. |
| "we get resources or sources in different font" | `backend/evidence/models.py` — `Claim{evidence, reasoning, confidence, source: RetrievedResource{title, url, snippet, source_type, published}}`, `RetrievedResource` from real Tavily/Semantic Scholar/arXiv/Open Library/YouTube retrievers | **[VERIFIED]** (PRD.md §5 req. 5, §8 criterion 3 — Wikipedia/arXiv/Semantic Scholar/Open Library confirmed working keyless under real use). The data already exists in exactly the shape needed to render "sources, visually distinct from the answer." |
| Sources never appear anywhere in the live app | `GroundAgent.__init__`'s `gather_evidence: bool = False` (`backend/agents/ground_agent.py:75`) — a real, wired, opt-in parameter; `gather_evidence()` (`backend/evidence/engine.py`) is fully implemented and calls it | **Root cause, not a design flaw:** `app.py`'s `_run_investigation` constructs every `GroundAgent` with `persist_to_graph=True` but never passes `gather_evidence=True`. **One flag was left off** when the demo was wired up under time pressure — not an architectural gap. Turning it on is necessary but not sufficient (see below — nothing downstream renders a `Claim` yet even once gathered). |
| "we cannot zoom in without again getting into loop" / "one abstraction level" | §0.5's already-named, already-unresolved gap: **Investigation Graph vs. question-scoped Model Graph** conflated into one `decomposes_into` edge type | **[THEORY]/[VISION]**, unchanged since hackathon night — this is the one item on the list that really is a genuine, not-yet-solved architecture gap, not a dormant feature. See below. |
| "the system must completely develop the whole graph not only a part" | §0's own established principle: **lazy generation, validated against LazyGraphRAG's ~0.1%-of-cost precedent over eager GraphRAG precomputation** | **Real tension, not a bug** — this instinct runs directly against a decision this project already made deliberately, with cited precedent, for cost reasons. Worth re-opening, but not by just reversing it uncritically (below). |

**What this means for scope:** restoring "answer → roadmap → sources" is mostly **wiring and a rendering layer** on top of code that already works, not a rebuild. The **map-style zoom** and **full answer↔graph↔source traceability** asks are the genuinely new architecture work — the rest of this section focuses there.

#### 0.6.1 The real gap: Investigation Graph vs. Model Graph, now forced by actual use

§0.5 named this in the abstract on hackathon night and explicitly deferred it. Live use now supplies the concrete symptom: `zoom_in` (pure navigation) and `investigate_deeper` (fresh investigation) were split into two intents specifically to stop zoom from silently re-triggering work — but the underlying graph both intents read from is still **one thing**, `decomposes_into`, which is simultaneously "how the agent explored" and "what's shown as the model of the subject." A map metaphor doesn't work on top of that single structure, because a map has two things this graph doesn't cleanly separate yet:
1. **Territory** — the actual, comprehensive structure of what's known (a model graph).
2. **A viewport into it at a chosen resolution** — what's rendered right now (the investigation/navigation trace).

Right now the "viewport" (`computeViewport()`, frontend/app.html) is doing the job of both, which is why it feels like there's only one abstraction level: there's only one graph to have a level *of*.

#### 0.6.2 The map metaphor, checked against real precedent — not just an analogy

Real map systems don't lazily compute infinite detail per pixel, and they don't precompute the whole planet at maximum detail either. They precompute a **small, fixed number of discrete zoom levels** ("tiles"), each independently cacheable, and *which features render* changes per level by a style rule, not by re-deriving the territory. This is directly useful here because it resolves the lazy-vs-eager tension in §0.6 above without picking either extreme:

- **Not fully eager**: don't precompute infinite depth under every entity the moment it's created (this is exactly what LazyGraphRAG's precedent already warned against, §0).
- **Not fully lazy either** (the current bug): don't generate *only* the single path a user happened to click, discarding siblings/context as an afterthought (`computeViewport`'s parent/sibling patch was a workaround for this, not a fix to the underlying generation strategy).
- **The map's actual answer**: generate a **bounded local neighborhood** around any node that's been investigated at all — its children, its siblings, its parent, maybe one ring further — eagerly, as a fixed-cost side effect of investigating that node once. That neighborhood is the "tile." Zooming within it is free navigation (no LLM call). Crossing its edge is what triggers new investigation (a new tile).

**Real prior art for the harder version of this, surveyed not adopted (same discipline as Graphiti/LightRAG in §0):**
- **Zoomable Multilevel Trees** (Kachkaev et al., [arXiv:1906.05996](https://arxiv.org/abs/1906.05996)) — a graph-drawing algorithm that maintains an explicit abstract tree *and* an embedded tree per zoom level, guaranteeing no label overlap/edge crossings at any level. Directly relevant to the frontend layout problem (breadthfirst re-layout on every focus change is already fragile, docs/Memory.md) if multiple named zoom levels become real.
- **Semantic Level of Detail for Knowledge Graphs** (2026, [arXiv:2603.08965](https://arxiv.org/html/2603.08965)) — uses heat-kernel diffusion on a graph Laplacian (built over Poincaré-ball embeddings) to *automatically* discover where a meaningful abstraction boundary sits, rather than a hand-tuned threshold — "continuous zoom" instead of a fixed number of discrete levels, validated on WordNet's taxonomy (τ=0.79 against real hierarchical depth). This is the closest existing formalization of "zoom in until a limit, then the abstraction level itself changes" — precisely the mechanism named this session. **Deliberately not adopted now**: it needs a graph embedding pipeline this project doesn't have, and would be premature to build before the simpler discrete-tile version has even been tried once. Worth a close read if the hand-tuned-threshold version (below) turns out to feel wrong in practice.
- **Pragmatic v1, if this moves to implementation** (not decided, not scheduled): a **hand-picked, small number of named abstraction tiers** per subject (e.g. System → Subsystem → Mechanism — not user-configurable at first), each tier's "tile" being the bounded neighborhood described above, with the zoom threshold being a simple, honestly-arbitrary rule (e.g. "more than N nodes already in view at this tier → the next zoom crosses a tier") rather than SLoD's spectral one. Closer to Google/Apple Maps' actual discrete-tile behavior than to the continuous-zoom paper — earns its way to the harder version only if the simple one is tried and found wanting, matching how every other mechanism in this project (provenance, claim relationships) was built minimally first and only extended after a real gap was observed.

#### 0.6.3 Full traceability: answer ↔ graph ↔ source, as one chain, not three separate ideas

The request "every answer must be equivalent to graph and source... graph can trace back to sources" is the Evidence Engine (0.6, table above), structural provenance (§0.3, already [VERIFIED]), and the model-graph split (0.6.1) **read together as one requirement**, not three. Concretely, once `gather_evidence=True` is turned on and its `Claim`s are attached to graph nodes (`attach_claim` already exists, Architecture.md §2's Graph Interface list — this part needs no new code, just calling it), the traceability chain becomes:

```
Answer text  <-- (already built, §0.3/§0.4)  -->  which claim(s) it was synthesized from
Claim        <-- (already built, evidence/models.py)  -->  its RetrievedResource (title/url/snippet)
Claim        <-- (0.6.1, not yet built)  -->  which Model Graph node it's evidence *for*
Model Graph node <-- (0.6.1, not yet built) --> which Investigation Graph trace produced it
```

The first two links already exist and are individually verified; the last two are exactly the model-graph split named in §0.5 and sharpened in 0.6.1. This reframes 0.6.1 from "a nice-to-have UX improvement" to "the missing middle link in a traceability chain the project already committed to" (Rules.md rule 4, PRD.md §5 req. 7) — raising its priority relative to how it read on hackathon night.

**What this section deliberately does not do:** decide a Neo4j schema for the Model Graph, decide the exact tile-boundary rule, or write any code. Consistent with every other design pass in this document (§0.2, §0.5), the next step earns the right to a schema by testing the cheapest version of the idea first.

**Superseded by 0.7 below, same day** — the "next session starts here" list above was written before a second, independent pass at this same question sharpened the conclusion. Left in place for the record (§0.1's traceability discipline: don't retroactively tidy a design's own history), but 0.7's ordering is the one to actually follow.

### 0.7 Model Graph: From Investigation Trace to Navigable World Model (2026-08-29)

**The correction 0.6 didn't go far enough on.** 0.6.1 named the Investigation-Graph-vs-Model-Graph split as *a* gap. This pass reframes it as *the* gap — not one item on a list alongside the evidence flag and the zoom UX, but the thing that makes the other two items make sense at all: **the graph should not be a record of the agent's own investigation. It should be a navigable model of the subject, which the investigation happens to be the method of constructing.** `decomposes_into` fails as a model relation for reasons sharper than "zoom feels wrong" — a real worked example makes this concrete: "how does a smartphone turn a photo into something sendable" decomposes, under investigation, into Capture/Processing/Encoding/Network/Server/Recipient — but those aren't a hierarchical decomposition of one thing into its parts, they're **stages of a process**, related by sequence and data-flow, not containment. No amount of zoom-UX polish fixes a graph whose edges are the wrong semantic type to begin with.

**Four layers, not one graph:**

```
QUESTION (context, not a graph node — see below)
   │
   ├──> MODEL GRAPH        "what's actually true about the subject" — navigable, the map itself
   │        │
   │        └──> attached to: CLAIMS   "why we believe this element/relation exists"
   │                  │
   │                  └──> SOURCES     real RetrievedResource citations
   │
   └──> INVESTIGATION TRACE   "how the agent constructed the above" — provenance, not the map
```

**Question is context, not a root node.** The same subject answers differently depending on what's asked (already [VERIFIED] for claim relationships, §0.1's `R = f(A, B, Q)` finding) — putting Question *inside* the navigable graph would make every model a permanent commitment to one framing. It stamps what it produces; it isn't itself part of what gets zoomed around in.

**Two primitives, not five — `ModelElement` collapses further than it first looked like it would:**
- **`Node`** — the single "thing" kind. `entity` / `process` / `abstraction` are a `kind` tag on this one primitive, not separate classes: a camera sensor and an abstraction like "Payment System" are structurally identical (relations + investigation status + resolution level), differing only in what they represent — exactly the distinction §0's original research already ruled belongs in the reasoning layer, not the storage schema ("keep the graph mechanically dumb; no hierarchy/zoom logic in Neo4j"). A `process`-kind node's relations are predominantly sequential (`then`/`feeds`) rather than structural (`contains`) — that's a property of which edges point at it, not a reason to give it its own node class.
- **`Relation`** — reified as its own node (not a plain Neo4j edge with properties) from the start, not as a later special case. §0.5 already left open "is a relationship itself a claim?" — if a relation can have multiple independent sources, get contradicted, or be superseded the way any other claim can, it needs edges of its own (`EVIDENCED_BY` → `Claim`), which a plain edge-with-properties can't cleanly support in a property graph. Reifying every `Relation` uniformly avoids a schema migration the first time a contested edge shows up.

**`Claim` is explicitly not a `ModelElement`.** It's the attachment between a `Node`/`Relation` and its `Sources` — one layer down, not a peer category inside the model graph (a correction to this section's own earlier diagram, which had drawn claims as one of the model graph's internal boxes alongside entities/relations/abstractions). This matches the UI shape the model already wants: Model Map → Claims/Explanation → Sources, as three visually distinct strata, not one.

**The model is a network, not a tree — a real, deferred UI consequence, not just a data-model one.** The electric-grid example makes this concrete: Generation/Transmission/Distribution aren't siblings under one parent, they interact directly, and a shared Control/Markets layer cuts across all three. Once the Model Graph is genuinely this shape, `frontend/app.html`'s breadthfirst tree layout is the *structurally wrong* renderer, not a mistuned one — flagged here so it's expected at implementation time, not discovered as a surprise; not solved now.

**Where this leaves the lazy/eager tension (0.6.2):** unchanged in substance, restated more precisely — "lazy" wasn't the wrong call, "path-only" was too lazy a version of it. The evolution is full-eager (rejected, cost) → current path-only-lazy (rejected, this section's actual complaint) → **bounded model expansion**: investigating any `Node` at all eagerly populates its immediate neighborhood (the "tile"), and every `Node` honestly carries its own investigation status (`explored` / `partially_explored` / `unexplored`) rather than the graph pretending un-investigated territory doesn't exist. This is the same conclusion 0.6.2 reached, now derived from the four-layer split instead of the map analogy alone — two independent routes landing on the same answer is a good sign, not a coincidence to paper over.

**Research consulted, same discipline as always (survey real precedent, adopt nothing wholesale):** Zoomable Multilevel Trees ([arXiv:1906.05996](https://arxiv.org/abs/1906.05996), explicit abstract+embedded tree per zoom level — relevant once the network-not-tree layout problem above is actually tackled); provenance-for-KGs work arguing traceability must be attached to graph content rather than assumed from structure ([Amaral, Rodrigues, Simperl, *ProVe*, 2024](https://journals.sagepub.com/doi/10.3233/SW-233467); [Sarazin et al., *Full Traceability and Provenance for Knowledge Graphs*, 2024](https://journals.sagepub.com/doi/10.3233/FAIA241309)) — directly supports treating Claim/Source as first-class attached structure rather than a UI afterthought; **Context Graphs** ([arXiv:2406.11160](https://arxiv.org/abs/2406.11160)), arguing plain triples lose exactly the contextual metadata (time, provenance, and — most relevant here — the asking-context) that this project's own `R = f(A,B,Q)` finding already demands a bare edge can't hold alone.

**Still, deliberately, not decided: `ModelElement`'s (i.e. `Node`'s and `Relation`'s shared) exact field set.** Both this section's two-primitive collapse and its Claim/Relation reification calls are recommendations for the next session to react to, not a schema. No Neo4j change, no code, per this document's standing discipline (§0.1) and this section's own explicit instruction not to design storage before the semantics are agreed.

**Superseded in its "two primitives" framing by 0.8 below, same day** — 0.7's ordering still holds; its primitive count gets sharpened to one.

### 0.8 Stress test: Node/Relation against smartphone, grid, PayPal, and one hard edge case (2026-08-29)

**Method, stated up front:** 0.7 proposed two primitives (`Node`, reified `Relation`) as a recommendation, explicitly not yet earned. This section stress-tests it against three worked examples plus one deliberately adversarial case, per this document's standing rule that a design earns its schema by surviving a real test, not by sounding right.

**Smartphone pipeline, electric grid, PayPal — all three survive cleanly**, each for the same reason: what looked at first like it needed a third primitive (process stages, feedback/market loops, role-in-a-system-vs-decomposition) turned out to be expressible as `Node{kind: ...}` connected by typed `Relation`s, with `kind` (`entity`/`process`/`abstraction`) carrying the distinction as metadata rather than as separate graph object types — consistent with §0's original "keep the graph mechanically dumb" rule holding up under real pressure, not just in the abstract.

**The adversarial case — "Payment," simultaneously process, event, and relation depending on framing — also survives, and sharpens the design rather than breaking it.** The resolution: because a `Relation` is already reified as a node (0.7), "Relation" was never a separate primitive from "Node" in the first place — it's a **role** a graph object plays (having `FROM`/`TO`-style connecting edges to other elements, under a given question) that a node can occupy *while simultaneously* having further edges of its own. "Payment" doesn't have to choose an identity: it can be the connector between Account A and Account B for one question ("how does value move") while also carrying `evaluated_by → Risk Engine` / `recorded_in → Ledger Entry` for a deeper one — accumulating structure as more gets investigated, never forced to pre-commit to being "really" an entity or "really" a relation.

**This is real prior art, not an invented workaround** — the same shape as Wikidata's statement-node design (already cited in this doc for statement ranks) and the classic **N-ary relation pattern** from ontology engineering, which exists specifically to handle "this connector needs its own properties/relations." It also resolves an n-ary case for free: a relation needing more than two participants (a fee depending on amount *and* currency *and* country) is just a relation-node with more than one outgoing edge — no third primitive required there either.

**Revised verdict: one primitive, not two.** `Node`/`Relation` was directionally correct but over-counted — a `Relation` is a `Node` occupying a connecting role for a given question, not a distinct type. §0.7's schema-design deferral is unaffected by this — if anything it's now simpler than 0.7 assumed: one field set to design, not two.

**Two things this does NOT resolve, named rather than glossed over:**
- **Render rule (presentation, not data):** the model supports a relation-node being drawn as a compact labeled edge *or* an expandable node with its own substructure — nothing yet decides which, when. Same category of deferred decision as 0.7's tile-boundary rule; needs a real rendered example to design against, not an abstract rule now.
- **`kind` tag consistency (a real, precedented risk, not hypothetical):** `kind` is open-ended by design (new tags like `event`/`state` can appear without a schema change), which is also exactly the shape of failure this project has already hit twice — `discovered_entity_name` and `working_framing` both required fixing prompt-level self-report inconsistency after the fact (docs/Memory.md). No mitigation designed yet; flagged now specifically so it isn't rediscovered as a surprise the way those two were.

**Superseded by 0.9 below, same day** — 0.8's next-steps list is correct in ordering; 0.9 answers step 1 directly.

### 0.9 Node's minimal semantic contract (2026-08-29)

**[THEORY], answering 0.8's open question directly — meaning before fields, per this session's own instruction, and grounded against real code, not designed in the abstract.**

**1. What makes something a Node — the invariant.** Not "whatever the LLM decides is important." §0.1's **near-decomposability criterion** (Simon, 1962 — `[VERIFIED]` for entity discovery: a component earns its own structure when interactions *within* it are much stronger than interactions *between* it and its siblings) was scoped to entity discovery, but nothing about the criterion is entity-specific — it transfers directly to the unified `Node` primitive. Consequence, sharper than either 0.7 or 0.8 stated: **Node-hood itself is question-relative, not just a node's relations or kind.** `R = f(A, B, Q)` extends one level further than previously pushed — not only "what relationship holds between two things" but "does this even deserve to be a thing" is a function of the asking question.

**2. What `kind` means.** Not intrinsic (§0.8's Payment case already ruled that out) and not merely cosmetic either, since it should shape expected edge patterns (`process`-kind nodes lean `then`/`feeds`; `entity`-kind nodes lean `contains`/`part_of`) — real enough to matter, not real enough to be permanent. Resolution: **`kind` is an annotation on the (Node, Question) pairing, not a property of the canonical Node record.** The same canonical node can be `process` under one question's Model View and `concept` under another without contradiction, because the annotation was never attached to the node itself.

**3. What identifies a Node — a real, verified-against-code finding, not a hypothetical.** Checked directly: `find_or_create_entity` (`backend/graph/interface.py:117`) resolves identity by **exact case/whitespace-insensitive name match, globally, with zero context** (`MATCH (n:Node) WHERE toLower(trim(n.name)) = toLower(trim($name))`). This means the "Transmission (electric grid) vs. Transmission (telecom)" collision this session used as a thought experiment is **already the live system's actual behavior today** — not a future risk, a present, checkable gap. Two rejected fixes and the one that survives:
   - *Scope identity globally by bare name (current behavior)* — rejected, demonstrably wrong (the homonym collision above).
   - *Scope identity per-question* — rejected: recreates exactly the "per-viewer dynamic copy" anti-pattern §0's original research already ruled out via Palantir Ontology's precedent, and would stop the graph from ever accumulating cross-question knowledge about the same real thing — defeating the entire point of a canonical graph.
   - **Scope identity by (name, nearest discovery-time abstraction ancestor)** — narrower than global, broader than per-question. The graph already has abstraction nodes structurally; this makes an existing lookup context-aware instead of context-blind, rather than inventing a new mechanism. This is standard **entity linking / word-sense disambiguation** territory in knowledge-graph construction — real, well-studied precedent to read closely if this becomes load-bearing, not adopted wholesale now.

**4. What a Node conceptually holds — categories, not a field list:**
   - A **canonical referent identity**, scoped per (3).
   - Zero or more **per-question interpretive annotations** (`kind` included) — and this is not a new mechanism: `Question.dimension_name` / `GroundDecision.working_framing` (`backend/questions/models.py`) are an **already-`[VERIFIED]`** version of exactly this pattern (question-scoped interpretive metadata), currently attached only to Questions. Extending it to Nodes reuses a proven mechanism rather than inventing a parallel one.
   - An **investigation-status marker** (0.7's `explored`/`partially_explored`/`unexplored`) — a property of the canonical node itself, not question-scoped, since "how much is known about this" accumulates across every question that has ever touched it.
   - Its **participating edges** — always structural (real graph relationships), never a field stored on the node.

**Named, not solved, per this section's own discipline:** the entity-linking scope rule in (3) is a direction, not an algorithm — "nearest discovery-time abstraction ancestor" needs a real multi-question worked example (not yet run) to confirm it actually disambiguates correctly rather than just plausibly. 0.8's two open items (render rule, `kind`-drift risk) are unaffected by this section and remain open.

**Superseded/completed by 0.10 below, same day** — the constructed test this section called for was run as a traced-through thought experiment (no code yet, per this section's own instruction) rather than left as a to-do.

### 0.10 Identity-rule test: traced against three constructed questions (2026-08-29)

**[THEORY], a worked trace, not a code run** — five acceptance criteria, checked against `(name, nearest discovery-time abstraction ancestor)` from §0.9(3), using: Question A ("how does an electric grid transmit electricity") discovering `Node(name="transmission")` under ancestor `Electric Grid` (→ **T₁**); Question B ("how does a cellular network transmit information") discovering the same-named node under ancestor `Telecommunications Network` (→ **T₂**); Question C ("compare transmission in electric grids and telecom networks").

| # | Criterion | Result | Why |
|---|---|---|---|
| 1 | No false merge (T₁ ≠ T₂) | **Passes** | `(transmission, Electric Grid) ≠ (transmission, Telecommunications Network)` as tuples. But this bottoms out in a dependency worth naming honestly: it only holds because the two *ancestors* don't themselves collide — the rule pushes the homonym problem up one level, it doesn't eliminate it. A later scenario with colliding ancestor names would face the identical original problem one level up (see the root-case note below). |
| 2 | No unnecessary duplication | **Passes** | A second question still under `Electric Grid` resolves to the same `(transmission, Electric Grid)` tuple → reuses T₁. |
| 3 | Cross-question accumulation | **Passes**, same mechanism as (2) | Identity is anchored to the persistent abstraction ancestor, not to question text — exactly why per-question scoping was rejected in §0.9. |
| 4 | Comparison stays possible (Question C) | **Passes, but only with a newly-identified dependency** | Question C has no single ancestor of its own — it's *about* two scoped nodes at once. Retrieving T₁ and T₂ specifically (not an unscoped third node, not an accidental single match) requires **intent parsing to extract a disambiguating scope hint from the question's own phrasing** ("...in electric grids" → `Electric Grid`; "...in telecom networks" → `Telecommunications Network`) and pass it into the lookup. The identity rule *supports* this (nothing prevents deliberately fetching two scoped nodes) but does not *provide* it — scope-hint extraction doesn't exist anywhere in the current intent layer (`backend/questions/intent.py`) and is a real, separate piece of design/implementation work this test surfaced, not something the identity rule delivers for free. |
| 5 | Recursive structure survives | **Passes, contingent on (1)** | Once T₁/T₂ are genuinely separate nodes, anything decomposed from either attaches to the correct one automatically — no special-casing needed. |

**Net verdict: the identity rule survives 4 of 5 criteria outright and the 5th conditionally — good enough to proceed, not good enough to call fully closed.** Per this session's own rule ("if it fails any of those, we don't patch around it, we revise the identity semantics") — this is not a failure, so no revision is triggered. But criterion 4's dependency is a genuine, previously-unnamed requirement, not a footnote: **comparison-scoped lookups need a scope-hint channel**, and that's now a tracked open item, not an assumption.

**One honest edge case surfaced, not solved:** the ancestor-scoping rule has a base case — top-level abstractions (`Electric Grid`, `Telecommunications Network` themselves) have no ancestor to scope *by*, so identity resolution for them still falls back to global name matching, inheriting the original collision risk one level up. Less likely to trigger in practice (top-level abstraction names are coarser-grained, less homonym-prone than mid-graph entity names like "Transmission"), but not impossible, and not fixed by anything designed so far — named here so it isn't mistaken for a solved problem.

**Superseded/completed by 0.11 below, same day** — the Node→Claim→Source trace this section called for was run against the actual graph interface code, not left as a to-do.

### 0.11 Evidence-chain test: traced against real graph-interface code (2026-08-29)

**[THEORY]/[BUILT], a worked trace against real code, not a code run** — three properties, checked against `backend/graph/interface.py`'s actual `attach_question`/`attach_claim` and §0.3/§0.4's already-`[VERIFIED]` provenance tooling.

**1. Does a Claim belong to the Node (not float near a Question)?** Checked directly, not assumed. The real chain today is **`Node -[HAS_QUESTION]-> Question -[ANSWERED_BY]-> Claim`** (`attach_question`/`attach_claim`, `backend/graph/interface.py:429,474`) — a two-hop path that already exists, not the direct `Node -[has_claim]-> Claim` edge either the diagram in this arc or the original sketch proposed. **Recommendation: keep it two-hop, don't add a direct edge** — a direct edge would duplicate a fact the two-hop path already encodes (which node a claim is about, derivable via which question it answers), risking the copies drifting apart. Passes, via structure that already exists.

**2. Does a Relation (Node-role) support Claims without a second epistemic architecture?** Checked whether `attach_question`'s node-matching is entity-specific: it isn't — `NODE_LABEL` is one generic label for every canonical node, entity or otherwise. A Relation-as-Node (e.g. `captures` in `Camera -[captures]-> Raw Image`) attaches to a `Question` and receives `Claim`s through the *identical* two-hop path, with zero special-casing required. **This is direct evidence the §0.8 collapse to one primitive was the right call, not merely an elegant one** — the fact that this works with no new mechanism is the actual payoff, not a coincidence.

**3. Does claim provenance survive synthesis (which underlying pieces a synthesized claim actually traces back to)?** Better news than a fresh design problem: **this is already built and `[VERIFIED]`**, not newly needed. `trace_claim` (§0.3 — structural: direct/derived/synthesized/unresolved by child count) and `audit_synthesis` (§0.4 — content: atomic-proposition-level investigated/uninvestigated classification, tested clean across 3 real sessions including 2 negative controls) already answer exactly this question. **The catch, precisely stated:** both currently read the SQLite `AgentState` tree (`GroundResult.child_results`), not Neo4j `Node`/`Claim` structure. The real next task is **re-pointing already-proven tooling at the new structure**, not inventing synthesis-provenance from scratch — a smaller, better-understood job than either of us was treating it as.

**Net verdict: the evidence chain passes.** Two of its three hard parts are already solved by existing, verified code (provenance tooling; generic node-question-claim attachment); the third (direct vs. structural attachment) resolves by *not* building what was originally sketched. Per the user's own framing: this doesn't mean the architecture is finished — the §0.10 top-level-collision gap and the scope-hint requirement are still open — it means the specific thing being tested is no longer a blocker, and what's left are two named, scoped tasks rather than open questions.

**Next session starts here, now genuinely schema-adjacent:**
1. ~~Turn on `gather_evidence=True`...~~ **[DONE — see 0.12.]**
2. Re-point `trace_claim`/`audit_synthesis` at Neo4j `Node`/`Claim` structure instead of `AgentState` — an adaptation of proven tooling.
3. Design the scope-hint mechanism from §0.10 criterion 4 (an addition to `Intent` in `backend/questions/intent.py`).
4. Only then: the actual `Node` schema — by this point informed by six real, evidence-grounded design passes (0.6-0.12) rather than designed from a standing start.

### 0.12 Punch-list Pass 1 — evidence wiring, verified end-to-end (2026-08-29)

**[VERIFIED].** `gather_evidence=True` added to `app.py`'s `_run_investigation` (already had `persist_to_graph=True`) — the entire attachment mechanism (`GroundAgent._finish`, `backend/agents/ground_agent.py:346-364`) was already built and required zero other changes, confirming 0.6's original finding that this was wiring, not design.

**Real run** (smartphone-photo pipeline + earlier PayPal-session content already in the shared VM graph), verified by querying Neo4j directly, not by trusting the chat reply: **84 real `Claim` nodes**, reachable via the already-existing `Node -[HAS_QUESTION]-> Question -[ANSWERED_BY]-> Claim` path (§0.11's finding holding up under a real run, not just a trace), each carrying a genuine `source_url` (arXiv papers, Wikipedia articles) — the full `Question → Node → Claim → Source` chain is real and queryable today, not hypothetical.

**A genuine quality finding, not a wiring failure:** for a business/technical question ("PayPal's payment authorization microservices"), arXiv's keyword search returned top hits about CMS/LHCb particle decay and the ATLAS detector — completely irrelevant. But checking `Claim.confidence` directly showed **the synthesis step already catches this correctly**: those irrelevant claims scored `confidence: 0.0` (evidence text honestly states "the provided resource does not contain any information about..."), while genuinely relevant sources retrieved for payment-adjacent questions scored `0.8`-`0.85` ("Smart Contracts, Smarter Payments," "Cross-border Exchange of CBDCs using Layer-2 Blockchain," "SoK: Stablecoins in Retail Payments"). **The confidence signal is trustworthy; nothing currently acts on it** — every claim gets attached regardless of score. This is a small, precisely-scoped follow-up (filter or threshold at attach-time or at render-time), not evidence the evidence system doesn't work.

**Not yet done, deliberately out of scope for Pass 1 per the punch-list's own "don't combine passes" instruction:** no UI renders any of this yet (sources aren't visible anywhere in `frontend/app.html`); no confidence filtering; `trace_claim`/`audit_synthesis` still read `AgentState`, not this new Neo4j structure (Pass 2).

### 0.13 Punch-list Pass 2 — provenance re-pointed onto Neo4j, verified end-to-end (2026-08-29)

**[VERIFIED].** A key finding shaped this pass before any code was written: `trace_claim`'s direct/derived/synthesized classification is a statement about *how the agent investigated* (child count) — which, by this project's own SQLite-vs-Neo4j split (SQLite = what the investigator did, Neo4j = what knowledge it produced), correctly belongs on the investigation-trace side. So Pass 2 is **not** a reimplementation of that classification in Neo4j terms — it's a **bridge**: start from a Neo4j entity, find your way to the SQLite investigation that produced it, and run the existing, completely unchanged `trace_claim` on it.

**The bridge is free — no schema change, because the connective tissue already existed:** `Question.id` (`backend/questions/models.py`, a uuid set once at construction) is the literal same Python object flowing into both `AgentState.question` (SQLite) and `attach_question`'s `question_id` argument (Neo4j) — verified by reading both call sites, not assumed. `find_agent_id_by_question_id` (new, `backend/agents/provenance.py`) does a linear scan of SQLite for a matching `question.id`; `trace_claim_from_entity` (new, same file) calls `get_questions_for_entity` (already existed, `backend/graph/interface.py:574`) and bridges each result through to `trace_claim` unchanged.

**All 6 acceptance criteria verified against real, live data (the smartphone-photo investigation from 0.12, same VM, same run):**

| # | Criterion | Result |
|---|---|---|
| 1 | `trace_claim` traces starting from a Neo4j Node | **Passes** — `trace_claim_from_entity('smartphone photo transmission')` and `('Image compression')` both ran live. |
| 2 | Distinguishes direct/derived/synthesized | **Passes** — real output showed `[synthesized]` (3 children) for the top-level question and `[direct]` (0 children) for its leaves, correctly. |
| 3 | `audit_synthesis` works with Neo4j-backed `known` | **Passes** — `known` built from `trace_claim_from_entity`'s bridged children or nodes without touching `audit_synthesis` itself, since it was already structure-agnostic (`answer: str`, `known: list[str]`) — no code changes to it were needed at all. Real run: 49 atomic claims extracted, 49 investigated / 0 uninvestigated — correctly recognizing clean synthesis with no coverage gap, the same signature §0.4's Session-1/3 negative controls showed. |
| 4 | No regression | **Passes** — `trace_claim` and `audit_synthesis` internals are byte-for-byte unchanged; only new, additive entry points were written. |
| 5 | No Neo4j schema expansion | **Passes** — zero new node labels, relationship types, or properties; only existing `get_questions_for_entity`/`find_or_create_entity` were used. |
| 6 | SQLite remains (not deleted, not migrated) | **Passes** — `trace_claim` still reads `AgentState` exactly as before; the bridge only adds a lookup in front of it. |

**One unrelated, real finding surfaced along the way (not a Pass 2 defect):** `audit_synthesis`'s first provider attempt (`groq/openai/gpt-oss-120b`) returned atomic claims with wrong field names (`claim`/`status` instead of the schema's `text`/`origin`) — a schema-compliance failure on Groq's side, not a data or Neo4j issue. The existing fallback chain caught it and Gemini succeeded cleanly. Flagged here so it isn't mistaken for a regression if seen again; not fixed (out of scope, pre-existing, orthogonal to this pass).

**Punch list status: Pass 1 and 2 done and verified. Pass 3 (scope-hint channel, §0.10) is next, then schema.**

### 0.14 Punch-list Pass 3 — scope-hint channel: mechanism sound, extraction unreliable (2026-08-29)

**Split verdict, not a clean pass or fail — exactly the kind of result the acceptance test was designed to surface.** Two independently-testable pieces, per this pass's own instruction to keep it narrow: the identity-*resolution* mechanism (Cypher-level scoping in `find_or_create_entity`), and the intent-*extraction* layer (does `parse_intent` actually populate `scope_hint` from real phrasing). They came back with opposite results.

**Mechanism: `[VERIFIED]`, deterministically, zero LLM calls.** `find_or_create_entity('TestTransmission', scope_hint='Electric Grid')` and `scope_hint='Telecommunications'` produced two distinct node ids; calling the first again reused the same id; an unscoped call correctly (if non-deterministically, `LIMIT 1`) matched one of the two — exactly the documented fallback behavior, not a bug. `backend/questions/models.py` (`Question.entity_scope_hint`), `backend/graph/interface.py` (`find_or_create_entity`'s scope-aware query, reusing the existing `description` field — no schema expansion), `backend/agents/ground_agent.py` (`_finish()` passes it through), and `backend/api/app.py` (every handler wires `intent.scope_hint`/`entity_b_scope_hint` through, `handle_compare` now actually resolves both sides in Neo4j instead of only building a display-layer label) are all in place and behave correctly when given a real scope hint.

**Extraction: fails, reproducibly, across all three of the acceptance test's own questions.** Isolated `parse_intent` calls (no full investigation, cheap):

| Question | `entity_name` | `scope_hint` |
|---|---|---|
| "How does transmission work in an electric grid?" | `'Transmission'` | `None` |
| "How does transmission work in telecommunications?" | `'Transmission'` | `None` |
| "Compare transmission in electric grids and telecommunications." | `'transmission in electric grids'` | `None` |

Not just "the hint gets dropped" — the compare case is a **worse failure mode than the one anticipated**: instead of leaving `scope_hint` unset (which would at least fail safely to the original unscoped behavior), the model folded the disambiguating context *into* `entity_name` as one compound string. That breaks canonical identity in a new way this pass didn't originally name: `'transmission in electric grids'` (from the compare phrasing) and `'Transmission'` (from the plain phrasing) are different name strings entirely, so the SAME real-world thing, asked about two different ways, would now resolve to *different* nodes — the opposite of criterion 2/3's "no unnecessary duplication," and not fixable by the scope-aware Cypher logic at all, since that logic never sees a separated name+scope to work with.

**A live full-investigation run (Question A, ~200s, real evidence gathering) independently confirmed the same finding** via the persisted `AgentState`: `entity_name='Transmission' scope_hint=None`, before the isolated test above narrowed it down cheaply — consistent, not a fluke of one call.

**Diagnosis, not yet a fix:** the system prompt (`backend/questions/intent.py`) gives an explicit worked example naming this exact scenario ("Transmission" in an electric grid vs. telecommunications) and a dedicated schema field for it — and the model still didn't use it reliably. This suggests the gap isn't "the model doesn't understand the concept," it's that **splitting a compound noun phrase into (bare name, disambiguating context) is a harder extraction task than the schema assumes**, closer to a real NLP span-extraction problem than a simple classification field. Matches this project's own prior, hard-won lesson (§0.9's `kind`-drift risk citation): self-report/extraction fields have failed before in exactly this shape (`discovered_entity_name`, `working_framing`) and needed dedicated fixing, not just a schema addition.

**Also surfaced, a separate real gap, not yet fixed:** `scope_hint` only threads through `_finish()`'s terminal entity resolution — the DECOMPOSE branch (`ground_agent.py`, where a parent's decompose decision creates a new child entity mid-investigation) still calls `find_or_create_entity` unscoped. A child entity discovered while investigating a scoped parent doesn't inherit that scope. Not exercised by this pass's top-level test, but real and worth naming before it's mistaken for solved.

**Per this pass's own stopping rule** ("if the scope hint fails, we learn where the identity model actually breaks — that's it, no attempt to solve every ambiguity in natural language now"): this is exactly that outcome. The identity *model* (§0.9's design) is not what broke; the *extraction* implementation is, and it's a scoped, nameable problem (prompt/extraction reliability for compound noun phrases), not evidence the whole approach needs rethinking.

**Not done, deliberately, per "keep it surgical":** no prompt-engineering attempt to fix extraction reliability yet; no renderer work; no schema freeze. The mechanism half of Pass 3 is done. The extraction half is a real, separate, next problem — not solved by more testing.

**Update (2026-08-29, same day):** the decompose-branch gap named above **is now fixed** — `ground_agent.py`'s decompose branch passes `scope_hint=self.question.entity_scope_hint` to the parent-entity lookup, and `app.py`'s `_sync_decomposition`/`handle_zoom_in` were fixed the same way (both had the identical bug: correctly resolving a scoped entity once, then re-resolving it unscoped two lines later for the session's display mirror — which would have made the UI look wrong even when Neo4j was right). Not yet re-verified live end-to-end (blocked the same day by all three LLM providers — Groq TPD, Gemini free-tier daily quota, and Cerebras billing — being simultaneously exhausted mid-test). Since extraction, not the mechanism, is the open failure mode, a live re-run is expected to reproduce §0.14's own finding rather than reveal something new, unless/until extraction itself is fixed.

### 0.15 View, Investigation, and World Model — a view is not knowledge (2026-08-29)

**[THEORY], design only — explicitly not touching `handle_compare` or any other code this pass.** A second-order correction on top of 0.7-0.9: those sections established *what* the World Model is (`Node`/`Relation`, question-relative `kind`, scoped identity). This section names something they didn't: not every conversational action should be allowed to **write** to it.

**Three things, not two, and they were being conflated:**

```
WORLD MODEL     persistent knowledge about the modeled domain — Nodes, Relations, Claims, Sources.
                Updated ONLY by Investigation.

INVESTIGATION   the process that discovers/updates the World Model —
                Question -> decide -> investigate -> evidence -> claims -> update model.

VIEW            a temporary arrangement of existing World Model content, produced for one
                question — "compare A and B," "show the economic angle," "zoom into X."
                Reads the World Model. Never writes to it.
```

**The rule, stated as plainly as this project's other load-bearing rules:** *a view is not knowledge.* Asking the system to compare two things, or look at something through a lens, is a request to *render* the existing World Model differently — it is not, itself, a discovery that should be persisted as new canonical structure. Confusing the two is what makes a comparison feel like it's "polluting" the graph — because today, it literally is.

**The concrete example that motivated this, already true of live code, not hypothetical:**

```
World Model (already exists, from real investigations):
  Generation   --produces--> Electricity
  Transmission --moves-->    Electricity
  Distribution --delivers--> Electricity

User asks: "Compare Generation and Transmission."

Current handle_compare (backend/api/app.py):
  creates a NEW canonical entity "Generation vs Transmission"
  creates "compares" edges to both sides
  PERSISTS all of this to Neo4j
  -> the World Model now permanently contains a node that isn't a thing in the
     domain, it's a question someone happened to ask about the domain.

Desired (View semantics):
  resolve Generation (existing node)
  resolve Transmission (existing node)
  render an ephemeral comparison — ID'd to this session/request, never written
  to Neo4j as new canonical structure
  -> when the user moves on, the World Model is EXACTLY what it was before:
     Generation --produces--> Electricity
     Transmission --moves--> Electricity
     Distribution --delivers--> Electricity
     unchanged, because nothing was learned about the domain — only about how
     two already-known things relate, from this one question's angle.
```

**Why this is worth naming before schema, not after:** §0.5's still-open question — "is a relationship itself a claim, and does a relationship need its own provenance" — has a cleaner answer once View exists as a distinct concept. A `compares` relationship invented to answer one comparison question is a **View-layer construct**: it doesn't need provenance the way a `Relation` in the persistent World Model does, because it was never a claim about the domain in the first place. Trying to give "Generation vs Transmission" the same epistemic weight as `Generation --produces--> Electricity` was always a category error — this section just makes the category explicit.

**This also directly answers the original zoom frustration, restated precisely:** the complaint was never really "zoom doesn't work" — it was that the system had no way to show *a slice of the territory* without either (a) mistaking the slice for the whole world (early hackathon-era rendering bugs) or (b) mistaking a rendering choice for new territory (`handle_compare`'s persistence today). Once World Model / Investigation / View are three separate things, "zoom" is simply a View — reads the World Model at a chosen resolution (0.6.2's tile), writes nothing, costs nothing, and investigation only fires when the View hits the edge of what's known.

**What this does NOT do, on explicit instruction:** fix `handle_compare`. It stays exactly as it is — persisting a comparison node — until this semantic rule is documented and agreed (this section), at which point fixing it becomes a small, well-scoped, low-risk change (stop calling `find_or_create_entity`/persisting a new node for the comparison; keep resolving the two real sides via the now-fixed scope-aware lookups from §0.14; build the comparison's answer/relationship as session-local View state, the same shape `SessionState`'s in-memory mirror already handles for everything else that isn't persisted to Neo4j). Not done now, on purpose — this section is the semantic rule the fix depends on, not the fix.

**Revised punch-list ordering, superseding 0.6/0.7/0.11's lists — this is the one to follow:**
```
Scope hint (mechanism)   [DONE, §0.14]
    v
Node identity            [DONE, §0.9-0.10]
    v
Evidence                 [DONE, §0.12]
    v
Provenance               [DONE, §0.13]
    v
View / Playground semantics   <- this section
    v
Scope hint (extraction)  [OPEN — §0.14's real remaining gap]
    v
Node schema              [NOT STARTED]
    v
Model-graph implementation
    v
Network-aware renderer   [explicitly LAST — 0.7 already named the current
                            breadthfirst tree layout as structurally wrong once
                            the model is a real network; fixing it before the
                            model and View semantics exist would be styling a
                            renderer for data that doesn't exist yet]
```

### 0.16 Node's field-by-field derivation (2026-08-29)

**[THEORY], design only.** Every candidate tested against the same five questions (does this describe the thing itself / its context / how we discovered it / what we believe about it / does it belong to a View instead), against what 0.6-0.15 already established — not against intuition. Two of the candidates either of us would have reasonably guessed **fail** the test; that's the actual finding of this section, not a formality before accepting a pre-agreed list.

**Passes — real Node fields:**

| Field | Passes because | Established in |
|---|---|---|
| `id` | Describes the thing itself — a canonical identifier has to exist before anything else can be said. | (uncontroversial) |
| `name` | Describes the thing itself — the raw label. | (uncontroversial) |
| `scope` | Describes the thing itself, **not its context** — this is the correction worth stating precisely: scope isn't metadata sitting *next to* an otherwise context-free identity, it's *constitutive* of identity. "Transmission (Electric Grid)" and "Transmission (Telecommunications)" aren't the same thing with different context attached; they're different things, and scope is *how* they're different. | §0.9(3) — identity = (name, nearest discovery-time abstraction ancestor) |
| `investigation_status` | Describes what we believe about it (`explored`/`partially_explored`/`unexplored`) — and critically, unlike `kind` below, this does NOT vary by question. How much has been learned about a thing accumulates across every question that's ever touched it; it doesn't reset or fork per-question. | §0.9(4) / §0.7's bounded-model-expansion resolution — **missing from your own draft list, worth re-adding explicitly** |
| `created_at`, `updated_at`, `merged_from` | Describe how the record itself came to exist/change — administrative history of the node-as-record, not a claim about the world or a question's view of it. | Already in `GraphNode` (`backend/graph/models.py`) — pre-existing, still holds |

**Fails — real candidates that don't survive the test:**

| Candidate | Why it fails | Where it actually belongs |
|---|---|---|
| `kind` (entity/process/abstraction/...) | Fails question 1 outright: **already established as question-relative** — the same node is `process` under one question's view and `concept` under another (§0.9(2)). It describes how a question currently interprets the thing, not the thing itself. Your own draft listed this as a Node field; applying your own test to it says otherwise. | View/Question layer |
| "structure" (relations to other nodes) | Not a field at all — real graph edges (a `Relation`-role node pointing at this one), never a stored property. Real and load-bearing, just not part of a field list. | Graph structure, reached by traversal, not stored |
| "epistemic links" (Claims) | Same shape as structure — reached via the already-existing `Node -HAS_QUESTION-> Question -ANSWERED_BY-> Claim` path (§0.11), never a property on the node. | Graph structure, reached by traversal, not stored |
| `question`, `dimension`, `zoom_level`, `comparison`, `user_intent` | Your own instinct, confirmed correct by the same test — these describe the asking, not the thing. | View/Question layer (§0.15) |

**Two real tensions surfaced by doing this carefully, named rather than silently resolved:**

1. **`description` is currently overloaded, and shouldn't stay that way once this schema is actually frozen.** §0.9/§0.14 deliberately reused the existing `description` field as the `scope` carrier — the right call *for a minimal, testable Pass-3 mechanism*, explicitly not the frozen schema (§0.14: "a minimal, testable mechanism ... not the frozen Node schema"). Now that `scope` has earned its way into the real field list on its own merits (above), it should become its own field, separate from `description` (which stays as an optional, human-readable summary, unrelated to identity). Continuing to conflate them past this point would be carrying a testing shortcut into production data.
2. **Checked directly against the live VM's Neo4j (read-only, zero LLM calls, per this section's own "next session" plan below — done same day, not deferred):** `GraphNode.type` (`"entity" | "domain"`) is **entirely unused in practice** — every one of 113 real nodes is `type="entity"`; `type="domain"` has zero occurrences. `find_or_create_entity` always creates with the `"entity"` default, and nothing in the real investigation path ever passes `"domain"`. This isn't "may overlap with `kind`'s `abstraction` tag" — it's that the domain/entity axis has never actually done any work in the live system, so there's nothing there to reconcile with `kind` so much as a dead distinction to retire once `kind`'s View-layer version exists. **A third, previously unnoticed wrinkle, found while checking this:** `frontend/app.html`'s `SessionState.add_node(kind=...)` already has its *own*, disconnected `kind` concept (`"entity"` / `"abstraction"`, used only for Cytoscape node-shape styling) — a third parallel axis alongside Neo4j's `type` and the new semantic `kind` from §0.9, none of the three currently aware of each other. Not merged here — named so the eventual View-layer `kind` implementation doesn't accidentally leave two dead ones behind instead of one.

**Resulting Node, semantics only, no types/constraints/Neo4j decided:**
```
Node
├── id                    (identity)
├── name                  (identity)
├── scope                 (identity — NOT context; see above)
├── description           (optional, human-readable, separate from scope)
├── investigation_status  (what we believe about it — explored/partially_explored/unexplored)
├── created_at / updated_at / merged_from   (record history)
└── [relations and claims are NOT fields — reached via graph structure]
```

**Not decided here, on purpose:** whether `type`/`kind` merge into one field once the tension above is checked against real data; Neo4j property types/constraints; whether `investigation_status` needs sub-states per-relation as well as per-node (an open question, not raised before, worth naming: can a `Node` be `explored` while a specific `Relation` it participates in is still `unexplored`? Plausible, not tested — flagged, not answered).

**Update (2026-08-29, same day) — the split is done and verified; §0.16 is frozen.** `scope: Optional[str]` is now its own real property on `GraphNode` (`backend/graph/models.py`) and `create_node`/`find_or_create_entity` (`backend/graph/interface.py`) — matching/creating against `n.scope`, not `n.description`. Verified live against the VM's Neo4j, deterministically, zero LLM calls (same discipline as §0.14's mechanism check):

```
find_or_create_entity('SplitTestTransmission', scope_hint='Electric Grid')     -> id=e7fea979...  scope='Electric Grid'      description=None
find_or_create_entity('SplitTestTransmission', scope_hint='Telecommunications') -> id=1d890f64...  scope='Telecommunications' description=None
find_or_create_entity('SplitTestTransmission', scope_hint='Electric Grid')     -> id=e7fea979...  (same as the first call)

A != B (no false merge):                                    True
A == A2 (repeated call with the same scope reuses the node): True
scope is a real property, description stays clean (None):   True
```

Old nodes created under the pre-split mechanism (§0.14's `TestTransmission` fixtures, scope sitting in `description`) are now unreachable by scope-aware lookups and were **not migrated** — deliberately, per this section's own note above: disposable mechanism-verification test data, not real investigated content.

**§0.16's Node field list is now frozen:** `id`, `name`, `scope`, `description`, `investigation_status`, `created_at`/`updated_at`/`merged_from`. `type`/`kind` merging and Neo4j-level types/constraints remain explicitly open (not blocking anything downstream).

**Next session starts here:** how `Node`s and `Relation`s are actually represented as a network in Neo4j while keeping View state (§0.15) out of the canonical model — the bridge from proven semantics into a real implementation. Not a full rewrite: `handle_compare`'s fix (make it build an ephemeral View instead of persisting a comparison node — §0.15) is the first concrete, low-risk piece of that bridge, now unblocked by both a frozen field list and documented View semantics.

### 0.17 Typed relations and free topology — research pass, code deferred (2026-08-29)

**[THEORY], not yet implemented — user explicitly asked for research before code.** This picks up exactly where §0.16 left off ("how Nodes and Relations are actually represented as a network"), forced this time not by a constructed stress test but by a real, unprompted live-use failure the user hit and pasted in full.

**0.17.1 — The forcing example.** User asked *"show me the workings of a payment... where mastercard works and where paypal works."* The text answer was genuinely rich: 5 stages (Initiation/Authorization/Capture/Settlement/Reconciliation), with Mastercard and PayPal each doing something *different and specific* at each stage — e.g. "PayPal performs its own internal authorization... if funded by a linked card, PayPal will forward an authorization request to that card's network (e.g. Mastercard)." That sentence alone asserts three real relations: `PayPal --authorizes--> (the transaction)`, `PayPal --delegates_to--> Mastercard`, `Mastercard --routes--> (issuing bank)`. None of it reached the graph. The graph held 3 nodes ("Payment", "Payment Process", "Payment Process Stages") joined by `decomposes_into`, with zero children under "Payment Process Stages" — so `zoom_in` correctly (per the already-`[VERIFIED]` §-earlier zoom_in/investigate_deeper split) reported nothing to show, and only a follow-up `investigate_deeper` produced real children (Authorization/Capture/Settlement) — still joined only by `decomposes_into`, still with no Mastercard/PayPal nodes or edges at all.

**0.17.2 — Verified against the live code, not assumed.** Two claims checked directly, not recalled from memory:

- `create_relationship(source_id, target_id, relationship_type, properties=None)` (`backend/graph/interface.py:200`) is **already fully generic** — `relationship_type` is an untyped string parameter, `MERGE`d straight into the Cypher query. It requires two *existing* node IDs; it has no opinion about tree shape, single-parent-ness, or vocabulary. Confirmed by direct read, not memory.
- `ground_agent.py`'s decompose branch (`ground_agent.py:254`) calls it with exactly one hardcoded literal: `create_relationship(parent_entity.id, child_entity.id, "decomposes_into")`. This is the *only* call site that ever writes an edge in live investigation. Confirmed by direct read.

So the finding is precise, not vague: **the storage layer already supports arbitrary typed relations between arbitrary existing nodes — the decision layer (`GroundDecision` / `decide_next_step` in `ground_agent.py`) never asks for anything but "one new child, `decomposes_into` its one parent."** This is a gap in one call site and one Pydantic schema, not a storage or schema redesign.

**0.17.3 — Two separable problems, previously conflated as one.** The user named both in the same breath ("more types of connections" / "full control... networks, trees, pyramids"), but they're independent axes:

1. **Edge vocabulary.** Every edge today says `decomposes_into`, regardless of whether the real relation is compositional ("Authorization is part of the payment flow"), causal/sequential ("Authorization precedes Capture"), role-based ("Mastercard routes the request"), or delegating ("PayPal delegates to Mastercard"). This is a *labeling* problem.
2. **Topology.** Today, every edge is parent → *freshly discovered* child, one per decompose step — a strict tree, one edge per new node, ever-growing depth-first. The payment example needs a genuine **network**: `PayPal` connects to *multiple* stage nodes (Initiation, Authorization, Capture, Settlement, Reconciliation), `Mastercard` connects to a *different, overlapping* subset of the *same* stage nodes, and `PayPal --delegates_to--> Mastercard` connects two *actor* nodes that are siblings of neither. No tree can express this without duplicating "Mastercard" once per stage.

**0.17.4 — Cross-check against three other stress examples already in this document**, to make sure the fix generalizes rather than being a payment-specific patch:
- Electric grid (§0.7/0.8): `Control` regulates *both* `Generation` and `Transmission` — same lateral-cross-link shape as PayPal/Mastercard, already named there as unrepresentable by a tree.
- Smartphone pipeline (§0.6.1, the original forcing example for the whole Model Graph arc): a manufacturing *sequence*, not a decomposition — `decomposes_into` was already known to be semantically wrong for it, just never fixed at the mechanism level until now.
- Authorization → Capture → Settlement (this session's own `investigate_deeper` output): three stages the model itself describes as "linked" and sequential ("Authorization guarantees availability... Capture finalizes... Settlement actually moves the money") — currently flattened to three interchangeable `decomposes_into` children of one parent, losing the order entirely.

All four examples want the *same* two things: a real vocabulary word instead of "decomposes_into", and permission to connect to a node that isn't a brand-new child of the current parent. That convergence is the actual justification for treating this as one fix, not four.

**0.17.5 — Why "full freedom" needs one guardrail, not zero.** Section §0's own founding research (agent orchestration, cost/spawn budgets) already rejected "let the model do whatever, unbounded" once, for the same underlying reason it would bite here: an LLM given a truly open-ended relationship-type field will name near-duplicate synonyms for the same concept across calls (`routes`, `routes_to`, `forwards_to`, `sends_to` for what is semantically one relation), silently fragmenting the graph into look-alike edges that never traverse together. This is the exact same shape of problem already named and deliberately deferred for scope-hints (§0.14) and for `type`/`kind` (§0.16) — not solved here either, just flagged up front so it isn't rediscovered as a surprise later: **relationship-type vocabulary drift is a known, accepted, deferred risk**, not an oversight.

**0.17.6 — Design sketch (semantics only, not committed, not coded).** Two additive fields on `GroundDecision` (`backend/questions/models.py`), used only when `action == "decompose"`:

- `relationship_type: Optional[str]` — the LLM's own word for how the *discovered child* relates to its parent, defaulting to `"decomposes_into"` when unset (fully backward compatible — every existing call site keeps working unchanged). Prompted with a short *non-exhaustive* example list (`produces`, `routes_to`, `authorizes`, `delegates_to`, `regulates`, `precedes`, `depends_on`, `decomposes_into`) so the model has a shared vocabulary to reach for instead of inventing prose each time — mitigating, not solving, 0.17.5's drift risk.
- `additional_relations: Optional[list[DiscoveredRelation]]`, capped (e.g. 5 per step) — each a `{source_entity_name, target_entity_name, relationship_type, reasoning}` naming a relation *between entities already known in this investigation* (old-to-old, old-to-new, or new-to-new), *not* required to route through the current parent. This is what actually buys the network/pyramid shapes: `PayPal --delegates_to--> Mastercard` becomes expressible as an `additional_relations` entry the moment both names have been mentioned, with no change to Neo4j, no new node type, and no change to `create_relationship` at all — it already accepts any two existing IDs.

Both fields are optional and additive: a `GroundDecision` that never sets them reproduces exactly today's tree-of-`decomposes_into` behavior, so this is a strict superset, not a rewrite. Topology (tree vs. network vs. pyramid) is deliberately **not** a mode the agent picks up front — it falls out naturally as an emergent property of how many `additional_relations` actually get named for a given subject, which matches this document's standing principle (§0.7) that `Node`/`Relation` is the one dumb primitive and shape is discovered, never prescribed.

**Not decided or built here, on purpose:** the exact `DiscoveredRelation` schema/field names; how `additional_relations`' entity names get resolved to IDs (presumably `find_or_create_entity`, same as the existing child path, but not restricted to create — should prefer resolving to something already discovered this investigation over silently minting a duplicate); whether relationship-type vocabulary needs canonicalization/dedup now or can stay deferred like scope-hints; how many relations-per-step is actually safe before graphs blow up in size for one answer. **Next session, if the user wants to move to code:** the smallest verifiable slice is just `relationship_type` (0.17.6's first bullet) — one new optional field, one call-site change (`"decomposes_into"` literal → `decision.relationship_type or "decomposes_into"`), fully backward compatible, directly fixes nothing about topology but immediately stops every edge in the graph from lying about being a decomposition. `additional_relations` (the network-topology piece) is the bigger, second slice, deliberately not bundled with the first.

**Update (2026-08-29, same day) — the `relationship_type` slice is built and `[VERIFIED]` live against the VM.** Implemented exactly as sketched, nothing more: `GroundDecision.relationship_type: Optional[str]` (`backend/questions/models.py`), prompt guidance in `decision.py`'s `_SYSTEM_PROMPT` (compositional → leave unset → defaults to `"decomposes_into"`; actor/routing/etc. → name the verb-phrase), and `ground_agent.py`'s one call site changed to `decision.relationship_type or "decomposes_into"`. One more fix turned out to be required in the same slice, found by direct code read before shipping: `get_decomposition` (`backend/graph/interface.py`) hard-filtered its Cypher match to the literal `relationship_type: 'decomposes_into'` — any child written under a different type would have been silently invisible to `zoom_in` and the live graph sync, reproducing the "no further sub-components yet" bug for a new reason. Widened to match any outward edge; the two callers (`_sync_decomposition`, `handle_zoom_in`) needed no changes since they only ever consumed the returned nodes, never the type.

Verified two ways against the VM's real Neo4j (`opc@<VM>:~/app`, scp'd + restarted, same deploy discipline as every other pass this session):
1. **Full agent run**, "How does a card payment move from a customer to a merchant?" (persist_to_graph, gather_evidence, depth=2/steps=3, 79s wall time) — produced `'Card Payment' -[decomposes_into]-> 'Authorization'` and `'Card Payment' -[decomposes_into]-> 'Capture and Settlement Phases'`, confirmed written in Neo4j by direct Cypher query, not just the agent's own log line. Both stayed at the default — correctly, per the mechanism's own guardrail: this question's real structure at master level *is* compositional (payment phases), so `decomposes_into` is the right label, not a case the fix was supposed to change. This is the acceptance test's regression check (existing investigations still produce `decomposes_into`) passing for the right reason, not by accident.
2. **Targeted `decide_next_step` calls** (direct, bypassing HTTP) aimed at questions with a real actor/routing relationship: *"Who routes the authorization request from the acquiring bank to the issuing bank, and what specific role does Mastercard play in that routing step?"* against entity `"Payment Authorization"` produced `discovered_entity_name="Payment Network"`, **`relationship_type="routes_to"`** — a real, correctly-chosen non-default label, reached on the first attempt with no prompting toward that specific word. Two adjacent probes (PayPal-forwards-to-Mastercard; electric-grid Control-regulates-Generation) both returned `action="answer"` instead of decomposing further — not a failure of the mechanism, just the model judging enough was already known to answer directly rather than discover a new entity at that point; the mechanism was never exercised on those two, not exercised-and-wrong.

This satisfies all six of the user's stated acceptance criteria: existing investigations still default correctly (1); a real non-default relationship was produced (2); it reaches Neo4j, confirmed by direct query rather than trusting the log (3); zero schema changes (4); topology untouched — still exactly one child per decompose step (5); no relationship explosion — same one-edge-per-step shape as before (6). Vocabulary observed so far: `decomposes_into` (default, phase-based questions) and `routes_to` (actor/routing question) — too small a sample to say anything about the drift risk named in 0.17.5 one way or the other; watch for synonym fragmentation (`routes_to` vs `forwards_to` vs `routes_request`) as real usage accumulates, per that section's own guidance not to solve it preemptively.

**`additional_relations` (the topology/network slice) remains not started, per the user's explicit instruction to prove vocabulary in isolation first** before introducing cross-branch edges — next session's natural starting point once more real-usage vocabulary has been observed.

**Update (2026-08-29, same day) — real usage arrived fast, and it changes the plan.** A live 4-question test session (§0.17.10 below) showed the vocabulary problem is worse than "too small a sample": across 4 deliberately actor/role-framed questions, `relationship_type` stayed at the default every single time, including one clear miss — `'Privilege Escalation' -[decomposes_into]-> 'Intrusion Detection System'`, where an IDS *detecting* privilege escalation got written as if IDS were a structural *part of* privilege escalation. This forced the next research pass (0.18) rather than waiting for more organic data.

### 0.17.10 Live 4-question test — the vocabulary problem measured, not assumed (2026-08-29)

Run locally against the VM's live backend (SSH-tunneled `localhost:8080 -> VM:8000`, zero local Neo4j setup — reused the VM's real graph and provider chain directly, no credentials moved between machines). Topic: how a cyberattack works, chosen specifically to let each follow-up question deliberately probe an actor/role relationship rather than a phase:

1. "How does a cyberattack work, reconnaissance to impact?" → `decomposes_into` × 3 (Reconnaissance, Weaponization, Delivery) — correct, genuinely compositional.
2. "Go deeper into Weaponization — how does an exploit target a vulnerability?" → `decomposes_into` (Exploit development) — arguably still correct, still a sub-phase.
3. "How do attackers escalate privileges, and what role does an IDS play in detecting it?" → `decomposes_into` (Privilege Escalation), then `decomposes_into` × 2 for its children, **one of which is `Intrusion Detection System`** — this is the clean miss. IDS is not a part of privilege escalation; it is an external actor that observes it. The prompt guidance added in this same session (0.17.6, "leave `relationship_type` unset only when the relationship really is plain composition") was directly in front of the model and didn't prevent this.
4. "How do ethical penetration testers use these same techniques defensively?" → `decomposes_into` again, plus a separate, unrelated `relates_to` edge from a different code path (the `explain` intent handler, misfired by an intent-classification bug — noted, not part of this mechanism).

Net: 0 non-default `relationship_type` values across 4 real, deliberately-adversarial questions, versus 1-for-1 in the earlier isolated `decide_next_step` probe (§0.17, "routes_to"). The difference between the two results is itself the finding, chased down in 0.18.

## 0.18 Diagnosing the "decompose"-verb bias, and what makes a relation worthy of the model (2026-08-29)

**[VERIFIED] by controlled experiment**, prompted directly by the user's own read of 0.17.10: *"the investigator still overwhelmingly thinks in trees."* Two competing explanations were possible going in — (a) the prompt wording for `relationship_type` is just too weak, needs better examples/emphasis, or (b) something structural is crowding it out regardless of wording. These predict different fixes (a: tune the prompt; b: change the shape of the decision), so it was worth resolving empirically rather than guessing.

**The experiment.** Took the exact real content that produced the miss (0.17.10 case 3's known-text about IDS monitoring privilege escalation) and ran it through two different framings against the same live provider chain:

- **As-is (already observed):** fed through `decide_next_step`'s real schema and prompt, where the field asking about relationships lives inside an action literally named `"decompose"`. Result: `decomposes_into`.
- **Decoupled:** a standalone call, new system prompt, explicitly told *"you are NOT deciding what to investigate next, and you are NOT deciding how to decompose a topic"* — its only job is naming actor/causal/functional relationships between entities already in the text, with compositional relationships explicitly out of scope. Same underlying facts, same provider chain (Groq → Gemini → Cerebras fallback, same as production).

**Result:** `'Intrusion Detection System (IDS)' -[spots]-> 'Privilege Escalation'`. Correct actor relation, correct direction, on the first successful call. Same model family, same facts, same day — the only thing that changed was whether the question was asked *inside* an action called "decompose" or as its own independent decision.

**This resolves the question in favor of (b), not (a).** The failure isn't that the model doesn't understand the concept of a non-compositional relationship — the decoupled call proves it can name one correctly, unprompted with examples specific to this case. The failure is that asking about it as a rider on a decision whose own name is "decompose" biases the completion toward composition before the relationship question is even reached. Better prompt wording on the same field was already tried (0.17.6) and didn't fix case 3 — consistent with a structural cause, not a wording one.

**Design implication — `additional_relations` gets promoted.** 0.17.6 filed `additional_relations` as "the bigger, second slice, deliberately not bundled with the first," framed purely as the mechanism for topology (cross-branch edges). This experiment shows it's also the fix for the vocabulary problem the first slice couldn't solve: relation-naming needs to happen as its own decision, decoupled from whichever entity happens to be getting decomposed this step — not because topology and vocabulary were ever actually separable goals, but because the *only* tested way to get correct vocabulary was to ask about relations independently of "decompose." The two problems turned out to share one fix.

**Relation-worthiness — what makes a candidate relation worth writing to the world model, not just prose color.** Framed the same way 0.9 tested candidate Node fields (five questions, not intuition), tested against every relation the decoupled call actually returned (IDS spots Privilege Escalation; attackers exploit misconfigurations; IDS monitors privileged actions; IDS builds behavioral baselines; SIEM correlates events; ...):

1. **Both ends must be independently a "thing"** — something that could stand as its own Node under some question, not an adjective or a sub-fact about one entity. "IDS spots Privilege Escalation" passes (both are real entities elsewhere in the graph); "privileged actions deviate from normal behavior" fails — "normal behavior" is a description, not a Node candidate. The raw decoupled-call output actually contained both kinds, confirming this filter is necessary, not theoretical — an unfiltered "extract all relations" pass produces graph-unworthy noise alongside the good ones.
2. **The relation must be stable, not an artifact of one phrasing.** "IDS spots Privilege Escalation" would hold under almost any question about either entity. A relation that's only true under the exact wording of one question is a View-layer fact (0.15), not a World-Model one — this is the same distinction that already governs why `handle_compare`'s canonical "A vs B" node is wrong, applied to relations instead of nodes.
3. **The relation must be independently useful for a different question than the one that surfaced it** — i.e., would traversing this edge later help answer something else? "IDS spots Privilege Escalation" would help answer "what detects privilege escalation" or "what does an IDS do," neither of which is the question that discovered it. This is the real test for "worthy of the model" vs. incidental detail.
4. **Direction and vocabulary should describe the actual acting party**, not be forced into a generic symmetric label — "spots"/"detects" names who does what to whom; a flattened `relates_to` (as accidentally produced by the unrelated `explain`-handler bug in 0.17.10) discards exactly the information that made the relation worth having in the first place.

**Topology safety — arbitrary connections without becoming semantic garbage.** The answer isn't a topology *rule* (no cap on fan-out, no restriction on which nodes may connect) — it's that relation-worthiness (above) is the gate, applied per-candidate at write time, not a shape constraint on the graph. `create_relationship` staying mechanically dumb (any two existing IDs, any string) was always fine per 0.7's founding principle; what was missing was a filter *before* that call, not a constraint *on* it. A network can be as tangled as the real domain requires, as long as every edge in it individually passes the four-question test above — that's what keeps "give the agent full freedom" from degrading into noise, without ever needing to prescribe tree vs. network vs. pyramid as a mode someone picks.

**Not decided or built here, on purpose:** the exact shape of the decoupled relation-extraction call in production (a second LLM call per step has a real cost/latency price — the 0.17.10 test already showed individual calls taking 60-90s+ under evidence-gathering load; whether relation-extraction needs to run every step or only at synthesis time is unresolved); whether `additional_relations`' entities resolve only to already-known nodes or may also mint new ones; how many relations-per-step is safe. **Next step, when the user is ready to code:** design `additional_relations` as a genuinely separate decision (its own system prompt, its own call or its own schema section with independent framing — not a field appended to `GroundDecision`), gated by the four-question worthiness test above, and re-run the exact 0.17.10 IDS case end-to-end as the acceptance test.

**Update (2026-08-29, same day) — built and run against the exact IDS acceptance case; two real defects found, mechanism otherwise sound.** Implemented as `backend/questions/relation_extraction.py`: `extract_relations()` (own system prompt, explicitly told it is not deciding whether to decompose anything) and `is_relation_worthy()` (the mechanically-enforceable half of the four-question test — bans compositional types and generic/symmetric ones; points 2-3 of the test are left to the extraction prompt itself, since they're judgment calls a function can't verify from the candidate alone). Wired into `GroundAgent._finish` — the same single choke point every terminal outcome already passes through — as a second, independent call on `result.answer`, tolerant of total provider failure (degrades to zero relations, same as `gather_evidence`'s retrievers; never allowed to break the answer it's enriching).

Run against a fresh GroundAgent investigation reproducing the exact 0.17.10 IDS scenario. Checked against the four things the user asked to inspect, not just "did the call succeed":

1. **Direction — FAILED.** Produced `'Privilege Escalation' -[detects]-> 'Intrusion Detection System'` — backwards. IDS is the actor; this has Privilege Escalation detecting IDS. The standalone diagnostic in this same section (run minutes earlier, same content) got the direction right; this run, with a full question/entity context in front of it, got it wrong. The one prompt difference between the two: this call's user prompt opens with `"Entity under discussion: {entity_name}"` before the passage — a plausible cause is that naming the current investigation's entity first primes it as the grammatical subject of any relation the model then extracts, independent of which entity is actually doing the acting. Not confirmed, just the leading hypothesis — consistent with this section's own finding that framing, not content, is what moves these calls.
2. **Type — passed.** `detects` is a real, specific, non-compositional verb — the vocabulary half of the mechanism worked even though the direction half didn't.
3. **Worthiness — passed, with a caveat surfaced by it.** Both `Privilege Escalation` and `Intrusion Detection System` are real, independently-standing nodes. But `find_or_create_entity('Privilege Escalation')` correctly reused a node already created by an *earlier, unrelated* session (the 0.17.10 live test) rather than creating a duplicate — good dedup — while the *current* investigation's own entity, deliberately named `Privilege Escalation Test b4feeb` to keep this test isolated, never got connected to the new relation at all. The extraction call normalized the artificial test name down to the real-world term it recognized, and exact-name-match resolution (the same limitation already named for scope-hints in 0.14) sent it to a different node than the one this investigation was actually about. Likely overstated by this test's artificial naming — production entities won't carry a `Test b4feeb` suffix — but it's a real, generalizable instance of the same exact-match fragmentation risk, not unique to this mechanism.
4. **Isolation — passed cleanly.** Checked directly: the test's own entity node (`Privilege Escalation Test b4feeb`) has exactly one edge, `HAS_QUESTION`, and nothing else — the relation-extraction call created zero decompose edges, zero extra investigation-tree structure, and didn't touch the ground-agent loop's own state. The `decomposes_into` edge visible in the query results (`'Privilege Escalation' -[decomposes_into]-> 'Privilege Escalation Techniques'`) predates this run entirely — leftover from the earlier 0.17.10 live session, surfaced only because the diagnostic query matched by name substring across the whole shared store, not created by this test.

**One more data point, not yet judged either way:** the call also produced `'OSSEC' -[is_an_example_of]-> 'Intrusion Detection System'` and `'OSquery' -[is_an_example_of]-> 'Intrusion Detection System'` — concrete tool names the model introduced from its own knowledge, not named in the question. `is_an_example_of` isn't in the banned list (it's not compositional in the whole/part sense, and it's not generic/symmetric) and it does pass the four-question test on inspection — both ends are real standalone entities, the fact is stable, and "what IDS tools exist" is a genuinely different, legitimately answerable question this edge would serve. Left as-is rather than added to the banlist reflexively: this looks like a new, real relation category (taxonomic/class-membership) the worthiness test already happens to accept correctly, not a filter gap — flagged for the user to confirm rather than assumed.

**Not fixed yet, on purpose — diagnosis first, per the user's explicit instruction.** The architectural goal is confirmed working in the one place that matters most: the investigation tree and the world-model relation are already living as separate structures (isolation passed cleanly), which is the actual foundation this whole arc has been chasing. What's broken is narrower than "the mechanism" — it's specifically (a) source/target direction under this exact prompt framing, and (b) entity-name resolution consistency between the investigation's own entity and whatever name the extraction call settles on. Both are plausibly fixed by the same kind of small, targeted change already used elsewhere in this section (e.g., not leading the extraction prompt with the investigation entity's name, or passing the investigation's own already-resolved entity as a hint for resolution rather than free text) — but per the user's instruction, nothing changes until this is discussed.

**Update (2026-08-29, same day) — controlled A/B on direction, 3 trials per condition, same passage/entities/model chain, only the framing changed:**

- **Prompt A** (current production framing, `"Entity under discussion: Privilege Escalation"` leading the call): A1 `IDS -[spot]-> Privilege Escalation`; A2 `Privilege Escalation -[is detected by]-> IDS`; A3 `Privilege Escalation -[can be detected by]-> IDS`.
- **Prompt B** (neutral framing, explicitly "do not assume either entity is the source"): B1 `IDS -[monitors]-> Privilege Escalation`; B2 `IDS -[detects]-> Privilege Escalation`; B3 `IDS -[detects]-> Privilege Escalation`.

**Honest read of this, not the cleaner story it would be nice to report:** all 6 trials are factually *correct* once passive voice is accounted for — A2/A3's `Privilege Escalation -[is detected by]-> IDS` means the same true thing as `IDS -[detects]-> Privilege Escalation`, just represented with the acted-upon entity as `source_entity` and the relationship type flipped to passive to compensate. **None of the 6 controlled trials reproduced the original defect** — the earlier acceptance-test miss, `Privilege Escalation -[detects]-> Intrusion Detection System`, is factually *false* (Privilege Escalation does not detect anything); that specific error didn't recur here in either condition. So this experiment does not confirm the "entity under discussion primes the wrong subject" hypothesis as the explanation for that specific miss — it may have been a rarer, independent model error this sample didn't happen to catch.

**What the experiment DID find, cleanly and consistently across all 3 trials each way:** Prompt A's framing correlates with passive-voice construction (entity-under-discussion as grammatical subject, relationship type flipped to compensate); Prompt B's neutral framing correlates with active-voice construction (actual actor as source, direct verb). Both are true statements about the world, but they are *not* the same graph edge — `X -[detects]-> Y` and `Y -[is detected by]-> X` are structurally different edges, and a graph mixing both conventions for logically-equivalent facts makes "what does X detect" vs. "what detects X" queries unreliable depending on which voice the model happened to pick that call. This is a real, independently-worth-fixing finding — arguably more actionable than the original one-off direction error, since it's reproducible 6/6 rather than a single unreproduced instance.

**Where this leaves the plan:** the original "entity under discussion" hypothesis is downgraded from confirmed to unresolved — worth retesting on the exact original failing case rather than declared fixed or refuted. The voice-consistency issue is newly confirmed and stands on its own regardless of that outcome. Both remain undecided-not-yet-fixed, per the user's explicit instruction to diagnose fully before changing anything.

**Update (2026-08-29, same day) — canonicalization tested on an 8-row adversarial voice matrix: 8/8, then built for real.** Ran `extract_relations` (real production function, unmodified) on 8 single-sentence surface-form variants across 3 fact pairs (IDS/escalation active+passive+modal ×2, malware/damage active+passive, compiler/grammar active+passive), then a standalone canonicalization call on each raw result. All 8 converged on the correct canonical `(source, relationship_type, target)` for their pair — 6 of 8 were already active/correct at extraction time (single isolated sentences are far less ambiguous than a dense paragraph, which is likely why); the 2 that came out passive (`caused_by`, `depended_on_by`) were both correctly flipped by canonicalization, with no invented content in either correction (checked specifically for this — canonicalization normalized voice/direction only, never added a claim that wasn't in the raw candidate).

This was frozen and wired into production, not left as a diagnostic script: `canonicalize_relation()` (same schema/prompt validated above) and a small deterministic `normalize_relationship_type()` — a string-level synonym table built only from variants actually observed in this project's own test runs (`detects`/`spots`/`spot`/`monitors` → `DETECTS`, `causes` → `CAUSES`, `depends_on`/`depend_on`/`depends`/`depend` → `DEPENDS_ON`, `routes_to`/`route_to`/`routes` → `ROUTES_TO`, `is_an_example_of`/`example_of` → `IS_EXAMPLE_OF`; anything unmapped passes through as a consistently-formatted upper-snake-case string rather than being merged with anything — unmapped is not the same as unworthy). Both run in `GroundAgent._finish`'s relation loop, after `is_relation_worthy`, before `create_relationship` — canonicalization falls back to the raw (already-worthy) candidate on total provider failure, matching the same tolerance already established for `extract_relations` and `gather_evidence`.

**Confirmed live in production, not just in a test script:** re-ran the exact IDS/Privilege-Escalation scenario end-to-end through the real `GroundAgent` pipeline post-deploy. Result: `'Intrusion Detection System (IDS)' -[DETECTS]-> 'Privilege Escalation'` — correct direction, normalized uppercase verb. (Older edges from the pre-fix acceptance-test run are still sitting in the same shared Neo4j store and surfaced in the same query by name-substring match — leftover data, not a new defect; the *new* run's own edge is the one above.)

**Update (2026-08-29, same day) — identity resolution, diagnosed against the existing (name, scope) model, not solved with a new LLM call.** Read `find_or_create_entity` directly (`backend/graph/interface.py:127`) rather than guessing: when `scope_hint` is omitted, the lookup is a global, case/whitespace-insensitive exact-name match across the *entire* graph, with no domain awareness at all — and `ground_agent.py`'s relation-extraction integration calls it on both `source_entity`/`target_entity` with no `scope_hint` argument. This makes the user's predicted "Transmission" collision a structural certainty, confirmed by code read before any test was run.

Ran the adversarial test anyway, to see exactly how it manifests: `extract_relations` on three domain sentences ("Transmission carries electrical power" / electric grid; "Transmission carries packets" / computer networking; "Transmission uses fiber optic cable" / telecommunications). Extraction itself does zero disambiguation — all three returned the bare name `'Transmission'`, no domain qualifier added on its own. Resolving each with `find_or_create_entity('Transmission')` (today's actual behavior, no scope hint) sent **all three to the identical node id** — confirmed collision, not hypothetical. Resolving the same three calls with `scope_hint=<domain>` (the mechanism that already exists, verified working since §0.16) produced three correctly distinct node ids. The resolver isn't missing — it's simply never invoked with the information it needs, at this one call site.

**Recommendation, not yet built:** the fix is narrower than "build an identity resolver" — one already exists and works. What's missing is threading a scope hint through the relation-extraction call site, the same way the decompose branch already does for its own parent/child resolution (`self.question.entity_scope_hint`). The real open question, worth testing rather than assuming: relations connect *two* entities, which may not share the current question's scope (most observed cases so far — IDS/Privilege-Escalation, PayPal/Mastercard — happen to share one domain with the investigation, but that's not guaranteed in general). Applying the current investigation's scope hint to both ends is the obvious first thing to try, but should be tested against a case where the two relation endpoints plausibly belong to *different* scopes before being trusted, rather than assumed correct by analogy to the decompose branch.

**Update (2026-08-29, same day) — cross-scope test run, result is Outcome 2: blanket scope application is unsafe, not just insufficient.** Paired two entities with opposite identity profiles — `Router` (genuinely ambiguous: a networking device and a woodworking tool share nothing) against `Internet` (genuinely invariant: one real thing, no domain-relative senses) — and resolved each under two different investigation scopes. Raw stored data, read directly from Neo4j, not inferred from IDs alone:

```
{'name': 'Router',   'scope': 'Computer Networking'}   id=7f21ea24...
{'name': 'Router',   'scope': 'Woodworking'}            id=4fbadc4e...   <- correctly a different node
{'name': 'Internet', 'scope': 'Computer Networking'}    id=689c5864...
{'name': 'Internet', 'scope': 'E-commerce'}             id=86a67b02...   <- WRONGLY a different node
```

`Router` disambiguated correctly — exactly the case the scope mechanism was built for. `Internet` did not: the same real-world concept was split into two permanently-separate nodes purely because two different investigations happened to be framed under different scope labels. This is the user's predicted Outcome 2, confirmed with real data: **scope is a disambiguation constraint, not a mandatory identity component** — applying it uniformly to every relation endpoint is exactly as wrong as never applying it, just in the opposite direction (fragmentation instead of collision).

**What this rules out and what it doesn't.** It rules out "wire the current question's `entity_scope_hint` onto both relation endpoints" as a safe general fix — confirmed unsafe, not merely untested. It does **not** mean the existing `(name, scope)` identity mechanism is wrong; `find_or_create_entity`'s exact-match-plus-scope lookup did precisely what it was asked to do in both cases — the fault is entirely in *what gets asked of it* at the relation-resolution call site, matching this section's own recurring pattern (§0.18 throughout: the storage/matching layer keeps being sound; the decision layer keeps being where the gap actually lives).

**Not solved here, on purpose — this is the real next research question, not a next slice to code:** something has to decide, per relation endpoint, whether that entity's identity is scope-relative (needs the current domain to disambiguate, like `Router`) or scope-invariant (should resist fragmentation across investigations, like `Internet`) — and it isn't obvious that a small ruleset can make that call the way `normalize_relationship_type`'s synonym table could for verbs, since "which real-world things are domain-invariant" isn't a small, enumerable set the way "which verbs mean detect" is. Per the user's explicit framing: this shouldn't be "solved" by reaching for an LLM identity-resolver reflexively — the deterministic mechanism has now been shown to work correctly whenever it's given the right question to answer; what's missing is *what information* reaches it, not a smarter resolver. Left open, not designed: whether that information is a per-endpoint scope decision made at extraction time, a check against existing graph neighborhood before minting a new scoped node, or something else — worth its own dedicated pass rather than an answer bolted onto this one.

**Update (2026-08-29, same day) — "candidate-before-minting" test: does an existing unscoped candidate ever get reused? No.** Tested the specific mechanism the user proposed, against `find_or_create_entity` exactly as it exists today (zero code changes, zero LLM calls — this test is pure deterministic Cypher): mint `Electricity` with no scope at all (`A`, `scope=None`), then look it up again with `scope_hint="Physics"` (`B`).

```
A: Electricity, no scope_hint -> id=f5be0caa...  scope=None
B: Electricity, scope_hint='Physics' -> id=91fe67f2...  scope='Physics'
A == B? False
```

A brand-new node was minted rather than the existing global candidate being reused — confirmed directly from the query itself (`coalesce(n.scope, '') = toLower(trim($scope_hint))`): a node with `scope=None` coalesces to `''`, which is never equal to a real scope string like `'physics'`. **This answers the question decisively: the current mechanism has no notion of "compatible unscoped candidate" at all.** It isn't doing anything resembling candidate-search-with-context-compatibility — it does exact string equality on scope, full stop. A pre-existing global concept is exactly as invisible to a scoped lookup as a genuinely different, wrongly-colliding entity would be. This is the same root cause already identified for the `Internet` fragmentation above, now confirmed at the mechanism level rather than only observed at the outcome level — stopped here rather than running the remaining planned sub-cases (a same-family scope-conflict re-check, an unscoped-lookup-among-multiple-candidates check), since they exercise the identical code path and were very unlikely to add information beyond what this one pair already settled.

**Secondary, unrelated finding worth flagging separately so it isn't mistaken for part of the identity result:** each Neo4j round-trip in this test took roughly 15-25 seconds — unusually slow for pure Cypher with no LLM involved, and slow enough that the test script's own output was initially lost entirely to Python's stdout buffering when the process got killed by a timeout before flushing (resolved by re-running with unbuffered output). Likely cause: this test opens a brand-new driver/connection from a short-lived script process, incurring full TCP+Bolt-handshake+auth overhead per invocation — a cost the actual running application never pays, since `uvicorn` holds one long-lived driver for the life of the process. Noted as an infrastructure observation, not a finding about identity resolution.

**Update (2026-08-29, same day) — "candidate competition" test: a real, throwaway deterministic prototype, not just diagnosis of existing code.** The identity discussion up to here concluded `find_or_create_entity` is a lookup, not an identity mechanism — no candidate search, no context matching, no notion of uncertainty. This test asked the next real question: can a small, deterministic (zero-LLM) mechanism, given real graph neighborhood, actually distinguish `Router[Computer Networking]` from `Router[Woodworking]` given a new ambiguous mention — and correctly recognize when it *can't*, rather than guessing?

Built a throwaway `resolve_entity(name, context, candidates)` prototype: token-overlap scoring between the new mention's text and each existing candidate's real graph neighborhood (its attached relations' verb + target-entity words). First had to attach real relations to the two `Router` nodes — the earlier cross-scope test only ever printed extracted candidates, never persisted them, so there was no neighborhood to test against yet: `Router[Computer Networking]` got `CONNECTS_TO -> Network`, `FORWARDS -> Packets`; `Router[Woodworking]` got `SHAPES -> Wood`, `USES -> Cutting Bit`.

```
Candidate vocabularies:
  Router[Computer Networking]: ['connects', 'forwards', 'network', 'packets', 'to']
  Router[Woodworking]: ['bit', 'cutting', 'shapes', 'uses', 'wood']

"A router forwards packets between networks." -> scores {Networking: 2, Woodworking: 0} -> REUSE(Networking)   -- correct
"A router is used to shape and guide wood."   -> scores {Networking: 1, Woodworking: 1} -> AMBIGUOUS            -- WRONG, expected REUSE(Woodworking)
"The router is important."                    -> scores {Networking: 0, Woodworking: 0} -> AMBIGUOUS            -- correct
```

**Mixed result, and the failure is diagnosable, not mysterious.** Case 1 (clear signal) picked correctly. Case 3 (genuinely no signal) correctly refused to guess — the `AMBIGUOUS` outcome the user specifically wanted as a legitimate third state actually fired, not just as a theoretical option. Case 2 should have picked `Woodworking` (it contains "wood," a real neighborhood word) but tied 1-1 instead — because `Router[Computer Networking]`'s vocabulary contains the token `'to'`, a meaningless fragment produced by naively splitting `CONNECTS_TO` on its underscore. "Used **to** shape" in the mention text spuriously matched that fragment, manufacturing a false tie.

**This is a stopword/tokenization bug in a quick throwaway prototype, not evidence against the underlying concept.** The mechanism correctly distinguished the clear case and correctly preserved ambiguity in the genuinely uninformative case — the one miss has an identified, narrow cause (verb-phrase tokens like `CONNECTS_TO` need stopword filtering or a minimum-informative-token threshold before being used as neighborhood vocabulary, not a deeper flaw in "compare context tokens against graph-neighborhood tokens" as an approach). Worth naming plainly rather than either overselling (this isn't "solved") or underselling (this isn't "the deterministic approach failed") — it's a real signal that graph-neighborhood-based matching is *directionally viable*, with a concrete, fixable rough edge, not a verdict either way on its own yet.

**Not decided here, on purpose:** whether fixing the tokenization artifact and re-running is worth doing before committing to this direction, versus treating 1-clear-hit/1-clear-correct-refusal/1-fixable-miss as sufficient signal to design `resolve_entity()` properly (better token weighting, not just presence/absence — a word like "network" appearing in a candidate's neighborhood should count for more than an incidental preposition fragment). Left for the user's call, per this section's standing discipline of not tuning immediately after a single failure without first understanding why it failed.

**Update (2026-08-29, same day) — six-case evidence-type matrix: 6/6, not a patch-and-rerun of the same three cases.** Per the user's explicit call ("don't spend another experiment merely fixing 'to'"), designed a richer test spanning distinct evidence *types* against the same two `Router` candidates, rather than re-running the same three sentences. Two minimal, necessary fixes were made to the prototype first — not a scoring formula, just hygiene the six cases actually require: (1) basic stopword filtering (removes the exact `CONNECTS_TO -> "to"` artifact that broke the previous run); (2) each candidate's own `scope` string folded into its vocabulary alongside its graph-neighborhood words, since case B specifically needs a bare domain-name reference to count as evidence even with zero neighborhood-word overlap. The outcome space was also split into three genuinely distinct states — `REUSE` / `AMBIGUOUS` (no candidate has any evidence) / `CONFLICT` (multiple candidates have real, comparable evidence) — rather than collapsing the latter two.

```
Candidate vocabularies (neighborhood + scope, stopwords removed):
  Router[Computer Networking]: [computer, connects, forwards, network, networking, packets]
  Router[Woodworking]:         [bit, cutting, shapes, uses, wood, woodworking]

A - lexical:        "The router forwards packets."                                    -> REUSE(Networking)   scores {Net:2, Wood:0}
B - domain:          "In computer networking, the router matters a great deal."         -> REUSE(Networking)   scores {Net:2, Wood:0}
C - relational:      "The router connects networks and forwards packets."               -> REUSE(Networking)   scores {Net:3, Wood:0}
D - opposing lexical: "The router cuts and shapes wood."                                -> REUSE(Woodworking)  scores {Net:0, Wood:2}
E - no evidence:      "The router is important."                                        -> AMBIGUOUS           scores {Net:0, Wood:0}
F - conflicting:      "This router forwards packets while also cutting wood."            -> CONFLICT            scores {Net:2, Wood:2}
```

**6 for 6, including the case that actually mattered most: F is genuinely distinct from E, not the same outcome under a different name.** E correctly reports zero evidence anywhere; F correctly reports real, comparable, competing evidence on both sides — the resolver didn't collapse "nothing to go on" and "conflicting signals" into one shrug, which is exactly the distinction the user's `resolve_entity()` contract sketch needs (an `AMBIGUOUS`/no-evidence result looks structurally different from a `CONFLICT`/competing-candidates result, and a real implementation should return different `candidates`/`evidence` payloads for each). B is the most informative pass of the six: it had zero neighborhood-word overlap and was resolved purely by the candidate's own scope string — confirming that fold-in was load-bearing, not decorative.

**Honest limits of this result, named rather than glossed over:** this is six hand-written sentences against two hand-built candidates with hand-attached neighborhoods — a clean-room test of whether the evidence-type *concept* behaves sensibly, not a stress test against messy real extraction output at scale (synonym drift, partial neighborhoods, candidates with only one relation attached, three-or-more-way ambiguity). It settles the narrower question the user posed — "can context discriminate between competing identities, across genuinely different evidence types, including recognizing when it can't" — cleanly enough to move from throwaway heuristic to a real `resolve_entity()` design, per the user's own standard for when a prototype has earned that. It does not yet settle whether raw token-overlap counting is the right long-term scoring mechanism (the user's own caveat: "don't choose the exact formula yet" still stands) — only that the REUSE/AMBIGUOUS/CONFLICT *shape* of the decision is sound.

**Update (2026-08-29, same day) — `resolve_entity()` frozen and built for real, wired into relation persistence.** Per the user's explicit call to stop experimenting and freeze the contract: implemented `IdentityResolution`/`CandidateEvidence` (`backend/graph/models.py`) and `resolve_entity()` (`backend/graph/interface.py`), matching the frozen shape exactly —

- **Four decisions, not two.** `REUSE`/`CREATE` are actions a caller can safely act on; `AMBIGUOUS` (no candidate has any evidence) and `CONFLICT` (multiple candidates have real, comparable evidence) are both "don't guess," kept distinct rather than collapsed, per the F-vs-E result above. `selected_node` is `None` for both of the latter — by construction, not by convention.
- **Candidate search, not lookup.** New `_find_all_candidates` returns every node matching a name across *all* scopes — the search step `find_or_create_entity` never did (it stops at the first match or requires an exact scope match, which is exactly what caused both the `Transmission` collision and the `Internet` fragmentation earlier in this section).
- **0 candidates → `CREATE`** (via the existing `find_or_create_entity`, tagged with `scope_hint` if given — same default behavior, just reached through a decision that records *why*). **1 candidate → `REUSE`** it (this project's standing preference for reuse over duplication when there's no competitor to weigh it against — a case the six-row matrix didn't test directly, since it always had two candidates, but a direct, well-justified extension of the same principle). **2+ candidates → scored** by token overlap between context (+ `scope_hint`, folded in as ordinary evidence per the "scope is evidence, not identity" correction — never an override) and each candidate's real graph neighborhood plus its own scope string.
- **The persistence rule the user specified directly:** `ground_agent.py`'s relation loop now resolves *both* endpoints before calling `create_relationship`, and skips the relation entirely — logging why — unless both resolve to `REUSE` or `CREATE`. An `AMBIGUOUS`/`CONFLICT` endpoint on either side means the relation is not persisted; no half-known edge reaches the world model.

**Verified against the real deployed function, not just the throwaway script — identical result, 6/6:**

```
A - lexical:          REUSE  Router[Computer Networking]   Matched: forwards, packets
B - domain:            REUSE  Router[Computer Networking]   Matched: computer, networking
C - relational:        REUSE  Router[Computer Networking]   Matched: connects, forwards, packets
D - opposing lexical:  REUSE  Router[Woodworking]            Matched: shapes, wood
E - no evidence:       AMBIGUOUS  (none)                     No candidate has any matching evidence.
F - conflicting:       CONFLICT   (none)                     Multiple candidates have comparable evidence (2 each).
```

Same decisions, same selected nodes, same matched-token evidence as the validated prototype — confirming the production implementation is a faithful, not just similar, realization of the frozen contract.

**Not decided or built here, on purpose, matching the user's own framing of what comes next:** whether raw token-overlap is the right long-term scoring mechanism, versus weighted evidence (a distinctive word like "packets" counting for more than an incidental one) — deliberately deferred, not because it's wrong, but because nothing has yet demonstrated it's *needed*. Relation-worthiness refinement and evidence-on-relations (attaching Claims/sources to edges, not just nodes) are named as the next major direction, not started here — per the user's own sequencing, identity resolution is not to be touched again until one of those surfaces a reason to.

## 0.19 Long-range vision — captured, not started (2026-08-29)

**[VISION], explicitly deferred.** The user sketched a much larger direction worth preserving verbatim in spirit, even though none of it is scheduled: treating the graph not just as an investigation scaffold but as a genuine **learning system** — Node/Relation extended with epistemic state (unknown/discovered/supported/contested/understood), a learner/mastery model layered on top of the world model (what does the user already understand, what are they missing, what should they learn next), semantic zoom framed as resolution rather than repeated "tell me more," questions treated as operators that project a *View* over the graph (process view, causal view, dependency view, comparison view, temporal view, economic view) rather than as chat history, contradiction as a first-class relationship between competing Claims rather than smoothed into one synthesized paragraph, and time/versioning on both Nodes and Relations so the model can represent how a system evolved, not just its current state.

This is real and worth pursuing eventually, but it is at least three separable research programs (topology/relation-worthiness — 0.18, now underway; evidence attaching to relations, not just nodes — a natural next extension of 0.11/0.12; learner/mastery modeling — the biggest, least-grounded piece, and one that assumes a working relational world model underneath it that doesn't exist yet). Deliberately sequenced behind 0.18 rather than started in parallel, per this project's own standing rule against building the ambitious version before the small one is proven (the same reasoning that ruled out a full agent-orchestration framework in §0's original stack research).

## 0.20 Conversation state — a missing layer, diagnosed and designed, not yet built (2026-08-29)

**[THEORY], design only — per explicit instruction: diagnose fully, write the state contract, before touching code.** Forced by a real, reproduced bug: *"explain me how actually scalability work in real life games..."* was classified as `explain` (not `new_investigation`), returned `"scalability hasn't had any questions attached to it yet"`, and the user's follow-up `"yes"` was then classified as `new_investigation` and fabricated a full question about scalability out of one word.

### Root causes, traced through actual code, not assumed

**A — `explain`'s own name has too much authority over classification.** `backend/questions/intent.py`'s `_SYSTEM_PROMPT` defines `"explain"` narrowly (provenance: "why is X here") but the user's message *starts with the literal word* "explain." This is the same failure shape as §0.18's "decompose"-verb bias, confirmed earlier the same day in a completely different part of the system: an action's own name biases an LLM classifier toward itself whenever that word appears in the input, independent of the semantic distinction the prompt is trying to draw. Not a coincidence — the same underlying weakness, twice.

**B — there is no conversational state anywhere in this codebase.** Traced the full chain: `/chat` (`backend/api/app.py:297-318`) builds `SessionContext` from exactly `current_entity`/`current_abstraction`/`known_entities` (`intent.py:97-100`) — nothing about what the assistant just said, no notion of a pending offer. Grepped the entire backend for `pending`/`awaiting`/`confirm`: the only hit is `AgentStatus.PENDING`, an unrelated internal `GroundAgent` state. `Intent.action` (`intent.py:70`) is also a closed six-value `Literal` with no "cannot determine" escape hatch — the classifier is forced to produce one of six real actions for every message, including "yes." With no pending-state signal and no safe fallback, it fabricated a full `new_investigation`.

**C — found while tracing the chain, not previously reported: `handle_explain` never sets `session.current_entity`.** (`backend/api/app.py:168-181`) — it calls `session.add_node(entity_name)` but never updates the actual focus-tracking field, unlike `handle_zoom_in`/`handle_investigate_deeper`, which both do. Even with conversation state added, "explain" wouldn't correctly establish focus for whatever comes next without this fix.

### The architectural correction: three states, not two

The system already distinguishes *world model* ("what exists") from, increasingly, *knowledge state* ("what do we actually know about it," per §0.18's Claims/evidence work). It has never had a third: **conversation state** — "what is happening between the user and the system right now," specifically whether the assistant's last turn made an offer the user might now be responding to. These three must stay separate rather than being inferred from each other: a Node existing is not evidence of sufficient knowledge (already established, §0.6 onward); the system saying something is not evidence that a reply to it is now pending (the actual bug here).

### State model

```python
class PendingAction(BaseModel):
    """A single, structured, machine-executable offer the assistant made in its
    last reply -- never a raw string. Exists so a bare "yes" resolves
    deterministically instead of asking an LLM to guess what it refers to."""
    action: Literal["new_investigation", "investigate_deeper"]
    entity_name: str
    question_text: Optional[str] = None
    dimension_name: Optional[str] = None
    dimension_description: Optional[str] = None
    scope_hint: Optional[str] = None
    created_at: str
```

- `SessionState` (`backend/api/session.py`) gains `pending_action: Optional[PendingAction] = None`.
- `Intent.action` gains a seventh value: `"no_action"` — a safe outcome for input that isn't clearly any of the other six and doesn't relate to session context (e.g. "hello," "thanks," "asdf"), so the classifier is no longer structurally forced to invent one of six real actions for everything.
- **Confirmation handling does NOT go through `Intent`/`parse_intent` at all**, per the user's explicit correction to the original proposal: a small, deterministic, non-LLM classifier (`_classify_confirmation(message) -> Optional[bool]`, a short explicit affirmative/negative word list — same "start small, extend only on observed need" discipline as `normalize_relationship_type`'s synonym table) runs *before* intent parsing, on every turn, unconditionally. Only when a message doesn't look like a yes/no-shaped reply does it ever reach the LLM classifier.

### Lifecycle

```
NONE
  │  assistant makes an explicit offer (handle_explain, on 0 attached questions)
  ▼
PENDING
  ├── confirmation=True  → execute the structured action → NONE
  ├── confirmation=False → "okay, skipping that" → NONE
  └── message doesn't look like yes/no at all → cleared as a new-topic policy → NONE, falls through to normal parse_intent
```

Deliberate policy choice, flagged as a choice rather than a certainty: an unrelated message clears any pending offer rather than preserving it indefinitely — avoids a stale "yes" three turns later accidentally re-triggering an old offer. Revisit if real usage shows this is too aggressive (e.g. a user asking one clarifying question before answering yes/no).

### Proposed minimal changes (not yet made)

1. `PendingAction` model + `SessionState.pending_action` field.
2. `_classify_confirmation()` — deterministic, in `backend/api/app.py` or a small new module; short word lists, not NLP.
3. `/chat` orchestration: check confirmation *first*, every turn, before `parse_intent` — execute/cancel/no-op against `pending_action` deterministically; only fall through to `parse_intent` for non-yes/no-shaped messages, clearing any stale `pending_action` first.
4. `handle_explain`: set `session.current_entity = entity_name` (parity fix, root cause C); on zero attached questions, instead of a dead-end reply, set `session.pending_action` to a `new_investigation` offer and phrase the reply as an actual question ("X hasn't been investigated yet — want me to look into it?").
5. Tighten `_SYSTEM_PROMPT`'s `"explain"` definition (root cause A) — explicit contrastive examples ("Explain how X works" → `new_investigation`, NOT `explain`) so the action's own name carries less classification weight. A prompt fix, not a guarantee — should be tested empirically against real phrasing before being trusted, same discipline as every other prompt change this section has made.
6. Add `"no_action"` to `Intent.action` with brief prompt guidance.

### Explicitly deferred, per the user's own framing as "the real long-term architecture," not part of this slice

- **Per-question knowledge-coverage sufficiency** (a Node can have *some* knowledge but not knowledge sufficient for *this specific* question — the "Scalability has claims about the definition but none about MMO-scale networking" case). This slice's gate stays coarse: zero attached questions → offer to investigate. Distinguishing "has some knowledge" from "has enough knowledge for this question" needs a real relevance/coverage mechanism that doesn't exist yet — naming it, not building it.
- **Skipping re-investigation when sufficient knowledge already exists** (depends on the above).
- **Contextual continuation** ("why?", "how?", "what about networking?" referring back to the current focus) — a real, separate feature, not touched here.

### Transition table (extends the user's own draft with the concrete design above)

| # | Input | Conversation state | Path | Expected |
|---|---|---|---|---|
| 1 | "Explain how scalability works in games" | any | intent prompt fix | `new_investigation` |
| 2 | "Why is PayPal here?" | any, has claims | `explain` | provenance answer |
| 3 | "Explain PayPal" | any, 0 questions attached | `explain` | sets `pending_action`, offers to investigate |
| 4 | "yes" | `pending_action` = investigate(Scalability) | deterministic confirm layer | executes investigation, clears pending |
| 5 | "yes" | `pending_action` = None | deterministic confirm layer | "nothing pending" reply — no LLM call at all |
| 6 | "no" | `pending_action` = investigate(X) | deterministic confirm layer | cancels, clears pending |
| 7 | "Show me PayPal" | any | `zoom_in` | navigation, sets `current_entity`, clears any stale pending |
| 8 | "Go deeper into PayPal" | focused PayPal | `investigate_deeper` | investigates, clears any stale pending |
| 9 | "asdf" / "hello" | any (not yes/no-shaped) | `parse_intent` → `no_action` | polite no-op, not a fabricated action |

### Regression test matrix (to write alongside implementation, not after)

Rows 1, 3→4, 3→6, 5, 7, 8, 9 above, each as a concrete input/expected-output assertion. Rows requiring the deferred sufficiency mechanism (the user's own TEST 3 and TEST 8 continuation case) are explicitly out of scope for this pass's tests — asserting behavior for a mechanism that doesn't exist yet would be testing a promise, not code.

**Update (2026-08-29, same day) — §0.20 built, deployed, and verified end-to-end on the real VM, all three regression cases passing:**

```
Test 1: "explain me how actually scalability work in real life games..."
        -> intent_action=new_investigation (not "explain"), full question phrasing
           preserved in the master-level reasoning ("...scalability for millions of
           concurrent users"), real substantive synthesized answer.
Test 2: "yes" with no pending_action -> intent_action=no_action, instant (no LLM
        call at all -- confirmed by latency: near-zero vs. minutes for every real
        investigation), "nothing pending" reply.
Test 3: "What do we know about Load Balancing?" (never investigated) ->
        intent_action=explain, offers to investigate, sets pending_action,
        current_entity correctly set (root cause C fixed) -> "yes" ->
        intent_action=new_investigation, pending_action executed for real,
        full substantive answer about load balancing.
```

Implementation matches the design exactly: `PendingAction` + `SessionState.pending_action` (`backend/api/session.py`), additive Postgres migration (`backend/api/db.py` — `alter table ... add column if not exists`, since `CREATE TABLE IF NOT EXISTS` has no effect on an already-provisioned database), the deterministic `_classify_confirmation` running before `parse_intent` on every turn, `_execute_pending_action` reusing the existing handlers via a synthetic `Intent` (no duplicated logic), `handle_explain` fixed (sets `current_entity`, offers instead of dead-ending), `"explain"`'s prompt boundary tightened, `"no_action"` added. One real infrastructure snag hit during testing, unrelated to the fix itself: Groq's daily token cap was fully exhausted mid-test, correctly falling through to Gemini every time — slower, not broken; confirms the existing fallback chain (§ established earlier this project) still works under real exhaustion, not just in theory.

**A second, related bug surfaced live during testing — not yet fixed, diagnosed precisely, not guessed at.** After a real `investigate_deeper` produced a rich synthesized answer listing "Authorization" as one of several payment-process phases (prose only — the master-level decision chose to answer directly rather than decompose into it), the user zoomed into "Authorization" and got "no further sub-components yet." Checked Neo4j directly rather than assuming why:

```
Authorization node: id=d27cd90e..., scope=None, created_at=2026-08-28 (a PRIOR day, unrelated investigation)
Edges: decomposes_into FROM 'Card Payment', 'Card payment flow', 'payment', 'Payments' (4 different, differently-cased/named parents, all pointing INTO Authorization)
Zero outgoing edges from Authorization itself.
```

Refined diagnosis, corrected from the initial hypothesis: "Authorization" is not missing — it's a real, legitimately-shared node from **entirely unrelated prior sessions**, reused via `find_or_create_entity`'s global exact-name match (no `scope_hint` — `zoom_in` only passes one if the message names a domain explicitly). It genuinely has zero children, so "no sub-components yet" is *factually true for that specific node* — but it is a foreign node, disconnected from the user's own current "Payment Process" investigation entirely. The rich content the user's own `investigate_deeper` answer had just produced about Authorization was never captured as graph structure anywhere, because two mechanisms each assumed the other owned it: the decompose branch didn't fire (the model chose one synthesized answer instead of decomposing into Authorization as its own sub-question), and `extract_relations`' own prompt explicitly tells it to *skip* compositional relationships ("X is a phase/part of Y") on the assumption decompose handles those. The compositional fact "Payment Process has Authorization as a phase" fell through the gap between both mechanisms and was never written down by either.

**Separately, a real design gap the user named directly: `zoom_in`'s dead-end message is the same shape of problem §0.20 just fixed for `explain`, not yet extended to it.** `handle_zoom_in`'s "No further sub-components yet — try 'go deeper into X'..." is the pre-§0.20 pattern: report a dead end and require the user to type the exact right follow-up, rather than offering a `PendingAction`. Proposed fix, not yet built: extend the *already-proven* mechanism — `zoom_in` still never investigates on its own (that stays a deliberate, load-bearing design choice, unchanged), but its dead-end reply should set a `pending_action` offering `investigate_deeper`, the same way `handle_explain` now does, so a plain "yes" works instead of requiring the literal phrase "go deeper into X."

Neither of these two follow-on findings is fixed yet — reported precisely, not guessed at, awaiting direction on priority.

## 0.21 Subject vs. Entity — the original vocabulary, reconciled with Node/kind (2026-08-30)

**[THEORY], design only.** The user restated the project's own original abstraction vocabulary from
memory, unprompted, months into building on top of it — Abstraction = a boundary around what's
currently being studied; **Subject** (2D abstraction) = a boundary drawn around domains only, just
named ("Quantum Mechanics" circling Physics/CS/Information Theory); **Entity** (3D abstraction) = a
boundary around domains *plus the specific question(s) it's trying to solve* (a company, project,
org — understood as a solution, not just a label, per §6 "Entities as Solutions" — PayPal solves
"how do people transact online without physical exchange," Stripe solves a different problem
entirely). This is `docs/SystemDesign.md` §3-6, verbatim, not a new idea — worth stating plainly
before anything else in this section: **the user re-derived their own original spec from memory and
it matched exactly**, independent confirmation that the theory itself was never the problem.

**The actual finding: this is the same conclusion §0.6-§0.16 already reached, from a completely
different direction, under different names.** That arc spent eleven sections stress-testing
`Node`/`Relation` against real worked examples (smartphone pipeline, electric grid, PayPal, the
adversarial "Payment" case) and independently concluded: one primitive (`Node`), `kind` as a
question-relative annotation rather than an intrinsic property, and the same node interpreted
differently depending on which question is asking (§0.8-§0.9). **Subject and Entity are not new
`kind` values needing new machinery — they're the two `kind` values that were missing from the list,
and they resolve a specific gap the earlier arc left unnamed:**

- **Subject** = `Node{kind: "subject"}` — a boundary whose only claim is "these domains belong
  together for the purpose of this investigation." No question it specifically solves; it's a
  region, not a solution.
- **Entity** = `Node{kind: "entity"}` — the same boundary shape, but with at least one attached
  `Claim`/relation that names the specific question/problem it exists to solve (§0.6's "Entities as
  Solutions" — the query that already runs today, "what questions does this thing answer," is the
  literal test for whether something has earned Entity rather than Subject).
- Both are ordinary `Node`s under §0.8's collapse — the distinction lives in the `kind` annotation
  and in what's attached (a solved-question claim), not in a separate schema or a separate primitive.
  This is consistent with, not a change to, §0.16's frozen field list (`id`, `name`, `scope`,
  `description`, `investigation_status`) — `kind` was already excluded from that list on purpose,
  precisely because it's View/Question-layer, not a Node property (§0.16's "fails" table).

**"AI agent power to build boundaries and name them" is a real, specific, nameable next capability
— not a vague ambition.** It's the concrete act this project has been calling, at different points,
"the Node schema implementation" (§0.16's punch list) and "kind as a View-layer annotation" (§0.9):
a decision, distinct from `decompose`/`answer`/`boundary_hit`, where the agent looks at what it's
currently holding — a cluster of domains, or a cluster of domains plus a specific problem it's
solving — and deliberately draws and *names* that boundary, choosing Subject or Entity by the same
test named above (is there a specific question this boundary is understood to solve, yes or no).
This is genuinely new relative to today's live code: `abstraction_name` today is a string the intent
classifier picks incidentally, attached via one `contains` edge — never a deliberate act the agent
reasons about and could get right or wrong. Making it a real decision is what turns "the graph has an
abstraction node called X" into "the agent decided X deserves to be a named boundary, and decided
whether it's a Subject or an Entity, and could explain why."

**"Zoom in = going inside the node to see its own internal graph" is not a new requirement either —
it's §0.6.1/§0.6.2's tile metaphor and §0.15's View semantics, confirmed correct by being re-derived
independently.** Zooming into PayPal should open PayPal's own bounded neighborhood — the domains and
sub-entities inside its boundary — not return a one-line "known components" summary. That's exactly
what a View (§0.15) reading a bounded tile (§0.6.2) of the World Model already means; nothing about
this section changes that design, it just reconfirms it from the Subject/Entity angle. **A concrete
gap this cross-check surfaces, worth stating precisely:** `handle_zoom_in`'s current one-line summary
and `handle_compare`'s still-unfixed node-persisting behavior (§0.15's own named example, not yet
built) are the two places where live code still lags this already-designed View model — not because
the design is wrong, but because the View/Investigation/World-Model split (§0.15) was designed and
never implemented end-to-end.

**Dimensions/Perspective, separately — genuinely new relative to the original system, and correctly
so.** The user is right that the system as originally conceived had no working Scale/Perspective/Time
mechanism; `dimension_name`/`dimension_description` (and composed multi-lens steering via
`Question.dimensions`) are real, `[VERIFIED]` additions built after the original spec, and they slot
into this reconciliation cleanly: a dimension is what a **View** (§0.15) applies to a Subject or
Entity to generate a question, exactly matching SystemDesign.md §12's `Abstraction + Dimension ->
Question` rule — dimensions were never meant to be Nodes or boundaries themselves, and they aren't
one here either.

**What this section does not do, on purpose, matching this document's own standing discipline:** it
does not add `subject`/`entity` to any enum in code, does not change `find_or_create_entity` or
`create_relationship`, and does not implement the boundary-naming decision. Per the user's own
explicit choice this round (documentation first, feature second), this section's job is only to
confirm the vocabularies are the same thing and name the concrete next build item precisely enough
that it doesn't need re-deriving from scratch next session.

**Next session starts here, now with two independently-confirmed reasons to do it in this order**
(the original §0.16 punch list, unchanged, just re-affirmed): scope-hint extraction reliability
(§0.14's still-open gap) → the Node schema, now including `kind ∈ {subject, entity, process,
abstraction, ...}` as a View-layer annotation with Subject/Entity's solved-question test as the
concrete rule for choosing between them → a real boundary-naming decision in the agent's decision
step, alongside `decompose`/`answer`/`boundary_hit` → `handle_compare`/`handle_zoom_in` rebuilt as
Views per §0.15, rather than persisting or dead-ending. The network-aware renderer (§0.15's ordering)
stays explicitly last.

## 0.22 Sibling relations — from a real literature survey to a live-verified fix (2026-08-30)

**[VERIFIED], real code shipped this pass.** Prompted by a concrete user observation: the graph is
"always trees" — e.g. investigating a money transaction surfaces Client, Client Bank, Merchant Bank,
Merchant, but the only edges are `decomposes_into` from the parent down to each; nothing ever
connects Client Bank directly to Merchant Bank, even though the real-world relationship (forwards
funds to) is exactly the kind of thing worth a graph edge. Per the user's own new standing rule
("we need real research for every decision we make from now on"), a literature survey ran before any
code changed — findings and citations below, then the fix, then live verification.

**Root cause, confirmed at the code level before researching anything:** `_finish()`
(`backend/agents/ground_agent.py`) called `extract_relations(self.question.entity_name, result.answer)`
— always ONE named entity plus that same entity's own answer text. Every sibling discovered under the
same parent via `decompose`'s `discovered_entity_name` was invisible to this call; it never saw the
sibling set at all, only ever the current entity's own framing.

**Literature survey findings (a full research pass, condensed):**
- This is an established task with a name — **document-level relation extraction** (DocRED,
  Yao et al., ACL 2019, arXiv:1906.06127) — built specifically because sentence/entity-local
  extraction misses facts spanning multiple entities. Every serious architecture in this space
  (span-based joint extraction, table-filling, OpenIE) separates "what is the entity set" from
  "score all pairs in that set" into two distinct passes — never "radiate from one named entity."
- The bias this project hit is real and independently documented from four angles: entity-salience/
  primacy-bias literature (models over-weight the earliest/topic-framed entity), GraphRAG's own
  published failure note that its "default prompt... can lead to attention spread... causing the
  model to miss entities" and that LLM-built KGs measurably show hub-and-spoke, power-law degree
  distributions, a formal causal treatment of entity bias (Wang, Mo et al., EMNLP Findings 2023,
  arXiv:2305.14695), and NAACL 2025 Findings' *Entity Pair-guided Relation Summarization and
  Retrieval* (aclanthology.org/2025.findings-naacl.224), which fixed the identical LLM DocRE failure
  by explicitly enumerating candidate entity pairs rather than free-extracting from one topic framing.
- Fetched and read the actual production prompts of **Microsoft GraphRAG** and **LightRAG**
  (`graphrag/prompts/index/extract_graph.py`; `lightrag/prompt.py`) — both use the exact same
  two-pass shape: "(1) identify all entities, (2) from the entities identified in step 1, identify
  all pairs... clearly related." GraphRAG's own worked example extracts direct edges between three
  co-hostages with no shared "topic" entity at all — proof this pattern produces real sibling edges,
  not just theory.
- **Graphusion** (arXiv:2410.17600) names this project's exact failure as its own motivation
  ("existing approaches... miss a fusion process to combine... knowledge in a global KG") and fixes
  it with a dedicated cross-entity fusion pass, measuring +9.2% on sub-graph completion — the
  literature-backed fallback if recall is still too low after this pass's fix.
- Procedural/workflow text extraction (ProPara, NAACL 2018; arXiv:2407.18540's LLM prompting study,
  +8 F1 over prior SOTA) independently confirms the same two-pass discipline generalizes to
  sequential/causal text specifically — relevant to the Client→Bank→Bank→Merchant case named above.

**The fix, matching the literature's two-pass shape with data the agent already has:** `decompose`
already names each newly-discovered sibling via `discovered_entity_name` as it goes. `_investigate_loop`
now accumulates every one of those into `discovered_entity_names` across the loop, and `_finish` passes
it to `extract_relations` as `sibling_entity_names`. `extract_relations`'s prompt (`backend/questions/
relation_extraction.py`) was rewritten to explicitly list "entities discovered together" and instruct
the model to check every pair among them, not just pairs involving the one named "entity under
discussion" — the same instruction GraphRAG's and LightRAG's own prompts give, adapted to this
project's incremental (one-sub-question-at-a-time) decompose loop rather than a batch document pass.

**Live-verified** (`scripts/verify_sibling_relations.py`, real provider call, no mocking): given text
describing a client paying a merchant through two banks, `extract_relations("Client", text,
sibling_entity_names=["Client Bank", "Merchant Bank", "Merchant"])` returned `'Client Bank'
-[forwards_funds_to]-> 'Merchant Bank'` and `'Merchant Bank' -[credits]-> 'Merchant'` — genuine
sibling-to-sibling edges, neither anchored on "Client." A useful side effect observed live: passing
the sibling names also canonicalizes the model's own entity naming to match the already-known set
("Client Bank" instead of a freshly-invented "Client's bank"), which should reduce spurious near-
duplicate entities downstream in `resolve_entity` too, though that wasn't this pass's target.

**What this does NOT do, on purpose:** it does not add a second, separate "identify the entity set"
LLM call (GraphRAG's full two-call shape) — this project's decompose loop already produces that set
incrementally as a side effect, so reusing it is the smaller, already-grounded change. It does not
touch visualization. **Named, deferred next step (the user's "semantic boxes" idea, also surveyed this
pass):** Cytoscape.js **compound nodes** (already the project's chosen graph library, §1) are the
literature-confirmed standard mechanism for a labeled bounding region around a non-overlapping node
subset; for a node governed by two *overlapping* actor scopes at once (a case this project's own
`R = f(A,B,Q)` principle, §0.1/§0.9, already predicts will occur), compound nodes structurally can't
express it (confirmed: strict single-parent containment), and **`cytoscape.js-bubblesets`** — a
maintained adapter of Collins et al.'s BubbleSets (TVCG 2009), empirically outperformed by its
KelpFusion successor (TVCG 2013) on accuracy/completion-time — is the literature-backed answer for
that case. Neither is implemented yet; this pass's scope was the extraction fix only.

## 0.23 Graph Spaces — a research pass on multi-view projection and scoped subgraphs (2026-08-30)

**[THEORY], design only — explicitly not implemented this pass, per the user's own instruction.**
Forced by a real live bug, not a hypothetical: §0.22's box feature nested `Mastercard` inside `PayPal`'s
compound box purely because `PayPal -[USES]-> Mastercard` was AN edge out of a boxed entity — fixed at
the rendering level (box assignment now checks whether an edge's `relationship_type` is actually
compositional before treating it as containment; see the fix entry in `docs/Memory.md`). The user's
response named the principle underneath that bug precisely, and asked for a dedicated design pass
before building further: **"investigation may discover knowledge; it may not determine the topology of
that knowledge."** A box is a navigational boundary, not a claim about what's inside it.

**The single biggest finding of this pass, stated up front because it changes the shape of everything
below: "Graph Space" is not a new primitive needing new schema or storage.** It is what already falls
out of two things this project already has and just finished correctly wiring together — `boundary_kind`
(§0.21, marking which Nodes are bounded regions) and the compositional-vs-interactional distinction
on `relationship_type` (§0.17/§0.18, now actually enforced at render time, §0.22's fix). A "Graph Space"
is a Node with `boundary_kind` set, together with the subgraph reachable from it by following purely
*compositional* edges (`decomposes_into`, `contains`, `is_part_of`, `component_of`, `consists_of`) —
computed on read, not stored as its own object. This settles the question the user's proposal left open
(is Graph Space a fourth layer between World Model and View?): **no — it's a View-layer concept**,
exactly where §0.15 already put "a particular way of reading/arranging existing World Model content."
Nothing here requires a new field on `GraphNode`/`Relationship`, a new Neo4j label, or a new endpoint —
the data already fully supports it once the renderer respects the distinction, which it now does.

**Research grounding for the four questions the user posed, real citations, not first-principles guessing:**

- **What exactly is a Graph Space?** Confirmed against **modular ontology architecture** — a real,
  established pattern (the "root-thematic-foundations" pattern: a root module imports thematic modules,
  which may import secondary thematic modules in turn) where "ontology modules are meant to identify
  conceptually coherent subparts of the domain," and "domain clusters... enable topic-centered subgraph
  extraction, where selecting a cluster produces a self-contained graph with its own node types, edge
  types, and schema." This is the exact shape of "Payment Space containing Payment Stages Space
  containing Authorization" — a well-studied ontology-engineering pattern (modules/imports), not a novel
  invention, and it names the mechanism precisely: a Graph Space is a *module boundary* over the same
  underlying graph, not a copy or a separate schema.
- **Can Graph Spaces overlap?** Yes, confirmed against real prior art on **overlapping group membership
  in graph visualization** — Overlapping Stochastic Block Models are the standard formal model for "a
  node belongs to group 1 only, group 2 only, or both simultaneously," and hull/BubbleSets-style
  rendering (already surveyed in §0.22, Collins et al. TVCG 2009 / KelpFusion TVCG 2013) is the
  established visual technique for exactly this case — real-world graphs routinely have nodes with
  multiple group memberships, this isn't an edge case being invented here. **Nothing prevents this in the
  World Model today** — two different bounded entities can each have a compositional edge to the same
  node. What CANNOT currently do this is the *renderer*: Cytoscape's native compound nodes enforce
  strict single-parent containment (confirmed, §0.22), so §0.22's `parentOf` map is deliberately
  first-come-first-served — a real, named, temporary rendering limitation, not a design decision that
  overlap shouldn't exist. `cytoscape.js-bubblesets` remains the literature-backed fix, still deferred,
  now for a precisely named reason instead of a vague "maybe later."
- **Can a relation cross spaces?** Yes — not a research question anymore, a **live-verified fact**: the
  same PayPal/Mastercard graph that exposed the bug, after the fix, shows `PayPal -[USES]-> Mastercard`
  rendering as a real, visible edge crossing from PayPal's compound box to Mastercard sitting in Payment
  System's box. Confirmed via §0.15's own vocabulary: a Relation belongs to the World Model regardless of
  which Graph Space(s) its endpoints happen to render inside — the View layer's box-drawing must never be
  allowed to constrain what the World Model is permitted to say connects to what.
- **What does "open node" actually mean?** Research into **multiple-view/multiform visualization**
  (an established pattern: one underlying dataset, several coordinated views, each suited to a different
  task — "no single projection method yields universally optimal layouts," which is the formal version
  of the user's "same world, different projection" argument) surfaces that this project's current
  `handle_zoom_in`/`computeViewport` conflates two genuinely different operations under one name:
  - **Neighborhood focus** (what exists today): show a 1-hop window centered on a node, still situated
    within whatever context it was found in — `computeViewport`'s existing parent/sibling/children logic.
  - **Enter space** (not built): re-root the rendered viewport at that node's own compositional subgraph,
    treating it as the new top-level Graph Space being browsed — the ontology-engineering "import a
    module" / "topic-centered subgraph extraction" operation named above, applied to navigation instead
    of just schema. Clicking `Payment Stages` should feel like walking through a doorway into its own
    region, not like zooming a camera slightly.

**What this means for the "different types of graphs" half of the proposal (flow/causal/dependency/
timeline/state-transition views over the same World Model):** the multiple-view research above confirms
this is the right target shape, not an over-engineered one — but it surfaces a real, concrete gap worth
naming rather than glossing over: most `relationship_type` values in this graph today (`decomposes_into`,
`uses`, `routes_to`, ...) don't carry enough structured information to *auto-derive* a flow or causal
ordering among several children of one Graph Space (which comes first? what triggers what?). Producing a
real "flow view" or "causal view" projection would need either (a) new structured metadata on certain
relations (a sequence/ordering hint, a causal-vs-associative flag) captured at extraction time, or (b) a
dedicated LLM reasoning pass over an existing Graph Space's relations to infer that projection on demand.
Neither is decided here — named as the concrete open question the next design (or research) pass on this
specific piece should start from, not guessed at now.

**What this pass explicitly does NOT do, on the user's own instruction:** no code, no new schema, no new
endpoint, no `intent` type for "enter space" vs "zoom in." The next concrete, smallest-real-slice step, if
and when the user wants to move to implementation, is narrow and already scoped by the above: distinguish
"focus" from "enter space" as two real, distinct navigation actions in the intent layer and
`computeViewport`, before touching multi-projection rendering or overlap — the same "smallest verifiable
slice first" discipline §0.17.6 already used for `relationship_type` itself.

## 0.24 Focus vs. Enter Space — §0.23's smallest slice, built and live-verified (2026-08-30)

**[VERIFIED], implemented and tested live** — full detail and the exact acceptance-matrix results are in
`docs/Memory.md`'s entry of the same name; this is the short pointer §0.23 itself promised. Summary: two
new `Intent` actions, `enter_space` (re-roots the rendered view at an entity's own compositional
subgraph, dropping surrounding context) and `exit_space` (pops back), clearly distinguished from
`zoom_in` (which keeps surrounding context — unchanged). `SessionState` gained `current_space`/
`space_history`; `chat.html` gained `computeSpaceViewport`, a genuinely separate computation from
focus-mode `computeViewport` that finds "inside the space" via compositional-edge BFS and surfaces every
non-compositional edge touching that set as visible cross-space context, never folded into containment.

Live-verified against the user's own acceptance matrix on a real investigation: entering `payment`
produced a compound box with 13 children plus a genuinely NESTED sub-box (`Authorization`, itself boxing
its own three children from earlier-accumulated Neo4j history) — confirming nesting needs no special
code, it falls out of the same per-node logic recursively. Real interaction edges (`ROUTES_TO`,
`TRANSFERS_FUNDS_TO`, `ROUTES_DATA_BETWEEN`, `QUERIES`, `EVALUATES`, `EXPRESS_IN`) all rendered as
visible, non-swallowed edges crossing the box boundary. `go back` correctly returned "Back to the top
level." `Enter XACML` (a leaf reachable only via a non-compositional relation) correctly declined without
mutating any state — exactly the leaf row of the acceptance matrix.

## 0.25 Relation Semantics — grounding "what a relationship means" in real prior art (2026-08-30)

**[THEORY], design + one small implemented slice.** §0.24 shipped; the user's own framing for what comes
next: "First make [entity → relation → evidence → world model → view] reliable... then a learning model
becomes much more interesting." Explicitly NOT jumping to prerequisites/mastery/learning paths yet, per
that same instruction — this section is scoped to relation semantics alone.

**The forcing question, stated precisely:** this project already has `relationship_type` as a free
string, a small synonym-normalization table (`normalize_relationship_type`), and — as of §0.22's box fix
— a hardcoded "is this compositional" set duplicated in THREE places (`chat.html`'s box logic,
`chat.html`'s space-viewport logic, `app.py`'s `handle_enter_space`), with a code comment on the newest
copy admitting "must stay in sync with that JS copy." That duplication is itself the concrete bug this
section exists to prevent from recurring — a single canonical relation registry, not three hand-maintained
lists, is the actual near-term deliverable, not a speculative taxonomy exercise.

**Research grounding, not an invented list:**
- **The "composition" family is not one thing — real linguistics research already subdivides it.**
  Winston, Chaffin & Herrmann's 1987 taxonomy of part-whole relations (*Cognitive Science*,
  foundational enough that it shaped WordNet's own part-of treatment) identifies six distinct meronymic
  subtypes — component-integral object ("pedal-bike"), member-collection ("ship-fleet"), portion-mass
  ("slice-pie"), stuff-object ("steel-car"), feature-activity ("paying-shopping"), place-area
  ("Everglades-Florida") — and, critically, demonstrates that meronymy is **not uniformly transitive**
  across these subtypes (mixing subtypes in a chain can produce invalid "part of" syllogisms). Concrete
  implication for this project: the current single `COMPOSITION`/"is this compositional" bucket used for
  box-nesting is a **deliberate simplification**, not an oversight — box-nesting doesn't currently need
  transitivity reasoning, so collapsing all six subtypes into one bucket is fine for now, but a future
  pass that wants to reason ACROSS nested compositional edges (e.g. "is X ultimately part of Y three
  levels up?") must not assume that's always valid just because every edge along the way says
  `decomposes_into`.
- **"Does this relation type behave in a predictable way" already has an established, formal answer:**
  OWL/RDF property characteristics — **transitive**, **symmetric**, **inverse-of**, **functional**,
  **(ir)reflexive** (W3C OWL Reference). This is a better-grounded vocabulary than inventing bespoke
  "does this create ordering / imply inheritance" flags per relation: `precedes`/`follows` are a
  transitive, mutually-inverse pair; `depends_on` is transitive; `connects_to` is plausibly symmetric;
  `uses`/`routes_to` are neither. Declaring these as real OWL-style characteristics, not prose
  descriptions, is what lets code (and later, real traversal/inference — §0.29 in the user's own proposed
  sequence) ask a relation type "are you transitive?" instead of hardcoding per-type special cases.
- **DOLCE's relation split (immediate-relation vs. mediated-relation — a relation that holds directly vs.
  one that composes other relations)** is real prior art for a DEEPER version of this problem (a relation
  that is itself built from other relations) but is not needed for the near-term slice below — named so
  it isn't rediscovered as a surprise later, not adopted now.

**Concrete design: one canonical relation-type registry, replacing three hardcoded lists.** A single
table, keyed by canonical `relationship_type`, carrying:
```
family:      composition | causal | temporal | dependency | interaction | classification
transitive:  bool   (OWL-grounded, not guessed)
symmetric:   bool
inverse_of:  Optional[str]
```
`family == composition` is exactly today's "is this compositional" check (§0.22/§0.24's box/space logic),
now with ONE source of truth instead of three copies. `temporal` entries (`precedes`/`follows`, both
`transitive=True`, mutually `inverse_of`) are seeded now specifically because §0.23 named "most
relationship_type values don't carry enough structure to auto-derive a flow ordering" as the concrete
blocker for a future flow/causal View projection (§0.23's own deferred multi-projection idea, and the
user's proposed §0.27) — this doesn't build that projection, it just stops the prerequisite data model
gap from still being true when that pass starts.

**Relation evidence — reopening §0.5's old open question with the benefit of a now-real Claim/Source
model.** §0.5 asked "does a relationship need its own provenance" and deferred it; §0.15 said the answer
gets cleaner once View exists (it now does, §0.15/§0.23). Checked against the actual live code, not
assumed: `attach_claim` (backend/graph/interface.py) attaches a Claim to a **Question**, never to a
**Relation** — a relationship written via `create_relationship` (whether from decompose or from
`extract_relations`) has zero provenance of its own today. That is a real, precise, now-named gap:
`PayPal -[USES]-> Mastercard` currently carries no record of which source text or evidence produced it,
unlike a ground-level answer's Claims. Not fixed this pass — named precisely so it's a scoped future
slice (attach the `justification` field `extract_relations` already produces — currently only printed to
a log line, §0.22 — to the created Relationship as real provenance) rather than a vague aspiration.

**Confidence stays out of geometry, per the user's own explicit instruction** ("don't do thicker edge =
more true unless you explicitly define that visualization") — agreed and not contested; nothing in this
pass proposes confidence-driven rendering.

**What this pass DOES implement** (the smallest real slice, consolidating a documented duplication risk
rather than adding new speculative machinery): `backend/questions/relation_types.py`, a single
`RELATION_TYPES` registry per the shape above, seeded with the compositional set already in use plus a
handful of temporal/causal/dependency examples; `relation_extraction.py`'s compositional-ban check and
`app.py`'s `_COMPOSITIONAL_TYPES`/`handle_enter_space` now both call the same registry instead of keeping
separate hardcoded sets; the registry's family is exposed per-edge in `/graph`'s payload so `chat.html`'s
box and space-viewport logic can check `edge.family === "composition"` instead of maintaining its own
third copy of the list. `transitive`/`symmetric`/`inverse_of` are recorded in the registry now (so the
data model doesn't need another migration when §0.27+ actually uses them) but nothing in this pass
consumes them yet — declared, not yet acted on, matching this document's own "don't build the mechanism
before something real needs it" discipline.

## 0.26 Relations become knowledge objects — evidence attached additively, no migration (2026-08-30)

**[VERIFIED], implemented and live-tested against real Neo4j.** Full detail, citations, and the exact
verification output are in `docs/Memory.md`'s entry of the same name; this is the pointer. Summary:
relation identity — (source, relationship_type, target) — turned out to already be correct
(`create_relationship`'s own `MERGE` key), confirmed by reading the code rather than assumed; what was
missing was evidence, since neither call site in `ground_agent.py` ever persisted the `justification`
text it was already computing. Since a Neo4j relationship can't be the source/target of another edge,
full reification (making every relationship its own node, per this project's own older §0.6-§0.9
conclusion) was rejected FOR NOW in favor of an additive side-channel: `attach_relation_claim`
(`backend/graph/interface.py`) attaches an ordinary `Claim` node via a new `HAS_RELATION_CLAIM` edge
carrying `relationship_type`/`target_id`/`stance`, never touching the native `RELATES_TO` edge —
zero regression risk to any traversal function §0.17-§0.25 already verified live. `get_relation_confidence`
is a stated-simple heuristic (0.5 ± per supporting/contradicting claim, clamped), not a fabricated
rigor. Live-verified: the native edge count never duplicates no matter how many claims attach; confidence
arithmetic matched the formula exactly; a never-evidenced relation reports `confidence: None`, not a
default. Named, not resolved: decompose's own structural relations get evidence too now (the agent's own
reasoning, at a lower baseline confidence than text-sourced extraction claims) rather than either
fabricating citations or leaving the system's structural backbone without any provenance at all.

## 0.27 Semantic Graph Projections — one world model, multiple relation-family views (2026-08-30)

**[VERIFIED], implemented and live-tested (backend directly, frontend live in Chrome).** Full detail and the
exact verification output are in `docs/Memory.md`'s entry of the same name; this is the pointer. Summary: a
new `set_projection` intent lets the user switch which relation family the CURRENT view is filtered to
(`structure`/`flow`/`causal`/`dependency`/`network`/`all`), answering the user's own framing question — "who
decides which relations belong in a projection? Not the LLM" — with §0.25's `PROJECTION_FAMILIES` registry:
a deterministic name→family table, never an LLM re-reasoning about the subject. `handle_set_projection`
(`backend/api/app.py`) makes zero Neo4j writes and zero LLM calls; it only re-filters `session.to_payload()`'s
already-known edges by their `family` field, so the hard invariant (`G_after == G_before`, world model
literally unchanged across a view switch) holds by construction, not by convention — a relation family with
zero matches produces an honest gap message ("the model doesn't currently contain any X relationships for
what's in view... try investigating further"), never a silent re-investigation. A real consistency bug was
caught during live verification and fixed before shipping: the backend's gap-check originally scanned the
whole accumulated graph while the frontend intersected the projection with the tight 1-hop focus
neighborhood, so a reply could name a relationship that then failed to render. Fixed by giving both layers
the same scope rule — the entered space's own compositional-BFS-reachable subgraph if `current_space` is
set (`_space_reachable_ids` in `app.py`, mirroring `computeSpaceViewport` in `chat.html`), else the whole
known graph — proven live in both Python (`scripts/verify_projections.py`) and the browser (direct
`renderGraph`/`applyProjection` calls) to now agree exactly, including the "Cross-space relation still
accessible/hidden" case from the user's own acceptance matrix.

## 0.28 Topology-preserving extraction — the renderer was never the bug (2026-08-30)

**[VERIFIED against real Neo4j], root-caused and fixed with a single-sentence prompt change.** Full detail,
the synthetic 10-topology test matrix, and the three live end-to-end investigation traces are in
`docs/Memory.md`'s entry of the same name; this is the pointer. Summary: the user's suspicion that "the
system keeps turning everything back into a tree" was tested at every layer separately rather than patched
on sight. A synthetic 10-topology corpus (tree/network/DAG/cycle/nested-box/cross-space/workflow-with-
retry-cycle/nested-workflow/hub/mesh) fed directly into `renderGraph` with no LLM/Neo4j/intent-parser in the
loop passed 10/10 — the box-vs-edge, composition-vs-interaction rendering logic §0.22 built is genuinely
topology-agnostic. `computeViewport`'s focus/zoom windowing (the code path real navigation actually uses)
was then shown, also synthetically, to silently drop real edges more than one hop from the focused node
regardless of the true topology (a cycle's back-edge, 5/8 of a mesh's edges plus a whole node) — a real,
separate, distinct limitation, noted but explicitly not fixed this pass per the user's own sequencing.

The real end-to-end pipeline test (three fresh Chrome sessions, natural-language questions only, real
LLM investigations, no manual graph injection) found the actual bug one layer earlier than the renderer:
a tree-shaped question ("how is a computer organized") correctly produced a tree; a network-shaped question
("how do PayPal/Mastercard/Visa/banks/merchants interact") correctly produced a genuine network — regression-
testing the exact §0.22 PayPal/Mastercard containment bug live, with fresh LLM-generated content, and passing
under focus on both the hub node and a leaf node; but a sequence-shaped question ("the complete lifecycle of
an online payment... show where branches converge") produced a flat `decomposes_into` tree with **zero**
temporal edges and two dropped stages (Clearing, Settlement silently merged away), despite the agent's own
reasoning text explicitly narrating the correct order. Root cause, found by reading the actual extraction
code rather than the renderer: `extract_relations`'s system prompt (`backend/questions/relation_extraction.py`)
told the model to look for "actor, causal, or functional" relationships and enumerated verbs like
detects/causes/enables/depends on/routes to/regulates — but never once mentioned temporal/sequential
relationships as a category, even though `precedes`/`follows` already exist as real, registered TEMPORAL-family
members of §0.25's own `RELATION_TYPES`. `GroundDecision`'s decompose loop was a red herring: it structurally
can express a relationship_type for a new-child-to-parent edge, but has no field at all for sibling-to-sibling
relations (each decompose call only ever sees one parent-child pair, one sub-question at a time, by design) —
so any cross-sibling ordering could only ever come from `extract_relations`, and that call was simply never
told sequence was in scope.

The fix touched exactly one thing: `extract_relations`'s system prompt gained a paragraph naming
temporal/sequential/process relationships (precedes/follows, branch/convergence) as explicitly in scope, with
worked examples. Nothing else — not decompose, not the relation registry, not box assignment, not the
renderer, not projections — was touched, per the user's own explicit constraint, so a topology change afterward
could be attributed to this one variable. Re-run live (fresh Chrome session, identical question): confirmed by
querying Neo4j directly (`scripts/verify_test3_extraction.py`, bypassing the LLM and the in-memory session
mirror entirely) that a genuine `PRECEDES` chain — Risk checks → Authorization → Payment Capture → Clearing —
now exists where zero temporal edges existed before. The investigation didn't reach Settlement or a final
successful UI render this same run only because Groq's daily token quota, Gemini's daily free-tier request
cap, and Cerebras's billing all became exhausted simultaneously mid-run (an external operational constraint,
not a code defect) — a full end-to-end UI observation is the natural follow-up once quota resets.

## 0.29 Abstraction levels — a model-validation pass, no new schema (2026-08-30)

**[RESEARCH CONCLUSION — design-only, no code].** Full detail and the empirical trace are in
`docs/Memory.md`'s entry of the same name; this is the pointer. Prompted by §0.28's own closing question
("investigation discovers entities → relations give them semantics → relation families determine
topology → topology determines representation... how does an investigator move through that graph without
losing the topology that makes it meaningful?"), this pass asked one precise question before writing any
code: **can one entity have different valid relational structures at different abstraction levels, while
remaining the same entity in one world model** — and if so, does expressing that need a new primitive?

> **Discovery.AI does not store different graphs for different abstraction levels. It stores one world
> model; scope selects which compositional region is being examined, projection selects which relation
> families are emphasized, and topology emerges from the resulting subgraph.**

The answer, checked against the actual code and a live empirical trace rather than assumed: **no new schema
is required.** Eight conclusions, framed as findings about the *current* model rather than universal claims
(kept falsifiable on purpose):

1. **Abstraction is currently represented through scope, within this model** — not a universal claim that
   abstraction *is* scope in general. `Node.kind` (`abstraction`/`entity`) is a binary tag, not a scale;
   `current_space` selects a compositional-reachability closure. No third, independent "abstraction level"
   field exists or is needed for what's been observed so far.
2. **Relationship families are independent of abstraction/scope** — proven, not assumed: the real §0.28 Test
   3 investigation already has `Authorization` carrying coarse `PRECEDES`/`CAN_DECLINE` relations to its
   siblings (Risk checks, Payment Capture) alongside `QUERIES`/`EVALUATES`/`EXPRESS` interaction relations
   among its own decomposed children (Authorization Enforcement/Engine/Policies, XACML, Rego) — same entity,
   two families, zero duplication, discovered by the existing pipeline with no special-casing.
3. **World Model vs. View remains strict**: nodes/typed relationships/evidence in Neo4j; `current_entity`/
   `current_space`/`current_projection` in session state only. No view operation may mutate the world model —
   the same invariant §0.27 already proved for projections holds here too.
4. **Projection is independent of scope** — already true in running code: `handle_set_projection`
   (`backend/api/app.py`) scopes its match-check to `session.current_space`'s reachable subgraph when one is
   entered, so a space and a projection already compose as two independent settings on one session, not two
   competing graphs.
5. **Entering a space is scope reassignment**, defined concretely as
   `scope(node) = compositional-reachability-closure(node)` (`computeSpaceViewport` in `chat.html`) — one
   operation, not three bundled effects. No new persistent "abstraction level" field was added to represent
   it.
6. **Topology remains derived, not stored**: `topology = f(scope, projection, relationship families)`. Tree,
   DAG, cycle, network, mesh are properties of whatever subgraph is currently exposed, recomputed on demand —
   never a `topology` field attached to a node or graph.
7. **Navigation is an operation, not a data dimension.** Focus/enter/exit/back manipulate the scope pointer
   (with `space_history` as its undo stack, §0.24) — they are verbs over state, not additional World Model
   axes.
8. **No new schema or code was added in this pass.** The remaining known gap — `computeViewport`'s plain
   focus mode is a cruder, less consistent 1-hop scope mechanism than `computeSpaceViewport` (§0.28's own
   documented limitation) — is a navigation/view convergence problem for a future pass, explicitly not
   evidence that the World Model needs another primitive.

**Empirical basis** (`scripts/verify_test3_extraction.py`'s real Neo4j output, replayed through the live
`computeSpaceViewport`/`renderGraph` in Chrome, zero new code, zero LLM calls): entering `Authorization`
against the actual Test 3 graph exposed its own internal interaction graph (`Enforcement -QUERIES->
Engine -EVALUATES-> Policies -EXPRESS-> XACML`) as the space's own structure, while the coarse temporal
chain (`Risk checks -PRECEDES-> Authorization -PRECEDES-> Payment Capture`) remained visible as cross-space
context — from the same nodes and edges, `graph.nodes`/`graph.edges` confirmed byte-identical before and
after the scope switch.

## 0.30 Focus and Enter Space are one operation, not two — a research conclusion, no code (2026-08-30)

**[RESEARCH CONCLUSION — design-only, no code, evidence-verified].** Full detail and the live test traces are
in `docs/Memory.md`'s entry of the same name; this is the pointer. Direct follow-on from §0.28's own
documented limitation (`computeViewport`'s plain focus mode silently drops real structure — a cycle's
back-edge, most of a mesh — depending on which node gets clicked) and §0.29's closing question about
navigation. The question was posed narrowly and falsifiably, exactly as instructed: **are Focus and Enter
Space actually the same semantic operation with different bounds, or genuinely different operations that
happen to look similar** — checked against the real code and live tests, not assumed either way.

**Finding: they are the same operation.** Both `computeViewport`'s focus branch and `computeSpaceViewport`
turn out to be instances of one general primitive:

```
closure(node, maxDepth, familyFilter, direction)
```

with **Enter Space** = `closure(node, ∞, {composition}, forward)` and **Focus** ≈
`closure(node, 1–2, all-families, bidirectional)` — two named parameterizations on the same three axes
(depth, family, direction), not two unrelated algorithms. This falsifies the naive assumption the user
explicitly warned against adopting uncritically ("do not make `computeSpaceViewport()` the answer merely
because it already works") in the opposite direction from expected: the two mechanisms turned out to be
*more* unifiable than assumed, not less — the architecture got simpler after testing, not more complicated.

**Live re-tests of the previously-undocumented cases** (DAG, hub-leaf, nested-workflow under Focus — none of
these had been run under focus mode before, only under whole-graph mode in §0.28) surfaced the sharpest new
evidence: focusing a DAG's root makes its convergence node disappear; focusing the convergence node makes the
root disappear — the same two-branch structure gives a *different, mutually exclusive* partial view depending
on which end gets clicked, despite the underlying graph never changing. One initial prediction in this pass
(that a nested workflow's outer box would vanish entirely under focus) was checked live and found **wrong**
— Focus's parent+sibling rule happened to recover the immediate box because the focused node's direct parent
was richly connected — and corrected before being written up, rather than reported as originally guessed.
Space, entering the same nested node's own compositional parent, was shown to be strictly more complete in
that case (its context step reaches one hop past the compositional boundary; Focus's fixed depth does not) —
but Space isn't available at all for a compositionally-flat topology (`enter_space` explicitly refuses a leaf
with no compositional children), so "just use Space" is not a general fix; Focus's own bounded behavior at
`(small depth, all families)` has to become honest on its own terms.

**The disclosure principle, elevated to an explicit architectural rule:** a viewport is allowed to be
incomplete; it is not allowed to imply completeness when it is bounded. Neither mechanism discloses
truncation today — Space is complete along its one guaranteed dimension (compositional depth) but silently
truncates its own context step at one hop past the boundary; Focus silently truncates at its fixed radius
with no signal either way. For a system whose stated purpose is building an accurate mental model from
evidence, an unmarked missing edge is not a cosmetic gap — a viewer forming a belief from `Risk Checks →
Authorization → Capture` with `Clearing → Settlement` invisible and undisclosed has been taught something
false by omission, not merely shown an incomplete picture.

**Closing shape, no code this pass:**

```
One World Model
       ↓
One General Reachability Primitive: closure(node, maxDepth, familyFilter, direction)
       ↓
┌────────────────────┬─────────────────────┐
│ Focus               │ Enter Space         │
│ bounded depth       │ compositional depth │
│ all families        │ unbounded           │
│ bidirectional        │ forward             │
└────────────────────┴─────────────────────┘
       ↓
Bounded View
       ↓
Explicit Truncation Disclosure
```

No new Node type, no new graph type, no new stored topology field, no duplicate graph — consistent with
§0.29's own standard of not adding a primitive the existing model can already express. §0.31 is scoped as the
natural next pass: design the bounded-reachability contract and disclosure semantics precisely (what a
truncation message says, what "more relations available" means as a UI affordance) *before* touching
`computeViewport`'s implementation — not started yet, per the same one-section-at-a-time discipline every
prior pass in this project has followed.

## 0.31 The bounded-reachability contract — specified and tested, not yet implemented (2026-08-30)

**[SPECIFICATION — validated against a standalone prototype, no production code changed].** Full detail,
the prototype itself, and every test result are in `docs/Memory.md`'s entry of the same name; this is the
pointer. §0.30 concluded that Focus and Enter Space are two parameterizations of one reachability primitive;
this pass wrote that primitive down precisely enough to implement, and tested the spec — not the shipped
app — against the same topology cases that previously failed, before touching `computeViewport` at all.

**The primitive.** `reach(seeds, maxDepth, familyFilter, direction)` performs a multi-source BFS over nodes
only, bounded by depth/family/direction; edge inclusion is then a **separate, final pass**: every edge in the
full graph with both endpoints in the resulting node set is included, not just the edges the traversal
happened to discover. This decoupling is the actual fix for the cycle/mesh edge-drop bug named in §0.28/§0.30
— today's `computeViewport` conflates "how a node was reached" with "which edges exist among what's shown,"
which is exactly why a cycle's back-edge disappeared even when all three of its nodes were visible. Enter
Space and Focus are then two compositions of this one primitive, not two algorithms:

- **Enter Space** = `reach({root}, ∞, {composition}, forward)` for the core, plus
  `reach(core, 1, all-families-except-composition, both)` for context — the family exclusion on the context
  step is required, not incidental: an earlier draft of this exact prototype used an unrestricted `all`
  filter for context and it walked back up through the parent's own composition edge, silently reintroducing
  the outer context §0.24 deliberately drops when entering a space. Caught by testing the prototype, not
  assumed correct, and fixed before being written up here.
- **Focus** = `reach({node}, 1, all, both)` for the core, plus one more forward hop specifically from whatever
  was reached backward (the parent shell) to recover sibling context — the same composition pattern
  `computeViewport`'s existing children/parentEdges/siblingEdges triple already approximates by hand, just
  expressed as two `reach()` calls instead of three ad hoc filters.

**Return shape**, sufficient for both rendering and disclosure: `{nodes, edges, truncatedNodes,
truncatedEdges}`, where truncation is a real, always-computable property — count every edge in the full graph
touching exactly one node currently in view (present on one side, absent on the other). Truncated iff that
count is nonzero. Hidden structure is never represented as ghost nodes or placeholder edges in the graph (that
would risk being mistaken for discovered content); it is metadata the UI turns into a disclosure affordance —
a badge on the specific frontier node that has more beyond it, e.g. "Authorization ⋯+2", not just a generic
page-level counter, so the disclosure is spatially anchored to where the missing structure actually is.

**Tested against the topology matrix, prototype only, before writing any of this into the shipped app:**

| Case | Before (shipped) | After (prototype) |
|---|---|---|
| Cycle, focus on any node | 2/3 edges shown, back-edge silently dropped | **3/3 edges, 0 truncation** — fully recovered by the corrected edge-inclusion rule alone, no depth change needed |
| Mesh, focus on a low-degree node | Node + 5/8 edges silently dropped | Same 4/8 edges shown (bounded depth genuinely can't reach the rest) — but now **honestly reports** 1 hidden node, 3 hidden edges instead of implying completeness |
| DAG, focus on root or sink | The other end (convergence or source) silently vanishes | Same 3/4 nodes shown either way (irreducible under any finite depth) — but now **honestly reports** 1 hidden node, 2 hidden edges every time |
| Nested workflow, enter the inner space | (not previously measured for truncation) | Correctly shows the boundary-crossing context node, correctly excludes the outer parent, and **honestly reports** exactly 2 hidden nodes / 3 hidden edges for what's one hop further out |

The mesh and DAG results are the important negative result, kept rather than smoothed over: **bounded depth
cannot be made to always show everything** — that would defeat the purpose of a bounded, readable view in the
first place, and no clever algorithm changes that. What the contract actually delivers is not completeness,
it's honesty about incompleteness, which is the specific property the user's own principle demanded ("a
viewport is allowed to be incomplete; it is not allowed to imply completeness when it is bounded").

**Focus's existing radius is unchanged** — `maxDepth=1` stays exactly what made Focus readable in the first
place. Nothing about this spec asks Focus to see further; it only asks Focus to (a) include every edge that
genuinely exists among whatever nodes it already shows, and (b) say so when something real is being left out.

**Not done in this pass:** no change to `computeViewport`, `computeSpaceViewport`, or any shipped file — the
prototype lives only in an ephemeral browser console session, deliberately kept out of the codebase until the
spec is accepted. §0.32 is scoped as implementation + full topology regression against this exact contract.

## 0.32 Bounded reachability, implemented — Focus and Enter Space rebuilt on one primitive (2026-08-30)

**[VERIFIED], deployed and live-tested against the real app, not just the §0.31 prototype.** Full detail and
every test result are in `docs/Memory.md`'s entry of the same name; this is the pointer. §0.31's contract was
implemented exactly as specified, with the explicit constraint honored: the contract itself was not
redesigned during implementation. `frontend/chat.html` gained `reach(graph, seeds, maxDepth, familyFilter,
direction)` (BFS over nodes, bounded by depth/family/direction), `edgesAmong` (every edge in the full graph
with both ends in a node set — a pass kept strictly separate from the traversal that found those nodes, the
actual fix for the cycle/mesh edge-drop bug), and `truncationByNode` (per-node counts of real edges leading
outside the current view). `computeSpaceViewport` and a new `computeFocusViewport` are now both built from
these three functions instead of two independently hand-rolled traversals; `computeViewport` dispatches
between them unchanged. A disclosure badge (`data.truncated`, a dashed amber border, and a `⋯+N` suffix baked
into the node's own label — anchored to the specific node with hidden structure, not a page-level counter)
renders whenever `truncationByNode` reports a nonzero count.

**Every acceptance criterion named for this pass, verified live against the deployed app (not the prototype)
in a real Chrome tab:**

- Whole-graph rendering: still 10/10 on the full §0.28 synthetic topology corpus, zero regression.
- Cycle under Focus: **3/3 edges, zero truncation** — fully recovered at Focus's unchanged radius, matching
  §0.31's prototype result exactly.
- DAG under Focus, root or sink: same 3/4 nodes shown either way (irreducible at a small bounded depth), but
  now correctly discloses 2 hidden edges on the two intermediate nodes in both directions — symmetric,
  honest, no longer silent.
- Mesh under Focus, low-degree node: same 4/8 edges shown, now with `+1` badges on exactly the three nodes
  that have a real hidden connection to the unseen node. Mesh under Focus, high-degree node: full recovery,
  **zero** false-positive truncation badges — the contract only ever reports real hidden structure, never
  flags a genuinely complete view.
- Hub under Focus on a leaf: full recovery, zero boxes formed (interaction ≠ composition, unchanged).
- Enter Space on a nested workflow (`Authorization`, nested inside `Payment Process`): box correctly formed
  over its 5 compositional children, the cross-boundary `Capture` correctly shown as context, and the exact
  predicted disclosure from §0.31 — `Authorization` and `Capture` together accounting for the 2 hidden nodes
  / 3 hidden edges one hop past what's shown.
- Enter Space on a doubly-nested box (`Payment Stages`, nested inside `Payment`): correctly shows only its
  own internal chain, correctly excludes the outer siblings (`PayPal`, `Mastercard`), correctly discloses its
  own incoming parent edge as 1 hidden edge.
- Cross-space edges: unchanged — both boxes form, both boundary-crossing interaction edges survive, and the
  nodes reached only as context now honestly disclose that their own containing structure isn't shown either.
- Projection composed with an entered Space (`Authorization`, `flow` projection): still correctly filters to
  the temporal chain within scope — §0.27's behavior unaffected by the underlying rewrite.
- World Model: `graph.nodes`/`graph.edges` array identity and length confirmed unchanged across every single
  test above — navigation causes zero graph mutation, by construction (`reach`/`edgesAmong`/`truncationByNode`
  only ever read).
- Determinism: the same graph and parameters, called twice, produced byte-identical node and edge sets both
  times — `V = f(G, root, depth, family, direction, mode)` holds as a real property of the shipped code, not
  an aspiration.

No new Node type, no new graph type, no stored topology field, no duplicate graph — the standard held from
§0.29 through this pass.

## 0.33 Mining the real World Model — non-tree topology already exists in the wild (2026-08-30)

**[VERIFIED against real Neo4j, zero LLM calls].** Full detail and the complete script output are in
`docs/Memory.md`'s entry of the same name; this is the pointer. With every LLM provider exhausted
simultaneously (confirmed via `/provider_status` before starting), live end-to-end investigation was not
possible — so this pass mined the graph every investigation this whole project has ever run has already
written to the same Neo4j database, using `scripts/mine_world_model_topology.py` (pure graph analysis:
weakly-connected components, directed-cycle detection, convergence counting, nested-composition detection,
cross-boundary-edge detection, temporal-chain walking, and per-node family-mixing) against the project's own
`get_family` registry rather than re-deriving classification.

**278 nodes, 253 edges, and the World Model is demonstrably not a tree:**
- A genuine 5-node directed cycle already exists (`payment gateway → acquiring bank → card network → issuing
  bank → merchant → payment gateway`), built from individually-real extracted edges — named honestly as an
  aggregate property of several separately-run investigations over time, not a claim that any single
  reasoning pass asserted the loop consciously.
- Real convergence points exist with up to 8 distinct incoming edges (`Authorization`, from five *separately
  run, time-separated* investigations) — and every one of them resolved onto the *same* canonical node
  instead of fragmenting into duplicates, which is new evidence that identity resolution holds across
  sessions, not only within one investigation's own sibling set (the only scope it had been checked at
  before).
- Nested spaces (composition depth ≥ 2) occur organically in three lineages beyond the one already studied.
- Cross-space edges are real but narrowly evidenced — all four found instances trace to one lineage.
- Temporal chains have not yet been observed spontaneously outside the one deliberately-tested case, an
  honest limit rather than a claimed generalization.
- The single most consequential finding: **71 of 253 edges (28%) fall outside §0.25's `RELATION_TYPES`
  registry entirely** — not because they're meaningless (`SENDS_TO`, `FORWARDS_TO`, `ROUTES_REQUEST_TO` are
  obviously interaction-family relations), but because the registry's exact-string lookup doesn't recognize
  surface variants of verbs it already half-knows (`routes_to` is registered; `routes_request_to` is not;
  `is_example_of` is registered; `is_an_example_of` is not). A quarter of everything ever extracted is
  currently invisible to family-based projection and topology classification.

**Explicitly not done in response to that last finding, on the user's own instruction:** the 71 unmapped
relation names were not manually added to the registry. Patching entries one at a time would make today's
graph look cleaner while leaving the actual problem — an ever-growing, ad hoc vocabulary with no theory of
when two surface relations are the same thing — completely unaddressed. §0.34 is scoped to research relation
identity/canonicalization properly before touching the registry at all.

## 0.34 Predicate identity & relation vocabulary — a research pass, no code (2026-08-30)

**[RESEARCH CONCLUSION — design-only, no code].** Full detail is in `docs/Memory.md`'s entry of the same
name; this is the pointer. §0.33's mining pass found 28% of all extracted edges outside the relation-type
registry, with a clear instruction not to patch it name-by-name: "First understand relation identity. Then
let the registry become the consequence of that model, rather than a growing dictionary of whatever verbs the
LLM happened to produce."

**Research question:** how can arbitrary linguistic relation expressions be mapped into a small, stable
semantic vocabulary without letting the LLM silently redefine the ontology?

**The first, necessary correction: "canonicalization" was never one operation — the code already has two
genuinely orthogonal mechanisms, and treating them as one thing obscures where the real gap is.**
`canonicalize_relation` (an LLM call) does *direction normalization* — passive/modal voice to active voice,
never touching which verb is used. `normalize_relationship_type` (deterministic, hand-curated) does *spelling/
format normalization* — a small synonym table, explicitly scoped to variants already observed in real runs.
`get_family` does *family classification* — one canonical predicate string to one coarse family bucket. None
of these three is, or was ever meant to be, *predicate identity resolution*: deciding whether two different
verb strings (`routes_to`, `forwards_request_to`, `sends_to`) denote the same real-world relationship before
family lookup even runs. That missing layer is the actual gap §0.33 found — not a canonicalization bug, a
genuinely absent pipeline stage:

```
Extraction → Direction normalization → Predicate normalization → Identity resolution → Family classification → World Model
```

**Ten principles, kept as a checklist rather than prose so future passes can be checked against them
directly:**

1. Surface form ≠ predicate identity.
2. Predicate identity ≠ relation family.
3. Family is intentionally coarse (a rendering/projection bucket).
4. Predicate identity is fine-grained (a real-world-relationship-preserving distinction).
5. Equivalence between two surface forms requires verified semantic equivalence, checked against real
   examples — never assumed from string or embedding similarity alone.
6. Unknown relations remain preserved, never silently dropped or force-merged.
7. Normalization is deterministic and conservative — decided by curation, not by an LLM asked at extraction
   time whether two things it just said mean the same thing.
8. Unknown ≠ unworthy (already the standing rule in `relation_extraction.py`; extended here to the vocabulary
   layer, not just the worthiness layer).
9. A wrong merge is strictly worse than an unmapped relation — a merge silently and permanently changes what
   the graph claims; an unmapped edge only says "this hasn't been classified yet," which is recoverable and
   honest.
10. Registry growth is incremental and observable (the mining script *is* the observation mechanism — run it
    periodically, review new unmapped verbs in small batches, exactly as `_RELATIONSHIP_TYPE_SYNONYMS`'s own
    documented discipline already states: built from variants actually observed, never a speculative ontology
    populated up front).

**One refinement to the "conservative, no confidence score" conclusion from the prior draft of this
research, per direct correction:** predicate-identity decisions stay deterministic yes/no at the registry
level — that part holds. But the *evidence supporting* a given yes/no decision can and should be recorded
during curation, without becoming a runtime confidence score:

```
alias: FORWARDS_REQUEST_TO -> ROUTES_TO
reason: same argument roles, same operational meaning
verified_examples: [...]
status: verified
```

This preserves the distinction the whole project has maintained since §0.26: knowledge about the world can be
probabilistic (relation evidence, confidence); ontology decisions about what a predicate *is* should not be.

**A concrete design worth naming for a future implementation pass, not built now:** an `unknown` pseudo-family
in `PROJECTION_FAMILIES`, surfacing exactly the relations with no registered family — turning the 28% gap
from an invisible blind spot into something a user can deliberately go inspect, the same "honest gap over
silent invention" principle §0.27/§0.31 already established for topology, applied here to vocabulary. The
relation model this points toward keeps `surface_predicate` and `canonical_predicate` as genuinely separate
fields (evidence attaches to the assertion, never to the canonical predicate string itself) — valuable later
once multiple sources express the same fact in different surface forms, which hasn't been built and isn't
needed yet.

**Not done in this pass:** no registry change, no new pseudo-projection, no schema change. The named next
step is a small adversarial test — not of hand-picked toy examples, but of the actual 71 unmapped
relationship_type strings already sitting in the real 253-edge graph from §0.33 — to check whether this
theory holds against the mess the system has already produced, before any of it is implemented.

## 1. Consolidated stack

| Layer | Choice | Fallback / later |
|---|---|---|
| Graph store | **Neo4j** (local Docker) | FalkorDB; Neo4j AuraDB when cloud-hosted |
| Agent orchestration substrate | **LangGraph** (core graph/checkpointing engine only, not its agent layer) | Google ADK if a full framework is wanted later |
| LLM provider | **Free-tier providers** (Google Gemini / Groq / Cerebras, fallback chain), per Implimentation-Research/Free-LLM-APIs.md — no budget for Claude/OpenAI, neither has a usable free tier | Cohere trial for rare master-level calls; Claude API tiered by agent level if this ever gets a budget |
| LLM adapter | **Instructor's native `from_provider()`** (`"google/…"`, `"groq/…"`, `"cerebras/…"` strings), talking to each provider's own SDK directly | — |
| Structured output | **Instructor** (`instructor.from_provider(model, async_client=True)`) | Pydantic-AI if orchestration consolidates into one framework |
| Evidence/resource APIs | **Tavily** (web), **Semantic Scholar** + **arXiv** (papers), **Open Library** (books), **YouTube Data API v3** (video) | Exa or Brave if Tavily recall proves insufficient |
| Evidence Engine reference implementation | `gpt-researcher` (study/reuse retriever-plugin pattern) | Stanford STORM (multi-perspective planning pattern) |
| Vector search | **LanceDB** (embedded) | Qdrant embedded → server as a migration path |
| Claim/evidence temporal pattern | Borrowed design from **Graphiti** (read source, not a dependency) | — |
| Recursive retrieval pattern | Borrowed design from **LightRAG** (dual-level: leaf vs. synthesis) | — |
| Task queue / message bus / state store | **asyncio + SQLite** (`aiosqlite`) | Temporal.io once durable multi-machine orchestration is needed |
| Backend API | **FastAPI** (REST + WebSocket) | — |
| Graph visualization | **Cytoscape.js** + `react-cytoscapejs` | — |

Explicitly avoided and why: Kùzu (archived Oct 2025, no safe upstream), Celery/Redis (Redis's RSAL/SSPL license change adds an unnecessary early decision — Valkey is the open fork if ever needed), Claude Agent SDK (not open-source, hard-locks the LLM provider), CrewAI/AutoGen (too opinionated / in maintenance mode for this bespoke agent-tree shape), adopting Graphiti or GraphRAG wholesale (their data models are tuned for conversational memory / batch document ingestion, not this project's Domain/Abstraction/Dimension/Question model).

## 2. Layer responsibilities

- **Graph Interface** (`/backend/graph`) — the only code allowed to talk to Neo4j directly. As actually built through Phase 5 + the post-Phase-5 graph-persistence pass: `get_node`, `get_neighbors`, `get_subgraph`, `create_node`, `create_relationship`, `create_abstraction`, `expand_abstraction`, `contract_abstraction`, `attach_entity` (entity→abstraction), `merge_entity` (canonical-entity dedup/merge by precedence rule, Palantir-style — see §0), `find_or_create_entity` (case-insensitive exact-name lookup before create — the lighter-weight dedup an *agent's own discovery* needs at the moment of creation, distinct from `merge_entity`'s harder after-the-fact job), `attach_question`, `attach_claim`, `get_claims_for_question`, `supersede_claim` (temporal claim history, Graphiti-inspired). Nothing above this layer writes Cypher directly. The schema itself stays deliberately simple (typed nodes/edges/properties only) — no hierarchy/zoom logic lives in Neo4j; that logic belongs entirely in the agent/Question Engine layers above (§0's "keep the graph mechanically dumb" principle).
- **Question Engine** (`/backend/questions`) — pure function of `(Abstraction, Network, Entity, Dimension, Level, Objective, Known, Unknowns) → Question(s)`, implemented via Instructor's `from_provider()` against the free-tier chain (Google Gemini / Groq / Cerebras) with Pydantic schemas — see §1's LLM provider row for why, not Claude. Level-aware: same dimension at Master vs. Ground level must produce structurally different questions (verified in Phase 2 — ground/master word overlap under 10% on a real test). **Lazy by design** (see §0): called on-demand when the user/agent actually interrogates a node/dimension, never precomputed across a whole abstraction upfront. `decide_next_step` also carries **dimension steering** (`Question.dimension_name`/`dimension_description`, and composed multi-lens steering via `Question.dimensions` — [VERIFIED], §0's dimension-steering/composability entries in Memory.md) and **implicit-framing exposure** (`GroundDecision.working_framing`, set when a master-level decompose has no explicit dimension to name what lens it used anyway — [VERIFIED, n=1]).
- **Evidence Engine** (`/backend/evidence`) — takes a Question, fans out to the retriever APIs (Tavily/Semantic Scholar/arXiv/Open Library/YouTube), returns typed `Claim { evidence, source, reasoning, confidence, contradictions, timestamp }` objects, and writes temporal claim edges into the graph using the Graphiti-inspired valid-time/superseded pattern.
- **Epistemic layer** (`/backend/questions` + `/backend/agents`, all off-graph — SQLite/in-process only, no Neo4j schema change, per §0.3-§0.5) — three narrow, separately-earned mechanisms, not one "epistemics engine": **structural provenance** (`backend.agents.trace_claim` — [VERIFIED] — classifies how a resolved question's answer was derived, by child count, from the AgentState tree every run already persists); **content provenance** (`backend.questions.audit_synthesis` — [VERIFIED, 3 sessions] — a separate auditor call, not a self-report, that decomposes a synthesized answer into atomic propositions and classifies each as traceable to the investigated material or not, without judging truth); **claim relationships** (`backend.questions.analyze_claim_relationships` — [PARTIAL, one experiment] — classifies pairs of already-grounded claims as complementary/alternative/conflicting/unrelated; reliably avoids false "conflicting" calls but has not yet demonstrated the harder "competing causal explanation" judgment it exists to provide — see §0.5). None of these three are wired into the default `GroundAgent`/synthesis path — they are standalone, independently-callable tools, not automatic behavior, until proven and integrated deliberately.
- **Roadmap Generator** (`/backend/questions` or its own module — decide at Phase 6) — `generate_roadmap(abstraction) -> list[Question]`, a pure function over the already-built graph (entities + attached questions + evidence), not a new agent tier (PRD.md §4a). Orders master-level questions before ground-level per branch, then by zoom-chain position, producing the "start here" reading sequence the UI renders alongside free graph exploration. Runs once per abstraction on demand — not continuously, and not part of the lazy per-question generation path above.
- **Agent Runtime** (`/backend/agents` + `/backend/runtime`) — **Master + Ground agent classes as the fixed core**; a Ground agent's own recursive decomposition of a hard question is what produces intermediate "Domain/Subdomain-like" structure, as a runtime artifact of recursion depth, not as pre-declared classes (see §0). Decomposition is **sequential, not batched**: one sub-question investigated at a time, its result folded into context, then re-decide — matching AgenticArchitecture.md §23's actual GENERATE→INVESTIGATE→INTEGRATE→CHECK COMPLETENESS loop (this replaced an initial batch-decompose design after a live evaluation found it never actually adapted mid-investigation — see Memory.md). Vertical-only typed messages (`MessageType` declares the full AgenticArchitecture.md §19-21 taxonomy as the protocol surface; only `BoundaryHitMessage`/`ExpansionRequestMessage` have concrete classes so far, built when Phase 4 first needed them) — no lateral peer-to-peer channel by default — flow through an asyncio pub/sub bus, built on a LangGraph state machine for the Master's own checkpointing. **A persisted priority task queue was planned here but was not built** — `MasterAgent` schedules its selected Ground Agents via a single `asyncio.gather` call with no priority ordering; cost/priority-based task allocation across branches remains explicitly deferred (Phases.md "Later / not yet scheduled"). The Master enforces a hard spawn budget (e.g. 1 agent for a simple lookup, more only for genuinely complex/broad queries) before spawning anything — non-negotiable per §0, not a later optimization; this part *is* built and verified.
- **Recursive discovery → graph persistence** (`GroundAgent`'s opt-in `persist_to_graph`, `backend/questions`' `GroundDecision.discovered_entity_name`) — closes the loop the rest of this section describes in the abstract: a decomposition does not automatically create a new entity (most sub-questions are just narrower questions about the *same* entity); a new canonical entity is created only when the model's own decompose judgment identifies a genuinely separable, independently-investigable component, resolved via `find_or_create_entity` and linked to its parent via a `RELATES_TO{relationship_type:"decomposes_into"}` edge. Every terminal question (answered, synthesized, or boundary-hit) attaches to its resolved entity. Without this, a Ground Agent's discoveries lived only in the SQLite agent-state store and vanished at the end of each run — the knowledge graph is what makes them persistent.
- **Abstraction Manager** (part of `/backend/agents`, owned by the Master agent) — controls breadth/depth/resolution/boundary of the currently active abstraction; receives `BOUNDARY_HIT`/`EXPANSION_REQUEST` messages and decides expand/contract/split/merge/reframe. Abstractions are treated as **cheap, revisable views over a canonical graph** (§0), not permanent structural commitments — merging or discarding one should be a low-cost operation.
- **API layer** (`/backend/api`) — FastAPI app exposing the graph and agent state to the frontend: REST for CRUD/initial graph load, WebSocket for live updates as agents discover new nodes/questions/evidence.
- **Frontend** (`/frontend`) — React + Cytoscape.js. Renders abstractions as compound/nested nodes (so "entity" vs. "network" is a visual zoom state, matching the design spec's Zoom operation exactly). Clicking a node surfaces its attached dimensions/questions/resources.

## 3. Folder structure

```
/backend
  /graph        Neo4j driver + Graph Interface functions
  /agents       Master + Ground agent classes (dynamic recursion depth, no fixed Domain/Subdomain schema), LangGraph state machine, message types
  /questions    Question Engine: dimension+abstraction+level -> question, Instructor schemas
  /evidence     Evidence Engine: retrievers, Claim/Evidence/Confidence/Provenance models, temporal edges
  /runtime      asyncio task queue, SQLite state store, pub/sub message bus
  /api          FastAPI app, REST + WebSocket endpoints
/frontend       React + Cytoscape.js graph UI
/docs           PRD.md, Architecture.md, Rules.md, Phases.md, Design.md, (later) Memory.md
docker-compose.yml   Neo4j service
```

## 4. Data flow (single request, simplified)

```
User defines/selects Abstraction (cheap, revisable view over the canonical graph)
        -> Master Agent applies spawn-budget rule, spawns N Ground Agents (N small by default)
        -> Ground Agent: Question Engine generates ONE question on-demand for (entity, dimension, level) -- not the whole tree upfront
        -> Ground Agent: Evidence Engine retrieves resources for that question
        -> Result (Claim + Evidence + Confidence) written to Graph Interface
        -> If the question needs deeper decomposition: Ground Agent recurses into its own sub-questions,
           forming intermediate structure dynamically (this is where "Domain/Subdomain-like" layers emerge, only if needed)
        -> If boundary hit: BOUNDARY_HIT -> escalate vertically (parent chain only, no lateral hop) -> Master decides expand/reject
        -> Frontend receives update over WebSocket, renders new nodes/edges/questions as they're produced (not batch)
```

## 5. Cloud-portability notes

Every v1 choice has a documented path to hosted infrastructure without a rewrite:
- Neo4j: local Docker → AuraDB (same driver, connection string change).
- LanceDB: local files → LanceDB Cloud (same API).
- asyncio+SQLite runtime: swap for Temporal.io when durable multi-machine orchestration is needed (same message/task shapes, different executor).
- FastAPI + React: deploy anywhere (Docker container / any PaaS) unchanged.
