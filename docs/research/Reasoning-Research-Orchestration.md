# Main Block — Reasoning Engine × Research Engine Orchestration (research, 2026-10-28)

Main block = **Discovery.AI** (reasoning) + **Dewey** (research). This doc covers
how Dewey should be built and how the two should loop. Code facts come from
reading this repo. Literature claims are cited at the end and labelled when
they come from secondary sources.

---

## 1. How the two connect today (code facts)

| Where | What actually happens |
|---|---|
| `ground_agent.py:255` | `decide_next_step` → `answer` / `decompose` / `boundary_hit`. When it answers, the **answer comes from the LLM's own memory**. |
| `ground_agent.py:276-280` | **Only after** deciding to answer: `gather_evidence(self.question)`. The evidence is attached to the result but **never fed back into the answer**. |
| `evidence/engine.py:113` | The query is **the raw question text**, sent unchanged to **all 8 retrievers** regardless of topic (arXiv for "history of jazz", CppReference for biology). |
| `evidence/engine.py:119` | **One LLM `synthesize_claim` call per retrieved resource**: 8 retrievers × 2 results = up to **16 LLM calls per answered node**. Gemma's free tier is reportedly ~15 RPM, so one node can use a full minute of quota. |
| `RetrievedResource.snippet` | Only search snippets. No page is ever fetched or read in full. |
| `engine.py:19` | Non-answer filter at confidence < 0.2 → `RetrievalOutcome`, not a `Claim`. **Good: keep it.** |
| `research/investigate.py` | `plan_targeted_investigations` / `close_coverage_gaps`: an **outer loop already exists** at the artifact level. It re-investigates concepts whose required fields are missing. **Good: build on it.** |

**Main weakness:** the reasoning and the research don't interact. The model
answers first and the sources are looked up afterwards. Evidence is added
after the fact and can't correct the answer. That's the opposite of what a
learning product needs, because lessons must be grounded in sources.

---

## 2. What the field has learned

