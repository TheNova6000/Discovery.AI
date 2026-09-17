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

## 0.35 The queued adversarial test, run — the theory holds, with three real counterexamples (2026-09-03)

**[TEST ONLY, per explicit instruction — no registry change, no prompt change, no schema change, no code.]**
Re-mined the live graph directly (`scripts/mine_world_model_topology.py` plus a one-off script pulling the
distinct relationship_type strings, both read-only): **278 nodes, 253 edges, 71 unmapped edges — but only
56 *distinct* relationship_type strings**, not 71 (some repeat: `EXEMPLIFIES` alone accounts for 6, `SENDS_TO`
for 3). That distinction matters for everything below — the test corpus is 56 unique predicates, checked
against their real `(source, relationship, target)` triples, not invented examples.

**1. Genuinely distinct predicates, or surface variants?** Mostly variants, and clustered exactly where §0.33
predicted: **15 of the 56 strings** (`SENDS_TO`, `ROUTES_THROUGH`, `ROUTES_REQUEST_TO`, `RELAYS_TO`,
`TRANSMITS_TO`, `FORWARDS_TO`, `FORWARDS_REQUEST_TO`, `TRANSMITS_DATA_TO`, `SENDS_REQUEST_THROUGH`,
`RECEIVES_REQUEST_FROM`, `SENDS_AUTHORIZATION_REQUEST_TO`, `ROUTES_REQUEST_THROUGH`,
`FORWARDS_TRANSACTION_TO`, `FORWARDS`, and the already-registered `routes_to`) all describe the same real
-world shape — one party handing a request or data toward another — in the payment-routing domain alone.
This is strong, direct support for §0.34's core premise: the registry's problem is genuinely vocabulary
breadth, not that these are 56 unrelated real relationships.

**2. Do apparently-equivalent predicates collapse correctly TODAY?** No — and this is the pass's most
important finding, because it's not a theory gap, it's a **live, verified bug in the existing pipeline's own
two tables being out of sync**, found by reading `backend/questions/relation_extraction.py` and
`backend/questions/relation_types.py` side by side rather than assumed. `_RELATIONSHIP_TYPE_SYNONYMS`
normalizes `detects`/`detect`/`spots`/`spot`/`monitors`/`monitor` to `"DETECTS"` — but `RELATION_TYPES` (the
family registry) **has no `detects` entry at all**. Normalization succeeds, family lookup still fails, silently.
Directly confirmed against the real data: both `'detects'` and `'DETECTS'` sit in the 71 unmapped edges right
now. Every other synonym-table target (`CAUSES`, `DEPENDS_ON`, `ROUTES_TO`, `IS_EXAMPLE_OF`) checked out fine
against the registry — this is a narrow, specific gap, not a systemic one, but it's real and was previously
invisible (the two tables were never checked against each other directly before this pass).

