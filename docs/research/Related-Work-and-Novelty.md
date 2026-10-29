# Related Work, What to Borrow, and How New Our Ideas Are (2026-10-28)

Scope: Discovery.AI (reasoning engine), Dewey (research engine + Archive), and
Tuni'n (adaptive course portal). Sources are listed at the end. Where only an
abstract or a secondary summary was read, the claim is marked *(abstract)* or
*(secondary)*. "I found no X" means my searches didn't find one, **not** that
none exists.

---

## 1. What our system actually is (as built, not as planned)

| Part | Built today | Verified |
|---|---|---|
| Recursive investigation | Master + recursive Ground agents; answer / decompose / boundary decisions; dimension "lenses" (scale, perspective, time) steer decomposition; spawn budget | Phases 3–4, live runs |
| Knowledge graph | Neo4j canonical entities, abstractions, typed relations, non-strict hierarchy | Phase 1 PASS on new Aura |
| Epistemics | RetrievalOutcome → Evidence → Claim → Answer types; claim lifecycle (supported / contradicted / superseded); subclaims; duplicate resolution | R1–R5: 83 offline checks PASS |
| Coverage | CoverageStatus scale (mentioned → misconception-corrected); lexical first-pass checker (precision 0.59) | verify_coverage PASS |
| Dewey Archive | Shared, growing passage store (SQLite + FTS5) + research ledger (including "searched, nothing found") | 10/10 |
| Dewey engine | Archive first → ledger → routed providers → ingest → re-query; reports per source | 8/8 |
| Tuni'n | Brief, proposal, approval gate, two-module buffer, artifact compiler designed and partly written; Bloom/depth framework from the user's PDFs | not yet runtime-tested |

**Known central defect (live run 3):** answers are written from the model's
memory first, and evidence is attached afterwards, so 0 claims backed a
confident answer.

---

## 2. Related work, component by component, and what to borrow

### 2.1 Deep-research agents
| Work | What it does | Overlap with us | Borrow |
|---|---|---|---|
| **Open Deep Research** (LangChain) | Scope → brief → supervisor delegates to sub-agents with separate contexts → each compresses findings with citations → one-shot report. Parallel *writing* failed. | MasterAgent ≈ supervisor; Ground ≈ sub-agent | **Compressed, cited child results** passed upward (not raw trees); write the course once, after research. |
| **STORM / Co-STORM** (Stanford) | Perspective-guided questions, simulated writer/expert dialogue, outline, then article. Cost = max_turn × (max_perspective+1). | Our dimensions ≈ perspectives | **Perspective-guided gap questions** with the same explicit cost bound. |
| **DualGraph**, "A Tale of Two Graphs" (2026) *(abstract)* | Keeps a **knowledge graph** (what the agent knows) separate from an **outline graph** (how it writes). Gap queries come from KG topology + outline signals. Beats baselines on 4 open-ended deep-research benchmarks (53.08 RACE). | **Closest match to our design**: Neo4j graph = what we know; course plan = what we write | **Topology-driven gap detection**: entities with no supported claims, missing relation types, single-source concepts → new InformationNeeds. |
| **GPT-Researcher** *(secondary)* | Planner → parallel researchers → scrape → filter → aggregate | Dewey | Fetch + filter passages, not snippets (Dewey step 3). |

### 2.2 Interleaving reasoning and retrieval (the inner loop)
| Work | Borrow |
|---|---|
| **ReAct / IRCoT / Self-Ask** | Retrieve *between* reasoning steps; Self-Ask-style decomposition we already have. IRCoT led multi-hop baselines in several reports but not universally. |
| **CRAG / Self-RAG** *(secondary)* | **Grade evidence** as correct / ambiguous / incorrect → answer / re-query / broaden. CRAG is only as good as its grader, so measure it. |
| **SAAS over-search** (2026) | Agents search when they don't need to and fail to stop. → **Explicit stop rules** (sufficiency, novelty saturation, budget). |

### 2.3 Graph RAG: reading from our Archive + graph
| Work | Finding | Borrow |
|---|---|---|
| **HippoRAG 2** *(secondary comparisons)* | Generally strongest on multi-hop and precise factual retrieval; PageRank over an entity graph | Archive passages are already tagged with graph entity ids → **expand an Archive query through graph neighbours** (personalised-PageRank-style ranking) for multi-hop needs. |
| **GraphRAG** (Microsoft) | Community summaries suit broad "sense-making" questions; costs more tokens | Later: per-topic summaries as course overviews. Not needed now. |
| **LightRAG** | Cheaper, supports incremental updates | Supports our choice of an archive that grows incrementally. |