| Pattern | Idea | What we take from it |
|---|---|---|
| **ReAct** | Alternate *thought → search action → observation*. | The reasoning step decides *what it needs*; the retrieval result goes back into the next thought. |
| **Self-Ask** | Break the question into sub-questions, retrieve for each. | Discovery.AI already does this (`decompose`). Keep it. |
| **IRCoT** | Each reasoning step drives the next retrieval, and retrieved text refines the reasoning. Led multi-hop QA baselines in several reports, but **not universally** (VOTE-RAG found it below naive RAG on some benchmarks). | **Interleave, don't bolt on.** Retrieve *before* the final answer, not after. |
| **FLARE** | Retrieve only when the model's confidence drops. Results were the most variable across reports. | Don't use confidence-triggered retrieval as the *only* trigger. For learning content, always ground. |
| **Self-RAG / CRAG** | Grade retrieved documents: correct / ambiguous / incorrect. If insufficient → rewrite the query or broaden to web search. CRAG depends heavily on its evaluator's quality. | Add an explicit **evidence-sufficiency grade** that chooses between *answer*, *re-query*, *broaden provider* and *give up honestly*. |
| **Over-search (SAAS, 2026)** | Agents search when they don't need to and don't stop once evidence is adequate. Real cost and latency. | Need **stop rules**: sufficiency, novelty saturation, budget. |
| **STORM / Co-STORM** | Find *perspectives* first, then ask questions from each perspective. Cost is bounded by `max_turn × (max_perspective+1)`. | Use perspectives (Discovery.AI's dimensions: scale / perspective / time; for learning: definition / mechanism / example / misconception / prerequisite) to generate the *outer-loop* gap questions. Budget them the same way. |
| **Open Deep Research (LangChain)** | Scope → research brief → supervisor delegates sub-topics to sub-agents with **separate contexts**. Each sub-agent **compresses** its findings with citations before returning. Supervisor loops until the brief is covered. **Multi-agent *writing* failed** (sections didn't fit together), so writing is one step at the end. | Brief = Tuni'n's `CourseDesignBrief` → `ResearchRequest`. MasterAgent = supervisor. Ground nodes must return **compressed, cited findings**, not raw output. Lessons are written once, after research. |
| **GPT-Researcher** | Planner writes research questions → parallel researchers search, scrape and filter → aggregate. *(Architecture from secondary sources.)* | Dewey needs **fetch + extract + passage filtering**, not just snippets. |

---

## 2b. User direction (2026-10-28): two engines + a growing archive

> "create our own database which is relevant, and over time the reasoning
> engine can use it again and again like a RAG system, or connect to the
> research engine again to research relevant parts if they don't exist yet."

So the main block has **three parts**, not two:

| Part | Role |
|---|---|
| **Discovery.AI**: reasoning engine only | Decides what it needs to know, judges evidence, forms claims, keeps the knowledge graph. **Never calls the web.** Reads evidence from the Archive. |
| **Dewey Archive**: our own database | A persistent, growing library of extracted source documents split into passages, with full provenance, indexed for search (keyword now, meaning-based later). Shared across all investigations and learners. **This is the RAG store.** |
| **Dewey Research Engine** | Fills the Archive: query planning → routing → search (keyless providers, DigitalOcean/Tavily optional behind the same interface) → fetch → extract → passages → **ingest into the Archive**. Runs only when the Archive can't answer a need. |

**Read-through flow, "archive first, research on a miss":**

```
Discovery.AI needs X  (InformationNeed)
   │
   ▼
Archive.query(X) ──► enough relevant, fresh passages?  ── yes ──► evidence → reasoning
   │ no / thin / stale
   ▼
Research ledger: was X already researched recently with nothing found?
   │ yes → return "known gap" (don't re-search; retry after a cool-down)
   │ no
   ▼
Dewey.research(X) → search → fetch → extract → ingest into Archive
   │
   ▼
Archive.query(X) again → evidence → reasoning
```

Over time a growing share of needs are answered **from the Archive with no web
call and no quota spent**. Each new course on a related topic makes the next
one faster and better grounded. That's the "evolving system".

**Kept separate on purpose:** the Archive holds *sources and passages* (what
was read). The Neo4j graph holds *entities, claims and relationships* (what was
concluded). A claim in the graph points to the Archive passage IDs it came from,
so provenance runs graph → passage → URL + retrieval time, and nothing is stored twice.

**Archive storage (default):** SQLite with **FTS5** (built-in keyword ranking,
no new dependency, no server) behind an `ArchiveStore` interface. Meaning-based
search (Gemini embeddings, or `sqlite-vec`) comes in a later slice. Supabase
Postgres + pgvector (already in `.env` as `DATABASE_URL`) is the deployment
option behind the same interface. Neo4j Aura isn't used for passages: the free
tier is capped at about 200k nodes, which raw text would fill.

**Archive record shape:** `Document` (canonical URL, title, provider,
source_type/role, licence note, retrieved_at, content hash, version) →
`Passage` (text ≤ ~1.5k chars, position, document ID, linked entity IDs,
need kinds served) → `ResearchLedger` (need fingerprint, when researched,
providers tried, outcome, next-retry time).

## 3. Responsibilities: who owns what

```
                ┌──────────────────────── DISCOVERY.AI (reasoning) ───────────────────────┐
                │ owns: what to ask · decomposition · claims · judgment · sufficiency ·   │
                │       contradictions · graph · ResearchResponse                         │
                └───────────────▲──────────────────────────────────┬──────────────────────┘
                     EvidenceBatch (passages + provenance          │ InformationNeed
                     + per-provider RetrievalReport)               │ (typed, budgeted)
                ┌───────────────┴──────────────────────────────────▼──────────────────────┐
                │                       DEWEY (research engine)                           │
                │ owns: query formulation per provider · source routing · search ·         │
                │       fetch · extraction · passage ranking · dedupe · cache/index ·      │
                │       robots/SSRF/rate limits · provenance stamping                      │
                └──────────────────────────────────────────────────────────────────────────┘
```

**Rule:** Dewey never judges truth and never creates a `Claim`. Discovery.AI
never calls an HTTP provider directly. `synthesize_claim` stays in
Discovery.AI because it is a judgment. `RetrievedResource` and `RetrievalOutcome`
stay as they are, so existing verify scripts keep passing.

### The contract (new types, small)

- **`InformationNeed`**: `question_id`, `text`, `need_kind` (definition /
  mechanism / example / comparison / history / implementation / evidence /
  misconception / prerequisite), `entity_name`, `scope_hint`,
  `exclude_urls` (already seen), `round` (0, 1, 2…).
- **`EvidenceBatch`**: ranked `Passage`s (text chunk ≤ ~1.5k chars, `RetrievedResource`
  as provenance, `rank_score`, `extraction_method`), plus a **`RetrievalReport`**
  (per provider: queried / skipped-no-key / rate-limited / robots-denied /
  failed / n results). The report makes "no evidence found" distinguishable
  from "couldn't search", which the project's rules already require.

---

## 4. Dewey internals (the research engine)

```
InformationNeed
  → 1. Query planner     need_kind + entity → 1–3 provider-specific queries
                         (keyword form for arXiv/OpenAlex, natural form for web,
                         symbol form for CppReference/GitHub). Deterministic
                         templates first; an LLM rewrite only on a re-query round.
  → 2. Router            Provider registry: capabilities × need_kind × domain.
                         "mechanism of BST" → web + Wikipedia + OER, not arXiv.
                         "evidence for X"  → OpenAlex/Semantic Scholar/arXiv.
  → 3. Search            Parallel, per-provider timeout + rate limit + key check.
  → 4. Fetch + extract   Top-N URLs only. robots.txt, SSRF guard, size/type caps,
                         trafilatura → BeautifulSoup fallback; PDF via pypdf.
  → 5. Passages          Split into chunks; cheap lexical ranking (BM25) against
                         the need → keep top-k (e.g. 4). THIS is the quota lever:
                         the LLM sees 4 passages, not 16 snippets.
  → 6. Dedupe/normalize  Canonical URL, near-duplicate text, same-source merge.
  → 7. Cache/index       SQLite: url→extracted text (TTL), query→results (TTL).
                         Reused across investigations and learners.
→ EvidenceBatch + RetrievalReport
```

Provider set for slice 1 (all keyless or already configured): DuckDuckGo web
search (installed), Wikipedia (fix the 403), arXiv, Semantic Scholar, Open
Library, CppReference, GitHub, Crossref (new, keyless). OpenAlex needs a free
key; Tavily, YouTube and DigitalOcean need keys and are optional. Playwright is
off by default.

---

## 5. The orchestration loop

### Inner loop: per question (in `GroundAgent`), IRCoT/CRAG style

```
decide_next_step(question, known)
 ├─ decompose → child questions (unchanged)
 ├─ boundary_hit → stop (unchanged)
 └─ answer → treat as DRAFT, not final
      round r = 0..R_max (default 2):
        need  = InformationNeed(question, need_kind, exclude seen URLs)
        batch = Dewey.retrieve(need)
        claims += synthesize_claim over batch passages (top-k only)
        grade = sufficiency(question, claims, report)
              SUFFICIENT  → final answer = re-answer GROUNDED in claims, with citations
              AMBIGUOUS   → reformulate need (LLM rewrite) and/or widen providers → loop
              INSUFFICIENT and r == R_max → final answer marked
                            "unsupported by retrieved evidence", draft kept as hypothesis
              CANNOT_SEARCH (report shows providers down) → mark "not verified", no fake claims
```

The **grounded re-answer** is the key change: the final `answer` is written
from the claims, and any sentence without support is marked. This reuses the
existing `audit_synthesis` that already checks lesson traceability.

### Outer loop: per investigation (already exists in `close_coverage_gaps`)

```
artifact = compile_research_artifact(abstraction)
gaps = concepts with missing required fields  ∪  contradictions  ∪  unsupported answers
for each gap (bounded by policy budget):
     perspective-guided question (STORM-style; need_kind from the missing field)
     → run_targeted_investigation (inner loop above)
stop when: no gaps | budget spent | novelty saturation (a round added 0 new claims)
```

### Stop rules (against over-search)
1. **Sufficiency**: required fields for this need are covered by claims with confidence ≥ 0.5.
2. **Novelty saturation**: a round produced no new claim and no new URL → stop.
3. **Budget**: `ResearchPolicy` gains `max_retrieval_rounds`, `max_llm_calls`, `max_fetches`. MasterAgent's spawn budget stays as it is.
4. **Cannot search**: every relevant provider failed or was skipped → stop and say so.

### Compression (Open Deep Research lesson)
A child node returns to its parent a **cited summary**, not the raw tree. The
parent's `known` context stays small, which limits context pollution and token
use on Gemma.

---

## 6. Why this is better than today

| Today | After |
|---|---|
| Answer from memory, evidence attached afterwards | Answer re-written from evidence; unsupported parts flagged |
| Same raw question to 8 sources | Need-typed queries routed to sources that fit |
| Snippets only | Full pages fetched, extracted, ranked into passages |
| Up to 16 LLM calls per node | ~4 synthesis calls plus 1 grade per round, with cache reuse |
| "No claims" means unclear whether nothing exists or search failed | `RetrievalReport` tells them apart |
| Outer loop by missing field only | Plus contradictions, unsupported answers and novelty-based stopping |

## 7. Risks / honest unknowns
- Gemma's real rate limits are unverified. The design must stay correct when
  quota is exhausted (fail to "not verified", never fabricate).
- DuckDuckGo search through `duckduckgo_search` is unofficial and may break, so
  it must not be the only web provider. SearXNG later needs Docker or a host.
- The sufficiency grade is an LLM judgment and is fallible. CRAG's weakness is
  the quality of its evaluator, so measure it against a small labelled set (as
  was done for the coverage checker).
- Re-answering from evidence adds 1 LLM call per answered node. Passage ranking
  should still lower total calls, but measure it.

## 8. Build order (each step independently verifiable)
1. **Dewey Archive**: `ArchiveStore` (SQLite + FTS5): Document/Passage/ResearchLedger,
   ingest with dedupe by content hash, `query(need) → ranked passages`. Pure local,
   fully unit-testable, no network.
2. **Dewey Research Engine core**: provider registry + `InformationNeed` /
   `EvidenceBatch` / `RetrievalReport`, the existing 8 retrievers moved behind it
   (out of Discovery.AI), plus DDG + Crossref; results ingested into the Archive.
3. **Safe fetch + extract**: robots/SSRF/size caps, trafilatura, passages.
   Tests: SSRF refusals, robots denial, extraction on saved fixtures.
4. **Read-through + split**: Discovery.AI's `gather_evidence` reads the Archive
   first and calls Dewey only on a miss (same return shape → existing scripts
   stay green). Discovery.AI no longer imports any retriever. Live comparison
   of first run vs repeat run on the same topic (web calls, LLM calls, time).
5. **Inner loop**: draft → retrieve → grounded re-answer → sufficiency grade →
   re-query. Budgets in `ResearchPolicy`. Live comparison against step 3.
6. **Outer loop upgrade**: contradictions + unsupported answers as gaps,
   perspective-guided gap questions, novelty stop, compressed child summaries.

## Sources
- RAG-reasoning surveys: https://arxiv.org/pdf/2507.09477 , https://arxiv.org/html/2506.10408v1
- IRCoT/Self-Ask/FLARE multi-hop comparison: https://aclanthology.org/2025.findings-emnlp.554.pdf ; counter-result: https://arxiv.org/pdf/2603.27253
- Agentic RAG paradigms comparison repo: https://github.com/linchengran/agentic-rag-research
- Over-search (SAAS): https://arxiv.org/pdf/2605.29796
- Self-RAG / CRAG (secondary): https://blog.langchain.com/agentic-rag-with-langgraph , https://www.analyticsvidhya.com/blog/2024/12/corrective-rag/
- Open Deep Research: https://www.langchain.com/blog/open-deep-research
- GPT-Researcher: https://github.com/assafelovic/gpt-researcher
- STORM: https://arxiv.org/pdf/2402.14207v2
- Deep research resource list: https://github.com/DavidZWZ/Awesome-Deep-Research