**3. Does context change predicate meaning?** Yes, concretely: `FORWARDS` appears once for `'Router' ->
'Packets'` (networking hardware) — structurally the same shape as the payment-routing cluster above
(X moves Y onward), but a different domain's vocabulary choice for what is arguably the same family-level
relationship. Supports collapsing at the **family** level (both are INTERACTION-shaped) while correctly
declining to collapse at the **predicate-identity** level (a router forwarding packets and a bank forwarding
a transaction are not evidence for merging `FORWARDS` and `FORWARDS_TRANSACTION_TO` into one canonical
predicate — same family, different real-world relationships, per principle 2 of §0.34's own checklist).

**4. Same string, different relations?** No clear case found in this pass — `EXEMPLIFIES`'s all 6 instances
(`Redis -> In-Memory Caching`, etc.) are internally consistent, all genuine classification-family examples. One
softer case worth naming: `CAN_FUNCTION_AS` (`PayPal -> payment gateway`) is a *modal/capability* claim
("PayPal is capable of acting as"), semantically weaker than a firm `instance_of`/`is_example_of` assertion —
not a counterexample to the theory, but a reminder that surface-similar predicates can carry different
epistemic strength, which a same-family merge would flatten.

**5. Relations that cannot safely be canonicalized without more context — real counterexamples, not
hypothetical:** `STORES` (`In-Memory Caches -> active player states`) and `HOLDS` (`In-Memory Caches -> hot,
mutable state`) look like an obvious merge candidate on string similarity alone, but checking the real
examples shows genuine ambiguity: is a cache *containing* transient runtime state the same relationship as
structural part-whole composition (`contains`/`decomposes_into`, already registered), or is it closer to a
dependency ("the system depends on the cache holding this")? A wrong merge here — collapsing `STORES`/`HOLDS`
into `contains` — would silently misclassify a functional/data relationship as structural composition, which
would then incorrectly drive box/space nesting (§0.25's compositional-family behavior). This is exactly
principle 9's predicted failure mode (`a wrong merge is strictly worse than an unmapped relation`), now found
in real data rather than argued abstractly. `mediates` (`computer -> hardware_software_interface`) and
`facilitates` (`Online Card Payment Ecosystem -> PayPal`) are similarly vague "enables/supports" verbs that
could defensibly land in CAUSAL or INTERACTION depending on reading — neither wrong, neither obviously right
without more context than the bare triple provides.

**6. Does the registry provide enough structure? No — a real family gap, not just a vocabulary gap.**
`FOUNDED` (`Elon Musk -> X.com`), `DEVELOPED` (`Confinity -> PayPal`), `ACQUIRED` (`eBay -> PayPal`),
`MERGED_WITH` (`Confinity -> X.com`) are historical/provenance facts about corporate lineage — not
COMPOSITION, not an ongoing INTERACTION, not CAUSAL in the mechanistic sense the family was built for, not
DEPENDENCY, not CLASSIFICATION. These four don't have a family to belong to even in principle, which is a
different, harder problem than "the vocabulary hasn't caught up" — the six-family taxonomy itself (Winston/
Chaffin/Herrmann composition + the five families §0.17-§0.22's live runs produced) was never checked against
biographical/historical relation content, because none of the topics investigated before payments/PayPal
happened to surface it. Named here, not solved — a seventh family (or an explicit "not modeled, informational
only" bucket) is a real open design question this test surfaces, not one §0.34 anticipated.

**7. Net verdict: the theory holds where it claimed to, and the counterexamples it predicted it might find,
it found — which is itself informative.** The core premise (surface variants dominate; a real predicate-
identity layer would meaningfully shrink the unmapped set) is well-supported: 15/56 collapse into one cluster
on inspection. But three of the ten principles' own predicted risks are now backed by real examples rather
than hypothetical ones: (a) principle 9's "wrong merge is worse than unmapped" — `STORES`/`HOLDS`; (b) the
family taxonomy's completeness — historical/provenance relations have nowhere to go; (c) a live, narrow, now-
verified bug independent of any predicate-identity work at all — `DETECTS`'s orphaned normalization target.
None of these overturn §0.34's direction; they sharpen exactly what a future implementation pass needs to
handle deliberately rather than discover live.

**Not done, deliberately:** no registry edit (not even the one-line `DETECTS` fix, tempting as it is — fixing
it now would be exactly the "patch one string at a time" pattern §0.33's explicit instruction ruled out,
and per this pass's own scope, test-only means test-only even for a bug this narrow). No new family added. No
prompt change. No schema change.

**Next session, if this moves to implementation (not decided, not scheduled):** the `DETECTS` synonym/registry
desync is the cheapest, most isolated real fix available and could reasonably be done alone, separately from
the larger predicate-identity design — worth flagging as a candidate "small, low-risk fix" distinct from
the harder, still-undesigned predicate-identity-resolution stage itself.

## 0.36 A seventh relation family: `HISTORICAL` — a research pass, no code (2026-09-03)

**[RESEARCH CONCLUSION — design-only, no code, per explicit instruction. GitHub issue #4.]** §0.35 named a real
family gap — `FOUNDED`, `DEVELOPED`, `ACQUIRED`, `MERGED_WITH` don't have a home in any of the six existing
`RelationFamily` values — but deliberately didn't solve it, tracked instead as issue #4, sequenced behind
issue #3 (fixed alone in the previous pass, see `docs/Memory.md`'s 2026-09-03 "Issue #3 fixed" entry).
This entry settles the design question. `relation_types.py` is still untouched; that's the next, separately
audited step.

**1. The four real observed triples** (pulled live from the world model in §0.35's mining pass, re-used here
rather than re-queried — Docker/Neo4j wasn't reachable in this session — `docs/Architecture.md` §0.35 point 6
is the source of record): `FOUNDED` (`Elon Musk` → `X.com`), `DEVELOPED` (`Confinity` → `PayPal`), `ACQUIRED`
(`eBay` → `PayPal`), `MERGED_WITH` (`Confinity` → `X.com`) — together, the real corporate history of PayPal's
founding, not four unrelated examples.

**2. Tested against all six existing families, and rejected from each for a specific, checkable reason, not a
vibe:**

| Family | Why it fails |
|---|---|
| `COMPOSITION` | Confuses a historical event with a current structural *state*. `ACQUIRED` looks like the strongest candidate (post-acquisition, PayPal genuinely became part of eBay) — but eBay divested PayPal again in 2015. A permanent `eBay CONTAINS PayPal` edge goes stale and wrong; `eBay ACQUIRED PayPal` stays true forever, because it's a dated fact, not a structural claim. Collapsing an event into a state is the same corruption class issue #5 names for `STORES`/`HOLDS` → `CONTAINS`. |
| `CAUSAL` | `causes` is `transitive=True`, a real, checkable property in the registry. Founding isn't transitive — if Musk founds X.com and X.com later founds a subsidiary, Musk didn't thereby found the subsidiary. A one-time act of origination is not a link in a mechanistic causal chain. |
| `TEMPORAL` | Wrong type signature, not just "doesn't feel temporal." `precedes`/`follows` relate two co-stages of *one described process* (`Risk Checks precedes Authorization` — same kind of thing on both ends). `FOUNDED`'s ends are a person and an organization — categorically different kinds, related by an act of origination, not by relative sequence in a shared workflow. Having a date is not the same property as being TEMPORAL-shaped. |
| `DEPENDENCY` | No ongoing functional-need semantics present. X.com doesn't `depends_on` Musk in the sense the registry already means by that word (continued operational need). Clean rejection. |
| `INTERACTION` | The closest miss. Every existing member (`uses`, `routes_to`, `queries`, `detects`, ...) is a *repeatable, ongoing* behavioral act between two actors that continue to coexist. `FOUNDED`/`ACQUIRED`/`DEVELOPED`/`MERGED_WITH` are each *singular and irrevocable* — once it happens, the entity's status is permanently different. A real cardinality distinction (repeatable vs. one-time), not a feeling. |
| `CLASSIFICATION` | Wrong type signature again — `instance_of` relates an instance to a category/concept. `FOUNDED` relates one concrete entity to another concrete entity. Not a close call. |

The `COMPOSITION` rejection is the one worth underlining, per the user's own framing: `ACQUIRED ≠ CONTAINS`.
An acquisition can *produce* a containment/ownership state, but the acquisition itself is the historical
event that produced it — the two must stay independently representable, or a later divestiture silently
corrupts the graph.

**3. Why this is an ontology gap, not vocabulary drift.** Every one of the six existing families models
either an ongoing *state* (`COMPOSITION`/`DEPENDENCY`/`CLASSIFICATION`) or a repeatable/mechanistic *process*
(`CAUSAL`/`INTERACTION`/`TEMPORAL`). None of them model a completed, dated *event* in an entity's own history.
This isn't invented from nothing — it's the same event/fluent distinction event calculus draws (Kowalski &
Sergot, 1986), and concretely, CIDOC-CRM (the real museum/cultural-heritage ontology standard) has a
dedicated `E5 Event` class with subtypes like `E63 Beginning of Existence` and `E96 Purchase`, kept separate
on purpose from its part-whole and property-bearing relations — `FOUNDED`/`ACQUIRED` map almost directly onto
those. Same grounding discipline this project already applies to `COMPOSITION` (Winston/Chaffin/Herrmann,
1987) and to the `transitive`/`symmetric`/`inverse_of` vocabulary itself (OWL/RDF) — not a new methodology,
the same one, applied one family further.

Considered and rejected as an alternative: leaving these four as an unmapped, "not modeled, informational
only" bucket (§0.35's other named option). Rejected because `PROJECTION_FAMILIES` already establishes that
families are how a user actually *queries* the graph ("show me the causal view") — an informational-only
bucket would be invisible to that whole mechanism, and nobody could ever ask "how did this company come to
exist" as a structured view. Unlike speculative infrastructure ahead of need (which §0.25 warns against),
this isn't speculative — four real, already-extracted edges exist right now with nowhere to go. That crosses
the same "something needs this now" bar the project has held everywhere else.

**4. The family: `RelationFamily.HISTORICAL`.** Alternatives considered and rejected: `PROVENANCE` (real
collision — `docs/Rules.md` and the claim/evidence system already use "provenance" for a different concept,
where a claim's evidence came from, e.g. `trace_claim`/`audit_synthesis` — one word, two unrelated meanings,
rejected on that basis alone); `ORIGIN`/`LINEAGE`/`GENESIS` (each undersells `ACQUIRED`/`MERGED_WITH`, which
aren't about descent or beginnings specifically); `EVENT` (names the ontological *justification* for the
family rather than its actual domain content, and risks the opposite scope-creep failure — reading as
"everything is secretly an event," since even an `INTERACTION` fact corresponds to some underlying event too).
`HISTORICAL` matches the existing naming register — `COMPOSITION`/`CAUSAL`/`TEMPORAL`/`DEPENDENCY`/
`INTERACTION`/`CLASSIFICATION` are all broad, general nouns, not narrow or poetic ones — without overclaiming
a tighter shared essence across founding/developing/acquiring/merging than actually exists.

**5. The boundary — corrected from the first draft, and the correction matters.** The first-pass definition
("a singular, dated event that establishes, transforms, or terminates an entity's existence or ownership
status") over-fit to three of the four examples and broke on `DEVELOPED`: `Confinity DEVELOPED PayPal` is a
real historical relationship, but "ownership status" isn't what makes it historical, and requiring a known
date is unnecessarily strict — the graph may know something happened historically without knowing exactly
when. The corrected invariant:

> **`HISTORICAL` represents a relation whose truth is anchored to a completed event in the history of an
> entity, rather than to an ongoing state, a repeatable interaction, a structural relationship, or a logical
> classification.**

Existence/identity/ownership transformation is a *strong example* of this, not the definition itself:

```text
FOUNDED       -> completed origination event
DEVELOPED     -> completed development/origin event
ACQUIRED      -> completed ownership-transfer event
MERGED_WITH   -> completed organizational-combination event
```

Negative test, preserved from the first draft because it still holds under the corrected wording: "PayPal
launched a mobile app" is not automatically `HISTORICAL` — it doesn't anchor to a completed event that changed
what PayPal *is*, so it stays `CAUSAL`/`INTERACTION` territory or unmodeled. Same falsifiable-boundary
discipline the project already holds `is_relation_worthy` and `is_compositional` to.

**6. `MERGED_WITH`'s asymmetry is a real, checkable internal split within the family, not a footnote.**
`FOUNDED`, `DEVELOPED`, and `ACQUIRED` are each asymmetric actor-acted-upon relations. `MERGED_WITH` is
semantically **symmetric** — if Confinity merged with X.com, X.com also merged with Confinity, the same shape
as `connects_to`/`routes_data_between` in `INTERACTION` (`symmetric=True`). This is recorded here as an
explicit implementation invariant for the eventual `relation_types.py` edit, not left as documentation prose
to be rediscovered later:

```text
"founded":      RelationTypeInfo(RelationFamily.HISTORICAL)                    # asymmetric
"developed":    RelationTypeInfo(RelationFamily.HISTORICAL)                    # asymmetric
"acquired":     RelationTypeInfo(RelationFamily.HISTORICAL)                    # asymmetric
"merged_with":  RelationTypeInfo(RelationFamily.HISTORICAL, symmetric=True)    # symmetric
```

(Shown here as the settled design, not yet written to `relation_types.py` — that edit is the next, separately
audited step.)

**7. Explicit non-goal: `HISTORICAL` is not a generic "anything that happened in the past" bucket.** Every
`INTERACTION`/`CAUSAL` fact already extracted also "happened in the past" in the trivial sense that all
extraction is retrospective — that is not the test. The test is point 5's boundary: a completed event that
the relation's truth is *anchored to*, as opposed to an ongoing state/process/capability that merely has a
history. A relation that fails that test does not belong here regardless of tense or vocabulary, the same
way an unmapped relation that fails `is_relation_worthy` doesn't get force-fit into an existing family just
to reduce the unmapped count (§0.34's core principle, still the governing one).

**Not done in this pass, deliberately:** no edit to `relation_types.py`, no new `RelationTypeInfo` entries
committed, no change to `_RELATIONSHIP_TYPE_SYNONYMS` or `normalize_relationship_type`, no test written. Same
architecture-first/implementation-second/verification-third sequencing as `#2` → `#3`. **Next session, if this
moves to implementation:** add the four `HISTORICAL` entries shown in point 6 to `RELATION_TYPES`, verified
the same way `#3` was — `get_relation_info` resolving all four, `verify_relation_registry_consistency.py`
unaffected (none of these four are synonym-table targets, so this doesn't touch that check's find), committed
alone, `#5` still untouched.

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

## §0.37 — Extension decision: Learning Portal (Course Compiler + Challenge Engine), 2026-09-16 [design only]

Not a pivot — an additive extension decided after the user asked for a course-building/coding-exercise product ("freeCodeCamp powered by this") and chose, when given the choice, to build it **inside** this repo rather than as a separate service calling this one over HTTP or depending on it as a library. Recorded here in the same numbered-decision-log style as §0.1-§0.36 because it's exactly that kind of decision: a real choice with real alternatives, not a foregone conclusion.

**Why extend in-place rather than a separate service/library:** the alternative considered (new repo, calling `/chat` or importing `backend.agents`/`backend.evidence`/`backend.graph` from across a process boundary) would have meant either scraping structure back out of a chat-shaped API never designed to return one, or vendoring an internal dependency whose Rules.md/Architecture.md this new project wouldn't own and would drift from. Building inside this repo means the Curriculum Compiler can call the Graph Interface directly, exactly like the Roadmap Generator already does (Rules.md rule 14) — one codebase, one Rules.md, one Architecture.md, one Memory.md, not two systems whose contracts need to be kept in sync by hand.

**What this decision does *not* do:** it does not change §1-§5 above, does not touch the existing Neo4j schema's `GraphNode`/`Abstraction`/`Question`/`Claim` vocabulary (Rules.md rule 6), and does not add a second graph store. It adds new node/relation types (§6.2 below) the same way `HISTORICAL` was added to `RELATION_TYPES` (§0.36) — as a PRD-first, then-architecture, then-code, then-verified-script sequence — and it adds exactly one genuinely new trust boundary (§6.4, the Challenge Engine's sandbox) that has no precedent elsewhere in this codebase, because nothing before this has ever executed untrusted input as code.

**Why the Challenge Engine is architecturally separate from the agent/graph system, not a new agent tier:** every existing agent (`MasterAgent`, `GroundAgent`) only ever calls trusted, centrally-wrapped LLM/retriever APIs (Rules.md rule 2) — it never executes arbitrary content it retrieved. Running a learner's submitted code is a different class of risk entirely (arbitrary code execution, not arbitrary text generation), so it gets its own isolation boundary (a sandboxed runner) rather than being bolted onto `GroundAgent` as "one more thing an agent can do." This mirrors this project's own existing instinct to keep concerns in separate, single-responsibility layers (`/backend/graph` only talks to Neo4j, Rules.md rule 1) rather than growing one class to do everything.

**Status: [VISION], design only.** Nothing in §6 below is built. It follows PRD.md §9, added in the same change, per Rules.md rule 6's requirement that new vocabulary be a PRD decision first.

## 6. Learning Portal Extension architecture [VISION — entire section]

### 6.1 Stack additions

| Layer | Choice | Why | Do not substitute with |
|---|---|---|---|
| Curriculum-source retrievers | New `Retriever` subclasses (GeeksforGeeks, freeCodeCamp curriculum, GitHub tutorial/exercise corpora) | Same interface as existing retrievers (`backend/evidence/retrievers/base.py`) — no new plugin mechanism needed | Bespoke scraping code embedded outside `/backend/evidence` (violates Rules.md rule 2) |
| Code execution sandbox | **Docker**, one ephemeral container per submission, no network, CPU/memory/wall-time limits (`--network=none`, `--memory`, `--pids-limit`, a hard `timeout`) | This project already depends on Docker for Neo4j (docker-compose.yml) — no new infrastructure class introduced, just a second, differently-configured use of a tool already in the stack | Running submitted code in-process, on the host, or in the API server's own container; a hosted "code execution API" third party for v1 (adds an external trust dependency before the local path is even proven) |
| Course/Lesson/Exercise storage | **Neo4j** (`Course`, `Lesson`, `Exercise` node types, §6.2) | Same graph, new node types — consistent with "one world model, multiple projections," not a new store | A separate document store for course content |
| Learner Model storage | **SQLite** (`aiosqlite`), keyed by learner/concept | Same tool this project already uses for agent/session state (Rules.md §1's task-queue/state row) — per-learner mastery is session-shaped state, not graph-shaped knowledge | A new database technology for what is, structurally, another state store like `runtime/state_store.py` |
| Frontend motion/fluid effects (§0.38.3) | **Reuse `frontend/wasm-fluid`** (already-compiled Rust/WASM asset, `fluid-bg.js`) + dependency-free CSS/JS micro-interactions | Already built and live for the landing page; matches the project's real "vanilla JS/HTML/CSS, no build step" stack | A new JS animation library (GSAP, Framer Motion, etc.) |
| API keys for new Learning Portal integrations (§0.38.1) | Same `_collect_keys()` pattern as existing providers: plural, comma-separated env var (e.g. `GITHUB_API_TOKENS`), round-robined | One convention across the whole codebase, not a special case per integration | A bespoke single-key env var per new service |

### 6.2 New graph vocabulary (Rules.md rule 6 — PRD.md §9 authorizes this)

- **Node types:** `Course` (a compiled curriculum for one topic/abstraction), `Lesson` (attached to one concept `Entity`), `Exercise` (attached to one concept `Entity`).
- **Relation types**, added to existing families in `backend/questions/relation_types.py` (no new `RelationFamily` — §0.37's DEPENDENCY-reuse decision):
  - `requires` / `prerequisite_of` — `DEPENDENCY` family, asymmetric. The Curriculum Compiler's topological sort input.
  - `taught_by` — entity → `Lesson`, `INTERACTION` family (an entity is explained by a lesson, not composed of one).
  - `exercised_by` — entity → `Exercise`, `INTERACTION` family, same reasoning.
- Added the same way `#4`/`HISTORICAL` was (Memory.md 2026-09-03): design entry here first, then a code-only follow-up adding the `RelationTypeInfo` entries, then a verification script confirming `get_relation_info()` resolves each and `is_compositional()` stays `False` for all three (none of these are part-whole relationships — a regression class §0.37's own STORES/HOLDS guard (`verify_stores_holds_not_compositional.py`) already exists to catch, and this new script should follow its exact two-part shape: real-state check + synthetic-corruption check).

### 6.3 Layer responsibilities (new)

- **Curriculum Compiler** (`/backend/curriculum`) — `compile_course(abstraction) -> Course`, a pure function over the Graph Interface (Rules.md rule 14's constraint, extended): topologically sorts an abstraction's concept entities by `requires` edges, groups into modules, and writes a `Course`/`Lesson`/`Exercise` skeleton back via the Graph Interface. Never calls an LLM or retriever directly — gap-filling (a concept with no lesson yet) is delegated back to Lesson Authoring/the Challenge Engine, triggered separately, exactly as Rules.md rule 14 already requires of the Roadmap Generator.
- **Lesson Authoring** (`/backend/curriculum`) — takes a concept entity + its existing `Claim`s (already retrieved by the investigation engine) and composes an explanation, running the result through `audit_synthesis` (Architecture.md §2's epistemic layer, already built) before attaching it as a `Lesson`. Does not invent claims the investigation engine hasn't already surfaced — if a concept lacks sufficient evidence, that's a signal to run more investigation (existing Ground Agent path), not to let the author fabricate.
- **Challenge Engine** (`/backend/challenges`) — exercise schema (prompt/starter/tests/hidden tests/hints/reference solution), a sandboxed runner (`run_submission(code, tests) -> Result`, Docker-backed per §6.1), and an independent validation pipeline that runs *before* an exercise is ever served: the reference solution must pass its own tests, and a small set of deliberately broken mutants must fail at least one test each (mutation testing as a cheap proxy for "these tests actually discriminate correct from incorrect," not just "these tests run without crashing"). This is the concrete implementation of PRD.md §9.6.4-5.
- **Learner Model** (`/backend/learner`) — `record_attempt(learner_id, concept_id, result)`, `get_mastery(learner_id, concept_id)`, and `next_step(learner_id, course)` (the remedial-routing decision: two consecutive failures on a concept inserts a remedial lesson/exercise before the main path continues, per PRD.md §9.6.7). SQLite-backed (§6.1), reads the `Course` graph but never mutates it — mastery is learner state, not world-model state. **Gamification fields (§0.38.3) are pure derived functions over the same attempt log**, not separate authoritative state: `get_xp(learner_id)` sums a fixed per-outcome XP table over recorded attempts; `get_streak(learner_id)` derives consecutive active days from attempt timestamps (with a freeze/repair grace mechanic, Duolingo-style, itself just another recorded event in the same log — never a raw counter a client could set directly); `get_concept_rank(learner_id, concept_id)` maps a concept's recorded pass rate/attempt count to a Codewars-kyu-shaped tier. None of these three introduce new ground truth — they're read-side projections, exactly like a Roadmap or a graph view is a projection over the world model (§0's core principle, applied here to learner state instead of knowledge).

### 6.4 Data flow — course compilation and grading (two new flows, additive to §4)

```
COURSE COMPILATION (on top of the existing investigation flow in §4)
Existing Abstraction with an investigated subgraph
        -> Curriculum Compiler reads the subgraph via the Graph Interface only
        -> topological sort by `requires` edges -> modules/lessons skeleton
        -> for each concept lacking a Lesson: Lesson Authoring composes one from existing Claims,
           audited via audit_synthesis before attaching
        -> for each concept lacking an Exercise: Challenge Engine authors one, validates it
           (reference solution + mutants) before attaching
        -> Course/Lesson/Exercise nodes written back via the Graph Interface

GRADING (entirely new, isolated from the graph/agent trust boundary)
Learner submits code for an Exercise
        -> Challenge Engine starts an ephemeral, network-disabled, resource-limited Docker container
        -> runs visible + hidden tests against the submission inside that container only
        -> container is destroyed regardless of outcome (pass, fail, timeout, crash)
        -> Result -> Learner Model (record_attempt) -> next_step decision
        -> next_step surfaces a remedial insertion if the mastery threshold isn't met, else continues the Course
```

### 6.5 Cloud-portability note (extends §5)

- Docker-per-submission sandbox: local Docker → a managed container-sandbox provider (e.g. gVisor/Firecracker-backed) only once real multi-learner load justifies it — not adopted preemptively, matching this project's existing local-first-now discipline (Rules.md §4).
- `Course`/`Lesson`/`Exercise` nodes ride the same Neo4j → AuraDB path §5 already documents for the rest of the graph — no separate migration story needed.
- Learner Model's SQLite store follows the same swap-when-justified path as the rest of this project's SQLite usage (§5's asyncio+SQLite row) — Postgres (already used for session/auth per `backend/api/db.py`) is the nearer, more likely upgrade than Temporal.io, once multi-learner use is real.

## §0.38 — Three corrections/decisions from 2026-09-16 follow-up: multi-key rotation (doc gap), local-laptop deployment target, gamified/fluid frontend

### 0.38.1 Multi-API-key rotation — already built, was never documented (doc gap, not new work)

The user asked for "the comma-separated multi-key thing from Discovery.AI" to be added to the Learning Portal extension, on the (reasonable) assumption it needed building. **It already exists and is [VERIFIED] live** — `backend/questions/llm_config.py`'s `_collect_keys()` reads e.g. `GOOGLE_API_KEYS="key1,key2,key3"` (plural env var, comma-separated, de-duplicated against the singular `GOOGLE_API_KEY`/`GEMINI_API_KEY` too), builds `PROVIDER_KEY_POOLS: dict[provider -> list[str]]`, and `backend/questions/llm_client.py::structured_call()` round-robins across a provider's pool on each attempt (`key {i+1}/{len(attempts)}` logging), on top of the existing provider fallback chain (`GROUND_MODEL_CHAIN`/`MASTER_MODEL_CHAIN`) — two independent axes of resilience: which *provider* to try, and which *key* within that provider's pool. A separate, request-scoped bring-your-own-key path (`set_current_user_keys`/`get_current_user_key`, a `ContextVar`) takes precedence over the shared pool per-request, with careful env-var-reset handling so one user's personal key can never leak into another concurrent request (`_SERVER_DEFAULT_ENV`).

**This was simply never written down** in PRD.md/Architecture.md/Rules.md before this pass — a real doc-gap, not a code gap. Fixed here: §1's "LLM provider" stack row and §2's Question Engine bullet above should be read as including this (updating the actual table cells is a small follow-up edit, not repeated here to avoid duplicating the same fact in three places).

**What this means for the Learning Portal extension:** any *new* keyed integration it adds (a GitHub API token for the tutorial/exercise retriever, or any other service that turns out to need a key) must follow the exact same convention — a plural, comma-separated env var (`GITHUB_API_TOKENS`) collected the same way `_collect_keys` already does, round-robined the same way — not a new, one-off single-key pattern. Added as Rules.md rule 21.

### 0.38.2 Local-laptop deployment is the primary target, not an afterthought

Clarifying, not changing, existing direction: PRD.md §9.2 already said "v1 stays single-tenant/local-first," but the user's follow-up ("run on laptop, frontend layer locally, everything parsed to the place we want") makes it worth stating explicitly as an architectural commitment, because it constrains implementation choices directly: **the Learning Portal extension must run entirely from one laptop with one command sequence** — `docker compose up` (Neo4j, and the sandbox runner's Docker daemon, already required) + `uvicorn backend.api.app:app` — with **no separate frontend build step and no separate frontend server process**. This is not a new pattern to invent: `backend/api/app.py` already does exactly this for the existing chat/docs frontend (`app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True))`, plus explicit clean-URL routes for `/chat`, `/`, `/docs`). The Learning Portal's own pages (course/lesson/challenge views) get added to `/frontend` and served the same way — new HTML/JS/CSS files in the existing static directory, new FastAPI routes alongside the existing ones, not a second web server, not a Node build pipeline, not a deploy target that requires Vercel/Render/Supabase to exist. Cloud deployment (§6.5, §5) stays exactly what it already was: an optional later path, not a requirement to develop or use this locally.

**This is a development-stage target, not a permanent ceiling** (clarified 2026-09-16, in response to a direct question about it): local-first is where this gets built and used *now*; it does not foreclose opening the Learning Portal to other people later, exactly the way the base engine's own §5/§6.5 already keep a documented cloud-upgrade path open for every local choice instead of treating "local" as an architectural commitment. Concretely, nothing in §6 above assumes single-user forever — the Learner Model is already keyed by `learner_id` (§6.3), and Rules.md §4's "no auth/multi-user before a phase calls for it" is a sequencing rule (build it when a phase actually needs it), not a decision that it's never needed.

### 0.38.3 Gamified, fluid frontend — grounded in real platforms, reusing what this repo already has

Researched (2026-09-16) rather than invented from scratch: Duolingo's mechanics (XP, streaks with freeze/repair as forgiveness for the loss-aversion mechanic, a skill-tree/path as the primary course map, leagues/leaderboards) [1][2][3]; Codewars' per-kata **kyu rank** as a mastery tier attached to the *content*, not just the learner [4]; Exercism's mentor-quality "idiomatic, not just passing" feedback framing (informs hint/feedback tone, not a feature to build — no human mentorship in scope) [4]; LeetCode/HackerRank's difficulty-tiered practice sets [4]. None of these are adopted wholesale — filtered through this project's own constraints (single learner, local-first, no online multiplayer, §9.8's existing out-of-scope list) and its honesty ethos (README: a view is "never allowed to imply completeness"; Rules.md rule 4's evidence/confidence/provenance requirement) which rules out the one pattern actually flagged as harmful in the research itself: gamification that manufactures false progress signals [5].

**Concrete decisions:**
- **Course map is a path/tree (Duolingo-shaped), not the free-explore Cytoscape graph.** Keeps the Learning Portal surface distinct from graph exploration (Design.md's existing "reads linearly" decision) while giving it a visual, game-like shape instead of a flat list — a linear/branching path *is* the `requires`-edge topological order (Architecture.md §6.3's Curriculum Compiler output) rendered as a game map, not a new data structure.
- **XP, streak (with freeze), and a per-concept kyu-like rank are pure derived views over the real Learner Model attempt log (§6.3/§9.6.6) — never a separately-settable counter.** A concept's rank reflects real recorded pass/fail history exactly the way a `Claim`'s confidence reflects real evidence — this is the same honesty principle applied to gamification instead of knowledge. New Rules.md rule 22 makes this explicit, since it's the one place gamification research itself warns things go wrong [5].
- **No online leaderboard/league in v1** — genuinely out of scope per PRD.md §9.8 (no real-time multi-learner features), not merely deprioritized. A local-only "personal best" stat (fastest solve, longest local streak) is in scope; comparing against other people is not, until this extension ever grows a real multi-user story.
- **"Fluid" reuses `frontend/wasm-fluid`, not a new library.** This repo already ships a working Rust/WASM live-cursor fluid simulation (`frontend/wasm/fluid_flow.wasm` + `fluid-bg.js`), currently used as the landing page's background effect. The Learning Portal reuses that same compiled asset for its own background/transition motion (course-map page, pass/fail feedback moments) rather than adding a new animation library (Rules.md §1's spirit — don't introduce a new dependency for something already solved in this codebase). Confetti/celebration-moment micro-interactions (pass an exercise, complete a module) are small, dependency-free CSS/JS — matching the existing frontend's own "vanilla JS/HTML/CSS, no build step" stack (README), not a reason to pull in a new framework.
- **Frontend implementation approach is corrected to match what's actually live, not what was originally planned.** §2's Frontend bullet and §3's folder structure describe a planned "React + Cytoscape.js" frontend (Phase 6, still [VISION]); what's actually shipped (`frontend/chat.html`, `frontend/index.html`) is vanilla JS/HTML/CSS with Cytoscape.js loaded directly via CDN script tags — no React, no build step, confirmed by reading the live files, not assumed from the README's own tech-stack line. **The Learning Portal frontend follows the proven pattern, not the aspirational one**: plain HTML/JS/CSS files in `/frontend`, Monaco loaded the same CDN-script way Cytoscape already is, served by the existing FastAPI mount. If Phase 6's graph UI is ever actually built in React, revisit whether the Learning Portal should match it then — don't build the React version speculatively now on the strength of a plan that hasn't been executed yet.

[1] [The 10 Best Gamified Learning Apps for Adults in 2026](https://yukaichou.com/gamification-examples/10-best-gamification-education-apps/) · [2] [Duolingo gamification explained — StriveCloud](https://www.strivecloud.io/blog/gamification-examples-boost-user-retention-duolingo) · [3] [Apps That Use Streaks: 10 Real Examples — Trophy](https://trophy.so/blog/streaks-feature-gamification-examples) · [4] [10 Best Coding Practice Platforms & Challenge Sites (2026) — Scrimba](https://scrimba.com/articles/best-coding-practice-platforms-and-challenge-websites-in-2026/) · [5] [When Gamification Spoils Your Learning — arXiv:2203.16175](https://arxiv.org/pdf/2203.16175)

## §0.39 — Phase 6 build session, 2026-09-16: `generate_roadmap` implemented, decisions made, environment constraint found

First actual Phase 6 implementation, not just design. Three decisions worth recording, plus one real environment constraint that limits what could be verified this session.

**1. Roadmap Generator lives in its own module, `/backend/roadmap`** — §2 had explicitly deferred this ("`/backend/questions` or its own module — decide at Phase 6"). Decided for its own module: `order_roadmap_steps`/`_compute_zoom_depths` only need `backend.graph.models` (`GraphNode`/`Relationship`/`QuestionNode`/`ClaimNode`) — zero dependency on `backend.questions` — so a dedicated module keeps the layering honest (Rules.md rule 1) instead of implying a dependency that doesn't exist.

**2. PRD.md §4a's ordering rule, made concrete.** The spec text ("master-level questions before ground-level questions within each branch... within a level, order by zoom-chain position") is read here as a **global** two-key sort — `(level_rank, zoom_depth, stable_tiebreak)` — not a per-branch interleave (which would require a different, recursive tree-walk structure the spec doesn't actually describe). This produces exactly what the text's own worked-example framing implies ("orient broad before drilling into specifics"): every master-level question across the whole abstraction surfaces before any ground-level question, ordered by how deep its entity sits in the zoom chain. `scripts/verify_phase6.py`'s `check_basic_ordering` is the concrete case this interpretation was tested against.

**3. `RoadmapStep` is richer than PRD.md §4a's bare `generate_roadmap(abstraction) -> list[Question]` sketch** — it also carries `entity_id`/`entity_name`/`zoom_depth`/`claims`, because a frontend rendering a roadmap needs that context and re-querying the graph per step would violate rule 14's "reads only, no repeated round-trips implied." The sequencing *algorithm* matches the spec exactly; the *return shape* was widened for the same reason `EntityExplanation`/`QuestionProvenance` (Architecture.md §2) already carry more than a bare id — a real consumer needs the data, not just a pointer to go fetch it again.

**4. Environment constraint — what's actually verified vs. not.** This session's shell had no `docker` binary and no `neo4j` Python package pre-installed (`pip install neo4j` was run to at least make `backend.graph`/`backend.roadmap` importable for a pure-logic test). No live Neo4j instance was reachable, so `generate_roadmap`'s own async I/O shell (the `get_subgraph`/`get_questions_for_entity`/`get_claims_for_question` calls) was **not** exercised end-to-end. What *was* run and passed: `scripts/verify_phase6.py`'s 5 checks against `order_roadmap_steps`/`_compute_zoom_depths` directly, using hand-built fixtures — the actual sequencing logic, just not the database round-trip around it. Phases.md marks Phase 6 `[PARTIAL]`, not `[VERIFIED]`, until someone runs `docker compose up` + a real investigation + a real `GET /roadmap` call on a machine with the full stack available — most likely the next session, on the actual laptop this is meant to run on (§0.38.2).

**What else was added this session, [BUILT] alongside the above:** `GET /roadmap?abstraction_id=...` in `backend/api/app.py` (mirrors `/resources`/`/node_detail`'s existing plain-dict, no-new-writes shape; 404s via `GraphInterfaceError` on a bad id), and `frontend/roadmap.html` (vanilla JS/HTML/CSS per §0.38.3's frontend-approach correction, served automatically by the existing `StaticFiles` mount at `/roadmap.html` — no new route needed for the page itself, only for the API). The page takes a raw `abstraction_id` — there is deliberately no topic-name-to-abstraction-id resolution wired in yet; that's a real gap, not an oversight, and is the natural next small step once this is verified live.

## §0.39.2 — Same day, continued session: live end-to-end verification actually run — one real bug found and fixed, one real gap found and left open

§0.39's environment constraint turned out narrower than it read: **Docker was never actually required** — README.md already documented "point at an existing Neo4j/Aura instance instead" as a first-class path, just never exercised. This session created a free Neo4j Aura instance, pointed `.env`'s `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` at it (no `NEO4J_DATABASE` needed — `backend/graph/driver.py` never reads that var; Aura free tier has exactly one database anyway), confirmed `driver.verify_connectivity()` succeeded, then ran `pip install -r requirements.txt` (this session's earlier `pip install neo4j` alone hadn't pulled in `langgraph` and the rest — `uvicorn backend.api.app:app` failed on import until the full requirements file was installed) and started the real backend.

**1. A real bug, found live and fixed — not the flaky-free-tier-model noise it first looked like.** The first `POST /chat` investigation ("How does an online payment work?") ran for several minutes through the LLM key-pool's provider fallback (expected — Groq/Cerebras free-tier models frequently drift off the requested tool schema, all logged and retried, matching `llm_client.py`'s documented design) and then returned a *generic* failure: `"Something went wrong investigating that: 'charmap' codec can't encode character '‑'..."`. That's not a provider error — `'‑'` is a Unicode non-breaking hyphen, and `'charmap'` is Windows' `cp1252` console codec, which can't represent it. Traced to the source: `backend/questions/llm_client.py:227` already has a documented fix for exactly this class of bug (`safe_reason = reason.encode("ascii", errors="backslashreplace").decode("ascii")` before its own `print()`, with a comment explaining a prior incident) — but that sanitization was never applied anywhere else. `backend/agents/ground_agent.py` alone has 6 other `print(f"...{exc}")` call sites (`extract_relations failed`, `canonicalize_relation failed`, `attach_relation_claim failed`, `set_boundary_kind failed`, ×2 more), plus `backend/api/app.py`'s `/compare` logging and all 6 `backend/evidence/retrievers/*.py` modules — none sanitized. `ground_agent.py:509`'s `extract_relations failed, degrading to zero results: {exc}` is the one that actually fired this run: `extract_relations` internally exhausts `structured_call`'s full provider fallback chain and re-raises the last provider's raw error, which — because the LLM's own generated JSON echoed back inside that error text contained the U+2011 character (visible directly in the server log's raw Gemini `RelationExtraction` attempt: `"Fraud‑monitoring tools"`) — crashed the bare `print()` with `UnicodeEncodeError`. Because that crash happened *inside* an `except` block's body (not inside the `try`), it propagated straight up past `ground_agent`'s own enrichment-must-not-break-the-answer design intent, all the way to `app.py`'s outermost generic handler, turning a purely cosmetic logging problem into a total investigation failure. Fixed once, at the root, in `backend/__init__.py` — reconfigures `sys.stdout`/`sys.stderr` with `errors="backslashreplace"` at package-import time (runs before any submodule's first `print()`), rather than patching all ~14 call sites individually. This also covers `instructor`/`tenacity`'s own internal retry-logging (the `"API call failed on attempt..."` lines, which echo raw provider text directly) without needing to touch third-party code. Re-ran the identical investigation after the fix: completed successfully, `200 OK`, and the answer text itself still contains the same U+2011 characters (confirmed by inspecting the response) — proof the fix addresses the encoding, not that the Unicode happened to be absent on retry.

**2. A real gap, found and deliberately left open, not fixed this session.** With the crash fixed, the investigation produced a real graph (41 nodes / 55 edges in Neo4j for "online payment"). Calling `GET /roadmap?abstraction_id=online%20payment` (the id shown in the chat UI's own graph payload) 404'd — because that id is a session-local display id, not the real Neo4j node id, and more importantly because **`abstraction_id` refers to a `Abstraction` node, and nothing in the live app ever creates one.** `backend/graph/interface.py`'s `zoom_in(entity_id)` (§2086 area, `create_abstraction` + `attach_entity` over an entity's existing decomposition) is the *only* function anywhere in the codebase that can produce a valid `abstraction_id` — and a repo-wide search confirms it has zero callers outside its own definition and its `backend/graph/__init__.py` export. `backend/api/app.py`'s `handle_zoom_in` — wired to the chat `"zoom_in"` intent, e.g. a "focus on X" style message — is a **different function that happens to share the name**: pure navigation over `find_or_create_entity`/`get_decomposition`, explicitly documented (its own docstring) as "never triggers investigation... even when the entity has no known structure yet," and it never touches `Abstraction` nodes at all. Net effect: **today, a real user going through the actual live app — chat, navigation, everything — has no path that ever produces a working `/roadmap` link.** This session's live verification only reached a real `abstraction_id` by calling `backend.graph.interface.zoom_in()` directly, out-of-band, via a one-off script (`zoom_in('<the online-payment entity's real Neo4j uuid>')` → `Abstraction(id='26ce531a-...')`), which is not something any real user or the frontend can do. This is now the actual next blocker for Phase 6 being *usable*, separate from and upstream of the already-known "no topic-name→abstraction-id resolution" gap (§0.39's closing paragraph) — that resolution step has nothing to resolve *to* until something in the live app actually calls `zoom_in`/`create_abstraction` in the first place. Left open rather than fixed on the spot because it's a real product decision (which chat action should trigger it — an explicit "build a roadmap" action? automatically once a master-level entity's decomposition looks complete? on the existing `"zoom_in"` intent, which would require actually disambiguating the two same-named functions first) rather than a mechanical fix.

**3. With both of the above accounted for, the live path was verified end-to-end and passed:** `POST /chat` → real Neo4j graph → `zoom_in()` → real `abstraction_id` → `GET /roadmap?abstraction_id=...` → `200 OK`, 9 steps, correctly ordered by `(level, zoom_depth)` exactly as designed (depth 0 → depth 1 → depth 2, all `ground`-level in this particular investigation since it didn't happen to produce master-level questions) → `frontend/roadmap.html?abstraction_id=...` loaded in an actual Chrome tab via `claude-in-chrome`, rendered the same 9 steps with level/depth badges, sub-question provenance ("Sub-question of: ..."), and clickable resource links with confidence scores, zero browser console errors. This is the first time any part of the Learning Portal track has been confirmed working against a real, live-investigated graph rather than hand-built fixtures.

**4. Two data-quality observations, real but out of scope for Phase 6 itself, flagged for later:** (a) the roadmap's 9 steps included the same question text ("What is the role of the payment gateway...") 3 times over — `Question` nodes are apparently not deduplicated across repeated decomposition/retry passes the way `find_or_create_entity` dedupes entities; worth a look whenever someone next touches question attachment. (b) most attached resources scored 10-15% confidence — genuine evidence-retrieval weakness on this topic under the free-tier retrievers, unrelated to roadmap generation or ordering.

## §0.39.3 — Phase 6.1, same day: the real-user roadmap entrypoint built

Directly closes §0.39.2's point 2 (the `zoom_in`/no-caller gap).

**1. Rename over new abstraction.** `backend/graph/interface.py`'s `zoom_in` → `materialize_abstraction`, same function body and contract, `backend/graph/__init__.py`'s export updated to match. The rename itself is the fix for half the original problem: the old name's collision with `app.py`'s unrelated `handle_zoom_in` (pure navigation, never touches `Abstraction` nodes) is what let a zero-caller function hide through Phase 6's entire build-and-verify pass without anyone noticing. A distinct name makes that specific kind of hiding structurally harder, independent of anything else built this phase.

**2. Two real entrypoints, not one, matching the "Option A primary, Option B convenience" decision:**
- `POST /roadmap/build` (`BuildRoadmapRequest` in `backend/api/session.py`, handler in `app.py`) — `find_or_create_entity` then `materialize_abstraction`, returns `{abstraction_id, abstraction_name}` or 400 ("no discovered decomposition yet") for an entity with nothing to materialize. Unlike `GET /roadmap` (pure read, Rules.md rule 14), this one legitimately writes — it materializes an `Abstraction` node — so it's a `POST`, not folded into the existing read-only shape.
- A new chat intent, `"build_roadmap"` (`backend/questions/intent.py`), classified the same LLM-based way as `zoom_in`/`enter_space`/`investigate_deeper` are already distinguished from each other — added a full disambiguation paragraph to the intent prompt (packaging-request vs. viewing vs. investigating) rather than assuming the classifier would infer the distinction unprompted, matching how every other action in that prompt already gets explicit contrastive guidance. `handle_build_roadmap` does the same resolve-then-materialize steps and returns a markdown link, which `chat.html`'s existing `marked`+`DOMPurify` reply pipeline already renders as a real clickable `<a>` — no new rendering path needed.

**3. A bug this phase's own browser verification found, not something anticipated in advance:** `handle_build_roadmap` initially didn't set `session.current_entity`. Confirmed live, via direct DOM inspection (`wrap.dataset.entityName === ""`) after clicking the new "Build Roadmap" button on the `build_roadmap` reply's own chat message — the button had nothing to act on, because nothing had told the session what entity this reply was about. `handle_zoom_in` already sets `session.current_entity = entity_name` for exactly this reason (so `ChatResponse.graph.current_entity` flows through to `chat.html`'s `wrap.dataset.entityName`); `handle_build_roadmap` was missing the same line. Added it. This is a small fix, but the way it was found is the actual point: code review alone would very plausibly have missed it, since nothing about the missing line looks wrong in isolation — it only surfaces as a real gap once you click the actual button in an actual browser and watch it fail quietly.

**4. Frontend: a third button, not a new UI paradigm.** `frontend/chat.html`'s per-message options panel already had "Resources" and "Regenerate" (a `toggleBtn` → hidden `panel` → buttons pattern). "Build Roadmap" was added as a third button in that same panel rather than inventing a new UI surface (a banner, a modal, a separate "investigation complete" screen) — matches this project's existing "PendingAction" precedent of extending an established interaction shape instead of introducing a parallel one for a single new capability. Calls `POST /roadmap/build`, then `window.open('/roadmap.html?abstraction_id=...', '_blank', ...)` — the URL is deliberately site-relative rather than built from `apiUrl()` (which resolves against `CONFIG.BACKEND_URL`, the *backend's* origin): `roadmap.html` is a frontend page, and in the real deployed split (README.md: Vercel frontend + Render backend) those are two different hosts.

**5. What verification actually covered, and what it didn't.** `POST /roadmap/build`'s success path (curl, real local backend + real Aura Neo4j) returned the *same* `abstraction_id` §0.39.2's manual `zoom_in()` call had already produced for "online payment" — direct proof of the idempotent-by-name contract holding through the new endpoint, not just the underlying function in isolation. The failure path (an entity with no decomposition) correctly 400s with the documented message. The `"build_roadmap"` chat intent was verified the same way — a real `POST /chat` call, correctly classified, correct entity resolution, correct link in the reply. Browser-side, DOM inspection confirmed the button renders and the markdown link renders as a genuine `<a href="/roadmap.html?...">` (which is what surfaced point 3's bug) — but a full click-through-to-a-new-tab was not cleanly completed this session. Root cause, worth recording honestly rather than glossing over: `chat.html`'s `CONFIG.BACKEND_URL` is hardcoded to the real deployed production backend (`https://discovery-ai-bosm.onrender.com`), not same-origin-by-default the way `roadmap.html`'s own `CONFIG` already is (§0.39's build notes) — testing locally required overriding it at the console, and that override, plus a real cached Supabase login already present in this browser profile, produced enough async/reload interference that repeated attempts at a real click either landed on the wrong element or lost the override before the fetch fired. This is a real local-dev-ergonomics gap (chat.html should default same-origin like roadmap.html does, with the production URL as an override rather than the hardcoded default), not a defect in the shipped code path itself — flagged here rather than fixed, since fixing it means touching real, working production config and deserves its own deliberate pass, not a rushed edit mid-verification.

## §0.40 — Learning Research Mode: design decision, 2026-09-16, no code

Phase 6.1's live roadmap (§0.39.2/§0.39.3) surfaced something beyond the missing-entrypoint bug: the roadmap it produced was *real* (9 steps, correctly ordered, correctly rendered) but *shallow* — all `ground`-level, zoom-depth 0-2, most attached resources at 10-15% confidence. That's not a defect in Phase 6's ordering logic (which is exactly correct for what it was given); it's the base engine's own default investigation policy showing through: one question per entity, one evidence pass, decomposition bounded unless a user explicitly asks to "go deeper." Right default for exploratory chat (bounded latency/cost/key-budget/graph-growth); wrong as the *only* gate before compiling something meant to actually teach someone.

**The core distinction, and why it's architectural rather than a tuning knob:** Discovery.AI's existing objective is "investigate enough to construct a dependency/world-model graph." The Learning Portal's real objective is "investigate enough to teach the topic correctly and deeply." Those are genuinely different stopping conditions, not the same policy at two different depth settings — "stop because a dependency array exists" and "stop because the learning objective has been sufficiently researched and verified" produce different behavior even holding everything else constant, because the first is satisfied by structure alone and the second requires content (a definition, a mechanism, an example, its misconceptions, evidence meeting a confidence bar) per concept before that concept counts as done.

**Explicitly rejected approach: don't make `GroundAgent` deeper everywhere, and don't make the Learning Portal repeatedly call `investigate_deeper` as a workaround either.** The first blows up cost/latency for every ordinary chat question, including ones nobody wanted researched to course-depth. The second is fragile in a specific way: it would mean the learning product forces the research engine to behave differently through a sequence of manual, external commands rather than the engine itself understanding what "enough" means for this objective — every future caller with a similar need would have to rediscover and re-implement the same sequence of calls.

**Decided instead: two modes, one engine.** Both reuse the exact same `GroundAgent`, Evidence Engine, Graph Interface, and LLM key-pool (Rules.md rule 21) — nothing forks. What differs is an orchestration *policy* layered on top:

```
Discovery.AI investigation (unchanged)
    ├── Exploratory mode (today's existing default, byte-for-byte unchanged)
    │     -> bounded, shallow, dependency-oriented, stop once structure exists
    │
    └── Learning research mode (new, Phase 8.1-8.6)
          -> coverage-oriented: stop once each in-scope concept is research-complete
             (definition, prerequisites, mechanism, example, misconceptions,
             evidence meeting a confidence bar -- PRD.md §9.3a's list)
```

Full reasoning and the concrete per-concept completeness fields live in PRD.md §9.3a (added this session) rather than duplicated here — that's the spec surface, this is the "why now, why this shape" record. `docs/Phases.md`'s Phase 8 is restructured to match: what was a single flat "Curriculum-source retrievers" phase is now Phases 8.1-8.6 (Research Policy abstraction, Learning Research Planner, Coverage/completeness model, Deep investigation orchestration, Evidence/contradiction validation, Research-complete graph artifact) — the original retriever work isn't lost, it's repositioned into 8.4 as infrastructure serving the new orchestration rather than the phase's own starting point, since retrievers built against an unstated completeness bar would just be more sources feeding the same shallow-by-default stopping condition.

**Research completeness vs. learning completeness — kept as two separate concerns on purpose:** "has this concept been sufficiently understood and evidenced" (Learning Research Mode's job) is a different question from "can this become an effective lesson — what's taught first, what misconception gets preempted, what exercise actually tests understanding" (the Curriculum Compiler's job, unchanged in shape, Phase 9). The research engine is never made directly responsible for producing the final course; Phase 8.6 defines a research-complete graph artifact — still one Neo4j world model, multiple projections, §0's founding principle, not a second store — that Phase 9 consumes instead of a bare exploratory subgraph. Keeping this boundary means Phase 9 doesn't need to know anything about *how* a concept became research-complete, only that it did.

**What this session explicitly does NOT do:** no `ResearchPolicy`/planner/completeness-model code was written. This is a design-only pass — PRD.md §9.3a (the spec), this section (the reasoning), and Phases.md's Phase 8.1-8.6 restructure (the sequencing) — deliberately completed *before* any Phase 8 implementation starts, per the explicit instruction that prompted it: define Learning Research Mode before building retrievers or expanding Phase 6.1 further. `backend/roadmap`, `backend/graph`, `backend/api` are all unchanged by this section; only the three docs above were touched.

## §0.41 — Phase 8.1, same day: `ResearchPolicy` built, "add the abstraction before changing behavior"

§0.40 defined Learning Research Mode's shape but deferred all implementation. Phase 8.1 is the first real piece of it — deliberately the smallest possible one, per the instruction that framed this phase: build only the policy abstraction and prove it preserves today's behavior, nothing about deep orchestration yet.

**1. The values came from reading the engine, not from the earlier design sketch.** §0.40/PRD.md §9.3a's `ResearchPolicy` field list was a reasonable *shape* but not yet checked against what actually runs. Before writing `backend/agents/policy.py`, traced the real production numbers: `backend/api/app.py`'s `_run_investigation` (the only real `/chat` call site) constructed `GroundAgent` with `max_depth=DEMO_MAX_DEPTH` (2), `max_sequential_steps=DEMO_MAX_STEPS` (3), `gather_evidence=True` — three loose module-level constants, not `GroundAgent`'s own class defaults (`DEFAULT_MAX_DEPTH=2` happens to match, but `DEFAULT_MAX_SEQUENTIAL_STEPS=4` does **not** — the live app has been running at 3, not 4, this whole time, a real discrepancy worth surfacing rather than silently picking whichever number looked more "default"). The Evidence Engine's own `gather_evidence()` has a fourth real knob, `max_results_per_retriever` (`DEFAULT_MAX_RESULTS_PER_RETRIEVER=2`), never previously threaded through from `GroundAgent` at all — `EXPLORATORY_POLICY` wires it through for the first time, at its existing default value, so this is a zero-behavior-change addition, not a new lever being pulled.

**2. A field the design sketch implied but the engine doesn't have: spawn budget.** `MasterAgent`'s `spawn_budget`/`broad_spawn_budget` (Phase 4, `DEFAULT_SPAWN_BUDGET=3`/`DEFAULT_BROAD_SPAWN_BUDGET=6`) looked like the obvious `max_spawn_count`-shaped field for `ResearchPolicy`. A repo-wide search for `MasterAgent(` found exactly one call site: `scripts/verify_phase4.py`. The real, live `/chat` path drives `GroundAgent` directly and has never gone through `MasterAgent` at all. Including a spawn-budget field on `ResearchPolicy` would have quietly implied it controls something running in production when it controls nothing running today — left out of the dataclass entirely, documented as an explicit non-field with the reasoning above, rather than added-but-silently-inert like the five genuinely-forward-looking fields below.

**3. Five fields added, genuinely inert, documented as such rather than hidden.** `require_prerequisites`, `require_examples`, `require_misconceptions`, `require_evidence_validation`, `confidence_threshold` exist on `ResearchPolicy` (matching PRD.md §9.3a's completeness-criteria list) but nothing in `GroundAgent` or anywhere else reads them yet — they wait for Phase 8.3's Coverage/completeness model. `scripts/verify_phase8_1.py`'s check 4 makes this a tested guarantee, not just a comment: constructs a policy with every one of these flipped to its strongest "learning" value and confirms `GroundAgent`'s resolved attributes are unaffected, and that the agent object doesn't even carry these as attributes at all (`hasattr` checks) — proving there's no hidden partial wiring anywhere, not just an absence of an obvious one.

**4. The injection point stayed minimal on purpose.** `GroundAgent.__init__` gained one new optional parameter, `policy: ResearchPolicy | None = None`. When given, it's authoritative for the four wired fields; when omitted — every call site that existed before this phase, with zero exceptions (`scripts/verify_phase3.py`/`verify_phase4.py`/`verify_phase5.py`, `master_agent.py`'s own spawn node, and `GroundAgent`'s own two internal recursive-child-construction sites, which already pass fully-resolved values rather than a policy object) — nothing changes. `backend/api/app.py`'s `_run_investigation` is the one production call site actually switched over, from three loose kwargs to `policy=EXPLORATORY_POLICY`; `DEMO_MAX_DEPTH`/`DEMO_MAX_STEPS` are retired (their rich historical rationale comment — the depth=1/steps=1 regression story from docs/Memory.md — moved into `EXPLORATORY_POLICY`'s own field docstrings rather than being lost).

**5. Verification, two layers, kept deliberately distinct rather than conflated into one "it works" claim:**
- **Structural (deterministic, no LLM/Neo4j call, `scripts/verify_phase8_1.py`, 5/5 passing):** `EXPLORATORY_POLICY`'s values pin against the real numbers above (drift-detection, not just existence); `GroundAgent(policy=EXPLORATORY_POLICY)` resolves to attributes *identical* to the exact old-style call it replaced; `GroundAgent()` with no `policy` and no explicit kwargs — i.e. every pre-existing caller — resolves to exactly the same class defaults as before this phase existed; a `"learning"`-shaped policy's inert fields provably don't touch anything; `EXPLORATORY_POLICY` rejects mutation (frozen dataclass). This is what actually proves control-flow/config identity — the thing this phase can make a strong, provable claim about.
- **Live compatibility smoke test (one real `/chat` call, fresh topic "How does DNS resolution work?", not a cached repeat):** `200 OK`, ~276s, a real synthesized answer, 13 nodes/18 edges written to the real Aura Neo4j instance, routed through the new `policy=EXPLORATORY_POLICY` path end to end. Server log reviewed for crash signatures: no `UnicodeEncodeError`/`charmap` (the Phase 6 fix, §0.39, still holds — confirmed against fresh Unicode content in the real answer, not just an absence of Unicode this run), and the two `Traceback` lines present are the same pre-existing, already-documented, non-fatal Gemini/`instructor` mode-negotiation fallback (§0.39.2) — not a new failure. **What this proves is narrower than "identical behavior":** it proves the live path didn't break — a real compatibility check, not a claim that the investigation's output is provably byte-for-byte what it would have been pre-policy (LLM calls aren't deterministic across free-tier providers/keys/retries regardless of policy). The structural checks above are where the strong identity claim actually lives; this smoke test is what confirms the wiring is real, not just internally self-consistent.

**Governing principle this phase followed, stated plainly because it's the thing worth remembering if Phase 8.2 is tempted to skip it:** add the abstraction before changing behavior. Every number in `EXPLORATORY_POLICY` came from the running system, not from what seemed reasonable; every field that isn't wired yet says so in its own docstring rather than existing as an unexplained no-op.

## §0.42 — Phase 8.2, same day: Learning Research Planner, and a real scope correction to Phases.md's own original sketch

**The original Phase 8.2 line (Phases.md, written during §0.40's design pass) assumed the planner would be LLM-driven** — "given a topic, produces a research plan," with its own verify note conceding "plan content is inherently LLM-shaped." That assumption didn't survive the explicit instruction that actually kicked this phase off: *deterministic planner, unit tests with no LLM calls*. Reconciling those two things honestly, rather than quietly building something LLM-shaped and calling it deterministic, required narrowing what "planning" means here — and the narrower version turns out to be the more architecturally consistent one, not a compromise.

**What changed: the planner operates over an already-investigated subgraph, not a bare topic string.** `build_research_plan(abstraction_id, policy)` fetches the abstraction's existing members via `get_subgraph` — the exact same source `generate_roadmap` (Phase 6) already reads — and produces one `ConceptResearchTarget` per entity already discovered there. It does not decide "what concepts should exist for this topic that aren't in the graph yet"; that's a genuine, separate, LLM-shaped judgment (closer to what §0.40's Research Planner concept actually described), deliberately left for later rather than smuggled into a function this phase needed to keep provably deterministic. This mirrors Phase 6's own precedent almost exactly: `order_roadmap_steps` doesn't decide what's IN the graph either, only how to sequence what's already there — `plan_targets` does the same thing one level earlier in the pipeline (what's required, not yet what's true).

**What "required" means, made concrete without inventing new policy surface:** PRD.md §9.3a's completeness list has six fields — definition, prerequisites, mechanism, examples, misconceptions, evidence. Two of those (definition, mechanism) have no matching `ResearchPolicy.require_*` flag (Phase 8.1) because they're unconditional — every concept needs them regardless of mode, matching the PRD's own "base fields" framing. The other four map one-to-one onto `ResearchPolicy`'s existing `require_prerequisites`/`require_examples`/`require_misconceptions`/`require_evidence_validation` fields, which Phase 8.1 had already defined but left inert. This phase is the first thing that actually *reads* them — `_required_fields_for_policy` is a pure `getattr`-driven fold over `REQUIRED_FIELD_POLICY_GATES` (one dict, `backend/research/models.py`), not a hardcoded if-chain, so a future gated field is one dict entry, not a new branch. Confirmed live: `EXPLORATORY_POLICY` (every `require_*` False, Phase 8.1) yields `{definition, mechanism}` only; a `"learning"`-shaped policy with every flag `True` yields all six.

**Deliberately not a field yet: prerequisite entity edges.** A `ConceptResearchTarget` might naturally seem to want a `prerequisite_entity_ids` field — but the `requires`/`prerequisite_of` `DEPENDENCY`-family relation type that would populate it honestly doesn't exist in the graph until Phase 8.4 (Phases.md). Following the exact discipline Phase 8.1 set for `ResearchPolicy` (don't add a field with nothing real behind it, document the gap instead of faking control), `ConceptResearchTarget` stays at `{entity_id, entity_name, required_fields}` for this phase — `backend/research/models.py`'s own docstring says so directly.

**Module placement mirrors Phase 6's `backend/roadmap/` exactly, for the same reason:** `backend/research/{models.py, planner.py, __init__.py}`, I/O shell (`build_research_plan`) around pure logic (`plan_targets`), the pure logic is what's actually unit-tested. Own module rather than folded into `backend.agents` (which now owns `ResearchPolicy`, an orchestration-policy concept) or `backend.roadmap` (a different, already-shipped artifact) — `backend.research` depends on both (`backend.agents.policy.ResearchPolicy`, `backend.graph.models.GraphNode`) but neither depends back, keeping the layering one-directional (Rules.md rule 1).

**Verification, same two-layer discipline as Phase 8.1:** `scripts/verify_phase8_2.py`, 5/5, pure logic, no LLM/Neo4j call (exploratory-yields-base-fields, learning-yields-all-six, one-target-per-node with identity preserved, determinism, empty-input-yields-empty-output-not-error). Then, separately, a real live call — `build_research_plan` against the real "online payment" `Abstraction` from Phase 6/6.1's own live verification (`26ce531a-...`, real Aura Neo4j) — returned a real `ResearchPlan` with the abstraction's 5 real member entities as targets, each correctly carrying `{definition, mechanism}` under the exploratory policy. Both layers passed on the first real run, no debugging needed — a good sign the scope correction above was the right call, not just a defensible one.

## §0.43 — Phase 8.3, same day: Coverage/completeness model, and the honesty boundary it draws rather than papers over

Phase 8.2 answers "what should this concept contain" (`required_fields`, derived purely from policy). Phase 8.3 answers the genuinely different question: "what does it already contain, and is that enough" — `backend/research/coverage.py`'s `assess_target_completeness`/`assess_plan_readiness` (pure logic) plus `build_readiness_report` (I/O shell, `get_questions_for_entity`/`get_claims_for_question`, same Rules.md rule 14 constraint every prior phase in this track has followed).

**The real design question this phase had to answer honestly: what does "a field is present" even mean against today's actual graph schema?** PRD.md §9.3a's six fields (definition, prerequisites, mechanism, examples, misconceptions, evidence) read like six independently-checkable things. But `ClaimNode` (`backend/graph/models.py`) has no "which PRD field does this satisfy" tag — nothing in the schema distinguishes a claim that's a definition from one that's an example from one that's a misconception. Two honest paths existed: (a) add that classification via an LLM pass, which this phase's own scope explicitly excludes (matching Phase 8.2's "deterministic, no LLM calls" constraint — this phase inherits it, not a new decision), or (b) be precise about what current evidence actually demonstrates and report the rest as genuinely unknown rather than guessed. Chose (b), the same choice Phase 8.1 made for `spawn_budget` and Phase 8.2 made for prerequisite edges: don't add a signal with nothing real behind it.

**The resulting split, grounded in what today's Ground Agent actually produces, not invented:** `GroundAgent`'s single master-level question per entity ("What is the role of X in Y") and its one synthesized answer genuinely *does* cover "what is this and how does it work" — real content, not a stretch. So `CONFIDENCE_GATED_FIELDS` (`definition`, `mechanism`, and — since "evidence meeting a minimum confidence bar" is PRD.md §9.3a's own literal definition of the `evidence` field — `evidence` itself) are scored by whether that entity's real, non-superseded claims meet the active policy's `confidence_threshold`. The other three (`prerequisites`, `examples`, `misconceptions`) require content nothing in the current investigation pipeline asks for or tags — `UNCLASSIFIED_FIELDS`, always reported `"missing"`, every time, with an explicit reason string saying so (`"no evidence-to-field classification exists yet for this field (Phase 8.4)"`) rather than a bare `False` a caller would have to trust blindly.

**Consequence, confirmed rather than assumed:** any real `"learning"`-shaped policy (any policy with `require_prerequisites`/`require_examples`/`require_misconceptions` set) makes a target's `is_complete` honestly always `False` today, regardless of evidence quality — not a defect, the accurate statement that Phase 8.4's field-targeted investigation (the thing that would actually let a concept ask "give an example of X" as a distinct, taggable sub-question) doesn't exist yet. `scripts/verify_phase8_3.py`'s check 5 makes this a tested guarantee: a target under a full six-field policy, given a claim at 0.95 confidence, still reports exactly the three unclassified fields missing — not "always fails" indiscriminately, specifically the unclassified gap, with the three confidence-gated fields correctly marked present.

**Superseded claims excluded from "current evidence," reusing existing epistemic-layer convention rather than inventing a new one:** `ClaimNode.superseded_by` (Post-Phase-5's epistemic layer) already marks a claim as no longer the live truth about something; `_max_confidence` filters these out before computing whether a target's evidence qualifies. `scripts/verify_phase8_3.py`'s check 4 confirms a superseded claim at 0.95 confidence does NOT count — without this, a stale, since-corrected claim could make a concept look falsely "complete."

**Verified the same two-layer way as every phase in this track:** `scripts/verify_phase8_3.py`, 6/6, pure logic, no LLM/Neo4j call. Then, live: `build_readiness_report` against the real "online payment" plan (Phase 8.2's own live data) returned `is_ready=True` for all 5 real member entities — every one had real claims (4 to 18 active claims each, confidences from 0.10 to 0.90) clearing `EXPLORATORY_POLICY`'s `confidence_threshold=0.0`, with each field's reason string citing the actual claim count and confidence observed, not a placeholder. Passed clean on the first real run.

## §0.44 — Phase 8.4, same day: Deep investigation orchestration, bounded on purpose, and an honest (not a "success") live result

The explicit governing constraint for this phase: orchestrate targeted research for missing fields *without* turning the whole investigation engine into an uncontrolled deep-search system. Three independent, concrete bounds, not one vague one — detailed below, each one actually verified, not just stated.

**1. The real blocker Phase 8.3 (§0.43) left open: `ClaimNode` has no field-kind tag, and there was no source of one.** Closing it required an actual, small schema extension — `backend.questions.Question`/`backend.graph.models.QuestionNode` both gain `research_field: Optional[str] = None`, threaded through `attach_question`/`get_questions_for_entity`/`_record_to_question` (the `.get("research_field")` read, not `["research_field"]`, is deliberate: every question attached before this phase has no such property in Neo4j at all, and must read back as `None`, not throw). This is the minimum viable schema change that makes "a claim satisfies field X" a real, checkable fact instead of a guess — nothing more was added (no `field_kind` on `ClaimNode` itself, no new node/relation type, matching Rules.md rule 6's spirit even though a new optional field on an existing type isn't literally a new type).

**2. Bound #1, confirmed by reading the actual control flow, not assumed: `max_depth=0` genuinely forces a single answer, never recursion.** Traced `ground_agent.py`'s `_investigate_loop` directly: `budget_exhausted = self.depth >= self.max_depth or len(children_ids) >= self.max_sequential_steps` is computed every loop iteration, and the ONLY branch that spawns a child is gated `if decision.action == "decompose" and decision.sub_question_texts and not budget_exhausted`. With `max_depth=0` (and `self.depth` starting at 0), `budget_exhausted` is `True` from the very first iteration — even if the LLM decides `"decompose"`, that branch is skipped and execution falls through to the same boundary-hit conclusion path the comment right after it names explicitly ("Either a direct boundary hit, or 'decompose' requested with the depth/step budget exhausted"). This is a real, already-exercised code path from Phase 3 onward, not new logic invented for this phase — `run_targeted_investigation` just calls into it with `max_depth=0, max_sequential_steps=0` instead of the ambient `ResearchPolicy`'s values, a deliberate, explicit departure from "just pass policy through" documented directly in `investigate.py`'s module docstring.

**3. Bounds #2 and #3 are `plan_targeted_investigations`' own job, and are the part this session could unit-test directly:** `max_targets`/`max_fields_per_target` cap how much work one `close_coverage_gaps` call can trigger, and only `UNCLASSIFIED_FIELDS` are ever targeted (a `CONFIDENCE_GATED_FIELDS` gap — low-confidence base evidence — is a different, already-solved problem: the existing `investigate_deeper` chat intent). `scripts/verify_phase8_4.py`'s check 5 specifically confirms a *skipped* concept (one whose only gap is confidence-gated, not unclassified) doesn't consume the `max_targets` budget — the bound counts actionable work, not every concept glanced at.

**4. Curriculum-source retrievers deliberately deferred, not silently dropped.** The original Phase 8 sketch (before this session's restructure, §0.40) listed GeeksforGeeks/freeCodeCamp/GitHub retrievers as part of this phase. `run_targeted_investigation`'s `GroundAgent` call uses the Evidence Engine's existing `DEFAULT_RETRIEVERS` completely unchanged — the orchestration mechanism built here is retriever-agnostic by construction, so adding a curriculum-source retriever later is a drop-in addition to that list (same `Retriever` ABC, same multi-key-pool convention, Rules.md rule 21), not a re-architecture of anything in this phase. Scoped out explicitly because it's real, separable work, not because it was forgotten.

**5. The live result — reported exactly as it happened, not smoothed into a "success":** `close_coverage_gaps` run against the real "online payment" plan under a real `"learning"`-shaped policy (`confidence_threshold=0.3`), bounded to exactly 1 target × 1 field on purpose (proving the mechanism, not stress-testing the free-tier key pool). Before: `is_ready=False`, `ready_count=0/5`, "Payment gateway" missing `{examples, misconceptions, prerequisites}` — exactly Phase 8.3's predicted state for a fresh `"learning"`-mode plan. The orchestrator picked "examples" (alphabetically first among the three, respecting the 1×1 bound) and ran one real, bounded `GroundAgent` investigation: the LLM chose `action="answer"` directly on this run (so the `max_depth=0` decompose-block was never actually put to the test against a contrary LLM choice *this specific run* — §0.44 point 2's code trace is what establishes the bound holds regardless, not this one observation), gathered real evidence (Semantic Scholar 429-rate-limited and degraded gracefully, Tavily/YouTube skipped for missing keys — expected, not a failure), and persisted a real `Question` node tagged `research_field='examples'`.

After, re-running coverage assessment picked up the new tagged evidence and reported, precisely: `"a targeted question tagged research_field='examples' exists but its evidence (confidence 0.10) does not meet policy threshold 0.30"` — genuinely different from the `"no field-targeted question/evidence recorded yet for this field"` reason `misconceptions`/`prerequisites` still correctly show (untouched, per the 1×1 bound). **The field stayed `"missing"`** — not because anything in this phase's mechanism failed, but because the real evidence gathered for "give a concrete example of Payment gateway" scored 0.10 confidence, honestly below the 0.30 bar. This is arguably the more convincing live result than a clean "flipped to present" would have been: it proves the coverage model doesn't rubber-stamp a field the moment *any* evidence shows up — the confidence gate that already worked correctly in Phase 8.3's fixtures (`check_below_threshold_evidence_is_incomplete`) held just as correctly against a real, live, un-mocked LLM/retriever pass. The base fields (`definition`/`mechanism`/`evidence`) on the same concept, unaffected by this phase's new targeted question, still correctly showed `"present"` off the pre-existing 23 active claims at 0.60 confidence — confirming the extension didn't disturb Phase 8.3's original, already-verified behavior.

**What this means for Phase 8.5+:** the mechanism (target → tag → gather → re-assess) is proven real and correctly wired end-to-end. The gap left open isn't in this phase's code — it's evidence *quality* under this environment's actual retriever set (no Tavily/YouTube keys configured, Semantic Scholar rate-limited), a pre-existing, already-documented limitation (Phase 6's own "10-15% confidence" observation, §0.39.2), not something Phase 8.4 introduced or is responsible for fixing.

## §0.45 — Phase 8.5, same day: Evidence and contradiction validation, reusing the epistemic layer exactly as designed

Phase 8.4's own live result (§0.44) named the actual bottleneck directly: the mechanism works, evidence *quality* is the open question. Phase 8.5 doesn't try to fix evidence quality (that's a retriever problem, Phase 8.4's own deferred item) — it makes the *quality signals that already exist* visible and checkable, which is a different, narrower, achievable job.

**Same deterministic/LLM split as every phase in this track, applied one more time — and this time the split maps naturally onto what the user's own framing already separated:** "sufficiently supported / weakly sourced / duplicated / superseded" are all real, checkable facts about already-fetched `ClaimNode` data — no judgment call needed, so `assess_claim_validity` (`backend/research/validation.py`) computes all of them with zero LLM call. "Contradictory" is the one item on that list that's a genuine semantic judgment, not a field comparison — so `detect_contradictions` is the one function in this module that calls out, and it reuses `backend.questions.analyze_claim_relationships` (Post-Phase-5's epistemic layer) **completely unchanged**, exactly the reuse the original Phase 8.5 sketch called for, rather than this phase inventing a second contradiction-detection mechanism.

**Duplicate detection is grounded in an actual, previously-observed failure mode, not a hypothetical.** This project already recorded duplicate `Question` nodes for the same entity from repeated decomposition/retry passes (Phase 6's live verification, Memory.md) — the same retry pattern plausibly produces duplicate `Claim`s too, and nothing before this phase could catch it: Phase 8.3's coverage model only looks at aggregate confidence, so three duplicate claims citing the identical source would look exactly as "supported" as three genuinely independent ones. `assess_claim_validity` catches this two ways — exact `source_url` match and exact evidence-text match — deliberately NOT a near-duplicate/paraphrase detector (that would need an LLM or embedding comparison, exactly the kind of judgment call this deterministic layer draws the line at, same discipline as every UNCLASSIFIED_FIELDS decision in Phase 8.3).

**`has_independent_support` is the sharpest example of what this phase adds that Phase 8.3 genuinely couldn't see:** `distinct_source_count >= 2`, computed only over non-superseded claims' DISTINCT `source_url`s — not raw claim count, which duplicates would silently inflate. A concept "backed" by three claims all citing the same URL is not independently supported, even though it would sail through Phase 8.3's confidence check if that one source happened to be scored well.

**`detect_contradictions`' bound (`max_claims`, default 5) is the same "bounded, not an uncontrolled system" discipline Phase 8.4 established for investigation depth, applied here to prompt size instead:** an O(n²) pairwise-classification prompt against an unbounded claim set would scale badly on both cost and prompt-size grounds; skipped outright (`checked=False`, with an honest `skipped_reason`) rather than truncated silently, so a caller can always tell "checked, found nothing" apart from "never actually checked."

**Explicitly inherited, not re-proven here:** Architecture.md §0.5 already recorded that `analyze_claim_relationships`' real-world reliability at genuine contradiction detection — as opposed to reliably avoiding *false* conflict, which the original experiment did show — isn't established at scale; the controlled follow-up experiment Phase 7 itself is still waiting on. Phase 8.5 reuses the function exactly as it stands and is explicit in `ContradictionFinding`'s own docstring that a finding carries the model's reasoning for a reader to judge, not a verdict to trust blindly.

**Verified the same two-layer way as every phase in this track, both real, both against live data:** `scripts/verify_phase8_5.py`, 6/6, pure logic, no LLM/Neo4j call. Then, live, against the real "online payment" abstraction's actual claim sets — two distinct, deliberately chosen cases:

- **"card network" (4 real claims), the small case:** `assess_claim_validity` → `active=4, superseded=0, weak=4, duplicates=0, distinct_sources=4, has_independent_support=True` — every claim individually weak (consistent with this entity's already-recorded low confidence from Phase 6's original run, §0.39.2), but genuinely four distinct sources, zero duplication. `detect_contradictions` on the same 4 claims → `checked=True, findings=0`: the real LLM call succeeded end-to-end (after several free-tier schema-conformance retries along the way — normal, already-documented flakiness, not this phase's bug) and correctly classified every pair as non-contradictory. The claims themselves were essentially all "this retrieved resource doesn't answer the question" — genuinely non-contradictory content, just unhelpful, and the model correctly didn't manufacture a conflict where there wasn't one. That's the exact false-positive-avoidance behavior the original epistemic-layer experiment (§0.5) was built to confirm, now reproduced against real, live, un-mocked data instead of a designed test case.
- **"Payment gateway" (23 real claims), the bound test:** `detect_contradictions` → `checked=False, skipped_reason="23 active claims exceeds max_claims=5 -- skipped to bound pairwise LLM cost"` — the bound fired against a genuinely large real claim set, not just a fixture asserting the number.

Both a real success path and a real bound-triggered skip, observed in the same run, on real data — the two outcomes this module is actually designed to produce, both confirmed.

## §0.46 — Phase 8.6, same day: Research-complete graph artifact, and one real finding it surfaced along the way

The instruction that shaped this phase was explicit and narrow: *package and expose the research state — do not perform new research, do not compile curriculum.* Of every phase in this track, this is the one where "don't overstep the boundary" was the entire design problem, not a side constraint.

**The one design decision that makes the rule mechanically true instead of merely stated:** `compile_research_artifact` (`backend/research/artifact.py`) calls zero LLM APIs — not behind a flag, not optionally, structurally zero. It calls `build_research_plan` (8.2) and `build_readiness_report` (8.3), both already LLM-free reads, plus `assess_claim_validity` (8.5's deterministic half). Phase 8.5's `detect_contradictions` — the one real LLM call anywhere in this entire 8.1-8.6 track — is the piece this module was most tempted to fold in automatically ("just also run the contradiction check while we're compiling"), and deliberately doesn't. A caller who wants contradiction findings in the artifact runs `detect_contradictions` themselves, separately, under Phase 8.5's own bounds, and passes the results into `contradiction_reports_by_entity`. The alternative — an optional `check_contradictions: bool` parameter defaulting to `False` — was considered and rejected: a boolean default is one accidental `True` away from silently violating the rule; a parameter that doesn't exist can't be flipped. `ConceptResearchArtifact.contradictions` being `None` (not checked) versus a `ContradictionReport(checked=False, ...)` (checked, but Phase 8.5 itself skipped it) stays a real, preserved distinction through assembly — `scripts/verify_phase8_6.py`'s checks 4-5 test both halves of that distinction directly.

**The original sketch's own verify plan didn't survive contact with what the artifact actually needed to be, and that's recorded rather than quietly worked around.** Phases.md's original Phase 8.6 line proposed pointing `generate_roadmap` at "a Phase 8.6 research-complete subgraph," as if the artifact were itself a graph shape. It isn't, and shouldn't be — `ResearchArtifact` bundles policy metadata, per-field coverage, evidence provenance, and validity signals that a bare `Subgraph` (`GraphNode`/`Relationship` pairs, `backend.graph.models`) has no way to represent. What's still true, and what actually matters for PRD.md §9.3's "one world model, multiple projections" principle: `compile_research_artifact` is assembled entirely from the same upstream reads (`get_subgraph` via `build_research_plan`, `get_questions_for_entity`, `get_claims_for_question`) Phase 6's `generate_roadmap` already uses — one more read-only projection over the same canonical graph, not a second store, not a competing source of truth. The verify plan changed; the architectural principle it was trying to protect didn't.

**`prerequisite_entity_ids` is present on every `ConceptResearchArtifact`, always empty, for the same reason `ConceptResearchTarget` (Phase 8.2) already carries the identical gap:** the `requires`/`prerequisite_of` relation type doesn't exist in the graph yet (deferred alongside curriculum-source retrievers, §0.44). Kept as a real field now rather than added later, so Phase 9 can depend on this artifact's *shape* being stable today even though this one field's *content* is still pending.

**Verified the same two-layer way as every phase in this track:** `scripts/verify_phase8_6.py`, 6/6, pure logic, no LLM/Neo4j call. Then, live: `compile_research_artifact` against the real "online payment" abstraction under `EXPLORATORY_POLICY` — `is_ready=True`, 5/5 concepts, a real `generated_at` timestamp, real evidence-ref lists (4 to 23 entries per concept) with real claim ids and confidences, `contradictions=None` for every concept (correct — no contradiction reports were supplied, and the function never generated its own), `prerequisite_entity_ids=[]` for every concept (correct, the documented gap).

**A genuinely new, real finding, not something this phase set out to look for:** this was the first time `assess_claim_validity` (Phase 8.5, built but never previously run against every concept in one pass) got applied to the whole "online payment" abstraction at once. "Payment gateway" — 23 real claims — has **38 duplicate claim pairs**. That's not a hypothetical risk Phase 8.5's design notes speculated about; it's a real, substantial, previously-unquantified data-quality issue in this exact dataset, surfaced as a direct side effect of building the artifact that packages Phase 8.5's own output for the first time at this scale. Worth a real look — likely the same repeated-decomposition/retry pattern already implicated in the duplicate-`Question`-node observation (Phase 6, Memory.md) — whenever question/claim attachment is next touched, though diagnosing and fixing it is explicitly not this phase's job.

---

# Reasoning Engine Evolution — design pass, 2026-09-16 (PRD.md §10, Phases.md's R0-R5 track)

Phase 8 (§0.40-§0.46 above) proved a real capability but framed it as belonging to the Learning Portal. This section is the architectural correction: Discovery.AI is an independent research/reasoning engine; the Learning Portal is its first client, not the place its missing intelligence gets patched in from outside. **This is a design-only pass** — R0 (below) is the one part of this track that's actually "done," in the sense that it's a review exercise, not code; R1-R5 (Phases.md) are fully [VISION]. No file under `backend/` changes as part of this section. The explicit non-goals are listed in PRD.md §10.5.

**Framing, stated once so it doesn't need repeating in every subsection below:** every section that follows describes a *controlled generalization* of code that already exists and already works — `ResearchPolicy`, the Planner, Coverage model, Deep investigation orchestration, Evidence/Contradiction validation, the Research artifact, `MasterAgent`, `MessageBus`, `GroundAgent`, the Neo4j world model. None of it is being discarded. §0.56 has the concrete per-module migration mapping.

## §0.47 — Canonical Investigation State, and R0's actual test case

**Central statement:** Discovery.AI constructs and maintains an evidence-backed, dependency-aware, provenance-preserving investigation state. Answers, roadmaps, curricula, lessons, and other client-specific outputs are *projections* of that state, not separate things the engine independently produces.

**R0's gate, verbatim:** take one concrete example and describe Investigation → Tasks → Questions → Evidence → Claims → Subclaims → Dependencies → Validation → Coverage → Events → Final projections without switching terminology halfway through. Rather than inventing a clean textbook example, R0 was run against **real data already sitting in this project's own Neo4j instance** — the "How does DNS resolution work?" investigation from Phase 8.1's live smoke test (§0.41). Using real, messy data is a harder and more honest test than a made-up example would have been, and it surfaced real problems along the way (below), which is exactly what a design-review gate is for.

**The walkthrough:**

- **Investigation** — root question "How does DNS resolution work?", entity `DNS` (id `5931f230-...`), investigated under `EXPLORATORY_POLICY`.
- **Tasks** (today: implicit, inside `GroundAgent`'s recursion — R3's job is to make these explicit) — one task per entity: investigate `DNS`, investigate `Recursive Resolver`, investigate `Root name server`, investigate `TLD name server`.
- **Questions** — `DNS` itself decomposed rather than answered directly, so it has exactly one attached question ("How does DNS resolution work?") with **zero claims** — the top-level entity's "answer" is really a synthesis of its children's answers, never itself evidence-gathered. Each child got exactly one question: `Recursive Resolver`'s is "What is the role of the recursive resolver in DNS resolution?"
- **Evidence / Claims** — `Recursive Resolver`'s question has 4 real claims, confidences `[0.1, 0.15, 0.1, 0.6]`. **A real problem, found by running R0 against real data instead of a hypothetical:** three of those four claims are, verbatim, *"The provided resource does not answer the question,"* *"The resource does not answer the question,"* and *"The provided resource does not address DNS resolution or recursive resolvers."* These are retrieval failures — a source came back and didn't contain relevant information — represented as if they were low-confidence *claims about the world*. They aren't claims. §0.49 below makes this distinction explicit: a `Claim` should assert something about the subject; "this source wasn't relevant" is a different kind of fact (an evidence-gathering *outcome*, not a proposition about DNS), and conflating the two is one concrete way the current system's claim identity is weaker than it should be.
- **Subclaims** — none exist today for this investigation; today's pipeline produces one flat claim per source per question, never decomposed. §0.49/§0.53's design is what would let "the recursive resolver caches responses" and "the recursive resolver forwards queries to root servers" exist as distinct, separately-verifiable subclaims of a parent claim instead of run-on prose.
- **Dependencies** — `DNS -[decomposes_into]-> Recursive Resolver`, `Root name server`, `TLD name server` (structural/compositional, not yet distinguished as research-dependency vs. conceptual-dependency vs. teaching-prerequisite — §10.3's three-way split doesn't exist in the graph today, only one generic edge type does).
- **Validation** — never run for this investigation (Phase 8.5's `detect_contradictions` is opt-in and wasn't invoked here); if it had been, the three "doesn't answer the question" claims plus the one real 0.6-confidence claim would be a legitimate case for a contradiction/quality check to flag as "low signal-to-noise," not a contradiction exactly, but a real quality problem current tooling has no name for.
- **Coverage** — under `EXPLORATORY_POLICY`'s required fields (`definition`, `mechanism`), `Recursive Resolver` reads as `"present"` today (Phase 8.3's rule: any non-superseded claim meeting the confidence threshold counts) — **because `EXPLORATORY_POLICY.confidence_threshold=0.0`, even the three non-answer claims trivially "qualify."** This is a second real problem R0 surfaced: coverage's honesty depends entirely on the confidence threshold being non-zero and on claims actually being propositions, not retrieval-failure records — exploratory mode's permissiveness (deliberately correct for its own purpose, §0.44) masks the claim-quality problem entirely. A `"learning"`-mode policy with a real threshold (Phase 8.4/8.5's own live tests, §0.44/§0.45) would have caught this had it been run here.
- **Events** — none exist today (R2's job); the sequence that *should* have been recorded is legible only by reading raw `print()`-based logs (as this R0 review just did) rather than a queryable event log.
- **Final projections** — the only projection that exists today is the synthesized prose answer returned to `/chat`. A roadmap projection (Phase 6, real and working) and a research-readiness projection (Phase 8.3/8.6, real and working) also exist for other investigations, proving the "one state, many projections" idea already works when the underlying state is good — the DNS example's problem is upstream, in claim quality, not in the projection mechanism.

**R0's verdict:** the terminology holds together end to end without switching mid-walkthrough (the test explicitly asked for) — investigation/task/question/claim/subclaim/dependency/validation/coverage/event/projection all have one consistent meaning applied to one real case. It also did its actual job of surfacing real weaknesses the design must address, not paper over: (1) evidence-gathering failures are currently stored as claims instead of a distinct outcome type, (2) coverage's meaningfulness depends on a real confidence threshold that exploratory mode deliberately doesn't set, and (3) events/task-graph visibility genuinely don't exist yet. All three are addressed in the sections below, not deferred silently.

## §0.48 — Discovery.AI / Portal Ownership Boundary

**Discovery.AI owns:** research objectives, research policies, research tasks and their dependencies, questions, sources, evidence, claims, subclaims, claim identity, claim validation, contradictions, confidence, provenance, the knowledge graph, the investigation lifecycle. Its output is a structured, inspectable knowledge state — never a black-box prose answer with no way to inspect what produced it (already true today, worth keeping true deliberately as this evolves).

**A client (Learning Portal, a future research UI, a future CLI) owns:** presentation, sequencing for its own purpose, exercises/lessons/hints, learner state, gamification. A client requests research shaped for its purpose but never invents the epistemic structure of the research — it doesn't decide what concepts exist or what evidence supports them.

**Three distinct dependency relations, replacing one overloaded `requires`/`decomposes_into` edge (PRD.md §10.3):**
- `RESEARCH_REQUIRES` — Discovery.AI needed concept A investigated before it could properly investigate concept B. Internal to the engine's own process.
- `CONCEPTUALLY_DEPENDS_ON` — concept B is logically incoherent without concept A, independent of any teaching context. Discovery.AI's own judgment, evidence-backed like any claim.
- `TEACHING_REQUIRES` — a *client's* pedagogical judgment (learner level, course goals) about lesson ordering. Never Discovery.AI's to assert; the Learning Portal (Phase 9+) owns this entirely, informed by but not copied from `CONCEPTUALLY_DEPENDS_ON`.

Today's single `decomposes_into` edge (visible in R0's DNS walkthrough above) conflates the first two and has no representation of the third at all — exactly the gap `ConceptResearchTarget`'s already-documented `prerequisite_entity_ids` placeholder (Phase 8.2, always empty) is waiting on.

## §0.49 — Claim and Subclaim Model

**Refined, 2026-09-16 (same design pass, after further review of R0's findings before any R1 code exists):** the object chain is `RetrievalOutcome ≠ Evidence ≠ Claim ≠ Answer` — four distinct things, not points on one spectrum, and R1 must not begin by writing a large collection of classes before this chain's boundaries are precise. Each object gets its own paragraph below rather than being folded into `Claim`'s own definition, because folding them together is exactly the conflation R0 found.

**`RetrievalOutcome`** — represents what happened when a source/tool was actually used: which source was attempted, what came back, success/failure, a relevance judgment, and a failure reason when relevant. It *may* produce `Evidence`; it is never itself a `Claim`. This is the object R0's DNS example was missing entirely — three of `Recursive Resolver`'s four "claims" (§0.47) are exactly this: a source was tried, it wasn't relevant, and that fact was stored as if it were a proposition about DNS instead of a fact about the retrieval attempt.

**`Evidence`** — material that *can* support or challenge a proposition: the source, an excerpt/content, retrieval metadata, a relevance judgment, provenance. Critically, evidence existing is not the same as evidence being valid support for any particular claim — `Evidence` is a candidate, `Claim` is what asserts it actually supports something.

**`Claim`** — a proposition asserted about the world, per the structure below. Only a `Claim` carries a confidence score; a `RetrievalOutcome` does not, because "this source wasn't relevant" isn't a proposition that can be more or less true.

**`Answer`** — a human-readable synthesis, itself a *projection* of the underlying claims (§0.47's canonical-output principle), never the primary object.

**A second, independent separation R1 must also encode — five different things that are currently blurred into one number:**
```
claim existence     -- does a Claim object exist at all for this proposition
claim quality       -- is the claim actually a well-formed proposition (not a RetrievalOutcome misclassified as one)
confidence          -- the claim's own evidence-strength score
coverage            -- does a required field have a qualifying claim, per Phase 8.3's model
policy thresholds   -- what confidence a given ResearchPolicy demands before coverage counts a field "present"
```
R0's finding 2 (§0.47) is a direct consequence of NOT separating these: `EXPLORATORY_POLICY.confidence_threshold=0.0` means *policy threshold* is set so low that *claim quality* problems never surface through *coverage* — a `RetrievalOutcome`-as-`Claim` with confidence 0.1 counts identically to a real, well-sourced claim once the threshold is zero. Once `RetrievalOutcome`/`Evidence`/`Claim` are properly distinct objects (this section) and quality is asked as its own question independent of confidence (R1.1), this stops being possible even under a permissive policy — quality is a property of the claim itself, not something a threshold can accidentally launder.

**Structure**, generalizing beyond a rigid triple without losing identity (the shape the previous discussion settled on):

```
Claim
  subject, predicate, object          -- the core proposition, when it fits one cleanly
  qualifiers: list[str]                -- e.g. "usually," "for ordinary queries"
  modality: str | None                 -- e.g. "usually," "may," "under condition X"
  conditions: list[str]                -- e.g. "if the local resolver has no cached answer"
  normalized_form: str                 -- canonical text form, independent of exact wording
  source_question_id, evidence_ids, confidence, status, provenance
```

Not every claim is a clean triple (causal claims, conditional claims) — the model must not force one, but must still resolve to a `normalized_form` for deduplication (§0.50) even when subject/predicate/object don't cleanly apply.

**Subclaim, defined precisely:** a subclaim is a proposition that provides *necessary support* to a parent claim — not merely a related or shorter sentence. A relation vocabulary distinguishes *why* a subclaim relates to its parent, rather than one undifferentiated "related" edge:

```
SUPPORTED_BY        -- necessary support for the parent proposition
QUALIFIED_BY         -- narrows/conditions the parent, doesn't support or oppose it
ILLUSTRATED_BY        -- an example of the parent, not evidence for its truth
CONTRADICTED_BY       -- genuine logical/practical inconsistency (Post-Phase-5's existing epistemic-layer judgment, unchanged, §0.5/§0.45)
ALTERNATIVE_TO        -- competing explanation, not necessarily false (matches `analyze_claim_relationships`'s existing "alternative_explanation" category, §0.45 — this vocabulary and that function's output categories should stay reconciled, not diverge)
DERIVED_FROM          -- this claim was synthesized from a more granular subclaim, not sourced independently
```

A parent claim's completeness is a function of which of its *necessary* (`SUPPORTED_BY`) subclaims are themselves supported — not a raw count of anything related to it. Exact final field names/enum values are an R4 implementation decision, not fixed here; the categories and the reasoning for needing more than one relation type are the actual design commitment.

## §0.50 — Two-Tier Claim Identity (a hard rule, not a preference)

**Deterministic identity is mandatory, always available, and never blocks basic claim storage or deduplication:**
```
identity_floor = (source_url or evidence_text_normalized, entity_id, question_id)
```
This is exactly what Phase 8.5's `assess_claim_validity` already computes with zero LLM calls — and it already found 38 real duplicate pairs in one entity's claims on the very first real run (§0.46). The floor works today, unconditionally, and gets no worse if semantic extraction below never runs at all.

**Semantic identity is optional and additive:**
```
semantic_identity = (subject, predicate, object, qualifiers) | None
```
Populated only when structured extraction succeeds. **Absence must mean `semantic_identity = unknown`, never a fabricated or guessed structure.** This is not a hedge — it's a response to real, observed evidence from this exact session: every one of Phase 8's live runs hit repeated `RelationExtraction`/tool-call schema failures across multiple free-tier providers (`"missing properties: 'predicate'"`, malformed JSON, wrong tool name) — see §0.39.2, §0.41, §0.44's live logs. If claim identity *required* this extraction to succeed, claim storage and deduplication would inherit that exact reliability problem at the single most load-bearing layer of the system. Because the floor is deterministic and sufficient on its own, semantic identity can fail, degrade, or simply never run without blocking anything — it only ever adds precision when available, never removes correctness when absent.

**Consequence for R4's implementation:** deduplication, storage, and coverage checks are built against `identity_floor` first; `semantic_identity` is consumed opportunistically wherever it exists, and its absence is a normal, expected, non-error state everywhere it's read — the same "empty must be distinguishable from unknown" discipline Rules.md rule 9 already requires for claims generally, applied here to claim *identity* specifically.

## §0.51 — Commands, Events, and Projections

Three distinct things, kept distinct rather than collapsed into "messages":

- **Command** — an instruction: "investigate examples for Payment gateway." Means *please perform this operation*; may be rejected (budget exhausted, dependency unmet).
- **Event** — a record that something became true: "an examples-investigation task was created." Immutable once emitted; the source of truth for what happened, in order.
- **Read model / current state** — "what is this investigation's status right now" — derived from events, never the thing commands act on directly.

```
Command → Application service → Domain operation → Persisted state change → Domain event → Subscribers / projections / logs
```

**Command vocabulary (R2, not yet built):** `CreateInvestigation`, `InvestigateTask`, `InvestigateClaim`, `InvestigateDependency`, `DecomposeClaim`, `ValidateClaim`, `ResolveContradiction`, `ReassessCoverage`, `StopInvestigation`.

**Event vocabulary (R2, not yet built):** `InvestigationCreated`, `TaskCreated`, `TaskStarted`, `QuestionGenerated`, `EvidenceCollected`, `ClaimCreated`, `SubclaimCreated`, `ClaimValidated`, `ClaimSuperseded`, `DependencyDiscovered`, `ContradictionDetected`, `CoverageUpdated`, `TaskBlocked`, `BudgetExhausted`, `InvestigationCompleted`.

Every event carries a `correlation_id` (which investigation) and a `causation_id` (which command or prior event produced it) — the mechanism that makes "why did this branch get created" answerable after the fact, not just observable live. **Scope discipline, explicit:** an in-process typed bus only. No durable event log, no message broker, no distributed workers in this design pass — those are real future options (noted, not designed) once an in-process version has a real consumer proving the shape is right.

## §0.52 — Existing MessageBus Evaluation

`backend/agents/bus.py`'s `MessageBus` is real, tested (Phase 4), and already typed — its own module docstring describes it as "vertical-only" (parent↔child only, e.g. `BoundaryHitMessage`/`ExpansionRequestMessage`). Evaluated against R2's actual requirements:

| Requirement | Current `MessageBus` | Gap |
|---|---|---|
| Typed commands | Partial — `ExpansionRequestMessage`/`ExpansionDecision` exist, but the vocabulary is narrow (expansion-specific, not general) | Needs generalizing to the full command vocabulary above, or a sibling bus alongside it |
| Typed events | Partial — `BoundaryHitMessage` is event-shaped | Needs the full event vocabulary above |
| Horizontal (sibling-to-sibling) communication | **No** — vertical-only by design | This is the real open question, not a formality: does horizontal communication get bolted onto this bus, or does it deserve a structurally different bus given "vertical-only" was a deliberate original design choice (Rules.md rule 8's no-fixed-hierarchy spirit)? |
| Correlation/causation IDs | No | New addition either way |
| Persistence boundary | No — in-memory only, matches `GroundAgent`'s own SQLite checkpointing being the actual durability mechanism | Consistent with §0.51's "in-process only" scope — no gap to close yet |

**R2's actual decision, deferred to that phase, not settled here:** whether the existing vertical bus generalizes cleanly or whether a genuinely new, broader bus coexists with it for a transition period. The evidence above doesn't yet answer this — it defines exactly what the two options need to be evaluated against.

## §0.52.1 — R2, same day: the evaluation actually run against the real files, correcting the table above

The table above was written from general recollection during the design pass, not from re-reading `backend/agents/bus.py`/`messages.py` directly — R2's own stated acceptance criteria required the real files be read before deciding anything, so that happened first, and it corrected two things in §0.52 above rather than confirming them.

**First correction: the cited rule was wrong.** §0.52 attributed vertical-only-ness to "Rules.md rule 8's no-fixed-hierarchy spirit" — rule 8 is actually about not pre-declaring fixed `DomainAgent`/`SubdomainAgent` classes (agent *tier* structure), a different concern entirely. The real rule is **rule 9**, read directly from `Rules.md` this pass: *"No lateral (peer-to-peer) agent messaging. All coordination is vertical: a message goes to a parent or a child, never sideways to a sibling/cousin agent. If two branches need to share information, it goes up to their common ancestor and back down."* `bus.py`'s own docstring confirms this is load-bearing, not incidental: *"the only communication path that is ever realized is Ground -> (ancestor) Master, never Ground -> Ground (Rules.md rule 9's 'no lateral/peer messaging')."*

**This resolves §0.52's "real open question" outright — it was never actually open.** Generalizing `MessageBus` to carry sibling-to-sibling traffic would violate rule 9 directly, not just extend the bus's scope. The evaluation's answer is **coexist, not generalize** — settled by an existing project rule, not a fresh architectural judgment call R2 gets to make. This also isn't a loss: rule 9 exists because two branches sharing information laterally is unvalidated coordination surface with no real-world precedent (Rules.md's own "what the AI should NOT do" note on this exact rule) — the same caution this whole design pass has applied everywhere else (don't build infrastructure ahead of a proven need) already applied here, just not yet recognized as the same principle.

**Second correction: `MessageType` already has 14 values, not a narrow expansion-only vocabulary.** Re-reading `messages.py` found `TASK`, `QUESTION`, `DISCOVERY`, `EVIDENCE`, `HYPOTHESIS`, `DEPENDENCY`, `BOUNDARY_HIT`, `EXPANSION_REQUEST`, `NEW_ENTITY`, `NEW_DOMAIN`, `CONFLICT`, `ABSTRACTION_CHANGE`, `COMPLETION`, `FAILURE` — only `BOUNDARY_HIT`/`EXPANSION_REQUEST` have concrete payload classes today, the rest are explicitly "the protocol surface later phases... will give dedicated classes to when something actually emits them" (the enum's own docstring). This raised a real question: is this the same vocabulary the Reasoning Engine's proposed event list (`ClaimCreated`, `TaskCreated`, `CoverageUpdated`, ...) should extend, or a different one?

**Resolved as: a different one, by the same "coexist" logic already established for `Claim` itself.** `MessageType`'s vocabulary is scoped to one `GroundAgent` tree's own execution-internal escalation protocol (a boundary was hit, an expansion was decided) — genuinely a different layer than an investigation-level domain event ("a claim was created," "a claim transitioned status"). This project already has precedent for exactly this kind of two-layer coexistence without merging: `backend.evidence.models.Claim` (the existing, Neo4j-persisted, `GroundResult`-attached claim type) and `backend.reasoning.domain.Claim` (R1's newer, richer domain type) already coexist deliberately, unmerged, at different layers (§0.59's R1.2 entry). R2's event vocabulary gets the same treatment: new, separate types in `backend.reasoning`, not an extension of `MessageType`, and not a replacement for it either — `MessageType`'s existing 14-value taxonomy stays exactly as it is, doing exactly what it already does.

## §0.53 — Explicit Research Task Graph

Replaces invisible recursion (`GroundAgent` calling `GroundAgent` calling `GroundAgent`, real and working, but only inspectable by reading logs — exactly what R0's DNS walkthrough had to do) with a visible structure:

```
ResearchTask
  task_id, investigation_id, target_entity_id
  research_field: str | None    -- ties directly to Phase 8.4's existing UNCLASSIFIED_FIELDS targeting
  task_type: str
  parent_task_id: str | None
  dependencies: list[str]
  status: str                    -- runnable | blocked | running | complete | failed | budget_exhausted
  attempt_count: int
  budget: TaskBudget
  result_refs: list[str]
```

`GroundAgent` remains the worker that actually executes a task's investigation — this is not a `GroundAgent` rewrite. What changes is that a coordinator (§0.54) can see the whole task graph, decide what's runnable given dependencies, and — directly addressing Phase 6/8.6's real, observed duplicate-`Question`/duplicate-`Claim` problem — check *before* spawning whether an equivalent task already ran, is running, or has a reusable result, rather than always spawning a fresh `GroundAgent`.

## §0.54 — Existing MasterAgent Evaluation

`backend/agents/master_agent.py`'s `MasterAgent` already has `spawn_budget`/`broad_spawn_budget` and a real LangGraph node (`enforce_spawn_budget`) — built in Phase 4, tested (`scripts/verify_phase4.py`), confirmed via repo-wide search (Phase 8.1, §0.41) to have exactly one caller anywhere in the codebase and zero callers from the live `/chat` path, which drives `GroundAgent` directly.

| Requirement | Current `MasterAgent` | Gap |
|---|---|---|
| Explicit task graph, dependencies | No — spawns a fixed-width set of children, no dependency ordering | Needs §0.53's `ResearchTask` model |
| Runnable/blocked states | No | New |
| Retry ownership | No — retry logic lives inside `structured_call`'s own provider-fallback chain (`backend/questions/llm_client.py`), not at the task level | Needs a task-level retry policy distinct from the existing per-LLM-call one |
| Budget enforcement | **Yes, real, tested** — exactly the right shape (`spawn_budget`/`broad_spawn_budget`, enforced in its own node) | Reusable close to as-is |
| Duplicate-work prevention | No | New — this is where §0.53's "check before spawning" logic would live |

**Likely outcome, not a foregone conclusion:** resurrection and extension of `MasterAgent`, since its budget-enforcement shape is already correct and already tested — but R3's design pass should confirm this rather than assume it, keeping a controlled replacement genuinely on the table if the existing LangGraph-node structure can't cleanly absorb dependency-aware scheduling.

## §0.54.1 — R3, same day: the evaluation confirmed by re-reading the real file, not left as a leaning

Per this session's own discipline (applied identically for R2's bus evaluation, §0.52.1), `backend/agents/master_agent.py` was read directly before any R3 code was written, rather than relying on §0.54's summary of it. That confirmed the table above and settled the one open question it left ("resurrection vs. controlled replacement — not decided in advance"):

**What generalizes cleanly, confirmed by the real code:** `enforce_spawn_budget` is a dedicated LangGraph node that commits to a selection *before* `spawn_and_run` ever executes, checkpointed via `AsyncSqliteSaver` — exactly the "compute eligibility, then commit" shape a dependency-aware scheduler needs, just computing eligibility from a different, richer input (the task graph's runnable set, not a flat list slice). `spawn_and_run`'s mechanics — a `MessageBus` instance, a batch of `GroundAgent`s launched via `asyncio.gather`, then `bus.close()` — are directly reusable per scheduling round; `GroundAgent` remains the worker, confirmed by the code itself doing nothing but constructing and running it.

**What does NOT survive unchanged, also confirmed by the real code, not assumed away:** `enforce_spawn_budget`'s actual logic (`state["questions"][:budget]`, a fixed-width slice with zero dependency awareness) has to be replaced outright by a real runnable-set computation (§0.53's `compute_runnable_tasks`) — reusing the *node's position and commit-before-spawn discipline*, not its body. `MasterState` (a flat `TypedDict` built for one linear pass: one `questions` list in, one `ground_results` list out) needs additive extension to hold a `tasks: list[dict]` field whose statuses change round over round — LangGraph supports this natively via a conditional edge back to the scheduling node (a real cycle, not a hypothetical one), so the two-node linear pipeline generalizes into a scheduling loop without discarding either existing node.

**A decisive fact this evaluation surfaces that the original table didn't emphasize:** §0.54 already confirmed (Phase 8.1, §0.41) `MasterAgent` has zero callers from the live `/chat` path today. Whatever R3 builds carries zero live-traffic regression risk — a materially different risk profile than Phases.md's original "medium-high, touches real, working Phase 4 code" framing assumed, because nothing running today depends on `MasterAgent.run()`'s current behavior.

**Conclusion: resurrect and extend, confirmed rather than assumed.** No controlled replacement is warranted — the existing LangGraph-node structure absorbs dependency-aware scheduling by generalizing its node bodies and adding a cycle, not by being discarded.

## §0.55 — Investigation Lifecycle

An investigation's status today is implicitly "still running" or "the HTTP response came back" — nothing richer. A real lifecycle, exposable to a client without it needing to inspect internal `AgentState`/LangGraph structure:

```
created → planning → investigating → waiting_on_dependency → validating
  → partially_complete → complete
  → blocked | uncertain | contradictory | budget_exhausted | failed
```

`partially_complete`/`uncertain`/`contradictory` are not failure states — they're honest, valid research outcomes (directly continuous with Phase 8.3/8.4's own "the field honestly stayed missing" result, §0.44) that a client should be able to receive and act on, rather than the engine being forced into a binary done/not-done that hides real epistemic state. A client-facing status shape:

```json
{
  "investigation_id": "...",
  "status": "partially_complete",
  "completed_fields": ["definition", "mechanism"],
  "missing_fields": ["examples", "misconceptions"],
  "blocked_dependencies": [],
  "unresolved_claims": 3
}
```

## §0.56 — Phase 8 Migration

No code moves as part of this design pass. The mapping below is what a future implementation session follows — reframing ownership, not rewriting logic:

| Existing (Phase 8, `backend/agents/policy.py` + `backend/research/*`) | Becomes (Discovery.AI core) |
|---|---|
| `ResearchPolicy` | Investigation policy — same shape, reframed as engine-level, not Learning-Portal-level |
| `planner.py` (`build_research_plan`/`plan_targets`) | Task planning service, emitting `ResearchTask`s (§0.53) instead of a flat `ConceptResearchTarget` list |
| `coverage.py` (`assess_target_completeness`/`build_readiness_report`) | Coverage evaluator — logic unchanged, becomes a projection over the investigation lifecycle (§0.55) rather than a standalone report type |
| `investigate.py` (`plan_targeted_investigations`/`run_targeted_investigation`/`close_coverage_gaps`) | Task executor + gap-closing orchestration — the bounded, non-recursive investigation call becomes one `ResearchTask` execution among others in the graph, not a special case |
| `validation.py` (`assess_claim_validity`) | Claim/evidence validator — the deterministic identity floor (§0.50) |
| `validation.py` (`detect_contradictions`) | Reasoning validator — unchanged, reuses `analyze_claim_relationships` exactly as today, its output categories reconciled with §0.49's subclaim relation vocabulary |
| `artifact.py` (`compile_research_artifact`) | Investigation read model — a `ResearchArtifact` becomes one queryable projection over event-sourced state (§0.51), not the sole way to ask "what's the state" |
| Six required fields (`BASE_REQUIRED_FIELDS`/`UNCLASSIFIED_FIELDS`) | Required-output/claim-obligation vocabulary — unchanged in meaning, now understood as one example of a client-specified objective (PRD.md §10.4), not the only kind |

**The one correction this table exists to make concrete:** every module in the left column currently describes itself, in its own docstring, as Phase-8/Learning-Portal-scoped. Under this migration, none of that code changes; what changes is that `backend/research/` stops being "the Learning Portal's machinery" and becomes "Discovery.AI's reasoning core, which the Learning Portal happens to be the first caller of."

**Migration-mapping discipline, added before any R1 code exists rather than discovered mid-migration:** do not migrate existing Phase 8 *data* into the new model automatically. First produce an explicit old→new mapping for every ambiguous or invalid state already sitting in the real graph, and decide per state whether it becomes a valid object under the new model or is quarantined as evidence-of-what-happened without being treated as knowledge:

| Old state (real, observed) | New treatment |
|---|---|
| A `RetrievalOutcome`-shaped claim stored as `Claim` (§0.47's DNS example — 3 of 4 "claims" are non-answers) | Reclassify as `RetrievalOutcome`, not `Claim`; never silently keep as a low-confidence claim |
| `confidence = 0.0` under `EXPLORATORY_POLICY` | Stays a valid confidence value for a real claim; the fix is separating claim quality from confidence (above), not changing what `0.0` means |
| Missing semantic identity (§0.50) | Stays `semantic_identity = unknown` — never backfilled by guessing, never treated as a migration blocker |
| The 38 duplicate claim pairs (Phase 8.6, "Payment gateway") | Explicit `duplicate` status pointing at the canonical claim, not silently merged or silently left as 23 "independent" claims |
| Any claim never run through Phase 8.5's validation | Explicit `unvalidated` status — distinct from `validated` and from `rejected`, not defaulted to either |

**Why this table matters more than it looks:** the temptation in any migration is to write a converter that maps every old row to *some* new row so nothing "breaks." That would silently launder exactly the invalid states R0 found into the new model with a clean-looking schema — type-safety without semantic correctness. The mapping must be allowed to say "this old state was never valid; represent that it happened, but don't count it as knowledge" for at least the five rows above.

## §0.57 — Research API Boundary

The stable contract a client (Phase 9's Curriculum Compiler, first) is meant to consume, high level (full typed shape is an R5 implementation decision, not fixed here):

```
ResearchRequest
  topic, objective, mode, required_fields, learner_level (or other client-specific context), constraints (budgets)

ResearchResponse
  investigation_id, status (§0.55's lifecycle), root_entity_id,
  entities, relationships, claims, subclaims, evidence,
  coverage, contradictions, unresolved_tasks, provenance
```

A client never receives raw `AgentState`/LangGraph internals — only this shape. `ResearchArtifact` (Phase 8.6, §0.46) is the closest existing approximation of `ResearchResponse` today and is the direct ancestor this evolves from, not something separate built alongside it.

## §0.58 — R1.1, same day: the core invariant enforced as code, not just documented

The first real implementation in the Reasoning Engine Evolution track — `backend/reasoning/domain.py`. Deliberately the smallest possible slice, per explicit scope: `RetrievalOutcome`/`Evidence`/`Claim`/`Answer` only, no tasks, no bus, no `MasterAgent`, no Neo4j read/write, no LLM call, nothing beyond pure domain types with validation invariants.

**The invariant is structural, not a comment.** `classify_retrieval_outcome(outcome) -> Evidence | None` is the *only* function that produces `Evidence`, and it returns `None` for anything that wasn't a successful, relevant retrieval — a failed `RetrievalOutcome` cannot become `Evidence` because there is no code path that lets it, not because a docstring says not to. Confirmed directly, not just asserted: `backend/reasoning/domain.py` and `__init__.py` have zero imports from `backend.agents`/`backend.research`/`backend.graph`/`backend.questions` — only `pydantic` and the stdlib — so the "domain types sit below everything, nothing above them can leak back in" dependency direction (Phases.md's R1 entry) is a checkable fact, not an intention.

**Verified against the real DNS investigation data (§0.47), all 7 of the user's own acceptance points plus 8 structural checks, 12/12 on the first run (`scripts/verify_r1_1.py`):** the 3 real "does not answer the question" claims for `Recursive Resolver` correctly reconstruct as `RetrievalOutcome(success=False)` and produce no `Evidence`; the one real substantive claim (confidence 0.6) correctly becomes real `Evidence` then a real `Claim`, provenance to the real question id intact; a real `Answer` derives from that claim without the invariant allowing it to claim authority with nothing behind it; all 4 of `Recursive Resolver`'s real legacy claims, run through `reclassify_legacy_claim` — the one sanctioned migration entry point — land as `requires_reclassification`, never auto-promoted to a valid status; and all 39 pre-existing checks across `scripts/verify_phase6.py`-`verify_phase8_6.py` re-ran unaffected.

**What this proves, precisely:** Discovery.AI can now represent what actually happened during a real, already-completed investigation without confusing retrieval outcomes, evidence, claims, and answers — exactly the question this slice was scoped to answer, not the larger "can it fully reason over the world" question later slices address. R1.2 (wiring this distinction into live investigation output, not just retrospective reconstruction), R1.3 (the two-tier identity fields, §0.50), R1.4 (the full lifecycle-state transition logic), and R1.5 remain untouched, exactly as scoped.

## §0.59 — R1.2, same day: the classifier goes live, at the one real production site that needed it

R1.1 proved Discovery.AI could *represent* the distinction against already-completed data. R1.2's job, per the user's own framing, was narrower and harder: does *live* investigation produce the distinction correctly from the start. This meant finding and changing the one actual production call site, not a helper alongside it.

**The live path, mapped before any change, per the user's own explicit instruction:** `Question → GroundAgent.gather_evidence → synthesize_claim (one LLM call per resource) → Claim construction (unconditional) → GroundResult.claims → attach_claim → Neo4j`. `backend/evidence/engine.py`'s `gather_evidence` is the *only* place a `Claim` gets constructed from a retrieved resource — confirmed by grep, same discipline every phase in this session has used before touching anything. There is no second, parallel claim-creation path to also cover.

**The fix reuses a contract that already existed, rather than inventing a new judgment.** `backend/evidence/synthesis.py`'s system prompt already told the LLM, in plain language, since before this design pass began: *"If evidence says the resource does not answer the question... confidence MUST be low (below 0.2)."* Nothing was reading that signal — every draft, regardless of confidence, became a `Claim` unconditionally. `NON_ANSWER_CONFIDENCE_THRESHOLD = 0.2` in `engine.py` is that exact number, used for the first time to actually gate claim construction, not a new number invented for R1.2.

**Backward compatibility was structural, not just tested.** `gather_evidence_with_outcomes` is the real, new function that does the actual classification; `gather_evidence` (same name, same signature, same return type every existing caller — `ground_agent.py`, `scripts/verify_phase5.py` — already expects) becomes a thin wrapper returning just `.claims`. Neither call site needed to change. The one real behavior change, entirely intentional: a resource that reads as a non-answer no longer becomes a `Claim` at all, where it did before.

**A real bug surfaced by the smoke test before this ever reached a verify script.** The first implementation attempt set `failure_reason` on a `success=True, relevant=False` outcome — R1.1's own validator correctly rejected it (`"a successful RetrievalOutcome must carry raw_content"`). The fix clarified the actual semantics: `raw_content` is whatever came back, always, when `success=True`; `failure_reason` is reserved for `success=False` (a genuine retrieval/synthesis failure). Two near-duplicate constructors collapsed into one (`_retrieval_outcome_from_draft`, parametrized by `relevant`) once the semantics were right — the invariant caught the design ambiguity before it shipped, which is exactly what R1.1's validators are for.

**A real, additional improvement fell out as a side effect, not something this phase set out to add:** a `synthesize_claim` failure (`EvidenceRetrievalError`) was previously handled with a bare `continue` — zero record survived. It's now a real `RetrievalOutcome(success=False, failure_reason=...)`, consistent with R1.1's whole premise that the system should be able to represent what happened, not just what succeeded.

**Verified in two parts, and the live part's honest limitation is worth stating precisely rather than glossing over:**
- **Mocked, deterministic, 7/7 (`scripts/verify_r1_2.py` Part 1):** a fake retriever + patched `synthesize_claim` exercise a genuine answer, the exact real "does not answer the question" pattern, and a synthesis failure, in one call. All 7 of the user's acceptance points confirmed: retrieval outcomes for every resource always; the non-answer excluded from claims; the failure recorded, not dropped; evidence/claim counts both correct; `gather_evidence()` byte-for-byte unchanged for genuine answers; provenance intact.
- **Live, real network/LLM calls, against the exact real question that originally produced the failure pattern** ("What is the role of the recursive resolver in DNS resolution?") — not a full investigation re-run, just the one function that changed. Real result: this particular run's 4 sources (Wikipedia DNS/DNSSEC, two arXiv papers) *all* scored below the non-answer threshold — `retrieval_outcomes=4, evidence=0, claims=0`. Worse luck than the original investigation (which had found one genuine answer among four), most plausibly ordinary retriever-result variance under this environment's key set (no Tavily/YouTube), not a defect in the classifier. **What this specific run actually demonstrates:** the exclusion side, strongly — four real, live, un-mocked non-answers, zero false positives, zero claims wrongly created. It does not, by itself, show a genuine answer surviving a live call — that's what the mocked test establishes, and stating this precisely matters more than reporting a clean "it worked" that would blur which test proved which half of the behavior.

**Deliberately untouched, exactly as scoped:** `Claim`'s schema (`backend.evidence.models.Claim`, unchanged), Neo4j persistence, automatic deduplication (R1.3/R4), the claim lifecycle (R1.4), the bus, `MasterAgent`, any API surface.

## §0.60 — R1.3, same day: the two-tier identity becomes real, callable functions — and an honest count mismatch that isn't a bug

R1.1 defined the two-tier identity model (§0.50) in prose and left the fields sitting unused on `Claim` — `subject`/`predicate`/`object`/`normalized_form` existed, but nothing computed an actual identity from them. R1.3 closes that gap: `identity_floor`, `semantic_identity`, and `is_likely_duplicate` in `backend/reasoning/domain.py`, all pure, all reusable, none of them a lifecycle transition (that stays R4's job — `is_likely_duplicate` is the comparison a future transition will consume, not itself one).

**A real, missing field found while implementing, not anticipated in advance.** `Claim`'s deterministic floor (§0.50: "`(source_url or evidence_text_normalized, entity_id, question_id)`") requires `entity_id` — but R1.1's `Claim` never had one at all, only `source_question_id`. Added as a *required* field, not optional: an identity floor without it would let two claims about different entities collide as "the same claim" purely by wording coincidence, defeating the entire purpose of the floor. Six existing construction call sites (`domain.py`'s own `reclassify_legacy_claim`, five in `scripts/verify_r1_1.py`) needed updating — a normal, expected ripple from adding a required field to an already-shipped type, not scope creep.

**`identity_floor` ended up narrower than §0.50's original one-line sketch, and that's a real, deliberate implementation decision, not an oversight.** §0.50 said "source_url or evidence_text_normalized" — but `Claim` doesn't carry a `source_url` field directly, only `evidence_ids` (pointers to `Evidence` objects, which do have `source_url`). Rather than have `identity_floor` silently dereference `evidence_ids` (which would make a "pure, no I/O" function implicitly depend on a caller having already resolved those pointers, a hidden coupling), R1.3 scoped the floor to what a bare `Claim` object always has on its own: `(entity_id, source_question_id, normalized_form)`. Source-URL-aware identity is a real, valid future extension (R4, once claim/evidence resolution is a settled concern) — not lost, just not silently smuggled into a function whose whole point is being trustworthy in isolation.

**`semantic_identity`'s all-or-nothing rule is the direct, tested consequence of §0.50's "absence must mean unknown, never fabricated."** A claim with a `subject` and `predicate` but no `object` gets `None`, not `(subject, predicate, None, ...)` — a partially-filled tuple would silently imply more structure exists than actually does, exactly the kind of fabrication this whole design pass exists to prevent.

**The real-data test, and the count mismatch it surfaced, reported precisely rather than smoothed into a clean "it matches":** reconstructing "Payment gateway"'s real 23 claims (Phase 8.6's own exact fixture, §0.46) and running `is_likely_duplicate` pairwise found **4 duplicate pairs — not 38.** This is not a regression or a weaker mechanism; it's two real, deliberate scope differences from Phase 8.5's original entity-wide check: (1) `identity_floor` is *question-scoped* — two claims from *different* questions about the same entity are never compared as potential duplicates by this function, where Phase 8.5's check flattened an entity's entire claim set together regardless of which question produced each claim; (2) `identity_floor` never compares `source_url` (per the paragraph above), where Phase 8.5's check did. Both are real, narrower-but-more-conservative design choices, not omissions discovered too late to fix — question-scoping in particular is arguably *more correct*: two claims that happen to share wording but come from investigating different questions about an entity are a weaker signal of true duplication than two claims answering the identical question identically. The honest claim this test supports is "the new, general mechanism finds real duplicates in known-duplicated data" (4 > 0, confirmed), not "the new mechanism reproduces the old count" (it doesn't, for understood reasons) — `scripts/verify_r1_3.py` prints this distinction directly rather than letting a bare pass/fail imply more agreement than exists.

**Verified, same two-layer discipline, all real, no LLM/Neo4j call in Part 1:** `scripts/verify_r1_3.py`, 5/5 pure checks (floor shape, matching-floor duplicate, different-entity never-duplicate, semantic identity absence, semantic identity presence), plus the live Payment-gateway check above. All 51 pre-existing checks across Phase 6/8.1-8.6/R1.1 (39+12) plus R1.2's own 6-7 re-confirmed unaffected.

**Deliberately untouched, exactly as scoped:** no lifecycle transitions (R1.4/R4's job — `is_likely_duplicate` returning `True` does not itself set any claim's `status`), no source-URL-based identity yet (the honest gap above), no bus, no `MasterAgent`, no API.

**Architectural warning, recorded before R1.4 rather than discovered mid-implementation:** `identity_floor` is a *provisional* identity signal, not yet a globally unique claim identity. It answers "are these likely duplicates within this investigation context" — scoped to one `entity_id` and one `source_question_id` — not "are these the same proposition anywhere in Discovery.AI." A claim about "DNS caching reduces lookup latency" discovered while investigating DNS and the identical proposition discovered later while investigating a different, unrelated question would correctly NOT be flagged duplicate by today's `identity_floor`, even though they're the same real-world fact. That broader, cross-investigation semantic identity is real future work (`semantic_identity`, once reliably extractable at scale, is the natural candidate to eventually carry this — Architecture.md §0.50's own note that it's optional and additive already anticipates this), not something R1.3 claimed to solve.

## §0.61 — R1.4, same day: legal claim transitions, and why status is never derived from confidence

R1.3 gave `Claim` an identity. R1.4 gives it a lifecycle — but scoped precisely to the question the user posed it as: *given a Claim object, which statuses may it move between, and what conditions are required?* Not orchestration, not automatic validation, not a decision about *when* something should transition — that's application-layer work for later.

**The one rule that shaped every other decision in this section:** `transition_claim` reads `claim.confidence` nowhere in its body. This is not an oversight to fix later — it's the entire point. `if confidence > 0.7: status = ACTIVE` would recreate R0's original failure (Architecture.md §0.47) one layer up: a status is supposed to be an explicit, asserted epistemic fact ("this claim has been validated," "this claim has been superseded by a better one"), and collapsing that back into a bare number is exactly the confusion this whole track exists to undo. `transition_claim` instead requires an explicit `reason` and `actor` for every single transition, no exceptions, including the ones that feel routine (`candidate → normalized`) — a status is never free.

**The legal graph, and what's deliberately left undefined rather than guessed:**
```
candidate    -> {normalized, rejected, requires_reclassification}
normalized   -> {supported, duplicate, disputed}
supported    -> {validated, superseded}
validated    -> {active, disputed}
active       -> {superseded, disputed}
```
Every other status (`rejected`, `duplicate`, `disputed`, `superseded`, `legacy_invalid_claim`, `requires_reclassification`, and R1.1's original, now-unused `"attached"`) has an empty legal-targets set — not because a further transition could never exist, but because inventing one now would be exactly the "implement every possible transition before the meanings are proven" mistake the scoping for this phase explicitly named and rejected. `"attached"` in particular is quietly retired by this graph: R1.1's original placeholder lifecycle sketch included it, the user's authoritative R1.4 lifecycle doesn't, and rather than force it into the graph to preserve an unused enum value, it's simply never a legal target or source here — the enum stays for now (removing it would be a breaking change to an already-shipped type for no real benefit), but nothing routes through it.

**`"active"` means epistemically active — a real decision, made explicitly, not defaulted into:** the user posed this as an open question (Option A: "part of the investigation's accepted knowledge state" vs. Option B: "available for downstream consumers") and recommended Option A. Taken as the actual design: a claim's status describes its own epistemic standing within Discovery.AI's reasoning, never whether some particular client (the Learning Portal, a future API consumer) happens to be using it — that's the client's own filtering concern, layered on top, never a fact recorded on the claim itself. This keeps the ownership boundary from §0.48 intact one level deeper: Discovery.AI owns what a claim *is*; a client decides what to *do* with it.

**Structural conditions enforced per-transition, matching the specific reference each target status actually needs:** `superseded` requires `superseded_by`; `duplicate` requires `duplicate_of`; `supported` requires `evidence_ids` to already be non-empty on the claim (you cannot become "supported" by assertion alone — there has to be something there). `provenance_note` being required is generalized in this same pass from R1.1's narrower rule ("only the exception statuses need a reason") to "every status except the initial `candidate` default needs one" — every claim that has moved anywhere in its life now carries a stated reason, not just the unusual outcomes.

**A real correctness choice made deliberately, not by default: `transition_claim` reconstructs through `Claim(...)`, not `claim.model_copy(update=...)`.** Pydantic's `model_copy` does not re-run validators — using it would mean `transition_claim`'s own hand-written checks (superseded needs a reference, supported needs evidence) are the *only* thing enforcing `Claim`'s `_status_consistency` invariant on the result, with nothing double-checking that they stayed in sync with the model's own rule as either evolves. Reconstructing through the real constructor makes `Claim`'s own validator the actual, single source of truth for what a valid claim looks like — `transition_claim`'s pre-checks exist to produce a clear, specific rejection reason before construction, not to duplicate the model's authority over its own invariants.

**Verified, pure, no I/O, matching this scope precisely:** `scripts/verify_r1_4.py`, 12/12 — the full legal chain to `active`; both illegal transitions the user specifically named (`candidate → active`, `candidate → superseded`) correctly rejected; `active → superseded` rejected without a reference, allowed with one; confidence proven irrelevant by direct comparison (a 0.01-confidence claim and a 0.99-confidence claim transition identically); empty `reason`/`actor` always rejected; the original `Claim` never mutated; the result independently re-constructible (proof it's genuinely re-validated, not copied around the validator); R1.1's retrieval-failure invariant confirmed untouched. All 57 pre-existing checks (Phase 6/8.1-8.6/R1.1/R1.3) re-confirmed unaffected.

**Deliberately untouched, exactly as scoped:** no automatic transitions triggered by an LLM, retriever, or confidence value; no transition history beyond the single most-recent `provenance_note`/`last_transition_actor`; no Neo4j persistence of any transition; no event publication (the bus is R2, not this); no orchestration deciding *when* a transition should happen (R1.5/R4/application-layer work).

## §0.62 — R1.5, same day: closing R1's own coverage gaps — R1 is now fully built

R1.5 is consolidation, not new capability, exactly as scoped ("the final pure validation/serialization boundary before the bus or task graph"). Its actual job was auditing R1.1-R1.4's own test coverage for gaps that accumulated as each slice tested only what it added, and closing them before moving past R1 entirely.

**Two real, honest gaps found by that audit, not invented to have something to fix:**

1. **Serialization coverage was uneven.** R1.1's own verify script gave `Claim` a `model_dump_json` → `model_validate_json` round-trip test; `RetrievalOutcome`, `Evidence`, and `Answer` — three of the four core types — never got one, across R1.1-R1.4. A type that's never been round-tripped could have a field that doesn't survive serialization (a subtle bug pydantic wouldn't necessarily surface any other way) and nothing in this whole track would have caught it before now.

2. **Several identifier-shaped required fields had no non-empty constraint.** `RetrievalOutcome.question_id`/`source_title`/`source_url`/`source_type`, `Evidence.retrieval_outcome_id`/`source_title`/`source_url`/`source_type`, `Claim.entity_id`/`source_question_id` — none of these had `Field(min_length=1)`, meaning an empty string was silently valid everywhere R1.1-R1.4 shipped them. Added `min_length=1` to all of them this pass — a small, purely additive hardening (nothing in any existing test constructs these with empty strings, confirmed by re-running all of R1.1/R1.3/R1.4's suites unmodified before writing anything new).

**The deserialization-invariant check (`check_invariant_fires_through_deserialization`) is the one genuinely new *kind* of test in this pass, not just filling a gap the others already had a template for.** It hand-builds JSON representing an invalid `RetrievalOutcome` (`success=false, relevant=true`) and calls `model_validate_json` directly — bypassing the Python constructor path entirely — to confirm the cross-field invariant still fires. This matters because a `@model_validator(mode="after")` *should* run identically regardless of construction path (that's how pydantic v2 works), but "should, by the framework's own contract" and "confirmed, against this actual model" are different levels of assurance — and this whole design pass exists because assumptions like that are exactly where real bugs have hidden before (R1.2's own smoke-test-caught validator bug, §0.59). Worth confirming once, explicitly, rather than trusting the framework silently.

**Verified: 7/7, pure, no I/O.** All 4 core types now have a real round-trip test (both fully-populated and sparse-default cases for `Claim`); the deserialization-invariant check; all 6 new `min_length=1` constraints confirmed to actually reject empty strings, not just declared. All 69 pre-existing checks (Phase 6/8.1-8.6/R1.1/R1.3/R1.4) re-confirmed unaffected by the new constraints.

**R1 is now fully built — all five internal slices (R1.1-R1.5) complete.** The next work in this track, per the user's own explicit ordering throughout, is the bus (R2) or the task graph (R3) — not attempted in this pass, and not something R1's completion should be read as inviting without a fresh scoping conversation first, matching the discipline every phase in this session has followed.

## §0.63 — R2, same day: typed events/commands for what R1 already produces, and why the bus evaluation ended the risk before any code

R2's own acceptance criteria (§0.51/Phases.md) required the `MessageBus` evaluation (§0.52) to "actually run before any code changes, not be assumed." It ran first, against the real files (`backend/agents/bus.py`, `backend/agents/messages.py`), not from the design pass's memory of them — and it changed the outcome.

**The evaluation found the design pass's own citation was wrong.** §0.52 originally justified `MessageBus`'s vertical-only shape as following "Rules.md rule 8's no-fixed-hierarchy spirit." Re-reading `docs/Rules.md` directly during this pass found that rule 8 is about not pre-declaring fixed `DomainAgent`/`SubdomainAgent` classes — unrelated. The real rule is **rule 9**: *"No lateral (peer-to-peer) agent messaging. All coordination is vertical: a message goes to a parent or a child, never sideways to a sibling/cousin agent."* This is confirmed load-bearing, not incidental — `bus.py`'s own docstring cites it directly. §0.52.1 records this correction as a dated addendum, not a silent edit to §0.52, matching this session's established correction discipline.

**This resolves R2's own listed "design decision to settle" outright, rather than requiring a fresh judgment call:** extending `MessageBus` to also carry horizontal (sibling-to-sibling) traffic would violate an explicit, cited project rule — not just cut against a design preference that could go either way. **Coexist, not generalize.** `bus.py`/`messages.py` are untouched by this phase, and this is the correct outcome, not a deferral.

**A second, smaller finding from the same re-read:** `MessageType` (in `messages.py`) already has 14 values, with only `BoundaryHitMessage`/`ExpansionRequestMessage` given concrete classes. This could have been mistaken for the vocabulary this phase needed to define. It is not: `MessageType` is Phase 4's `GroundAgent`/`MasterAgent` execution-internal escalation protocol (boundary hits, expansion requests, spawn decisions); R2's events describe investigation-level domain facts (a retrieval happened, evidence was collected, a claim was created or transitioned). Different layers, same **coexist, don't merge** precedent this project already established for `backend.evidence.models.Claim` vs. `backend.reasoning.domain.Claim` — applied again here rather than re-litigated.

**What was actually built, scoped to what that evaluation left as necessary:** `backend/reasoning/events.py` —
- `DomainEvent` (base: `event_id`, mandatory `correlation_id`, optional `causation_id`, `occurred_at`) — the shared shape for a fact that has already happened, never itself rejectable.
- `RetrievalOutcomeRecorded`, `EvidenceCollected`, `ClaimCreated` — each wraps an already-produced R1 object (`RetrievalOutcome`/`Evidence`/`Claim`) unchanged; pure builder functions (`record_retrieval_outcome` etc.) construct them without re-deriving anything the caller didn't already have.
- `ClaimTransitioned` — carries both `previous_status` and `new_status` plus `reason`/`actor`, so the event alone answers "why is this claim in this status" without a separate fetch.
- `TransitionClaimCommand` — the one command defined, matching the one real state-changing operation R1.4 exposes (`transition_claim`). Unlike an event, a command may be rejected — `transition_claim` already does this via `ClaimTransitionRejected`, so issuing the command is a request, not a guarantee. It references the claim by `claim_id: str` rather than embedding a live `Claim` object — the one intentional field-naming difference from `transition_claim`'s own signature, correct because a command is data crossing a boundary while `transition_claim` is called in-process against an object the caller already holds.

**Deliberately not built:** `InvestigationCreated`, `TaskCreated`, `CoverageUpdated`, or any command beyond `TransitionClaimCommand`. Those name objects (`Investigation`, `ResearchTask`) that don't exist in the domain model yet — R3's job. Defining event types for objects nothing can yet produce would be the same "type-safety without semantic correctness" trap §0.56 already named and rejected for claim migration; the same discipline applies to event design.

**Also deliberately not built:** any bus wiring. This slice is types and pure builder functions only — no publish/subscribe mechanics, no durable log, no broker, no distributed workers. Wiring these events into a real publish path is a later, separate R2 sub-slice, mirroring R1.1 → R1.2's own "types first, wire into live output second" precedent rather than repeating it inline.

**Verified: `scripts/verify_r2_1.py`, 7/7, pure logic, no LLM/Neo4j/retriever/bus call.** Each builder wraps its real R1 object unchanged (#1); a 3-event causation chain (`record_retrieval_outcome` → `record_evidence_collected` → `record_claim_created`, each `causation_id` pointing at the prior `event_id`) is real and traceable back to a root event with `causation_id is None` (#2); empty `correlation_id` is rejected — not defaulted — on every event type and on `TransitionClaimCommand` (#3); `ClaimTransitioned` carries both statuses (#4); `TransitionClaimCommand`'s fields are a faithful match for `transition_claim`'s real parameters via `inspect.signature`, with `claim_id` explicitly carved out as the one correct, intentional difference rather than treated as a mismatch (#5); every event type and the command survive a `model_dump_json` → `model_validate_json` round trip (#6); `events.py`'s own source was inspected directly to confirm every import is stdlib, pydantic, or `.domain` — zero cross-package imports, keeping `backend.reasoning`'s dependency-direction guarantee intact through this new file too (#7). All 69 pre-existing checks (Phase 6/8.1-8.6/R1.1/R1.3/R1.4/R1.5) re-confirmed unaffected by re-running them unmodified.

**R2 is complete as scoped.** Its biggest listed migration risk ("touches real, working Phase 4 code") did not materialize, because the evaluation that was supposed to precede any code change concluded no change to that code was warranted. The next work in this track, per the user's explicit "loop until R3" instruction, is R3 (Explicit Research Task Graph) — starting with the same discipline: a real evaluation of `backend/agents/master_agent.py`, read directly rather than recalled, before any code is written.

## §0.64 — R3, same day: the ResearchTask domain type, and the evaluation that made "resurrect and extend" a confirmed fact rather than a leaning

R3's own listed design decision — "resurrect-and-extend `MasterAgent` vs. controlled replacement, leaning resurrection, not decided in advance" — was settled first, by re-reading `backend/agents/master_agent.py` directly (§0.54.1). That confirmed resurrection, identified exactly which pieces generalize (the checkpointed commit-before-spawn node shape, the bus+`GroundAgent`-per-batch spawn mechanics) and which don't (the flat-slice budget logic, the one-shot `MasterState` shape) — turning R3's implementation scope into a precise, evidence-based list rather than a guess.

**First slice, scoped the same way R1.1 was scoped ("the smallest possible slice... no bus, no orchestration wiring"):** `backend/reasoning/tasks.py` defines `ResearchTask` (§0.53's shape) and four pure functions — `initial_status`, `compute_runnable_tasks`, `detect_duplicate_task`, `transition_task` — with zero `MasterAgent`/LangGraph/`GroundAgent`/bus wiring. That wiring (replacing `enforce_spawn_budget`'s body, adding the scheduling cycle to `MasterState`) is explicitly later R3 work, mirroring R1.1 → R1.2's own "types first, wire into live output second" precedent rather than repeating the reasoning for why that split is used again.

**Directly targets the two gaps §0.54's evaluation table marked "New" — no existing code was available to reuse for either:**
- **Runnable/blocked states.** `initial_status` derives a fresh task's starting state structurally from whether it names any dependency (no dependency → `"runnable"`; any dependency → `"blocked"`) — nothing asserts this, it falls out of the graph shape. `compute_runnable_tasks` is the pure, read-only computation of which blocked tasks have *all* their dependencies `"complete"` (not just one of several — the multi-dependency case is exactly where a naive "any dependency done" check would wrongly unblock a task too early, and is explicitly tested).
- **Duplicate-work prevention.** `detect_duplicate_task` compares `(investigation_id, target_entity_id, research_field, task_type)` against existing tasks — the same structural-identity-comparison pattern as R1.3's `identity_floor`, applied to tasks instead of claims — and explicitly does not flag a match against a `"budget_exhausted"` prior task, since a permanently-dead task should never block a genuinely fresh attempt at the same work. This is the concrete fix for the real, quantified Phase 6/8.6 duplicate-`Question`/duplicate-`Claim` problem that motivated §0.53 in the first place.

**`transition_task` mirrors `transition_claim`'s (R1.4) discipline exactly, deliberately, not coincidentally:** every transition requires a non-empty `reason` and `actor`; the legal-transition graph (`blocked→runnable→running→{complete, failed}`, `failed→{runnable, budget_exhausted}`) is enforced, not inferred; retrying (`failed→runnable`) is only legal while `attempt_count < max_attempts`, and `budget_exhausted` is rejected unless attempt exhaustion is real, not asserted early. The result is reconstructed through `ResearchTask(...)`, not `model_copy(update=...)`, for the same reason R1.4 made that choice: `model_copy` skips validators, which would make this function's own hand-written checks the *only* thing enforcing `_status_consistency`, with nothing keeping the two in sync as either evolves.

**One deliberate design split, stated explicitly rather than left implicit:** `"blocked"`/`"runnable"` are structural facts derived from the dependency graph (no `reason`/`actor` needed — nothing decided them, the graph shape did); `"running"`/`"complete"`/`"failed"`/`"budget_exhausted"` are execution outcomes an actor asserts, and the model itself requires `provenance_note` whenever status is one of those four — the same "status is an explicit, asserted fact" principle R1.4 established for `Claim`, applied here to keep task lifecycle and claim lifecycle epistemically consistent with each other.

**Verified: `scripts/verify_r3_1.py`, 10/10, pure logic, no MasterAgent/LangGraph/GroundAgent/bus/Neo4j/LLM call.** `initial_status`'s two cases; `compute_runnable_tasks` correctly withholds eligibility until *all* dependencies (not just one of several) are complete; `detect_duplicate_task` finds a real duplicate, correctly ignores a task differing in any one of the four identity fields, and correctly ignores a `budget_exhausted` prior; every legal transition edge succeeds and every illegal one (skipping `runnable`, skipping `running`) is rejected; empty `reason`/`actor` rejected on every attempt; the retry path genuinely increments `attempt_count` on failure and is rejected once attempts are exhausted; `budget_exhausted` rejected until attempt exhaustion is real; `ResearchTask` round-trips through `model_dump_json`/`model_validate_json` both fully-populated and sparse; `tasks.py`'s own source inspected directly to confirm zero cross-package imports; the `_status_consistency` invariant confirmed to actually fire for all four execution statuses, not just declared. All 76 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1) re-confirmed unaffected.

**Deliberately not built in this slice:** any change to `master_agent.py` itself (the `enforce_spawn_budget`/`spawn_and_run` node bodies, the scheduling cycle, `MasterState`'s extension to carry a task list) — §0.54.1's evaluation identified exactly what that work requires, but doing it is a separate, later R3 sub-slice, not this one. Per the user's own "loop until R3, rectify further updates after R3 with different tests" instruction, this pure-logic slice is where R3's real-evaluation-plus-tests obligation is satisfied for this pass; wiring `ResearchTask` into `MasterAgent`'s live LangGraph is left for that later pass rather than compressed into this one.

## §0.65 — R3.2, same day: ResearchTask becomes a real MasterAgent input, `run()` untouched

R3.2 is exactly the wiring §0.64 deferred: `MasterAgent.run_task_graph(tasks, task_questions, *, actor, task_budget) -> TaskGraphResult`, a new method alongside the existing `run()` — not a replacement, not a refactor of it. `run()` has zero lines changed; its own `MasterState`/LangGraph graph is untouched. This is the same "existing implementation → small extension → migration → eventual cleanup" discipline this whole track has followed since R1.2's `gather_evidence`/`gather_evidence_with_outcomes` split.

**The scheduling loop, concretely, per round:** unlock newly-runnable blocked tasks via R3.1's `compute_runnable_tasks`; detect duplicates via `detect_duplicate_task` against already-`complete`/`running` tasks and short-circuit them straight to `complete` (copying the canonical task's `result_refs`, never independently executed); apply `task_budget` (a new, independently-settable concept — total tasks this call will execute — defaulting to `spawn_budget` only because that is this instance's already-configured "how much work at once" number, not because the two mean the same thing); transition the selected batch to `running`; construct and run real `GroundAgent`s via `asyncio.gather(..., return_exceptions=True)` (isolating one task's failure from crashing the round); transition each to `complete`/`failed` from its real, live outcome.

**A genuine, stated scoping decision, not a hidden shortcut:** this round-robin repetition is a plain Python `while` loop inside ONE checkpointed LangGraph node (`schedule_and_execute`), not a graph-level conditional-edge cycle. Both are legitimate LangGraph usage — `run()`'s own two-node linear shape doesn't need multiple rounds, so it never had to make this choice. Promoting the loop to real graph edges (which would let a crashed process resume from mid-round, not just re-run `ainvoke` from scratch) is a real, named, deferred extension — the safety cap (`len(tasks) + 1` rounds) guarantees termination regardless either way.

**Validation happens before any LangGraph state exists, and is eager, not discovered lazily.** `backend/reasoning/tasks.py` gained two more pure functions for this slice: `validate_task_graph` (DFS-based; rejects an unknown dependency id, or any dependency cycle, via `TaskGraphValidationError`) and `compute_tasks_blocked_by_failed_dependency`. The second draws a real, deliberate distinction R3.2's own acceptance tests forced into the open: a dependency that is merely `"failed"` might still succeed on retry, so a task blocked on it correctly stays ordinary, ambiguous-free `"blocked"`; a dependency that reached `"budget_exhausted"` is permanently dead, and a task blocked on *that* is explicitly, separately reported — "do not execute B as if A succeeded" made concrete as a queryable fact, not just an informal guarantee.

**One real design consequence of R3.1's own zero-cross-package-import contract, worked through rather than quietly loosened:** `ResearchTask` still has no `Question` field — adding one would mean `backend.reasoning` importing `backend.questions`, breaking the dependency-direction guarantee §0.58 established and every subsequent R1/R2/R3 slice's own verify script has re-confirmed by direct source inspection. Instead, `run_task_graph`'s `task_questions: dict[str, Question]` parameter carries the actual investigation payload at the orchestration layer, where `backend.agents` importing both `backend.reasoning` and `backend.questions` is exactly the allowed direction. `backend/agents/models.py` (via the new `TaskGraphResult`) is the first file to actually exercise that import — a one-way addition, confirmed safe (`backend.reasoning` has zero imports from `backend.agents`; no cycle).

**`AgentStatus.BOUNDARY_HIT` is deliberately treated the same as `AgentStatus.COMPLETE`** when recording a task's outcome — not a new judgment invented for this slice, but the same convention `scripts/verify_phase4.py` already encodes (`assert r.status in (AgentStatus.COMPLETE, AgentStatus.BOUNDARY_HIT)`, treating both as "not failed"). Acting on a task-graph-spawned boundary hit — escalating it, spawning a new branch — is Phase 7's abstraction-change protocol, explicitly out of scope for R3.2 and not silently absorbed into it.

**Verified: `scripts/verify_r3_2.py`, 11/11 deterministic checks, plus one optional live-provider smoke reported separately (Rule 14) and skipped in this environment (no provider key configured).** `decide_next_step` is monkeypatched exactly as `scripts/verify_phase4.py` already does — every check runs the real `MasterAgent`, real LangGraph state/checkpointing, and real `GroundAgent`, with only the one LLM-calling function replaced, never a fake orchestration layer. Covers: the exact DNS acceptance example's initial runnable/blocked split, dependency unlock, partial completion; duplicate detection; missing-dependency and dependency-cycle rejection at both `validate_task_graph` and `run_task_graph` itself; failed-vs-exhausted dependency handling; budget exhaustion (`task_budget=1` against the 3-task graph executes exactly one task, terminates in 2 rounds); a raising `GroundAgent` correctly recorded `"failed"` with its real error text preserved, not swallowed; idempotent re-entry (a second `run_task_graph` call against the first's own returned, now-`complete` tasks makes zero further LLM calls and executes zero further tasks); and the full graph completing end-to-end through the real orchestration path in 3 rounds (1 to run A, 1 to unlock-and-run B+C together, 1 to confirm nothing remains). All 79 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1) re-confirmed unaffected.

**Known limitations, stated rather than hidden:** two tasks with identical identity that both start already-`runnable` in the *same* round are both executed independently (duplicate suppression is only guaranteed once one has reached `running` or `complete` — the acceptance example's own duplicate-detection test uses the simpler, already-covered case); `BOUNDARY_HIT` handling defers real escalation, as stated above; idempotency is verified at the scheduler's data level, not via checkpointer-thread resumption across separate calls (each `run_task_graph` call gets its own checkpoint thread today, derived from the `MasterAgent` instance's own `agent_id`).

**R3 is now fully built across both its slices.** The next work in this track, per the original R3.2 prompt's own explicit non-goals, is R4 (claim/subclaim lifecycle orchestration — much of which R1.4 may already substantially satisfy at the single-claim level, worth reconciling rather than re-building) or R5 (the stable Research API) — not attempted in this pass, and not something R3's completion should be read as inviting without confirming scope first, the same discipline this whole track has held to since R0.

## §0.66 — R4.0, same day: the claim-lifecycle orchestration audit — three disconnected Claim representations, not one system needing new mechanics

An evaluation-only audit, no production code changed, run before any R4 implementation per this track's own established discipline (§0.52.1, §0.54.1). Its purpose: determine whether R4 is new lifecycle mechanics or orchestration around what R1.4 already built. Direct file inspection, not assumption.

**The central finding: there are three separate Claim representations in this codebase today, never unified, each with a different shape:**
1. `backend.evidence.models.Claim` (`backend/evidence/models.py:47`) — the real, live construction path (`backend/evidence/engine.py:146`). No `status` field; only `superseded_by` and an always-empty `contradictions` list (reserved for Phase 7).
2. `backend.graph.models.ClaimNode` (`backend/graph/models.py:84-97`) — the persisted Neo4j view. Fields: `id, evidence, reasoning, confidence, source_title, source_url, source_type, valid_from, superseded_by`. **No `status` field exists in the graph schema at all.**
3. `backend.reasoning.domain.Claim` (R1.1-R1.5) — the only one with a real `ClaimStatus` lifecycle (`domain.py:106-119`) and `transition_claim` (`domain.py:342-388`). Never persisted; never constructed from real Neo4j data except in a one-off test fixture (`verify_r1_1.py`'s own live-data reconstruction).

**`transition_claim` has zero production callers**, confirmed by repo-wide grep — called only from `scripts/verify_r1_4.py` and `scripts/verify_r2_1.py`. This is the same shape as R3's pre-R3.2 finding about `MasterAgent`: real, tested (12/12), completely disconnected from any live path. There is no "bypass" of `transition_claim` anywhere (grep for direct non-initial `Claim(status=...)` construction outside `domain.py` finds nothing) — the actual gap is structural, not a violation: the real, persisted claim-mutation path (`supersede_claim`, `graph/interface.py:889-911`, itself with zero production callers, exercised only by `verify_phase5.py`) operates on `ClaimNode`, which has no `status` concept to bypass in the first place.

**Validation is real but report-only, never wired to any mutation.** `assess_claim_validity` (`research/validation.py:22-64`, pure, deterministic, 6/6 tests) and `detect_contradictions` (`validation.py:67-132`, the one real bounded/opt-in LLM call, reusing `analyze_claim_relationships` unchanged) both produce reports (`ClaimValidationReport`, `ContradictionReport`) that nothing downstream consumes. Phase 8.6's real, quantified finding — 38 duplicate claim pairs in "Payment gateway" — has been *reported* since Phase 8.5 shipped and *reconciled in explanation* by R1.3 (the 4-vs-38 count difference, §0.60) but never *resolved*: no code anywhere calls `transition_claim` (or any equivalent) to actually mark either claim in a duplicate pair non-canonical. This is precisely R4's own pre-existing, still-open acceptance criterion (Phases.md's original R4 entry).

**Subclaims do not exist in code** — zero matches for `subclaim`/`sub_claim`/`SubClaim` anywhere in `backend/`. They do have a precise, already-settled design from before R1 was written (§0.49: "a subclaim is a proposition that provides *necessary support* to a parent claim," with a named relation vocabulary `SUPPORTED_BY`/`QUALIFIED_BY`/`ILLUSTRATED_BY`/`CONTRADICTED_BY`/`ALTERNATIVE_TO`/`DERIVED_FROM`) — a subclaim is a `Claim` in a relation to another `Claim`, not a new class, not a research task, not a raw text fragment. `Claim` has no field to express this relation today. Two superficially similar but genuinely distinct existing things, worth not confusing with it: `analyze_claim_relationships` (`questions/relationships.py`) classifies **peer** claims answering the same question, not parent/child support; `audit_synthesis`/`AtomicClaim` (`questions/audit.py`, zero production callers) decomposes an answer for content-provenance auditing, unrelated to claim hierarchy.

**Conclusion — direct answer to the audit's own question:** R4 is overwhelmingly orchestration and a bridging layer around lifecycle mechanics R1.4 already built, plus one small, genuinely new piece of domain surface (the parent/subclaim relation, already specified in §0.49, never coded). It is not a new lifecycle system. Rebuilding `ClaimStatus`/`transition_claim` would duplicate something that already passes its own tests; what's missing is (a) a real `ClaimNode ↔ reasoning.domain.Claim` mapping (nothing converts one to the other today), (b) a validation-orchestration step that actually calls `transition_claim` from `assess_claim_validity`'s findings, and (c) the additive parent/subclaim fields.

**Proposed R4 slices (not started):** R4.1 (pure `ClaimNode ↔ reasoning.domain.Claim` mapping, no persistence write-back), R4.2 (validation orchestration — resolve the real 38-pair finding via real `transition_claim` calls), R4.3 (additive parent/subclaim relation fields on `Claim`), R4.4 (persistence decision + wiring — explicitly deferred pending a scoping conversation on whether a lifecycle decision reaches Neo4j this pass, since `ClaimNode` has no `status` property to write it into without a schema change). Recommended next slice: **R4.1** — every other slice depends on it, and it is pure (no persistence-scope decision required first).

**Tests run for this audit (no code changed): `verify_r1_1.py`, `verify_r1_3.py`, `verify_r1_4.py` (12/12), `verify_r1_5.py` (7/7), `verify_r2_1.py` (7/7), `verify_phase8_5.py` (6/6), `verify_phase8_6.py` (6/6) — all exit 0, 0 failed, 0 skipped, no provider-dependent limitation (all pure/deterministic or read-only against already-persisted data).**

## §0.67 — R4.1, same day: the pure ClaimNode → reasoning.domain.Claim bridge, and why every mapped claim lands at the same status

R4.0's audit named this the recommended next slice: every other R4 slice depends on it, and it needed no persistence-scope decision first. `backend/research/claim_mapping.py`'s `claim_node_to_domain_claim(node, *, entity_id, source_question_id) -> Claim` is the one sanctioned forward mapping — pure representation conversion, no validation logic, no persistence, no lifecycle mechanics invented.

**`entity_id`/`source_question_id` are required, caller-supplied, never derived.** A `ClaimNode` alone carries neither — they come from the graph traversal that fetched it (which entity's question this claim answers). `ClaimMappingRejected` rejects an empty value on either, or empty/whitespace-only `evidence` text, explicitly — never fabricated as `"unknown"`.

**Every mapped claim lands at `status="requires_reclassification"`, unconditionally — a deliberate, single, uniform rule, not a per-case judgment call.** The reasoning: `ClaimNode` carries no R1-lifecycle status information at all (R4.0 confirmed this — only a binary `superseded_by`-or-not fact exists). This reuses `reclassify_legacy_claim`'s (R1.1) own already-sanctioned status for exactly this situation — real, persisted data never run through this model's own checks — rather than inventing a new judgment about which legacy claims "feel" more trustworthy. Two concrete consequences this design was built to guarantee, both tested: a `confidence=0.99` `ClaimNode` still maps to `requires_reclassification` (no confidence-based promotion — Rule B); a `ClaimNode` whose `evidence` text is R0's own real DNS non-answer string ("The provided resource does not answer the question") *also* lands at `requires_reclassification`, never at a trusted status. This mapper cannot reliably **detect** a retrieval failure from `ClaimNode`'s fields alone — that distinction requires the original `RetrievalOutcome`, which was never preserved for legacy persisted claims (R0's founding finding, unrecoverable after the fact) — so rather than fabricate that judgment (which would violate Rule A: no invented truth), the uniform status rule makes detection unnecessary: nothing, retrieval-failure-shaped or not, is ever promoted by mapping alone.

**`superseded_by` is carried through as real, independent data**, regardless of the uniform status choice — `Claim`'s own validator only requires `superseded_by` be set *when* status is `"superseded"`; it never forbids it being set under any other status. This preserves the graph's real fact (something marked this claim non-current) without asserting the stronger, unearned claim that it cleanly maps onto R1.4's own `"superseded"` lifecycle semantics.

**Deliberately, honestly lossy — documented and tested, per Test 9's own instruction to treat intentional loss as a first-class outcome, not a gap to apologize for:** `node.reasoning`, `source_title`, `source_url`, `source_type`, `valid_from` do not reach the resulting `Claim`. `reasoning.domain.Claim` has no field for raw source/reasoning text — that belongs on `Evidence`, a separate object this function does not construct. Constructing one would require either fabricating a `retrieval_outcome_id` (none exists — `ClaimNode` was never linked to a persisted `RetrievalOutcome`) or synthesizing `Evidence` straight from flat source fields — exactly the `"ClaimNode.sources → Evidence() without evidence validation"` red flag this slice's own review named explicitly. `evidence_ids` stays `[]`; a real Evidence bridge, if ever built, is separate, later work this slice does not attempt.

**No reverse mapping exists** (`domain_claim_to_claim_node` is absent, confirmed by inspection in the verify script itself, not merely by omission) — implementing one would require fabricating exactly the fields already dropped going forward. Rather than build an unsafe reverse mapping to satisfy a symmetry the data doesn't support, only the forward direction is implemented, and why is stated in the module's own docstring, not left for a reader to infer.

**Where this lives, and why it's a new, deliberate dependency edge:** `backend/research/claim_mapping.py`, not `backend/reasoning/` — that package's zero-cross-package-import contract (re-confirmed by every R1/R2/R3 verify script's own inspection check) would break the moment it imported `ClaimNode`. `backend.research` already imports `ClaimNode` (`validation.py`) and is exactly the layer R4.1's own objective named ("the existing claim representation used by the research/validation system"). This is the first time `backend.research` imports `backend.reasoning` — confirmed safe (no cycle: `reasoning` has zero imports from `research`) — the same shape as R3.2's `backend.agents → backend.reasoning` addition.

**Verified (original slice): `scripts/verify_r4_1.py`, 9/9, pure logic, no network/LLM/database/LangGraph call.** Valid forward mapping (#1); required-field failures explicitly rejected, nothing fabricated (#2); source `ClaimNode` confirmed unchanged after mapping (#3); high-confidence claim not promoted (#4); semantic identity stays unavailable while the deterministic floor remains available (#5); a retrieval-failure-shaped `ClaimNode` never reaches a trusted status (#6); two independently-mapped claims show no cross-contamination, and are confirmed via `hasattr` to genuinely lack `reasoning`/`source_*` fields — the documented loss, verified rather than merely asserted (#7); both of `ClaimNode`'s real status signals map through the identical documented rule (#8); no reverse mapping exists, confirmed by inspection (#9). All 79 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2) re-confirmed unaffected.

## §0.67.1 — R4.1-review, same day: three real questions answered from source, not narrative reassurance — no code-behavior change, three new tests

A dedicated review pass, requested before R4.2 could proceed, re-inspecting R4.1's actual source (not the prior slice report) against three specific concerns. All three were investigated by tracing the real production code; none required changing the mapper's logic — the original design decisions held up, but two of them weren't yet backed by an explicit, checkable guarantee, and the docstring's own wording needed tightening in one place. Recorded as a dated addendum, not a silent edit to §0.67, matching this session's established correction discipline (§0.52.1, §0.54.1).

**Question A/B — is `ClaimNode.evidence → normalized_form` correct, or does it risk confusing generated text with validated evidence?** Traced through three independent, real source locations, not assumed from the field's name: `ClaimDraft.evidence`'s own field description (`backend/evidence/models.py:36-38`) — "a concise, direct answer to the question, grounded only in the given resource" — is the model's own synthesized *proposition*, not a verbatim excerpt. `engine.py`'s `gather_evidence_with_outcomes` (`:72`, `:148`) uses that exact same string for both `RetrievalOutcome.raw_content` and `Claim.evidence`, unchanged. `ground_agent.py:502`'s `attach_claim(..., evidence=claim.evidence, ...)` is the *only* production call site that ever creates a `ClaimNode` (confirmed again by repo-wide grep, matching the `verify_phase5.py` test call site exactly). **Conclusion: `ClaimNode.evidence` is confirmed, from real code, to be the asserted proposition text, not raw retrieved material** — mapping it to `normalized_form` is correct, and mapping it to an `Evidence.excerpt` instead would have been the actual error, since that would conflate the model's own synthesis with independently-checkable material — exactly the confusion R1.1 was built to eliminate (§0.49). This finding is now stated directly in `claim_node_to_domain_claim`'s own docstring with the three source locations cited, not left for a future reader to re-derive.

**Question C — where does dropped provenance (`reasoning`/`source_title`/`source_url`/`source_type`/`valid_from`) actually survive?** Answer, made structural rather than reassuring narrative: `claim_id` is reused **unchanged** from `node.id` — a decision already made in the original slice, now explicitly tested (`verify_r4_1.py`'s new check #9). Because the id is identical, any later step holding the mapped `Claim` can always re-fetch the exact original, never-deleted `ClaimNode` (the Graphiti-inspired valid-time pattern keeps every claim, superseded or not) and recover every dropped field. This is not "trapped and inaccessible," as an earlier report loosely characterized it — it is "not duplicated onto the in-memory domain object, but reachable by the same id for as long as the graph exists." R4.2's own orchestration is expected to hold both objects side by side, correlated by this shared id, not the mapped `Claim` in isolation.

**Question D — does the mapper detect retrieval failures, or merely prevent their promotion?** Confirmed, precisely: **prevention, not detection.** The mapper has no way to distinguish a genuine weak claim from a retrieval-failure-shaped `ClaimNode` using `node`'s fields alone — that distinction lived in `RetrievalOutcome`, never persisted behind a `ClaimNode` (R0's own unrecoverable finding, re-confirmed here rather than assumed). New test #10 makes this structural: a genuine weak claim and a disguised retrieval-failure claim (R0's own literal DNS non-answer text) are fed through the mapper and asserted to receive **identical** status — proving uniform non-promotion, not content-based classification. The module's own docstring wording was tightened to state this distinction explicitly rather than let "never promoted" and "cannot be detected" sit in different places without being tied together.

**Question E — is `requires_reclassification` correct for every `ClaimNode`?** Re-confirmed yes, with one previously-untested edge case closed: `ClaimNode.confidence` has no bound of its own (`backend/graph/models.py`), while `reasoning.domain.Claim.confidence` requires `0.0-1.0`. New test #11 confirms an out-of-range `ClaimNode.confidence` is rejected via `Claim`'s own field validator (a `pydantic.ValidationError`) — the same logic-level-vs-model-level split `transition_claim` (R1.4) already established, now explicitly exercised rather than left as an unexamined gap. No new lifecycle state was added; superseded claims remain mappable (real historical facts, never deleted) with `superseded_by` carried through as independent data, exactly as originally designed.

**Result: option A — R4.1 is semantically safe; no mapping-logic changes were needed.** Three tests were added (`verify_r4_1.py` now 12/12) and the module's own docstring was expanded to cite exact source locations and state the prevention-vs-detection and recovery-by-id guarantees explicitly, closing the gap between what the code already did and what its documentation had fully spelled out. All 79 pre-existing checks re-confirmed unaffected.

**Next slice: R4.2** — validation orchestration, consuming `assess_claim_validity`'s real `ClaimValidationReport.duplicate_pairs` (mapped through this bridge, with the original `ClaimNode` held alongside the mapped `Claim` for provenance, per §0.67.1's Question C answer) to actually call `transition_claim`, finally resolving the still-open Phase 8.6 acceptance criterion rather than only reporting it.

## §0.68 — R4.2, same day: real duplicate pairs actually resolved via transition_claim — all 38 of Phase 8.6's original finding, not just the mechanism

R4's own original acceptance criterion (Phases.md, predating R1.4) was never satisfied by any prior slice: "re-running `assess_claim_validity`-equivalent logic... should either resolve or explicitly, correctly classify the 38 duplicate pairs." R4.0 found it still open; R4.1 built the bridge needed to reach it. R4.2 closes it — `backend/research/duplicate_resolution.py`'s `resolve_duplicate_claims`.

**One necessary, deliberate change to `backend/reasoning/domain.py` — not a redesign, one new edge in an existing table.** `_LEGAL_TRANSITIONS["requires_reclassification"]` gained `frozenset({"normalized"})`. Without it, R4.1's mapper output (always `"requires_reclassification"`, by design — §0.67) has no legal path to `"duplicate"` at all, since the existing graph only permits `normalized → duplicate`. This is the exact, single use case R1.4's own comment already anticipated when it left `requires_reclassification`'s outgoing set empty: *"not because one could never exist, but because inventing it now would be premature."* It is no longer premature — R4.2 is a real, proven need for it. Deliberately narrow: only `→ normalized`, mirroring what a fresh `"candidate"` claim is already trusted with — reaching `supported`/`validated`/`active` still requires the same real evidence/cross-check work every other claim must do, unchanged. Full R1.1/R1.4 regression re-ran and confirmed unaffected (no existing test asserted `requires_reclassification`'s legal targets were empty).

**Design: only the duplicate side of a pair transitions; the canonical side is untouched.** `claim_id_a` is treated as canonical, `claim_id_b` as the duplicate — an arbitrary-but-deterministic tie-break, stated as exactly that, not a confidence- or quality-based judgment (the "confidence never controls lifecycle legality" rule applies at the orchestration level here too, not only inside `transition_claim` itself). This is a deliberately narrower scope than "resolve everything about the pair" — advancing the canonical claim's own lifecycle (evidence sufficiency, cross-checking) is a separate judgment this slice does not make.

**A real correctness issue, found by testing against realistic data rather than assumed away, and fixed before this slice was considered complete:** the same claim can legitimately appear as the duplicate side of *more than one* pair — `assess_claim_validity`'s own `combinations()` over any 3+-claim cluster sharing one `source_url` produces exactly this (confirmed: real "Payment gateway" data below hits this constantly). Worse, a pair's "canonical" side can itself already be a demoted duplicate from an earlier pair processed in the same run (a duplicate chain, e.g. `(A,B)` then `(B,C)`). Naively processing pairs independently would either re-transition an already-`duplicate` claim (illegal — `"duplicate"` has no outgoing edges) or leave `C` pointing at `B`, a claim this same run just demoted, instead of at the real root `A`. `resolve_duplicate_claims` tracks this itself via `resolved_root_canonical`, an **in-run-only** map (never persisted or carried across calls — `ClaimNode` has no status to carry it in) — a claim is transitioned to `"duplicate"` exactly once, and every subsequent reference to it, including as a "canonical" for a later pair, resolves to the real root, never an intermediate.

**Every pair produces exactly one of five explicit outcomes** — `resolved`, `already_resolved`, `skipped_incompatible_status`, `unresolved_missing_claim`, `unresolved_mapping_failed` — never silently dropped; the four summary counts are guaranteed, and tested, to sum to `total_pairs`. **`skipped_incompatible_status` is confirmed, honestly, to be currently unreachable** given today's pipeline (every claim `resolve_duplicate_claims` ever sees comes from R4.1's mapper, which always starts at `requires_reclassification`, and both required transitions are always legal from there for a validly-mapped claim) — kept as a real defensive branch for a future caller/mapper that might not share this guarantee, confirmed by test rather than silently assumed exercised.

**Verified, Part 1 (pure): `scripts/verify_r4_2.py`, 7/7** — real pair resolution; missing-claim and mapping-failure handling, both explicit, neither a crash nor a silent drop; duplicate-of-duplicate (the same claim flagged against two different partners) resolved once, second occurrence correctly reported `already_resolved` against the same canonical; duplicate-chain flattening (`(A,B)` then `(B,C)`) confirmed to land `C` on the real root `A`, never the demoted `B`; `skipped_incompatible_status` confirmed unreachable for well-formed pairs; counts always sum to the total.

**Verified, Part 2 (real data, the acceptance criterion itself): "Payment gateway"'s real claims, fetched live, run through the REAL, unmodified `assess_claim_validity` — found 38 duplicate pairs, matching Phase 8.6's original finding exactly.** All 38 resolved through `resolve_duplicate_claims`: **15 newly transitioned to `status="duplicate"` via real `transition_claim` calls (with real, non-fabricated `duplicate_of` references), 23 correctly identified as in-run duplicates-of-duplicates via the chain-flattening logic above, 0 skipped, 0 unresolved.** Nothing was written back to Neo4j (R4.0's R4.4 remains its own, deliberately deferred decision) — every transition happened on in-memory `Claim` objects reconstructed through R4.1's bridge. All 87 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1) re-confirmed unaffected.

**This is the quantitative resolution the original R4 acceptance criterion actually asked for** — not "the orchestration mechanism runs successfully," but "all 38 real historical duplicate pairs were processed to an explicit, correct, individually-inspectable outcome," demonstrated with the real claim ids from the real graph, not asserted in the abstract.

**Deliberately not built in this slice:** persistence of any transition back to Neo4j (R4.4, still its own open scoping question — `ClaimNode` has no `status` property to write into without a schema change); the parent/subclaim relation (R4.3); any advancement of the canonical claim's own lifecycle beyond leaving it untouched; any change to R4.1's mapper contract.

**Next slice: R4.3** (additive parent/subclaim relation fields, per §0.49's already-specified vocabulary) or **R4.4** (the persistence scoping decision this slice's real transitions make newly concrete: should any of these now-computed `duplicate` statuses ever reach Neo4j, and how, given the schema gap R4.0 already found).

## §0.69 — R4.3, same day: the subclaim relation, implemented on Claim itself, ten scoping questions answered rather than assumed

§0.49 specified the subclaim relation vocabulary before any R1 code existed: *"a subclaim is a proposition that provides necessary support to a parent claim... a `SUPPORTED_BY`/`QUALIFIED_BY`/`ILLUSTRATED_BY`/`CONTRADICTED_BY`/`ALTERNATIVE_TO`/`DERIVED_FROM` relation vocabulary."* R4.3 is the first slice to implement it — two new fields on `Claim`, not a new class, exactly as §0.49 already required and this session's own guardrails re-confirmed.

**Ten scoping questions, each answered explicitly rather than left for a future reader to guess:**

1. **Parent vs. subclaim** — no structural distinction. A `Claim` is a "subclaim" only relative to the specific `parent_claim_id` it carries; the identical model plays both roles depending on which claim is asking.
2. **Cardinality** — one parent per claim, many children per parent: parent/subclaim relations form a **directed forest of claim decomposition** (many independent root claims can coexist; each has, at most, one parent) — not a single tree, and not a claim about the shape of the whole Discovery.AI graph, which already has other relation types (`duplicate_of`, `superseded_by`, `evidence_ids`) and is explicitly a network, not a tree, elsewhere in this document. Deliberately chosen over many-to-many: the real research workflow's own decomposition (`GroundAgent`'s sequential sub-question investigation) is already this shape, and a single `Optional[str]` field is the smallest representation that matches it. A claim genuinely needing multiple independent parents (e.g., one piece of evidence supporting two unrelated claims) is out of scope — a real, stated limitation, not an oversight.
3. **Directional** — always child → parent; never symmetric ("X supports Y" is not "Y supports X").
4. **Multiple parents** — not supported, per the cardinality decision.
5. **Parent and subclaim simultaneously** — yes, the normal, expected shape of nested support (a claim supporting a broader claim while itself being supported by narrower ones), tested as a real 3-level chain, not treated as a special case.
6. **Invalid/superseded parent** — no automatic cascading, ever, in either direction. `find_claims_with_invalid_parent` is a pure, read-only reporting function (mirroring `assess_claim_validity`'s own report-only shape) that names a subclaim whose parent is either missing from a given claim set or has reached a discredited status (`rejected`/`superseded`/`duplicate`/`legacy_invalid_claim`) — it never touches the orphaned subclaim's own status or confidence. What to do about an orphaned subclaim is a later, deliberate orchestration decision, the same split R4.2 already established between `assess_claim_validity` (report) and `resolve_duplicate_claims` (act).
7. **Independence from duplicate resolution** — confirmed orthogonal by direct test: a claim can carry both `duplicate_of` and `parent_claim_id` simultaneously with no model-level conflict. `backend/research/duplicate_resolution.py` required zero changes — no concrete conflict was found, confirmed rather than assumed.
8. **Domain-only, graph-only, or shared** — domain-only for this slice, the same deferral R4.2 already established for its own computed statuses: no `ClaimNode`/Neo4j schema change here. R4.4 owns the "does any of this reach the graph" decision for both.
9. **Identity and cycle constraints** — a claim cannot be its own parent, enforced by a new `_subclaim_consistency` model validator (cheap, needs no external context). `validate_subclaim_graph` (new, pure) rejects a `parent_claim_id` absent from a given claim set or any parent-chain cycle, direct or indirect — a direct reuse of R3.2's `validate_task_graph`'s exact DFS pattern, applied to `Claim` parent chains instead of `ResearchTask` dependencies.
10. **Smallest representation** — exactly two new `Optional` fields, `parent_claim_id: Optional[str]` and `relation_to_parent: Optional[SubclaimRelation]`, required together (the new validator rejects either being set without the other) — never a dangling, meaningless half-reference.

**Setting the relation is not a `transition_claim` concern.** It is established once, at construction, by whatever orchestration builds the claim — not a status change with its own legality graph. `transition_claim` itself is completely untouched by this slice.

**New pure functions, the same "fields first, real functions second" discipline R1.3 already used for `identity_floor`/`semantic_identity`:** `subclaim_relation(claim) -> Optional[ParentRelation]` (the real `(parent_claim_id, relation_to_parent)` pair, or `None` — never a fabricated or half-filled tuple, guaranteed by the model's own validator); `is_necessary_support(claim) -> bool` (`True` only for `SUPPORTED_BY`, per §0.49's own rule that only necessary support feeds a parent's completeness — every other relation value returns `False`); `validate_subclaim_graph`/`SubclaimGraphError`; `find_claims_with_invalid_parent`.

**Verified: `scripts/verify_r4_3.py`, 11/11, pure logic, no Neo4j/LLM/persistence call.** Relation shape and correct `None`-when-absent behavior; `is_necessary_support` correct across all six real relation values plus the no-relation case; self-parent rejected at construction; a dangling half-set reference rejected in both directions (relation without parent, parent without relation); a real 3-level parent-and-subclaim chain validated end to end; an unknown parent rejected; both a direct 2-cycle and an indirect 3-claim cycle rejected, a real valid tree accepted; orphan reporting confirmed for both a missing parent and a discredited (superseded) one, with the orphaned subclaim's own status/confidence confirmed unchanged; `duplicate_of` and `parent_claim_id` confirmed settable together without conflict; full serialization round-trip both with and without the relation set. All 90 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2) re-confirmed unaffected — the two new fields default to `None` and required no change to any existing construction call site, confirmed by the full regression run rather than assumed from optionality alone.

**Next slice: R4.4** — the persistence scoping decision both this slice and R4.2 left explicitly open: should `parent_claim_id`/`relation_to_parent` and R4.2's computed lifecycle statuses ever reach Neo4j, and how, given `ClaimNode` has neither a `status` nor a relation property today. A real architectural decision (source of truth, idempotency, restart behavior, transaction boundaries, reconciliation with stale graph state) — not an automatic "persist everything" step, and not attempted in this pass.

## §0.70 — R4.4 decision record: whether/how R4.2/R4.3's computed state reaches Neo4j

A scoping document, not implementation — no code changed to produce this, matching R0/R4.0's own precedent of a design pass before any code. Ten questions, each given a real, argued decision (or explicitly left open where a decision would be premature), grounded in what the actual codebase already does, not invented from scratch.

**1. Source of truth: Neo4j remains authoritative (option B).** The live `/chat` path, `assess_claim_validity`, and Phase 8.6's artifact compilation all read `ClaimNode` from Neo4j today — it is already the de facto system of record for what the rest of the system sees. `backend.reasoning.domain.Claim` is a rich *computation* layer, not a competing store: R4.1 maps FROM the graph, R4.2/R4.3 compute additional facts ABOUT what's in the graph, and persistence (this section) is what makes a computed fact durable by writing it back onto the same real node. A "versioned combination" (option C) is rejected for now — it would require version-tracking infrastructure (a schema field, comparison logic) that doesn't exist anywhere in this codebase yet, and nothing so far has shown a need for it strong enough to justify building it speculatively.

**2. Persistence boundary — what exactly is persisted, and how:**
| Field | Persist? | Shape |
|---|---|---|
| `status` | Yes | New flat property on the `Claim` node (`ClaimNode` has never had one — a real, minimal schema addition) |
| `duplicate_of` | Yes | BOTH a flat property AND a `DUPLICATE_OF` edge — mirroring `supersede_claim`'s own existing precedent exactly (`graph/interface.py:889-911` already does `MERGE (new)-[:SUPERSEDES]->(old) SET old.superseded_by = $new_claim_id`, i.e. edge + property together for the same kind of "this claim points at that one" fact) |
| `provenance_note` / `last_transition_actor` | Yes | Flat properties, extending the existing flat-property convention (`evidence`/`reasoning`/`confidence`/`source_title`/...) `ClaimNode` already uses |
| `parent_claim_id` / `relation_to_parent` | **Not in the first slice** — see Q10 | Would be an edge typed by the relation value itself (mirroring `attach_relation_claim`'s existing `relationship_type` flexibility), not a flat property, if/when built |
| `ClaimValidationReport` (the full report object) | No | Derived and cheap to recompute from already-persisted data (`assess_claim_validity` is pure, fast, deterministic) — persisting the report itself would be a redundant, staleness-prone cache of something re-derivable on demand |
| Investigation/run identity | No, not yet | No `Investigation` object exists in this codebase yet (that's R3/R5 territory); `last_transition_actor` already carries the orchestration's own name (`"r4_2_duplicate_resolution"`), sufficient provenance for now |
| Timestamps | Yes | One `updated_at`-style property on write, mirroring `AgentState.updated_at`'s existing pattern — cheap, useful for staleness visibility (Q6) |

**3. Idempotency: re-running the full R4.2 orchestration and re-persisting must be safe by construction, not by a special idempotency mechanism.** Every write is a `MERGE`-by-id `SET` (matching `attach_claim`/`attach_question`/`supersede_claim`'s existing convention) — setting the same value twice has no side effect. The real risk is upstream, in the *computation*: because `assess_claim_validity`'s own exclusion filter (`active = [c for c in claims if c.superseded_by is None]`) has no concept of the new `status` property, a persisted `"duplicate"` claim would still be read back as "active" by a later validation run unless that filter is extended to also exclude `status == "duplicate"` (and other terminal statuses) once persistence exists. **Flagged here as a real, concrete follow-up `assess_claim_validity` needs at persistence time — not resolved in this document, since it touches Phase 8.5 code this design pass didn't re-open.**

**4. Restart behavior: safe by construction, given per-claim atomic writes (Q5).** Before any writes: trivially safe, re-run from scratch. Mid-way through writes: some claims updated, some not — re-running recomputes the same correct result from live data and re-issues the same idempotent writes (harmless for already-correct ones). The "status written but relationship not yet" failure mode is closed structurally, not by careful sequencing: status, `duplicate_of`, and the `DUPLICATE_OF` edge are set in **one** Cypher statement per claim (Q5), so there is no window where they can be observed half-applied.

**5. Transaction boundaries: one transaction per claim.** This matches every existing write function's own granularity (`attach_claim`, `attach_question`, `supersede_claim` are each single-entity, single-statement operations) rather than introducing a new transaction-scoping philosophy. Per-run (one transaction for all 38 pairs) is rejected: a single failure would roll back everything already correctly computed, and nothing elsewhere in this codebase transacts at that scope. Per-cluster is rejected as unneeded complexity — claims in different duplicate clusters have no write-order dependency on each other.

**6. Stale graph state:**
- An older `status` already present — overwritten by the idempotent `SET`; no special-case code.
- A different `duplicate_of` already recorded (e.g., the graph changed between runs) — the new computed value wins (Q7), but the write should report old-vs-new explicitly (reading the property's prior value before the `SET`, then returning both — the same `RETURN old, new` shape `supersede_claim` already uses, adapted to compare a property's value rather than just returning both full nodes) so a *changed* decision is visible in output, distinct from a first-time write — not a silent overwrite.
- A missing parent / deleted canonical claim — already caught, for free, by validation this track already built: `validate_subclaim_graph` (R4.3) and the missing-claim handling in `resolve_duplicate_claims` (R4.2) both refuse to proceed on a reference that doesn't resolve within the currently-fetched real claim set. A persistence step should run these same checks as a precondition gate before writing anything, not re-invent the check.
- A partially-persisted previous run — safe by construction, per Q3/Q4.

**7. Authority of computed status: the freshly computed value is authoritative for its own write, unconditionally — full version/source-checking is deferred, not built speculatively.** The proposed richer check ("same investigation, same claim identity, same source version, same computation version") would require versioning infrastructure that doesn't exist anywhere in this codebase (`ClaimNode` has no schema-version field) — building it now, with no second consumer yet needing it, would repeat the exact "infrastructure before it's proven necessary" mistake this whole track has consistently avoided. The one cheap safeguard worth keeping: Q6's old-vs-new visibility on every write, so an overwritten *different* prior decision is at least auditable, even though it isn't gated.

**8. Failure and reconciliation: recompute-and-overwrite IS the reconciliation strategy for a first slice — no "preserve both versions" or manual-review workflow.** Because the computation (`assess_claim_validity` → `resolve_duplicate_claims`) is cheap, deterministic, and always re-derivable from current real data, there is no evidence yet that a divergence between computed and durable state needs anything beyond "recompute against current data and write the current answer" — building a conflict-resolution system for a problem that hasn't been observed would be speculative. This can be revisited if a real divergence case is ever actually found in practice.

**9. Provenance: persist onto the SAME real `ClaimNode`, by the same id — no new node type, no separate run-artifact node.** R4.1 already established that `claim_id`/`node.id` identity is the load-bearing recovery mechanism (§0.67.1's Question C); persistence should write the computed fields directly onto that existing node via `MERGE (c:Claim {id: $claim_id})`, the exact pattern `attach_claim` already uses — not a wrapping object, not a parallel store. A separate "run artifact" node is rejected for the same reason as full run-identity tracking (Q2): no consumer needs it yet.

**10. Scope of the first R4.4 implementation slice, if/when undertaken:**
```
R4.4 must implement (first slice):
  - One new graph-interface function (e.g. persist_claim_lifecycle) that
    MERGEs by claim id and SETs status/duplicate_of/provenance_note/
    last_transition_actor/updated_at in ONE Cypher statement, plus a
    DUPLICATE_OF edge when duplicate_of is set -- mirroring
    supersede_claim's existing shape, not inventing a new write pattern.
  - Reuse of existing validation (validate_subclaim_graph,
    resolve_duplicate_claims's own missing-claim handling) as a
    precondition gate before any write.
  - A verify script proving: round-trip (write, re-read, fields match),
    idempotent re-run (no duplicate edges/properties, no error), and a
    simulated partial-run recovery (re-running after "some claims written"
    reaches the same correct final state).

R4.4 does NOT need to implement, in this first slice:
  - parent_claim_id/relation_to_parent persistence -- R4.3 has no real
    orchestration yet that DECIDES actual parent/subclaim relationships
    from live investigation data (unlike R4.2, which had
    assess_claim_validity's real duplicate_pairs to act on). Persisting a
    relation with no real producer yet would be premature, the same
    "type-safety without semantic correctness" trap §0.56 already named.
  - Full run/investigation identity tracking.
  - A versioning/reconciliation system beyond Q7's cheap old-vs-new
    write-time visibility.
  - Any change to the live /chat path or assess_claim_validity's own
    exclusion filter (Q3's flagged follow-up) -- a real, separate,
    deliberate change to Phase 5/8.5 code, not bundled into this slice
    silently.

R4.4 is blocked by:
  - No new blocker beyond ordinary scoping -- unlike earlier phases, every
    real precedent needed (MERGE-by-id writes, edge+property duplication
    for a "points at another claim" fact, single-statement atomicity) is
    confirmed to already exist in graph/interface.py. The one real,
    separate follow-up this document surfaces but does not resolve is
    Q3's assess_claim_validity exclusion-filter gap.
```

**This document is a decision record, not a commit boundary.** No code was written or changed to produce it. The recommended next action is implementing exactly the first slice above, evaluated and scoped the same way every prior R-track slice has been — real inspection before code, focused tests, real regression, one narrow commit.

## §0.71 — R4.4 implemented: the first write to Neo4j in this entire track, and two real gaps it surfaced

Everything from R1 through R4.3 was pure, in-memory, or read-only by explicit scope. R4.4 is that scope's deliberate first exception, built exactly to §0.70's own first-slice contract — nothing more.

**Two layers, matching the exact split R4.1-R4.3 already established between `backend.reasoning` (pure) and `backend.research` (orchestration that may touch I/O):**
- **`backend/graph/interface.py`'s `persist_claim_lifecycle(claim_id, *, status, duplicate_of=None, provenance_note=None, last_transition_actor=None) -> ClaimLifecyclePersistResult`** — the low-level, primitive-parameter function, matching `attach_claim`/`supersede_claim`'s own existing convention exactly (no domain-object dependency; `backend.graph` still imports nothing from `backend.reasoning`, preserving Rules.md rule 1's layering). One Cypher statement, `MATCH` (never `MERGE`/`CREATE`) on the target claim id — this function cannot create a claim, structurally, not by a runtime check. When `duplicate_of` is given, the SAME statement also `MATCH`es the canonical claim and `MERGE`s a `DUPLICATE_OF` edge (a new relationship-type constant, `backend/graph/schema.py`, deliberately separate from `SUPERSEDES` — a duplicate is a same-time redundancy, not a temporal replacement) — mirroring `supersede_claim`'s own existing edge-plus-property pattern for "this claim points at that one" exactly, not inventing a new one. Captures the property's OLD value in the same statement (`WITH c, c.status AS previous_status, c.duplicate_of AS previous_duplicate_of`, before the `SET`) so a changed decision is visible without a second round trip.
- **`backend/research/claim_persistence.py`'s `persist_domain_claim_lifecycle(claim: Claim) -> ClaimPersistenceResult`** — the research-layer bridge, taking any already-transitioned domain `Claim` (from R4.2's `resolve_duplicate_claims`, or constructed directly) and calling the graph layer with its real fields. Catches `GraphInterfaceError` and reports `"rejected_missing_claim"` rather than letting an exception propagate — the same catch-and-report split R4.2 already established for `ClaimMappingRejected`.

**`ClaimNode` (backend/graph/models.py) gained five new `Optional` fields** — `status`, `duplicate_of`, `provenance_note`, `last_transition_actor`, `updated_at` — all read via `.get()` in `_record_to_claim`, the same "old nodes don't have it, read back as `None`, an honest 'not yet classified' state" pattern `QuestionNode.research_field` already established in Phase 8.4.

**Every §0.70 first-slice decision was followed exactly, not reinterpreted during implementation:** one transaction per claim, one statement covering status/duplicate_of/edge together (confirmed by direct source inspection — exactly one `session.run` call, not two); no claim creation (`MATCH`, not `MERGE`, on the target); no parent/subclaim persistence (confirmed by signature inspection — the function has no such parameters at all); recompute-and-overwrite as the only reconciliation strategy, with old-vs-new visibility on every write via `ClaimPersistenceResult.changed`.

**Verified: `scripts/verify_r4_4.py`, 12/12, against REAL Neo4j — the first live-write test in this entire track.** All writes scoped to a fresh, disposable test entity ("R4.4 Verify Test Entity") created by the script itself, mirroring `scripts/verify_phase5.py`'s own established convention for real write tests — no established real research entity (Payment gateway, DNS) was touched. Covers: normalized-claim persistence and round-trip; duplicate-claim persistence with both the property and a real `DUPLICATE_OF` edge; an idempotent repeat write (`changed=False`, no second edge — confirmed by a direct edge-count Cypher query); recompute-and-overwrite (a claim re-pointed at a different canonical correctly reports the old value and `changed=True`); a missing claim rejected with zero new nodes created (confirmed by a before/after count); a missing `duplicate_of` target rejected without half-applying the primary claim's status; atomicity confirmed by source inspection (exactly one `session.run` call); no parent/subclaim parameter exists; provenance/actor round-trip. All 90 pre-existing checks re-confirmed unaffected.

**Two real gaps confirmed by this slice's own tests, deliberately not fixed here, both flagged rather than silently bundled in or silently left untested:**
1. **§0.70's own predicted Q3 follow-up, now confirmed against a real persisted claim, not just anticipated:** `assess_claim_validity`'s exclusion filter (`superseded_by is None`) has no concept of the new `status` property — a real, persisted `"duplicate"` claim is still counted in `active_claim_count`. Test #11 constructs exactly this real case and confirms the gap exists.
2. **A second gap, freshly discovered while writing this slice's own tests, not predicted in §0.70:** `claim_node_to_domain_claim` (R4.1) still unconditionally maps every `ClaimNode` to `"requires_reclassification"` — it was built before `ClaimNode` had a `status` field and still doesn't read the one R4.4 now writes. Re-mapping an already-persisted `"duplicate"` claim silently discards that fact, restarting it at square one every time. Test #12 confirms this directly against a real persisted claim. Fixing this is real, separate R4.1 follow-up work — deciding exactly HOW a persisted status should be trusted on re-mapping (all statuses equally? only some?) is its own scoping question, not a silent inline patch bundled into a persistence commit.

**Neither gap blocks R4.4 as scoped** — R4.4's own job was "can a computed lifecycle decision reach Neo4j, atomically, idempotently, without creating anything," and both gaps are downstream consumers (Phase 8.5's validation, R4.1's own mapper) not yet updated to account for the fact that persistence now exists. **The end-to-end persisted lifecycle system is not considered fully closed until both are resolved** — recorded here so neither is forgotten, matching this track's own established discipline of naming a real gap the moment it's found rather than after the fact.

## §0.72 — R4.5: lifecycle rehydration and active-claim semantics — both R4.4-confirmed gaps closed

A semantic repair slice, not a new persistence feature, per its own scope: closes both gaps §0.71 recorded, and no others. Neither `ClaimNode` nor `persist_claim_lifecycle` changed — only how their already-persisted data is *read back*.

**Design question answered before coding, per the review's own instruction, not assumed:** should rehydration use (A) the already-expanded `ClaimNode` fields, (B) a separate graph read model, or (C) a persistence-to-domain hydration adapter? **Confirmed A, by direct inspection, not a guess** — `ClaimNode` already gained `status`/`duplicate_of`/`provenance_note`/`last_transition_actor` in R4.4, and `_record_to_claim` already reads them via `.get()`. No new read model or adapter was needed; the data R4.1's mapper needs was already sitting on the exact object it already receives.

**Gap 2 (the mapper) fixed in `claim_node_to_domain_claim`:** `node.status` is now honored exactly when it is (a) present, (b) a recognized `ClaimStatus` value (checked against `typing.get_args(ClaimStatus)`), and (c) internally consistent — a `"duplicate"` status has a real `duplicate_of`; a `"superseded"` status has a real `superseded_by`. Any of those three checks failing falls back to the ORIGINAL, unconditional `"requires_reclassification"` behavior, each with its own distinguishing `provenance_note` (never persisted / unrecognized value / inconsistent persisted state) — three different reasons produce three different messages, never one generic catch-all. A legacy `ClaimNode` (`status=None`, created before R4.4 existed, or never run through persistence) is completely unaffected — the exact same fallback path this function has always used, now reached explicitly rather than unconditionally. When a real, consistent status IS honored, `last_transition_actor` and `provenance_note` are rehydrated from the real persisted values too, not fabricated.

**Gap 1 (the validation filter) fixed in `assess_claim_validity` and `detect_contradictions`:** `active` now also excludes any claim whose persisted `status` is in a newly-public constant, `DISCREDITED_CLAIM_STATUSES` — promoted from R4.3's own private `_DISCREDITED_PARENT_STATUSES` (`{"rejected", "superseded", "duplicate", "legacy_invalid_claim"}`) rather than duplicating the same literal set in a second place where it could silently drift. `"disputed"` is deliberately excluded from this set — a disputed claim is contested, not discredited, and `detect_contradictions` (Phase 8.5's own opt-in LLM layer) is the mechanism for surfacing disputes, not silent exclusion from every other check. A claim with `status=None` (never persisted) is unaffected — `None not in frozenset(...)` is always `False`, the same exclusion behavior this function has always had for legacy data.

**Both fixes are purely additive to existing logic, not replacements:** the pre-existing `superseded_by is None` check in `assess_claim_validity` is untouched, confirmed still working via a dedicated test against Phase 5's own, separate `supersede_claim` path (a superseded claim has `status=None` but `superseded_by` set — excluded via the original check, exactly as before R4.5 existed). The mapper's fallback path for `status=None` is byte-for-byte the pre-R4.5 behavior, just reached through an explicit branch instead of unconditionally.

**Verified: `scripts/verify_r4_5.py`, 9/9** — checks #1-7 pure/synthetic (persisted normalized/duplicate rehydration, `duplicate_of` survival, active-claim exclusion, canonical-claim eligibility preserved, legacy-`ClaimNode` compatibility, three distinct malformed-status fallback cases), checks #8-9 against **real Neo4j**, scoped to a fresh, disposable test entity ("R4.5 Verify Test Entity") — no established real research entity touched. Check #8/#9 proves the FULL closed loop for the first time: persist a real duplicate decision → reload it from Neo4j → re-map it (now correctly rehydrating `"duplicate"`) → re-persist the identical, now-rehydrated decision → confirmed `changed=False`, zero additional `DUPLICATE_OF` edges — exactly the scenario R4.4's own check #12 found broken, now closed end to end. `scripts/verify_r4_4.py`'s checks #11/#12 were updated (assertions flipped, not deleted) to confirm both fixes rather than continuing to assert the now-resolved gaps — the historical record of what was found lives in git history and in §0.71 above, not in a stale, now-failing assertion. All 99 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2/R4.3/R4.4) re-confirmed unaffected.

**The end-to-end persisted lifecycle system, as scoped through R4.1-R4.5, is now closed:** a claim can be computed, transitioned, persisted, reloaded, and re-validated without losing or misrepresenting its lifecycle state at any step. Remaining, explicitly out of scope for this slice and not attempted: persisting `parent_claim_id`/`relation_to_parent` (R4.3 still has no real orchestration producing them from live data), full run/investigation identity, and any versioning/reconciliation system beyond the recompute-and-overwrite strategy R4.4's decision record already chose.

## §0.73 — R5.1: the stable Research API contract, as pure types — a projection, not a sixth claim model

Per the R5.0 audit's own recommended next slice: `ResearchRequest`/`ResearchResponse` (§0.57), types only — no compiler, no route, no orchestration. New package `backend/research_api/` (confirmed by inspection: no existing "API contract" package name exists; `backend/api/` is the HTTP-route layer, `backend/research/` already has its own documented Phase 8.2-8.6/R4 scope).

**The central risk this slice was explicitly warned about — creating a second, competing epistemic model — was avoided by construction, not by discipline alone.** Every field reuses a real, already-existing type from the package that already owns that concept: `Claim` (`backend.reasoning`, R1) for `claims`/`subclaims`; `GraphNode`/`Relationship` (`backend.graph`, Phase 1) for `entities`/`relationships`; `EvidenceReference`/`ConceptCompleteness`/`ContradictionFinding` (`backend.research`, Phase 8.6/8.3/8.5) for `evidence`/`coverage`/`contradictions`; `ResearchTask` (`backend.reasoning`, R3) for `unresolved_tasks`; `ClaimProvenance` (`backend.agents`, Post-Phase-5) for `provenance`. Nothing here is a new claim, evidence, or coverage shape — `ResearchResponse` is a projection over six already-existing models, not a seventh.

**Three fields with no clean single-value source today, resolved by NOT fabricating one rather than guessing:**
- **`root_entity_id`** — `ResearchArtifact` (Phase 8.6, R5's own named closest-existing-ancestor) is abstraction-scoped and may cover multiple concept entities (the real "online payment" abstraction has 5) with no designated root anywhere in `backend.graph.models.Abstraction` or `ResearchArtifact` itself. Stays `Optional[str] = None`, confirmed by direct inspection rather than defaulted to "the first concept" or any other heuristic that would misrepresent structure the data doesn't have.
- **`investigation_id`** — no standalone `Investigation` object exists anywhere in this codebase (confirmed repeatedly across R0-R5's own audits). Maps to the real, already-existing, durable Neo4j `Abstraction.id` (Phase 6) that `ResearchArtifact.abstraction_id` already carries — reusing real identity rather than inventing a synthetic investigation id.
- **`status`** — deliberately only `"complete" | "partially_complete"` (`ResearchResponseStatus`), derived from `ResearchArtifact.is_ready`, NOT Architecture.md §0.55's full aspirational 12-state investigation lifecycle. Most of those states (`waiting_on_dependency`, `budget_exhausted`, `blocked`, `uncertain`, `contradictory`, `failed`) have no real producer anywhere in this codebase today — inventing them now would repeat the "type-safety without semantic correctness" trap §0.56 already named for claim migration, applied here to investigation status instead.

**`subclaims` is a stated, deliberate near-duplication of `claims`, not an oversight.** R4.3 established that a subclaim is a `Claim` with `parent_claim_id`/`relation_to_parent` set — not a distinct type or identity. `subclaims: list[Claim]` exists for API-contract compatibility with §0.57's original sketch (which predates R4.3's actual implementation and imagined subclaims as a parallel list), but every entry in it is also present in `claims`; it is never a disjoint list. Left empty in this slice — no real orchestration creates parent/subclaim relations from live data yet, R4.3's own stated non-goal, still true.

**`required_fields` validation reuses Phase 8.2's own six-field vocabulary** (`BASE_REQUIRED_FIELDS | REQUIRED_FIELD_POLICY_GATES`, `{"definition","mechanism","prerequisites","examples","misconceptions","evidence"}`) rather than inventing a new enum — an unrecognized field name is rejected explicitly at construction, giving real substance to "invalid required fields are rejected" rather than accepting an arbitrary string set.

**Verified: `scripts/verify_r5_1.py`, 9/9, pure logic, no LLM/retriever/Neo4j call.** `ResearchResponse` constructed from a real `ResearchArtifact` fixture (`assemble_research_artifact`, the same pure function `scripts/verify_phase8_6.py` already tests) and real `Claim` objects (via R4.1's real `claim_node_to_domain_claim` mapper, not a fabricated shape); `investigation_id`/`status`/`root_entity_id` all confirmed preserved or honestly `None`; claims/evidence confirmed to carry the real computed values; `subclaims`/`unresolved_tasks`/`provenance` confirmed empty, each for its own stated real reason; full round-trip serialization including nested objects; no mutation of the source artifact or its `ClaimNode`s; invalid `required_fields`/empty `topic`/empty `investigation_id` all rejected explicitly; R1/R3/R4 lifecycle semantics (`transition_claim`/`ResearchTask`/`ClaimStatus`) confirmed unchanged by this new package's presence. All 109 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5) re-confirmed unaffected.

**Deliberately not built in this slice:** `compile_research_response` (R5.2 — the function that actually populates a `ResearchResponse` from a real, live investigation), any API route, any Neo4j change, any change to R1-R4's own behavior. No existing file was modified; every new file is additive.

## §0.74 — R5.2: compile_research_response, the pure projection compiler

The exact boundary this slice establishes and preserves:

```
ResearchArtifact          = the existing research-domain artifact/source (Phase 8.6)
ResearchResponse          = the stable API projection (R5.1)
compile_research_response = the pure projection compiler (this slice) -- reads
                             ResearchArtifact + optionally-supplied real data,
                             writes ResearchResponse, creates nothing new
```

No new epistemic objects are created; no lifecycle transitions occur (`transition_claim` is never called); no confidence gating occurs (a claim's status, not its confidence, decides nothing here — the compiler doesn't even inspect confidence); no persistence occurs; no orchestration occurs (no Neo4j/LLM/retriever/HTTP call).

**A real, load-bearing finding this slice's own repository inspection surfaced, not assumed from R5.2's own suggested shape:** `ResearchArtifact`/`ConceptResearchArtifact` (Phase 8.6) embed no real `reasoning.domain.Claim` objects at all — only `EvidenceReference` (`claim_id`, `source_title`, `source_url`, `source_type`, `confidence`), with no `normalized_form`/`entity_id`/`source_question_id`/`status`. Fabricating a `Claim` from an `EvidenceReference` alone would mean inventing `normalized_form` from a source citation — exactly the "`RetrievalOutcome → Claim`" collapse R1.1 was built to prevent, generalized to this new boundary. `compile_research_response` therefore accepts `claims`/`subgraph`/`provenance` as **optional, real, already-fetched parameters** — reused when a caller has them (e.g. via R4.1's `claim_node_to_domain_claim`, run separately), never fabricated when absent. `evidence`/`coverage`/`contradictions`, by contrast, ARE fully, honestly derivable directly from the artifact alone (it already embeds real `EvidenceReference`/the exact fields `ConceptCompleteness` needs/real `ContradictionReport` objects) — no external parameter needed for these three.

**`subclaims` is computed exactly as R4.3 and R5.1 already established:** `[c for c in claims if c.parent_claim_id is not None]` — a filtered view sharing the same object identity as the matching entries in `claims`, never a copy, never a new type.

**Verified: `scripts/verify_r5_2.py`, 8/8, pure logic, no LLM/retriever/Neo4j call.** A minimal zero-concept artifact compiles cleanly; the real Phase 8.6 fixture compiles with real evidence/coverage preserved; a parent/child `Claim` pair correctly splits into `claims`/`subclaims` with identity preserved (`is`, not `==`); `rejected`/`superseded`/`duplicate`/`legacy_invalid_claim`/`disputed` claims all retain their exact status, none filtered or reclassified; `root_entity_id`/`unresolved_tasks`/`provenance`/`subclaims` stay honestly empty when not supplied; full serialization round-trip including nested contradiction findings; the source artifact/concepts/claims are confirmed byte-for-byte unchanged after compiling twice; two compilations of the same input produce equal (`==`) results. All 118 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1) re-confirmed unaffected.

**Deliberately not built in this slice:** `POST /research` or any route (R5.3), retriever/LLM/Neo4j calls, curriculum compilation, prerequisite inference, lesson generation, frontend changes, any new lifecycle mechanics or claim/evidence/subclaim class. No existing file's behavior changed — `backend/research_api/__init__.py` only gained a new export.

## §0.75 — R5.3: POST /research, the real route — R5's own last deliverable, all three slices now closed

`backend/research_api/service.py`'s `fetch_and_compile_research_response(abstraction_id, policy)` is the I/O shell wrapping R5.2's pure compiler — fetches the real `ResearchArtifact` (Phase 8.6), each concept's real claims (re-fetched independently and mapped via R4.1's `claim_node_to_domain_claim`, rather than modifying Phase 8.6's own already-tested `compile_research_artifact` to also return its internal `claims_by_entity`), and the abstraction's real `Subgraph` (Phase 1) — then calls `compile_research_response`. Deliberately does not fetch `provenance` (`trace_claim`'s own separate SQLite agent-tree walk) on every request yet — a real, stated deferral, not a silent omission, since R5.2's compiler already handles an omitted `provenance` honestly.

**`POST /research` (`backend/api/app.py`) resolves `req.topic` exactly the way `/roadmap/build` already resolves `entity_name`** — `find_or_create_entity` → `materialize_abstraction` → a real `abstraction_id` — not a new resolution mechanism invented for this route. 400 (not 404) when the topic has no discovered decomposition yet, the same client-actionable-state convention `/roadmap/build` already established.

**A real, confirmed gap this route's own design surfaced: no named `"learning"`-mode `ResearchPolicy` exists anywhere in this codebase** (only `EXPLORATORY_POLICY`, Phase 8.1). `mode="learning"` is rejected with an explicit 501, not silently downgraded to exploratory and not given fabricated policy values with no real production precedent — the same "never claim a value is controlled by policy when it isn't" discipline Phase 8.1 itself established.

**Verified: `scripts/verify_r5_3.py`, 7/7 — the first check in R5's whole track to exercise the real route end-to-end.** Part 1, real Neo4j: `fetch_and_compile_research_response` against "online payment" (Phase 8's own real live-data abstraction, confirmed to still have a real 5-entity decomposition in this Neo4j instance at verification time — "PayPal," this project's original Phase 4-6 entity, no longer does; checked directly, not assumed) returns a real `ResearchResponse` with **52 real claims**, 5 real entities, 9 real relationships. Part 2, real HTTP via FastAPI's `TestClient` (no live server process needed): `mode="learning"` → 501; an unrecognized `required_fields` entry → 422 (`ResearchRequest`'s own R5.1 validator, exercised for the first time over real HTTP); a real, already-decomposed topic → 200 with a well-formed body; an undecomposed topic → 400. All 118 pre-existing checks re-confirmed unaffected.

**A real, non-epistemic finding from writing this test, worth recording since it could otherwise look like a route bug:** the Neo4j async driver is a module-level singleton bound to whatever asyncio event loop first creates it. Running real async Neo4j calls via a bare `asyncio.run(...)` and then handing off to `TestClient` (which runs the app in its own `anyio` thread-portal loop) leaves the driver bound to a now-dead loop, producing `RuntimeError: ... attached to a different loop`. Fixed in the test by closing the driver (`close_driver()`, within the same loop that created it) before Part 2 begins, and by using `TestClient` as a context manager (`with TestClient(app) as client:`) so every call in Part 2 shares one consistent loop — a real fact about async drivers across multiple event loops in one process, not a defect in the route or `fetch_and_compile_research_response` itself (already proven correct by Part 1's checks against the same real data).

**R5 is now fully built across all three slices (R5.1 types, R5.2 pure compiler, R5.3 real route).** The stable Research API contract Phase 9's Curriculum Compiler is meant to consume now exists, end to end, against real data. Deliberately not built: request-level provenance fetching, a `"learning"`-mode policy, any curriculum compilation, any frontend change.

## §0.76 — Phase 9.1: the Curriculum Compiler — Discovery.AI's first real client, restructuring begins

The first slice of "restructuring around Discovery.AI": a new top-level `backend/curriculum/` package that consumes R5's stable `ResearchResponse` as an ordinary client, never reaching into `backend.reasoning`/`backend.graph`/`backend.research` internals directly and never calling an LLM, a retriever, or Neo4j itself — the exact restriction docs/Rules.md rule 16 states for the Curriculum Compiler ("only reads from the Graph Interface... a concept missing a lesson or exercise is a gap it surfaces, not one it fills inline").

**`backend/curriculum/models.py`** defines three new, minimal types — `Module` (one already-complete concept plus its real `reasoning.domain.Claim` objects, filtered by `entity_id`, never copied), `IncompleteConcept` (a concept `ConceptCompleteness.is_complete` found `False`, surfaced with its real missing fields rather than silently dropped or compiled anyway), and `Course` (an ordered list of `Module`s, a list of `IncompleteConcept`s, and `ordered_by_prerequisites: bool`). No new claim/evidence shape — `Module.claims` holds the same `Claim` objects `ResearchResponse.claims` already carries.

**`backend/curriculum/compiler.py`'s `compile_course(response: ResearchResponse) -> Course` is pure**, mirroring R5.2's `compile_research_response` and R3.2/R4.3's own DFS-based dependency-ordering pattern (`validate_task_graph`, `validate_subclaim_graph`). Two real design decisions, confirmed by direct inspection rather than assumed:

1. **Ordering.** `Relationship.relationship_type == "requires"` edges, if present among the complete concepts, are topologically sorted via post-order DFS (dependencies-first) with real cycle detection — a genuine cycle raises `CourseCompilationError` naming the exact cycle, never silently dropped or infinite-looped. **Direct inspection of every current `Relationship` producer (Phase 1's extraction pipeline, Phase 6's materialization, Phase 8's investigation loop) confirms none assigns `relationship_type="requires"` today** — so `ordered_by_prerequisites` is honestly `False` for every real investigation as of this slice, and `modules` falls back to `ResearchResponse.coverage`'s own (discovery) order. This is recorded as a real, stated limitation, not silently smoothed over with a fabricated heuristic ordering (e.g. alphabetical, or confidence-based).
2. **Completeness gating.** A concept whose `ConceptCompleteness.is_complete` is `False` is never compiled into a `Module` — it is surfaced in `Course.incomplete_concepts` with its real missing fields (derived from `field_coverage`, not re-guessed). This is rule 16's own instruction applied literally: filling the gap is Lesson Authoring's/the Challenge Engine's job (unbuilt, Phase 10+), not this compiler's.

**Verified: `scripts/verify_phase9_1.py`, 5/5, pure throughout (no LLM/retriever/Neo4j call)** — a known prerequisite chain (`e-rec requires e-dns requires e-net`) is respected in module order; a real 2-node requires-cycle raises `CourseCompilationError` naming the cycle; an incomplete concept is surfaced in `incomplete_concepts` and never compiled into a module; with no `requires` edges present, modules fall back to honest coverage-list order and `ordered_by_prerequisites` is `False`; claims are grouped into the correct module by `entity_id` using the exact same `Claim` objects (identity, not copies). All 125 pre-existing checks (Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1-R5.3) re-confirmed unaffected by a full regression run.

**Deliberately not built in this slice:** any HTTP route consuming `compile_course` (Phase 9.2, next), any frontend course viewer (Phase 12.0), any lesson/exercise authoring (Phase 10+, a separate, still-unbuilt system this compiler's gaps are meant to feed), and no `"requires"`-edge producer — that is real graph-extraction/investigation work, out of scope for a pure compiler slice.

## §0.77 — Phase 9.2: POST /course, the real route wiring Phase 9.1 behind HTTP

`backend/api/app.py`'s `POST /course` is the exact same shallow-wrapper shape `/research` (R5.3, §0.75) already established, one step further — resolve `req.topic` (`find_or_create_entity` → `materialize_abstraction`, identical to `/research`) → `fetch_and_compile_research_response` (R5.3) → `compile_course` (Phase 9.1, §0.76) → return the `Course`. Reuses `ResearchRequest` directly rather than inventing a second, near-identical request shape for "the same topic, but as a course" — a course IS a research response, projected differently, not a separately-requested concept. Same `mode="learning"` → 501 and undecomposed-topic → 400 conventions as `/research`, for the same real reasons (no `"learning"`-mode policy exists; an undecomposed topic is a client-actionable state, not a missing resource).

**Verified: `scripts/verify_phase9_2.py`, 4/4** — Part 1, real Neo4j: `compile_course` over a live-fetched `ResearchResponse` for "online payment" produces a real `Course` with **5 real modules, 0 incomplete concepts, `ordered_by_prerequisites=False`** (confirming §0.76's own finding that no `"requires"` edges exist in this data yet, now observed live rather than only in a synthetic fixture). Part 2, real HTTP via FastAPI's `TestClient`: `mode="learning"` → 501; an undecomposed topic → 400; a real, already-decomposed topic → 200 with a well-formed `Course` body. All 129 pre-existing checks re-confirmed unaffected.

**Discovery.AI's Research API and the Curriculum Compiler are now wired end to end behind one real route, against real data.** Deliberately not built: any frontend course viewer (Phase 12.0), any lesson/exercise authoring (Phase 10+), request-level provenance, learner-level personalization (no `learner_level` producer exists yet — `ResearchRequest.learner_level` is accepted but not yet used by `compile_course`, an honest, stated gap, not a silent no-op passed off as a real feature).

## §0.78 — Phase 12.0 (minimal slice): a real course-viewer frontend, browser-tested against live data

`frontend/course.html` — the same vanilla HTML/CSS/JS stack `frontend/roadmap.html` already established (docs/Architecture.md §0.38.3's frontend-approach correction, no build step, no JS framework), served by the existing `StaticFiles` mount at `/course.html` (no clean-URL alias, same precedent as `/roadmap.html`, since `POST /course` already owns the bare `/course` path). A topic input calls `POST /course` and renders the returned `Course`: numbered modules with their real claims (`normalized_form` + confidence), an amber "not yet ready" section per `incomplete_concepts` entry with its real missing fields, and — only when `ordered_by_prerequisites` is `False` — an explicit banner stating the shown order is discovery order, not a verified teaching order. This mirrors §0.76/§0.77's own honesty discipline into the UI layer: the frontend never implies a prerequisite ordering the backend didn't actually compute.

**Browser-tested against real, live data**, not just curled: a stale dev-server process from an earlier session (started 2026-09-16, predating this session's `/course` route) was found still bound to port 8000, masking the new route behind a 405 (`StaticFiles` rejects non-GET/HEAD methods before Starlette's router reaches routes registered after the `/` mount in that older process's code) — a real, if mundane, operational finding, not a route bug; the stale process was stopped and a fresh one confirmed the route immediately. With a fresh server, `frontend/course.html?topic=online%20payment` rendered all 5 real "online payment" modules (Payment gateway, Acquiring Bank, card network, etc.) with their real claims and confidence percentages, the honest no-prerequisites banner, and zero incomplete-concept entries — matching `scripts/verify_phase9_2.py`'s own real-data numbers exactly.

**Deliberately not built:** lesson/exercise content per module (Phase 10/11, unbuilt), progress tracking or gamification (Phase 13, unbuilt), any styling beyond the minimal, honest-first pass already shared with `roadmap.html`. This is a genuinely minimal slice of Phase 12 — enough to prove the whole pipeline (topic → Research API → Curriculum Compiler → browser) works end to end against real data, not the full Portal UI Design.md §Learning-Portal eventually calls for.

## §0.79 — Phase S0.1: LLM environment preflight — a real has_any_provider_key() bug, not just a documented limitation

Requested as a narrow follow-up to the verification-hygiene pass (§ below): make the 9 `environment_blocked` scripts' actual requirements reproducible and inspectable without weakening any assertion. `scripts/preflight_llm_environment.py` reports, per provider, whether it's configured and actually wired into a real model chain — presence/count only, never a secret value (confirmed by a dedicated test, `verify_preflight_llm_environment.py` check #4, that zero of the real configured secret values ever appear in the report's own JSON serialization).

**Building the report surfaced a real, previously-hidden bug, not a limitation to document around:** `has_any_provider_key()` (`backend/questions/llm_config.py`) checked only the singular env var names (`GEMINI_API_KEY`/`GROQ_API_KEY`/`CEREBRAS_API_KEY`), never the plural multi-key rotation names this project's own documented convention uses (`GEMINI_API_KEYS` etc., §0.38.1) — this environment's real `.env` has 25 real, functional keys configured entirely under the plural names, and `has_any_provider_key()` had been returning `False` regardless. `PROVIDER_KEY_POOLS` (what the real production call chain actually reads) found them correctly the whole time — this was a verification-only helper bug, not a production LLM-call bug. All 9 `environment_blocked` scripts were misdiagnosed as environment-blocked when they were actually blocked by this one function.

**Fixed for real, not left as a documented gap, once the user explicitly authorized continuing past the reporting-only slice:** `has_any_provider_key()` moved after `PROVIDER_KEY_POOLS`'s definition and rewritten as `any(PROVIDER_KEY_POOLS[p] for p in ("google", "groq", "cerebras"))` — the exact same real pool the production chain uses, `cohere` deliberately excluded (confirmed dead: no `cohere/...` entry exists in `GROUND_MODEL_CHAIN`/`MASTER_MODEL_CHAIN`, the `cohere` package was never installed, per this project's own Phase 2 entry). Re-ran the full suite after the fix: **34 → 42 scripts genuinely execute now** (real LLM calls fire for the first time in a long while), 1 real, honest, pre-existing failure remains (`verify_phase5.py` — the same Semantic-Scholar-429/no-Tavily-key retriever variance already documented in this project's own Phase 5 Memory.md entry, reproduced again, not a new regression).

## §0.80 — Phase 10: Lesson Authoring — the first real, live, audited lesson

`backend/lessons/` — `compile_lesson(module: Module) -> Lesson`, the one I/O shell in this slice. Per Rules.md rule 2, the actual LLM call lives in `backend/questions/lesson_authoring.py` (`compose_lesson_explanation`), not in `backend/lessons` itself — the same package-boundary discipline `backend/curriculum` already keeps from `backend/research` (rule 16).

**Two separate calls, not one self-certifying call, mirroring `audit_synthesis`'s own original design principle:** `compose_lesson_explanation` composes an explanation from a module's real claims only (the system prompt explicitly forbids introducing any fact, example, or number not present in the given claims — enforced by construction, not just checked after the fact); `audit_synthesis` (Post-Phase-5 epistemic layer, reused completely unchanged, per Rules.md rule 19) then independently audits every atomic sentence of that explanation against the same claim texts. A lesson never certifies its own honesty.

**A real, honest empty state, not a fabricated lesson:** a module with zero real claims (a real, reachable case — nothing guarantees `ResearchResponse.claims` was populated by every caller) short-circuits to `status="insufficient_claims"` before any LLM call, with `fully_traceable=None` (not `False`) — "never attempted" and "attempted, found ungrounded" are kept as distinct, real facts (Rules.md rule 9's honesty discipline again).

**Verified live, first time end to end: `scripts/verify_phase10.py`, 4/4**, against the real "online payment" course (Phase 9.1/9.2's own live data) — "Payment gateway" (23 real claims) produced a real 333-character composed explanation, 3 audited sentences (all "investigated" — `fully_traceable=True`), and `source_claim_ids` exactly matching the module's 23 real claim ids, no fabricated or dropped provenance. The same Groq RDF-triple-terminology schema drift already documented for relation extraction (§0.18) reproduced here too (the model emitting `{claim, status}`/`{claim, classification}` instead of `SynthesisAudit`'s real `{text, origin}` shape) — the existing multi-key/multi-provider fallback chain absorbed it correctly, succeeding on a later provider, exactly as designed.

**Deliberately not built:** examples beyond what a real claim already contains (the system prompt forbids inventing one), any Neo4j persistence of a `Lesson` (this slice produces an in-memory artifact only), any API route or frontend rendering (a natural next slice, not this one), and no misconception-detection (PRD.md §9.6's `require_misconceptions` field remains one of Phase 8.3's honestly-`UNCLASSIFIED_FIELDS` — nothing tags a claim as a misconception yet for Lesson Authoring to draw on).

## §0.81 — Phase 10.2: POST /lesson — Lesson Authoring wired end to end behind HTTP

`backend/api/app.py`'s `POST /lesson` is the same shallow-wrapper shape `/course` (§0.77) already established, one step further: resolve the topic's `Course` exactly like `/course` does, find `req.concept`'s real `Module` by `entity_name` (case-insensitive — never a free-form prompt the LLM interprets), then `compile_lesson` (Phase 10, §0.80) it. `LessonRequest` (`backend/api/session.py`) is a new, minimal request shape — `topic`/`concept`/`mode` — reusing `ResearchMode` directly rather than inventing a parallel mode vocabulary.

**A real, three-way status distinction, not collapsed into a generic 404:** the topic itself having no decomposition is 400 (matching `/research`/`/course`'s own "investigate it further first" convention); `req.concept` not existing anywhere in the compiled course at all is 404 (the real "wrong resource name" case); `req.concept` existing but not yet clearing Phase 8.3's completeness bar (present in `Course.incomplete_concepts`) is 409, a genuinely different state from "doesn't exist," reported with its own real missing fields rather than silently folded into either the 400 or 404 case.

**Verified: `scripts/verify_phase10_2.py`, 4/4, against real Neo4j and real LLM calls (both now genuinely exercised, per §0.79's fix).** The real "online payment" course confirmed to have 5 real modules with claims; `mode="learning"` → 501; an unknown concept → 404; `POST /lesson` for the real "Payment gateway" concept → 200, `status="composed"`, 23 real `source_claim_ids` matching its module's real claims exactly.

**Discovery.AI's Research API, the Curriculum Compiler, and Lesson Authoring are now wired end to end behind real HTTP routes, against real data, with real LLM calls firing successfully.** **Correction, same slice, before this section's own commit landed:** the line above originally said frontend lesson rendering was "deliberately not built" — that held only briefly; `frontend/course.html` gained a real "Read lesson" button and lesson-rendering panel in this exact same commit (`b057324`). Browser-tested live: "Acquiring Bank," whose real claims are almost entirely "resource does not answer the question," correctly produced an honest *"There is insufficient material to construct a substantive explanation"* lesson rather than a fabricated one, with a green fully-traceable badge — the anti-fabrication design holding under a genuine worst case, not just an evidence-rich one. Zero browser console errors. What remains genuinely unbuilt: Neo4j persistence of a `Lesson`, and no exercise/challenge attached to a lesson yet — Phase 11 (Challenge Engine) is real, sandbox-execution work that requires a Docker daemon to build and verify honestly (a real container-isolation claim needs a real container to test against); this development environment has no Docker binary available, confirmed directly rather than assumed, so Phase 11 is deferred rather than built against an untestable, simulated sandbox.

## §0.82 — Dewey: the Learning Portal renamed and restructured into its own module, separate from Discovery.AI

**Decided 2026-09-17, directly by the user, not inferred:** the Learning Portal extension (PRD.md §9) is named **Dewey**, both as a product name and as a personified guide the learner actually interacts with — not a cosmetic rename, a real module-boundary decision. Two real namesakes: the **Dewey Decimal System** (a library classification system — organizing and helping someone find their way through a body of knowledge, the same job a compiled course does over Discovery.AI's own knowledge graph) and **John Dewey**, the philosopher/psychologist whose educational theory (learning through real, guided experience, not rote transmission) is the actual pedagogy this extension already embodies — a lesson is composed only from real investigated claims and independently audited for traceability (Rules.md rule 19), never asserted from an LLM's unsourced memory. The name fits work already built, not a marketing label bolted onto it after the fact.

**The restructuring, done at the package level, not just in documentation prose:** `backend/curriculum/` and `backend/lessons/` (Phase 9.1/Phase 10) moved to `backend/dewey/curriculum/` and `backend/dewey/lessons/` (`git mv`, history preserved). A new `backend/dewey/__init__.py` states the module boundary as an enforceable fact: Discovery.AI's own packages (`backend/graph`, `backend/agents`, `backend/questions`, `backend/evidence`, `backend/reasoning`, `backend/research`, `backend/research_api`) have zero knowledge of Dewey and never import from `backend/dewey` — confirmed by the move itself requiring no changes to any Discovery.AI package, only to Dewey's own two packages, `backend/api/app.py` (the one place that wires both together), and the four verify scripts exercising them. This makes PRD.md §10.1's "Learning Portal is the first client, not the place the capability is built" literally true at import time, not merely true in architecture prose.

**Dewey's voice, added to the one real LLM call this whole extension makes** (`backend.questions.lesson_authoring.compose_lesson_explanation`): the system prompt now asks the model to write "as Dewey... warm, curious, plain-spoken," including admitting insufficient evidence "the way a good teacher admits 'I don't have enough to go on here yet' rather than bluffing." This is a **style-only** instruction — it changes zero of the anti-fabrication constraints already in place (only the given claims, nothing invented, say so plainly when they're too thin) — confirmed unchanged by re-running `scripts/verify_phase10.py` against real data after the change, still 4/4.

**Verified after the move: all four affected scripts re-run clean** — `scripts/verify_phase9_1.py` (5/5), `scripts/verify_phase9_2.py` (4/4, real Neo4j), `scripts/verify_phase10.py` (4/4, real Neo4j + real LLM), `scripts/verify_phase10_2.py` (4/4, real Neo4j + real LLM + real HTTP) — confirming the rename touched zero behavior, only names and file locations.

**Doodle illustrations** (`frontend/assets/dewey/dewey-wave.svg`, `dewey-thinking.svg`, `dewey-explaining.svg`) — hand-drawn-style line-art SVGs, hardcoded to the existing brand accent color (`#2f6f4f`, matching `course.html`'s own palette) rather than `currentColor`, since these are loaded via `<img>` tags — confirmed directly that `currentColor` does not resolve against a parent element's CSS `color` property through an `<img>`-loaded SVG (it stays isolated to the SVG's own default), so hardcoding was the correct fix, not a shortcut. Wired into `frontend/course.html`: a waving Dewey introduces the page ("Course, with Dewey"), a thinking Dewey appears while a lesson is composing, and an explaining Dewey appears beside every rendered lesson. Browser-tested live alongside the frontend fix above — both new poses (thinking, explaining) confirmed rendering correctly, zero console errors, colors matching the brand palette exactly.

**Deliberately not done:** no rename of `Course`/`Module`/`Lesson`/`IncompleteConcept` themselves — they're generic curriculum domain types, and Dewey is the product/persona identity layered on top of them, not a class-naming convention (the same relationship "Discovery.AI" already has to `Claim`/`Evidence`/`ResearchResponse`). No visual redesign of the rest of the site (`index.html`, `docs.html`, `chat.html`, `roadmap.html`) — Dewey is scoped to the Learning Portal pages he actually appears on.

## §0.84 — Dewey Source Pack v0.1: ground-truth research over ~18 candidate sites, then two new retrievers

**Real research, not assumption, before any code.** Given a proposed source pack (Wikipedia, GeeksforGeeks, cppreference, MDN, Stack Overflow, TutorialsPoint, Khan Academy, Exercism, MIT OCW, freeCodeCamp, and others), every candidate's real `robots.txt`, license, and official API/bulk-archive options were checked directly — fetched live, not summarized from a search result. Two findings changed the plan materially:

- **GeeksforGeeks' own `robots.txt` explicitly disallows the `anthropic-ai` user-agent for the entire site** (`Disallow: /`), alongside `cohere-ai`/`CCBot`/`Bytespider`. No official API exists (only unofficial community scrapers on GitHub). **Excluded from the automated pack** — a specific site, opting out a specific class of crawler, by name, confirmed directly rather than assumed compatible because it's a popular ed-tech site.
- **Stack Overflow's `robots.txt` now blanket-disallows all crawling** (`Disallow: /` for `User-agent: *`) plus a `Content-signal: ai-train=no` header; the data-dump license separately bars LLM-training use. **The only sanctioned path is the real-time Stack Exchange API, used per-question on demand — never bulk harvesting.**
- TutorialsPoint explicitly disallows `GPTBot`/`ChatGPT-User`/`CCBot`. Khan Academy and Exercism's live sites are both gated by an active Cloudflare bot-challenge (confirmed by a real request returning a JS-challenge page, not a robots.txt line) — Exercism's actual exercises are open-source on GitHub instead, a real, fetchable alternative to the gated website.
- Wikipedia (open API, CC-BY-SA — already a real, existing retriever, `WikipediaRetriever`), MDN (CC-BY-SA + CC0, and its entire content is a public git repo, `github.com/mdn/content` — no scraping needed at all), cppreference (CC-BY-SA-3.0 + GFDL, official downloadable archive), GitHub (its `robots.txt` explicitly lists `ClaudeBot`/`anthropic-ai` as recognized crawlers with a stated crawl-delay), and MIT OpenCourseWare (`Allow: /`, Creative Commons) all confirmed genuinely open.
- **A real, load-bearing surprise found while implementing, not while researching:** cppreference.com runs real MediaWiki software with a real REST/action API (confirmed by its own `<link>` tags), but it sits behind an active Cloudflare bot-challenge that blocked `action=opensearch` outright (a JS-challenge page) while `action=parse` on a *known* page title succeeded cleanly in the same session, on the same client. Free-text search against the site is therefore not reliable — the official downloadable archive (or, as built here, a small individually-verified page list) is the correct acquisition method, not "no robots.txt restriction, so live search is fine."

**Architectural evaluation, done before writing a new type, matching this project's own R-track discipline:** the source-pack proposal's own design record suggested a new `SourceAdapter` (`search`/`acquire`/`extract`) producing a `ResearchBundle` (discovered entities, candidate relationships, source records, provenance). Direct inspection of the real, already-built Evidence Engine found this would duplicate existing, working machinery: `gather_evidence_with_outcomes` (R1.2) already turns retrieval into `RetrievalOutcome`/`Evidence`/`Claim`; entity/relationship discovery already happens downstream of that, from synthesized claim text (`decide_next_step`'s `discovered_entity_name`, `extract_relations`), never from raw retrieved text directly. Building a second pipeline that discovers entities/relationships straight from fetched pages would be exactly the "second competing epistemic model" R1-R5 repeatedly rejected. **Decision: coexist and extend, not replace** — new sources are `Retriever` subclasses slotting into the existing `DEFAULT_RETRIEVERS`, carrying new but purely additive metadata.

**What was actually built:** `RetrievedResource` (`backend/evidence/models.py`) gained two new optional fields, `source_role` (what kind of evidence this retriever structurally produces — `entity_discovery`/`explanation`/`technical_reference`/`implementation`/`evidence`/`reference`) and `acquisition_mode` (`api`/`controlled_document`/`archive`) — both `None` for anything not yet classified, never a guessed default. `Retriever` (`base.py`) gained matching `ClassVar`s (default `acquisition_mode="api"`, `source_role="unclassified"`). All 6 pre-existing retrievers were backfilled with accurate values (Wikipedia → `entity_discovery`; arXiv/Semantic Scholar → `evidence`; Open Library → `reference`; Tavily/YouTube → `explanation`) — a real, low-risk, purely additive completion of the new field across every existing real case, not just the two new ones.

**`CppReferenceRetriever`** — `acquisition_mode="controlled_document"`: an 11-entry, individually-verified page map (`_KNOWN_PAGES`) covering exactly the "C++ pointers and memory" example topic (pointer, reference, new/delete, the `cpp/memory` smart-pointer overview, `unique_ptr`, `shared_ptr`, array, pointer arithmetic, lifetime, storage duration) — every single title confirmed to resolve via a real, live `action=query&titles=...` call before being added, not guessed from familiarity with cppreference's URL scheme (one guessed title, `cpp/language/pointer_arithmetic`, was confirmed *not* to exist this way, and correctly excluded in favor of the real page, `cpp/language/operator_arithmetic`). `search()` matches query keywords against this map (never free-text search against the live site, per the Cloudflare finding above), fetches each match's real wikitext via `action=parse`, and strips only structural `{{template}}` noise — a real, stated limitation, not silently hidden: this does not fully render wikitext to prose, so a returned snippet can carry residual markup, the same way other retrievers' raw snippets already carry HTML/markdown artifacts `synthesize_claim` has to read past.

**`GitHubRetriever`** — `acquisition_mode="api"`, keyless (GitHub's repository search API works unauthenticated, confirmed live, at a lower rate limit; an optional `GITHUB_TOKEN` env var raises it). Searches repositories, not individual files — a repo's name/description is enough signal for `synthesize_claim` to judge relevance, and file-level code search is far more rate-limited. **A real, honest data-quality finding from testing against live data:** one real result for "C++ pointer tutorial examples" (`hiteshsuthar01/OK-`) had raw HTML markup as its GitHub-hosted repository description — confirmed this is genuinely what GitHub's API returns for that repo, not a parsing bug on this retriever's side. Not filtered out here; exactly the kind of low-relevance noise `synthesize_claim`'s existing confidence scoring already handles for every other retriever (the same category as an unrelated arXiv physics paper scoring near-zero for a payment-gateway question, Phase 5/Phase 6).

**No topic-routing logic was added to gate either new retriever** — both fire unconditionally, like every retriever in `DEFAULT_RETRIEVERS` already does, and rely on the same existing confidence-scoring mechanism (`synthesize_claim`) to naturally down-weight irrelevant results, rather than inventing a second relevance mechanism.

**Verified: `scripts/verify_source_pack.py`, 4/4.** `CppReferenceRetriever` returned 2 real hits for a real query (correctly tagged) and 0 fabricated hits for a query outside its coverage; `GitHubRetriever` returned 3 real repository hits (correctly tagged); all 8 `DEFAULT_RETRIEVERS` confirmed to carry a real, non-default `source_role`/`acquisition_mode`; a real, live, unmodified call to `gather_evidence_with_outcomes` for "What is a pointer in C++, and how do smart pointers like `unique_ptr` manage its memory?" produced 9 real retrieval outcomes and, honestly reported rather than rounded up, exactly 1 real synthesized `Claim` (from `cpp/memory/unique_ptr`, confidence 0.2 — borderline, close to the non-answer threshold, not a clean success) — with that claim's source correctly carrying `source_role="technical_reference"`/`acquisition_mode="controlled_document"` all the way through the unmodified existing pipeline. Full regression suite re-confirmed unaffected.

**Deliberately not built:** MDN-repo-clone / cppreference-archive-download acquisition modes (the "archive" mode stays a real, named, unimplemented category — `controlled_document` was the correct, smaller choice for this slice given cppreference's live-site fragility), MIT OCW/freeCodeCamp retrievers, any new relation type, any Neo4j schema change, and no `POST /research/source-pack` endpoint — the existing `/research` route already benefits from these two retrievers automatically, with no new API surface needed.

## §0.85 — Dewey Source Pack v0.1 Quality Pass: one real investigation, two real findings, one about the Source Pack and one about the evaluation script itself

Per the design conversation's own explicit instruction ("the source pack is connected, but not yet proven educationally complete... freeze the API, run a structured evidence-quality evaluation before adding another source"), `scripts/evaluate_source_pack_quality.py` runs one real, un-mocked `GroundAgent(persist_to_graph=True, gather_evidence=True)` investigation on the exact controlled topic named throughout this whole design conversation — "C++ pointers and memory" — and reports coverage/source-quality/evidence-quality/metadata-integrity findings, matching this project's own `evaluate_*` convention (a diagnostic report, not a pass/fail assertion).

**Real result, reported exactly as observed, not rounded up:** the investigation decomposed to 3 real entities (`Pointer`, `dynamic memory allocation`, `pointer_risk`) and produced 4 real claims (3 supported at confidence ≥0.5, 1 weak at 0.35), with 0 provenance errors (every claim's source correctly carried `source_role`/`acquisition_mode`) and 3 of the 8 retrievers' roles (`entity_discovery`, `evidence`, `technical_reference`) contributing a surviving claim this run.

**A real, honest environmental confound, named rather than hidden:** this specific run hit Groq's daily per-organization token quota (200,000 TPD) repeatedly — confirmed directly in the run's own log, 75 separate rate-limit errors across all 9 configured Groq keys (spanning 3 distinct Groq organizations, confirming the key-rotation pool is working as designed — some keys' own separate accounts still had headroom, which is how the run eventually completed purely within Groq's pool without ever needing the `google/gemini-2.5-flash`/`cerebras/gpt-oss-120b` fallback tiers at all). This is a direct, cumulative consequence of the extensive real live-LLM testing already run earlier the same session (the S0.1 fix that unblocked 9 previously-`environment_blocked` scripts, plus Phase 10/10.2's real lesson-composition calls, plus `verify_source_pack.py`'s own real run) — not a defect in this evaluation or in the Source Pack, but a real reason this run's decomposition depth and evidence-gathering breadth were likely narrower than they would be against a fresh daily quota. Named explicitly so a future re-run's (likely richer) result isn't mistaken for "the Source Pack got better" when the real difference would just be quota headroom.

**A second real finding, about this evaluation script's own methodology, caught and fixed before being reported as fact:** the original coverage check matched expected-concept keywords against *every* claim's text regardless of confidence, which made "smart pointer" register as a false positive — the one weak claim (confidence 0.35) read *"...does not cover delete, malloc, free, or smart pointers,"* and simple substring matching cannot distinguish "explains X" from "explicitly says it does not cover X." **Fixed before reporting a final number, not after:** the coverage check now only matches against discovered entity names and *supported* (≥0.5 confidence) claim text. Recomputed against this same run's real data: **4 of 12 expected concepts genuinely covered** (pointer, address, dynamic allocation, dangling/invalid-access), not the original, false 5 — 8 genuinely missing (reference, dereference, pointer arithmetic, array/pointer decay, stack and heap, lifetime/ownership, smart pointer, memory leak). Stated plainly: this is a partial, honest mitigation, not a complete fix — real negation-aware judgment would need an LLM call this diagnostic script deliberately doesn't make (keeping it a cheap, mechanical check per its own scope), so a more subtly-negated mention could still slip through undetected.

**What this run actually demonstrates, separated cleanly (per the design conversation's own explicit layering principle):** source acquisition and metadata integrity are real and working (0 provenance errors, real content from real sources, honest empty results where coverage doesn't exist) — but conceptual completeness for this one topic is genuinely narrow after one investigation pass, which is exactly the honest baseline a "coverage, not just connectivity" evaluation is supposed to surface, not a failure of the check.

**Deliberately not done:** no second live run attempted in the same session (Groq's daily quota was clearly still exhausted; a re-run now would likely hit the same wall and produce an equally-confounded result, not a cleaner one) — a genuinely clean quality-pass re-run is real, separate future work, best done against a fresh daily quota. No fix to the underlying decomposition depth/breadth (that's Learning Research Mode's own §9.3a scope, not this diagnostic script's).

## §0.86 — Experiment C: the coverage checker's own precision/recall, measured before trusting it further

Per the design conversation's own explicit instruction — validate the measurement tool before spending more quota trusting its output — `check_concept_coverage` (§0.85's coverage-check logic) was extracted into a standalone, pure, dependency-free function and tested against a 27-case hand-labeled benchmark (`scripts/evaluate_coverage_checker_precision.py`), zero LLM calls, zero quota risk. Every case's ground truth is a stated human judgment (covered/not-covered, with a reason), including the *exact* real claim text from §0.85's live run that caused the original "smart pointer" false positive — now a permanent regression case, not a one-off bug report.

**Real result: precision 0.48, recall 1.00, zero true negatives out of 27 cases.** The checker never once correctly identified a "not covered" case — every mentioned-only, negated, or vague/shallow claim that contained a concept's keyword was flagged "covered," the same class of error §0.85 found by accident, now shown to be the checker's *general* behavior, not an isolated incident. One additional, previously-undiscovered false positive found by deliberately adversarial construction: a claim about **Python's** garbage collector ("reference counting and cycle detection") registered as covering the C++ **"reference"** concept, purely because "reference counting" contains the substring "reference" — a topic-unrelated false positive, distinct from the negation-based ones.

**The honest, load-bearing implication: §0.85's "4 of 12 concepts genuinely covered" figure is very likely an *overestimate*, not a confound-corrected true value.** Recall of 1.00 means the checker never misses a real mention (safe to trust "concept X is entirely absent" when the checker reports it missing) — but precision of 0.48 means roughly half of everything it reports "covered" may not actually be. **Reframed, not silently kept as before:** this mechanical checker is a cheap, high-recall/low-precision *triage signal* — "not found" is a trustworthy negative result; "found" is not a trustworthy positive one without a real semantic judgment this cheap, zero-LLM-call function was never designed to make.

**Decision, made deliberately rather than by default:** do not add LLM-based semantic judgment to this checker in this pass. Two real reasons, not one: (1) this session has already hit Groq's daily quota once from cumulative live-LLM testing (§0.85) — adding a third LLM call per concept-check would make an already-quota-constrained evaluation loop worse, not better, at exactly the moment quota discipline matters most; (2) matching this whole project's own evaluate-before-build discipline, a real semantic-judgment mechanism deserves its own dedicated design pass (what labels does it need — the richer `ConceptCoverage` shape the design conversation proposed: mentioned/defined/explained/exemplified/connected-to-prerequisites/etc. — and what model tier, at what cost, is that worth for a diagnostic script), not a same-turn addition bolted onto a script that was deliberately built cheap. **Experiments A (clean rerun) and B (targeted investigation) are deferred, not because they're not worth doing, but because their output would be filtered through this same known-unreliable checker** — running them now would produce another confident-looking number built on a proven-unreliable measurement, exactly the mistake this experiment exists to prevent.

## §0.87 — Coverage contract formalized: `backend/dewey/coverage/` package, the checker renamed to what it actually does, negation/collision fixes measured (not guessed)

Direct continuation of §0.86, per the design conversation's own explicit instruction: "The next task should be neither Experiments A/B nor immediate LLM integration. It should be: Write the coverage contract and rename/reframe the current checker as lexical candidate detection." Evaluated against Phase 8.3's existing `FieldCoverage`/`ConceptCompleteness` before writing any code (both docstrings re-read) and confirmed a genuinely different axis — Phase 8.3 measures per-entity internal field completeness inside one investigation; this package measures cross-topic external curriculum-concept presence in free text — not a duplicate abstraction.

**`backend/dewey/coverage/schema.py`** — the formal `CoverageStatus` ontology: `ABSENT`, `MENTIONED`, `DEFINED`, `EXPLAINED`, `EXEMPLIFIED`, `BOUNDED`, `CONTRASTED`, `MISCONCEPTION_CORRECTED`. Written down *before* any checker capable of the richer values exists, so a future semantic checker has a real target to be evaluated against. The critical, structurally-enforced scoping decision: **`ConceptCoverageResult` has a `model_validator` that raises if any checker whose name starts with `"lexical"` claims a status outside `{ABSENT, MENTIONED}`** — not left as a docstring promise a future checker or downstream reader could quietly violate. A `.semantically_verified` property (`False` for `ABSENT`/`MENTIONED`, `True` only for `DEFINED`+) is the one thing downstream code should read to decide "is this concept genuinely known to be covered" — never `status != ABSENT`. Both additions came from an external review's explicit concern: "make sure the shared checker's output is impossible to misread downstream... a later evaluator could accidentally treat MENTIONED as completed coverage."

**`backend/dewey/coverage/benchmark_cases.py`** — the 27 hand-labeled cases from §0.86's Experiment C, moved out of `scripts/evaluate_coverage_checker_precision.py` (now deleted) into a permanent, reusable `BenchmarkCase` dataclass list, per the explicit instruction "The 27 hand-labeled cases are now valuable. Preserve them permanently."

**`backend/dewey/coverage/lexical_candidate_checker_v0.py`** — `check_concept_coverage`, renamed/reframed with its own honest capability statement in its module docstring: it can only ever output `ABSENT` or `MENTIONED`. Two real, benchmark-driven fixes, both Phase C.2 items:
1. **Clause-based negation detection** — text is split on `.`/`;`/`but` before each clause is checked independently, so "explains new... but does not cover smart pointers" correctly registers `dynamic allocation` as mentioned and `smart pointer` as absent, instead of one global negation check wrongly suppressing both.
2. **Per-concept domain-collision exclusion phrases** — a small, explicit `DEFAULT_EXCLUSION_PHRASES` map (currently one entry: `"reference"` excludes `"reference counting"`/`"reference cycle"`/`"garbage collect"`) fixes the Python-GC adversarial false positive from §0.86, without a general-purpose disambiguation mechanism this project explicitly doesn't want.

**A real regression caught and fixed during this same slice, not after:** the first version paired strict `\bphrase\b` word-boundary matching with an optional trailing `s` (to catch plurals). Running it against the persisted benchmark immediately showed recall dropping from 1.00 to 0.92 — `EXPECTED_CONCEPTS` deliberately uses partial-word stems (`"dereferenc"`, to match "dereference"/"dereferencing"/"dereferenced" in one pattern), and a trailing `\b` right after a stem can never match, since real text continues with more word characters at exactly that position. Fixed by anchoring the word boundary at the START of the phrase only, with a trailing `\w*` instead of a fixed optional suffix — preserves the "don't match 'new' inside 'renewed'" safety property word-boundaries exist for, while correctly matching "dereferencing," "decays," "allocated," etc.

**Real, measured result against the persisted 27-case benchmark (not assumed):**

| | before (§0.86, unnamed checker) | after (`lexical-candidate-v0`) |
|---|---|---|
| precision | 0.48 | **0.59** |
| recall | 1.00 | **1.00** |
| true negatives | 0 / 27 | **5 / 27** |

Negation + collision handling fixed 5 of the original 14 false positives at zero recall cost. **The remaining 9 false positives are not a bug** — 8 are `mentioned_only`/`shallow` cases where `MENTIONED` is the lexically correct, honest answer (a real, non-negated keyword genuinely appears) but the human ground truth was judging a different, semantic question ("was this genuinely explained?") that a lexical checker cannot answer by design. The 9th (`lifetime/ownership`, category `negated`) is a real, named limit of clause-level splitting: "Ownership models are important... but [it is] outside the scope of this page" splits into a clause that mentions "ownership" and a separate clause carrying the negation — clause-level splitting cannot see that the second clause retroactively scopes out the first. Closing that gap needs cross-clause or real semantic judgment, explicitly deferred to a future `semantic_coverage_checker_v1.py`, not patched here with a special case.

**`backend/dewey/coverage/lexical_candidate_checker_v0.py` also gained `diagnose_concept()`** — additive, does not change `check_concept`'s contract — returning the full per-clause breakdown (matched/negated/collision-excluded, with reasons) behind one verdict, built for a future coverage-diagnostic report rather than the pass/fail path.

**`scripts/verify_coverage.py`** (new, real `verify_*` pass/fail script, not `evaluate_*`) — asserts precision ≥ 0.59 and recall ≥ 1.00 against the persisted benchmark; a real regression test with a measured, not guessed, baseline.

**`scripts/evaluate_source_pack_quality.py`** updated to import `check_concept_coverage` from the new package instead of keeping its own copy — no duplicated coverage logic across two files. Its report's `expected_concepts_found_caveat` and module docstring both updated with the real 0.59/1.00/5-true-negatives numbers.

**Regression check against the rest of the system, run explicitly because a reviewer raised the possibility that the afternoon's retriever/checker changes could have degraded previously-working behavior, not just the checker's own precision:** the full 47-script `scripts/run_all_verifications.py` suite (spanning dozens of pre-existing scripts across unrelated topics that predate the Source Pack work) was run twice — once with output accidentally lost to a `tail -80` truncation on the invoking side, once with output correctly captured to a file. Real result: **46 passed, 0 environment-blocked, 0 timed out, 1 failed.** The one failure, `verify_phase5.py`, was re-run standalone and its real cause fully captured: a Groq 429 `rate_limit_exceeded` on every one of the 9 configured keys across all 4 organizations, each reporting `Used ~199,4XX-199,9XX / 200,000` tokens-per-day — genuine same-day quota exhaustion from this session's own cumulative live-LLM testing (two full-suite runs, the Quality Pass, the Source Pack verification), not a code defect. `run_all_verifications.py`'s own `environment_blocked` categorization only recognizes a missing API key, not a 429 against a *present* key — a real, minor categorization gap, named here rather than silently misreporting this as a code "failed." **No evidence of a registration-scope regression**: `CppReferenceRetriever`/`GitHubRetriever` being added to `DEFAULT_RETRIEVERS` did not break any of the 46 unrelated, previously-passing scripts.