### 2.4 Memory that grows and consolidates (fixes our duplicate concepts)
| Work | Mechanism | Borrow |
|---|---|---|
| **Mem0** | On each new fact: **ADD / MERGE-UPDATE / DELETE (contradiction) / no-op** decision | **Apply at entity-write time**: before creating "the BST property", decide whether it's the same as "BST Property" / "BST Invariant" → merge. This is the fix for the 4× duplicate concept seen live. Our `merge_entity` exists but nothing calls it at write time. |
| **A-MEM** | Zettelkasten-style notes that link and *evolve* when new memories arrive; contrasts itself with static agentic-RAG stores | Passage ↔ entity links in the Archive; update linked notes when a new version of a source arrives (versioning already built). |

### 2.5 Attribution and factuality (proving answers are grounded)
| Work | Borrow |
|---|---|
| **FActScore** | Split generated text into **atomic facts**, measure the share that's supported. → Our grounded-answer check: split the answer into atomic statements, check each against Archive passages / claims. |
| **ALCE** | Citation **precision** (cited sources are relevant) and **recall** (needed sources are cited). → The two numbers every run should report. |
| Sub-claim attribution (ACL 2024) | Separates groundedness errors from citation errors; detects partial support. → Report "partially supported" honestly instead of rounding up. |
| Generation-time vs post-hoc citation (2025) | Recommends retrieval-first, post-hoc citation for high-stakes use. → Matches our plan: retrieve first, write from evidence, audit after (`audit_synthesis`). |

### 2.6 AI tutoring and course generation (the Tuni'n side)
| Work | What it shows | Borrow |
|---|---|---|
| **TutorLLM** (2025) | Knowledge tracing (MLFBK) + RAG to tailor content to the learner's predicted state; recommends content, not whole curricula | A light **knowledge-tracing** model (e.g. Bayesian KT) per concept instead of hand-tuned mastery numbers, later. |
| **LOOM** (2025) *(abstract)* | Dynamic learner memory graph from conversations → topic planning → course generation; small study (n=10) found lessons relevant; users wanted more consistency and control | Validates the learner-graph + generate-modules idea; their "more control" finding supports our **approval gate**. |
| Persona/memory/**forgetting-aware** tutoring (2025) | Individual forgetting curves instead of static snapshots | Schedule **spaced retrieval** from per-concept forgetting estimates. |
| **LLM Agents for Education** survey (EMNLP 2025) | Knowledge tracing and curriculum design as agent tasks; multi-agent setups with a Learning Path Scheduler + Content Creator | Our split (curriculum planner ≠ lesson writer ≠ assessor) matches the field. |
| RAG lesson planning, Uganda (2024) | Even with RAG, **hallucination remained a key limitation** | Grounding has to be *checked* (2.5), not assumed because RAG was used. |
| Reliable scaffolding (2025) | LLM-as-judge helps but shows **position and verbosity bias** | Our LLM grading of open answers must be treated as fallible; randomise option order, cap answer length in judging. |
| Generate-verify-refine for personalised learning (TUM) | Multi-agent QA before content reaches the learner | Validate every module before publishing (artifact validator exists). |
| Products: LearnLM / NotebookLM / Khanmigo *(secondary)* | Pedagogy-tuned model; source-grounded notebooks; tutor with guardrails | NotebookLM is the closest product to "learn only from these sources", but it is user-supplied sources and not course generation. |

---

## 3. How new are our ideas? (honest assessment)

**Not new on their own:** recursive question decomposition, deep-research
agents, graph RAG, agent memory, knowledge tracing, RAG tutors, LLM course
generation. Each has strong prior work above.

**Less common in what I found, i.e. likely distinctive as a *combination*:**

1. **Claims with a lifecycle feeding a curriculum.** Deep-research systems end
   at a report. Tutors use RAG passages. I found no system where course
   content is compiled from claims that carry a *lifecycle* (supported →
   contradicted → superseded) with provenance down to the source passage, so a
   lesson can be re-checked when a claim changes. Closest: DualGraph (knowledge
   graph vs output structure) and NotebookLM (source-only answers).
2. **One shared, growing evidence Archive across learners, with a memory of
   failed searches.** Memory papers (Mem0, A-MEM) grow per-agent or per-user
   memory. A cross-learner research cache that also remembers "searched, nothing
   found, retry after X" (our ledger) to avoid over-search wasn't something I
   found described for curriculum building.
3. **Pedagogy as data, driven by evidence signals.** Bloom level per concept +
   a signal→technique table (from the user's PDFs) + mastery gating. ITS
   research has long done adaptive sequencing; the explicit, configurable
   mapping from LLM-graded assessment signals to a named technique is a
   practical, inspectable design rather than a research first.
4. **Discipline about what's known:** keeping "source fetched" apart from "source
   answers", keeping empty apart from unknown, and never treating an unchecked
   result as passed. This is engineering rigour; papers measure the same thing
   as attribution metrics (2.5).

**Where we're behind the state of the art:**
- Answers aren't grounded yet (the live defect). DualGraph, Open Deep Research
  and NotebookLM all retrieve before writing.
- No benchmark numbers. Every paper above reports metrics; we have none for
  claim support, citations, or learning outcomes.
- Coverage is a keyword check (precision 0.59). The field uses LLM/NLI
  judgments with measured agreement.
- Stopping is rule-based. Over-search research learns it.
- Mastery is hand-tuned rules, not a knowledge-tracing model.
- No user study (LOOM ran n=10; we have none).

**What would make the novelty claim defensible:** measure (a) atomic-claim
support rate (FActScore-style), (b) citation precision/recall (ALCE-style),
(c) Archive hit-rate and web calls per course over repeated topics (does the
archive really "evolve"?), (d) quota per course, (e) later, learning gains with
real learners.

---

## 4. Implementation plan: what we take, in order

| Priority | Borrowed idea | Into | Fixes |
|---|---|---|---|
| **P1** | Retrieve-then-write + post-hoc audit (P-Cite, FActScore atomic check) using GitHub's unused `Answer` model + `compose…` + `audit_synthesis` | Discovery.AI inner loop | Ungrounded answers |
| **P1** | CRAG-style evidence grade + stop rules (SAAS) | Inner loop | Over-search / under-search |
| **P1** | Fetch + extract full pages (GPT-Researcher style) + keyless web search | Dewey step 3 | 0 evidence, rate-limited raw queries |
| **P2** | Mem0-style ADD/MERGE/NOOP at entity-write time; fixed relation vocabulary | Graph writes | 4× duplicate concept, 3 redundant edges |
| **P2** | Compressed cited child results (Open Deep Research) | Master ← Ground | Context bloat, quota |
| **P3** | DualGraph topology-driven gap needs + STORM perspectives with cost bound | Outer loop | Insert/delete never investigated |
| **P3** | HippoRAG-style neighbour expansion over entity-tagged Archive passages | Dewey Archive query | Multi-hop retrieval |
| **P4** | Light knowledge tracing + forgetting curves; LLM-judge bias controls; generate-verify-refine | Tuni'n learner model / assessment | Mastery estimates, grading reliability |
| **Always** | Evaluation harness: 10 topics with hand-checked facts; report claim-support %, citation P/R, archive hit-rate, LLM calls | scripts/evaluate_* | Turns "it works" into numbers |

## Sources
- Open Deep Research: https://www.langchain.com/blog/open-deep-research
- STORM: https://arxiv.org/pdf/2402.14207v2
- DualGraph / A Tale of Two Graphs: https://arxiv.org/abs/2602.13830
- GPT-Researcher: https://github.com/assafelovic/gpt-researcher
- Recursive Language Models (blog): https://www.primeintellect.ai/blog/rlm
- Researchy Questions: https://arxiv.org/pdf/2402.17896
- CogMG: https://arxiv.org/pdf/2406.17231
- RAG-reasoning survey: https://arxiv.org/pdf/2507.09477 · Agentic RAG survey: https://arxiv.org/html/2506.10408v1
- SAAS over-search: https://arxiv.org/pdf/2605.29796
- CRAG (secondary): https://www.analyticsvidhya.com/blog/2024/12/corrective-rag/ · Self-RAG/LangGraph: https://blog.langchain.com/agentic-rag-with-langgraph
- HippoRAG 2 / LightRAG / GraphRAG comparisons: https://arxiv.org/pdf/2607.11683 , https://arxiv.org/pdf/2511.05549 , https://arxiv.org/pdf/2503.04338
- A-MEM: https://arxiv.org/abs/2502.12110 · Mem0: https://www.researchgate.net/publication/391246545 · Self-evolving agents survey: https://arxiv.org/pdf/2507.21046 · Memory papers list: https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- ALCE: https://collaborate.princeton.edu/en/publications/enabling-large-language-models-to-generate-text-with-citations/ · Attribution (ACL 2024): https://aclanthology.org/2024.acl-long.806.pdf · Generation-time vs post-hoc citation: https://arxiv.org/html/2509.21557v1 · REC: https://arxiv.org/pdf/2411.02448 · Attribution survey: https://arxiv.org/html/2311.03731
- TutorLLM: https://arxiv.org/abs/2502.15709 · LOOM: https://arxiv.org/abs/2511.21037 · Forgetting-aware tutoring: https://arxiv.org/pdf/2511.15163 · LLM Agents for Education: https://aclanthology.org/2025.findings-emnlp.743.pdf · Training LLM tutors: https://arxiv.org/pdf/2503.06424
- RAG lesson planning (Uganda): https://arxiv.org/pdf/2408.07542 · Reliable scaffolding / LLM-judge bias: https://arxiv.org/pdf/2508.05929 · TUM multi-agent QA: https://www.cs.cit.tum.de/bpm/multi-agent-llm-architectures-for-quality-assurance-and-governance-in-personalized-learning-systems/ · Lesson-plan evals case study: https://www.zenml.io/llmops-database/implementing-production-ready-llm-evaluations-for-ai-generated-lesson-plans
- LearnLM (secondary): https://thejournal.com/Articles/2024/05/16/Google-Unveils-New-LearnLM-Models-for-Students-Gemini-Features-for-Education.aspx
