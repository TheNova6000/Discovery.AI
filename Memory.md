# Tuni'n — Engineering Memory

## 2026-10-28 — Main-block restructure + loop 5d/5e

- **New layout** (docs/Architecture.md → "Current code layout", with old→new path map):
  `backend/main_block/` = `interface.py` (only public entry) + door (service/api/models/store) +
  `reasoning_engine/` (Discovery.AI, own `interface.py`, `model_chains.py`) + `research_engine/`
  (Dewey, own `interface.py`, `resource.py`, `sources/`). Outside: `backend/llm` (keys/transport),
  `backend/chat`, `backend/tunin`, `backend/api` (composition root), `backend/paths.py` (REPO_ROOT).
- Done by `scripts/restructure_main_block.py`; boundary checker enforces 4 rules (docs/Rules.md B1-B6).
  Verified: 0 failing modules, 0 old paths, 0 missing names, 30/30 suites, live ask from the existing Archive.
- Loop 5d/5e: discovery slot fix (E21), partial-evidence synthesis (E23), learner-only research focus
  (E24). Mitosis 4/4 grounded; chat mid-question grounded. Open: metaphase/anaphase wording to check;
  2/3 chat sub-findings ungrounded; faithfulness-judge variance (E22).

---

## 2026-10-28 — Iteration 05 + Main Block door (option B) + chat model

- Loop 05 (docs/research/loop/iteration-05.md): one grounding path for all
  answers (E14); fetch gate + stemming (E15/E16); Groq server-side schema
  rejections fixed via tolerant schemas — instructor maps every Groq mode to
  TOOLS (E17); section-aware chunking v2 + per-term pool + IDF rerank, chosen
  on a new retrieval benchmark: hit@4 0.69→1.00, MRR 0.62→0.85 (E19); clean
  outgoing search queries (E20). Live: Photosynthesis 3/3, TCP 4/4 grounded;
  ask(BST insertion) and ask(Calvin cycle) grounded 1.0.
- **Option B built** (docs/research/MainBlock-and-Chat.md): `backend/mainblock`
  (start_research / get_job / ask + HTTP routes, persisted idempotent jobs,
  ownership, restart→INTERRUPTED), boundary check script, ResearchGateway
  rewritten as a door client (direct retrieval deleted).
- **Chat model built**: `backend/chat` (own model chain, phases discovery →
  confirming → researching → ready, questions answered via the door, routes
  /tunin/chat/...). tunin/llm.py now uses the chat chain. Discovery topic
  extraction fixed (purpose clauses no longer part of the topic).
- 30 offline suites green. Pending: Mitosis re-run, live end-to-end chat
  (scripts/evaluate_chat_live.py), then the final Dewey database evaluation.

---

## 2026-10-28 — Loop iteration 03 done (docs/research/loop/iteration-03.md)

Gap-driven re-query: `grounding._fill_gaps` (≤2 gaps → targeted evidence →
recompose; gap claims persisted). Coverage message fixed (E9). Run 10: 3/3
answers grounded with verified citations, root covers definition + mechanism
+ ops + costs; one wrong statement traced to claim↔source distortion (E13,
new) → iteration 04. verify_grounding 20/20; 22 suites green.

---

## 2026-10-28 — Loop iteration 02 done (docs/research/loop/iteration-02.md)

Dewey step 3 built: `backend/dewey/fetch.py` (SSRF incl. redirects, RFC 9309
robots, caps, per-host spacing, trafilatura→bs4, Wikipedia extracts API with
sections + inline LaTeX); engine reads best 2 results in full; coverage needs
a full/excerpt passage; richer version never superseded; `DEWEY_FETCH=off`.
Grounding: only claims ≥0.5 ground; master grounds on descendants' claims.
Dewey archive query pool 4× + gate. Entity canonicalisation stage 1
(`backend/graph/canonical.py`, acronyms + keys, lazy backfill on Neo4j).
trafilatura 2.3.1 installed + pinned. Suites: 18 green (new fetch 10/10,
canonical 8/8 live). Run 9: 2/2 grounded, 0 new duplicate nodes, 167 s.
Next (iteration 03): gap-driven re-query (E12), relation schema (E5),
response scope (E6), coverage message (E9). Old graph duplicates NOT merged
— needs owner OK.

---

## 2026-10-28 — Improvement loop started (method saved: docs/research/loop/README.md)

Iteration 01 done (docs/research/loop/iteration-01.md): VeriCite-style
audit-verified citations, content_kind + metadata cap (0.35) + metadata never
counts as coverage, claim dedupe, Dewey relevance gate, archive content_kind
migration/backfill. Run 6: 0 citations on unsupported sentences, 0 metadata
over-trust, 0 duplicate claims, archive served all evidence with 0 new fetches.
Dominant remaining failure: thin evidence (summaries only) → iteration 02 =
Dewey full-page fetch/extract.

---

## 2026-10-28 (late night) — Live runs 4-5: first grounded answers

**Run 4** (`.scuba/logs/discovery_live_bst_run4_grounded.log`, 160s, Groq first):
grounding worked (both answers honestly NOT GROUNDED) but 0 claims. Dewey
ingested 9 docs/25 passages — all junk (arXiv physics papers, Open Library
titles, GitHub project lists); Wikipedia 429. **Bug fixed:** ledger recorded
"found" for irrelevant results (7-day skip) → new outcome `weak_results`
(6h), nothing_found 6h; verify_dewey_engine 9/9. Bad ledger rows reset.
**Root cause of Wikipedia 429 found:** contact-less UA + curl_cffi
`impersonate="chrome"` → 429; compliant UA or no impersonation → 200.
Fix: `CONTACT_USER_AGENT` in retrievers/base.py (Wikipedia, GitHub);
Wikipedia no longer impersonates Chrome. CppReference unchanged (untested).

**Run 5** (`.scuba/logs/discovery_live_bst_run5_wikifix.log`, 325s):
- **4 claims** (was 0); Wikipedia claim conf 0.90 real definition + O(h).
- **2 of 4 nodes GROUNDED**: root support 0.833, child support 1.0. The audit
  correctly flagged "O(n) worst case" / "O(log n) balanced" as unsupported
  (Wikipedia snippet only says "linear in height").
- Problems seen: (a) GitHub README-description claims rated 0.70/0.60 — too
  much trust in repo metadata; (b) root answer cites [1,2] on the very
  sentence the audit marked unsupported (citation precision gap); (c) same
  source claimed twice; (d) graph duplicates grew (Operations /
  BinarySearchTreeOperations / Insertion added); (e) ResearchResponse shows
  claims=1 vs 4 in memory; (f) Semantic Scholar 1×429.

---

## 2026-10-28 (late night) — P1a implemented: retrieve-then-write + Dewey evidence path

- `backend/questions/grounded_answer.py` — `compose_grounded_answer`: writes
  only from numbered evidence, cites [n], lists gaps; out-of-range citations
  dropped; retrieved text treated as data, not instructions.
- `backend/agents/grounding.py` — `ground_answer`: memory answer kept as a
  draft; final answer = composed from claims + `audit_synthesis` atomic-claim
  support ratio, recorded with `reasoning.domain.Answer` (first real use).
  No claims / irrelevant evidence / composer failure → grounded=False with a
  note; audit failure → support unknown (None), never 0.
- `GroundResult.grounding` (optional field); wired in `ground_agent.py` answer
  branch only when gather_evidence is on (evidence-off runs unchanged).
- `backend/evidence/engine.py` — default evidence path now asks Dewey
  (archive first, ≤2×per-retriever passages to the LLM, provider reports and
  evidence_source surfaced); `EVIDENCE_SOURCE=retrievers` restores old path.
- Dewey: "general" need kind routes to all providers; providers get keyword
  queries (`keyword_query`), Tavily keeps natural language.
- `scripts/verify_grounding.py` **9/9**; all 15 offline suites green
  (r1_5…r5_2, phase9_1, coverage, preflight, dewey archive/engine, key pool,
  grounding). `evaluate_discovery_live.py` now prints grounding per node.
- **Not yet verified live.** Next: one live BST run (asks user first — uses quota).

---

## 2026-10-28 (late night) — Groq first; merge kept; related-work + novelty research

- User decisions: **Groq first** in both chains (Gemma 4 fallback) — done,
  `verify_key_pool.py` 6/6; **keep** the earlier origin/main merge.
- `docs/research/Related-Work-and-Novelty.md`: related work per component
  (Open Deep Research, STORM, DualGraph, CRAG/Self-RAG, SAAS, HippoRAG 2/
  GraphRAG/LightRAG, Mem0/A-MEM, FActScore/ALCE, TutorLLM/LOOM/forgetting-aware
  tutoring), honest novelty assessment (combination is distinctive: lifecycle
  claims → curriculum; shared archive + failed-search ledger; pedagogy as data;
  behind SOTA on grounding, metrics, coverage, stopping, KT), and a P1–P4
  borrow plan. P1 = retrieve-then-write + atomic-claim audit using GitHub's
  unused `Answer` model; CRAG grade + stop rules; Dewey fetch/extract.

---

## 2026-10-28 (night) — GitHub / Aug-30 audit (read-only, nothing merged)

- `origin/main` = `b23ed0f`; already merged into `tunin` by an EARLIER session
  (reflog: `b014359` at 13:07 today). User did not want merges; this session
  only ran `git fetch`. User may want that merge undone — pending decision.
- GitHub's offline checks: 11 scripts / 83 checks all PASS (r1_5, r2_1, r3_1,
  r4_1-3, r5_1-2, phase9_1, coverage, preflight).
- Useful GitHub parts for the main issue: `reasoning.domain.Answer`
  (grounded ↔ claim_ids; designed but NEVER instantiated anywhere),
  RetrievalOutcome→Evidence→Claim gate, compose-only-from-claims + audit
  pattern (lesson_authoring + audit_synthesis), claim lifecycle, ResearchTask
  graph, ResearchResponse (relationships bug: subgraph is abstraction-scoped).
- **Aug 30 demo version (`a200b21`, last of 24 commits that day):** the
  reasoning path is the SAME — answer from LLM memory first, evidence after
  (`ground_agent.py:259-260` then). It looked better because (1) every retrieved
  resource became a Claim with no relevance filter — the filter added Sept 16
  (R1.2, `28cb75c`) exists because 3 of 4 such "claims" said "the resource does
  not answer the question"; (2) Groq was first in the chain and reliable;
  (3) sources weren't rate-limiting. Same depth/step limits as today (2/3).
  Nothing in its evidence path should be borrowed; Groq-first ordering is the
  only practical carry-over.

---

## 2026-10-28 (evening) — Live Discovery.AI run, key-pool fix, main-block design

**Live run (`scripts/evaluate_discovery_live.py "Binary search tree"`, new script
for human review — prints decision trace, result tree, claims+sources, graph
read-back, ResearchResponse).** Stopped by user before finishing. Observed:
- Master-level (31B) decomposition was sensible: structure / operations
  (insert, delete, search) / cost.
- Ground-level (26B) reasoning text was garbled: "trovare/found via standard
  computer science thanks", "beinanswerableable with a truths-based truth",
  "inlet-rules-that-invariantly-hold-true".
- 25 Gemma-26B timeouts (30s each, walking keys 1→5); Semantic Scholar 429 on
  raw sub-question queries.
- Code finding: `ground_agent.py:276` — the agent answers from LLM memory FIRST,
  evidence is gathered AFTER and never changes the answer; the raw question goes
  to all 8 retrievers; snippets only; up to 16 synthesis calls per answer.

**Key pool fix (`backend/questions/llm_client.py`).** 9 Gemini + 9 Groq keys
were already pooled from comma-separated `GEMINI_API_KEYS` / `GROQ_API_KEYS`,
but every call started at key 1 and walked all 9 keys (30s timeout each, up to
~4.5 min) before reaching Groq. Now: round-robin start key, per-key cooldown
after timeout/429 (retry window or 60s), max 3 keys per provider per pass then
fall through, max 4 concurrent calls per provider, 75s timeout for
gemma-4-31b-it. `scripts/verify_key_pool.py` (fake client, no network):
**5/5 PASS**.

**Chain order (`llm_config.py`):** ground = gemma-4-31b → groq gpt-oss-20b →
gemma-4-26b → gemini-flash-lite → cerebras(no keys); master = gemma-4-31b →
groq gpt-oss-120b → gemma-4-26b → gemini-2.5-flash → cerebras.

**Neo4j:** user-provided Aura works; username must be the instance id.
`verify_phase1.py` PASSED.

**Architecture agreed with user (docs/research/Reasoning-Research-Orchestration.md §2b):**
Discovery.AI = reasoning only (no web calls). Dewey Archive = our own growing
passage database (SQLite+FTS5 default) read FIRST, like RAG; Dewey research
engine fills it only on a miss, with a research ledger to avoid re-searching
known gaps. Graph keeps claims; claims point to Archive passage ids.
Build order §8: Archive → research engine core → safe fetch/extract →
read-through split → inner loop → outer loop.

**503 handling:** a 503 "model is currently experiencing high demand" (seen
live from gemma-4-31b-it) is model-wide, so `structured_call` now skips that
model's remaining keys and moves to the next model. `verify_key_pool.py` 6/6.

**Dewey research engine — build steps 1-2 DONE (offline-verified):**
- `backend/dewey/archive.py` — Dewey Archive: SQLite+FTS5 (porter, BM25),
  documents (canonical URL, versioned, content hash, provenance) → passages
  (≤1500 chars, entity-tagged) + research ledger (need fingerprint, outcome,
  next retry). DB: `DEWEY_ARCHIVE_PATH` or `<repo>/dewey_archive.sqlite3`
  (gitignored by `*.sqlite3`). `scripts/verify_dewey_archive.py` **10/10**.
- `backend/dewey/contracts.py` — `InformationNeed` → `EvidenceBatch`
  (source = archive | research | known_gap | unavailable) + `ProviderReport`.
- `backend/dewey/providers.py` — `ProviderRegistry`: the 8 existing retrievers
  wrapped with need-kind routing + key requirements + `status()` for a key page.
- `backend/dewey/engine.py` — `DeweyEngine.find(need)`: archive first → ledger
  → research → ingest → re-query. Retry windows: found 7d, nothing 24h,
  providers failed 1h. `scripts/verify_dewey_engine.py` **8/8** — one real bug
  found and fixed (an all-providers-down result was labelled "research").
- Limitation: wrapped retrievers swallow their errors and return [], so a 429
  shows as `no_results`, not `rate_limited`, until native providers (step 3).
- Not yet wired into Discovery.AI (step 4); retrievers not yet moved.

**Live run 3 (in progress, `.scuba/logs/discovery_live_bst_run3.log`):** ground-
level reasoning now clean English with 31B ("The question asks for the
structural properties and invariants of a BST…"). Gemma 31B returns frequent
500 INTERNAL (absorbed by key rotation); Wikipedia and Semantic Scholar both
returned 429 on raw sub-question queries — the archive/ledger is the fix.

**Live run 3 RESULT (1253s, 3 agent nodes, log `.scuba/logs/discovery_live_bst_run3.log`):**
- Answers: content correct (BST invariant, O(h)/O(log n)/O(n), traversals) but
  produced entirely from LLM memory — **0 evidence claims**. Wikipedia 429 ×3,
  Semantic Scholar 429 ×3, arXiv timeout, Tavily/YouTube no key, the other three
  silent (can't tell failure from empty).
- Graph: same concept stored 4× (BST Property / the BST property / BST Invariant /
  BST structural properties), root vs root node, 3 redundant BST→Search edges,
  mixed-case free-form relationship types; insert/delete never investigated.
- ResearchResponse: relationships=1 vs 14 edges in graph (projection mismatch);
  coverage reason "max confidence 0.00 does not meet policy threshold 0.00"
  (nonsense message); 21× Neo4j ANSWERED_BY unknown-relationship warnings.
- Gemma 31B: 60× 500, 36× 503 → very slow.
- **Main issue:** reasoning is not grounded — answer first, evidence after, and
  evidence acquisition fails silently. Fix = Dewey wired in (step 4) +
  evidence-first answering. Secondary: graph entity/relationship dedupe.

Nothing committed.

---

## 2026-10-28 (later) — Gemma 4 wired in, Dewey→Tuni'n rename, component research

- **Gemma 4 is now first in both LLM chains** (`backend/questions/llm_config.py`):
  ground `google/gemma-4-26b-a4b-it`, master `google/gemma-4-31b-it` then 26b.
  Verified live through `structured_call`: 26b 7.4 s clean; 31b 32 s after one
  absorbed 500. Gemma forced to `Mode.GENAI_STRUCTURED_OUTPUTS` (tool mode
  degenerated). `aiohttp` upgraded 3.9.5→3.14.5 and pinned `>=3.10,<4`.
- **Rename:** `backend/dewey/{coverage,lessons,curriculum}` → `backend/tunin/
  {coverage,lessons,course}`; `backend/tunin/__init__.py` added; frontend
  `assets/dewey` → `assets/tunin`; course.html + lesson voice say Tuni'n.
  "Dewey" now names the research engine.
- **Verified after rename:** `import backend.api.app` OK; `verify_coverage` 2/2;
  `verify_phase9_1` 5/5. `verify_phase9_2`/`verify_phase10` real-data parts
  SKIP/fail on the known Neo4j DNS blocker only.
- **Research:** `docs/research/Tunin-Component-Research.md` (research-engine gaps,
  free providers, learning-framework PDFs mapped to Bloom L1–L6 / depth D1–D4).
- **Neo4j restored (user-provided Aura, 5.27 Enterprise, empty):** old Aura host
  was deleted (NXDOMAIN). New instance rejected user `neo4j`; Aura's username is
  the instance id -- `.env` NEO4J_USER fixed. `verify_phase1.py` PASSED live.
- **User priorities:** fix Discovery.AI first, then Dewey research engine, then
  the rest; chat model stays separate from the reasoning agent; user supplies
  the frontend (`frontend template/` currently only a Lovable index.html shell).
- **Next:** build the Dewey research engine slice 1 (provider registry +
  keyless web search + safe fetch/extract + cache), per that doc §2.

---


**Status: implementation PAUSED mid-Phase 4 (artifact generation). Logged 2026-10-28.**
This file is the resume anchor. It records what was audited, what exists, what was
actually run, what is unfinished, and the exact next steps. It deliberately does
not describe unfinished work as complete.

---

## 1. Session identity

| Item | Value |
|---|---|
| Repository | `D:\Road to Practice` |
| Branch | `tunin` |
| HEAD | `b014359` — merge of `origin/main` into `tunin` |
| Parent of branch | `51f9b7b` (`test-sept16-afternoon`, preserved) |
| `origin/main` merged | `b23ed0f` (Dewey / Research API foundation) |
| Work committed this session | **None.** All Tuni'n code is untracked. |
| User changes preserved | `frontend/chat.html` (3-line modification, untouched), `backend/questions/llm_client.py.before-gemini-mode-fix` (untracked, untouched) |

No tracked file was modified by the Tuni'n work so far. `git status` at pause:

```
 M frontend/chat.html
?? backend/questions/llm_client.py.before-gemini-mode-fix
?? backend/tunin/
```

---

## 2. Objective (condensed from the user's brief)

Build **Tuni'n**, a research-driven adaptive learning portal on top of the
existing Discovery.AI repository:

DISCOVER → RESEARCH → REASON → DESIGN CURRICULUM → PROPOSE → **HARD APPROVAL** →
GENERATE COURSE → TEACH → ASSESS → ADAPT → REPLAN.

Non-negotiables recorded in the brief:

- Discovery chat extracts a structured course-design brief incrementally, not one
  giant form; conversation must survive restart.
- Discovery.AI is the reasoning/research engine; Tuni'n is a client. Open/free
  retrieval adapters may supplement evidence but must not become a second engine.
- The approval gate is hard: no module generation before the learner approves the
  exact proposal version.
- Generate real `.md` lessons, exercises, READMEs, rubrics, answer keys.
- Publish a maximum of **two active modules** at a time.
- Collect assessment attempts and module feedback, update a learner model, replan
  upcoming modules, generate remedial/extension modules.
- Use configurable learning methods including Feynman teach-back.
- Do not fabricate sources, claims, confidence, mastery, or verification.
- Never execute arbitrary generated code on the host.
- Separate adaptive learner state from model fine-tuning; never claim a model was
  fine-tuned when only records changed.
- Keep the existing vanilla HTML/CSS/JS + FastAPI static-mount frontend; no React
  or build step.
- Maintain six engineering-contract documents: `PRD.md`, `Architecture.md`,
  `Rules.md`, `Phases.md`, `Design.md`, `Memory.md`.

---

## 3. Audit findings

### 3.1 Repository foundation that already works

The checked-out branch (`test-sept16-afternoon`) was **behind** `origin/main`.
`origin/main` already contains the verified Dewey foundation, so a new branch was
created and `origin/main` merged in rather than reimplementing it.

Reusable, verified or built foundation:

- `backend/research_api` — stable `ResearchRequest` / `ResearchResponse` contract.
- `backend/research` — plan, coverage/completeness, claim validation, research
  artifact, contradiction detection.
- `backend/reasoning` — `RetrievalOutcome` → `Evidence` → `Claim` → `Answer`,
  claim lifecycle, subclaim DAG.
- `backend/agents` — `GroundAgent`, `MasterAgent`, research policy.
- `backend/graph` — Neo4j graph interface, canonical entities, abstractions.
- `backend/evidence/retrievers` — `WikipediaRetriever`, `ArxivRetriever`,
  `SemanticScholarRetriever`, `OpenLibraryRetriever`, `CppReferenceRetriever`,
  `GitHubRetriever`, `TavilyRetriever`, `YouTubeRetriever`.
- `backend/dewey/curriculum` — `compile_course(response)` and Course/Module models.
- `backend/dewey/lessons` — lesson compiler.
- `backend/dewey/coverage` — coverage ontology and lexical benchmark.
- Routes `/research`, `/course`, `/lesson`, `/roadmap`, `/roadmap/build` in
  `backend/api/app.py`.
- `frontend/course.html`, `frontend/roadmap.html` — existing vanilla UI patterns.
- `scripts/verify_phase8_1.py` … `verify_phase8_6.py` — baseline checks.

### 3.2 Baseline verification actually run

| Check | Result |
|---|---|
| `import backend.api.app` | **OK** |
| `scripts/verify_phase8_1.py` | **PASS** — 5/5 checks |
| `scripts/verify_phase8_2.py` | **PASS** — 5/5 checks |
| `scripts/verify_phase8_3.py` | **PASS** — 6/6 checks |
| `scripts/verify_phase8_4.py` | **PASS** — 6/6 checks |
| `scripts/verify_phase8_5.py` | **PASS** — 6/6 checks |
| `scripts/verify_phase8_6.py` | **PASS** — 6/6 checks |
| `scripts/run_all_verifications.py` | **NOT COMPLETED** — killed at 300 s timeout; no pass/fail summary was produced |
| `py_compile` on the 8 new Tuni'n files | **OK** |
| Runtime import of `backend.tunin.*` | **NOT RUN** (no `__init__.py`, no orchestrator/API yet) |
| Tuni'n unit/integration/E2E tests | **NONE WRITTEN** |
| Tuni'n browser verification | **NOT POSSIBLE YET** (no page or API) |

### 3.3 Environment and genuine blockers

| Blocker | Evidence | Consequence |
|---|---|---|
| Neo4j unreachable | `ValueError: Cannot resolve address 0d1f3514.databases.neo4j.io:7687` | Discovery.AI graph investigation cannot run locally |
| No Docker | `docker` not recognized | No local Neo4j, no code sandbox |
| No LLM provider key | `has_any_provider_key() == False`; pools = google, groq, cerebras | No live LLM discovery/feedback refinement; deterministic path required |
| Wikipedia API 403 | live probe returned 403 | One free retriever is effectively unavailable from this machine |
| arXiv API 200, OpenAlex 200 | live probe | arXiv works; OpenAlex has no retriever in the repo |
| `pytest_asyncio` absent | `ModuleNotFoundError` | Tests must use `asyncio.run()` inside sync pytest functions |
| `run_all_verifications.py` slow | 600 s per-script budget | Must be run in background with a long timeout |

Runtime: Windows, PowerShell (no `&&`), Python 3.11.9, pytest 8.4.2, httpx 0.28.1,
aiosqlite 0.21.0.

### 3.4 Design consequences

- The product must be fully usable **deterministically** (no LLM, no Neo4j).
- Research defaults to **direct retrieval** through the existing free retrievers,
  explicitly labelled `DIRECT_RETRIEVAL` with limitations.
- Lessons must not assert unverified subject facts. Deterministic lessons are
  structured study guides over **real retrieved sources** (title, URL, snippet,
  timestamp), plus exercises and teach-back prompts.
- Discovery.AI integration is implemented as an optional HTTP client
  (`POST {TUNIN_DISCOVERY_AI_URL}/research`), not as a replacement engine.
- Assessment of open-ended work is rubric/heuristic and **partial by design**;
  one MCQ can never imply mastery.

---

## 4. Architectural decisions

1. **New client package `backend/tunin`.** It consumes Discovery.AI contracts and
   retrievers. It does not modify `backend/dewey`, `backend/research_api`, or the
   graph.
2. **SQLite via `aiosqlite`** for learner-facing state. Neo4j remains the canonical
   research graph. Rationale: already a pinned dependency, transactional, small
   records, no new service.
3. **JSON payload columns + pydantic models.** Schema changes stay in `models.py`.
4. **Explicit lifecycle state machine.** Routes/orchestrator call `transition()`;
   invalid moves raise `InvalidTransition`.
5. **Hard approval gate encoded in the transition table.** `APPROVED` is reachable
   only from `AWAITING_APPROVAL`; `GENERATING_MODULES` only from `APPROVED`.
6. **Two-module buffer.** The approved plan holds all modules; only two are
   `published`/active at a time. Completed modules leave the buffer; adaptation
   publishes the next planned or generated module.
7. **Versioned artifacts.** New module version → new directory; previous versions
   and learner work are never overwritten.
8. **Mastery starts at 0.0 with zero evidence.** Transparent update rule with
   diminishing gains and small penalties; repeated, varied evidence is required
   before `ADVANCE`.
9. **No code execution.** Code exercises grade `UNSUPPORTED`/`manual_only`.
10. **Optional LLM only.** `backend/tunin/llm.py` checks `has_any_provider_key()`
    and falls back silently on any error.

---

## 5. Files created (untracked, `backend/tunin/`)

All eight files below `py_compile` cleanly. None has been runtime-tested.

### `models.py` (~21.8 KB)

Complete domain layer:

- Enums: `CourseState`, `ModuleStatus`, `ProposalStatus`, `ResearchMode`,
  `ResearchJobStatus`, `ExerciseKind`, `GradingOutcome`, `AdaptationAction`.
- Discovery: `SyllabusTopic`, `ProjectPreferences`, `CourseDesignBrief`
  (with `missing_required()`, `ready`, `merge_topics`, `asked`), `DiscoveryMessage`,
  `DiscoveryReply`.
- Research: `SourceReference`, `TopicResearch`, `ResearchBundle`, `ResearchJob`.
- Curriculum: `Lesson`, `ExerciseOption`, `Exercise` (MCQ validator enforces
  ≥2 options and an `answer_key` matching an option id), `MiniProject`,
  `CapstonePlan`, `ModulePlan` (validator requires objectives, lessons, exercises),
  `SyllabusMapping`, `CourseProposal` (+ `validate_plan`, `capstone_opted_out`).
- Assessment/learner: `GradingResult`, `Attempt`, `ModuleFeedback`,
  `FeedbackClassification`, `MasteryRecord`, `AdaptationDecision`, `CourseEvent`,
  `ArtifactRecord`.
- Aggregate: `Course`, `CourseSnapshot`.
- API request shapes: `CreateCourseRequest`, `DiscoveryMessageRequest`,
  `ProposalEditRequest`, `ApproveRequest`, `AttemptRequest`, `FeedbackRequest`.

### `state.py` (~5.3 KB)

Full transition table and `validate_transition()`. Notable edges:

- `DISCOVERY → BRIEF_READY`
- `BRIEF_READY → RESEARCH_PLANNING`
- `RESEARCH_RUNNING → RESEARCH_REVIEW`
- `RESEARCH_REVIEW → CURRICULUM_DRAFT`
- `CURRICULUM_DRAFT → AWAITING_APPROVAL`
- `AWAITING_APPROVAL → APPROVED` (hard gate)
- `APPROVED → GENERATING_MODULES → READY_TO_LEARN`
- `READY_TO_LEARN → MODULE_IN_PROGRESS → ASSESSMENT_PENDING →
  FEEDBACK_PENDING → ADAPTATION_PENDING → BUFFER_READY`
- `FAILED` is recoverable; `PAUSED` can resume to active states.

### `store.py` (~28 KB)

SQLite schema and CRUD:

`courses`, `messages`, `research_jobs`, `proposals`, `modules`, `attempts`,
`feedback`, `mastery`, `decisions`, `events`, `artifacts`, `idempotency`.

- DB path: `TUNIN_DB_PATH`, default `<repo>/tunin.sqlite3`.
- WAL, `busy_timeout=5000`, foreign keys.
- Course row stores brief/research/current proposal JSON; `proposals` table keeps
  version history.
- `list_modules()` de-duplicates by sequence, choosing the highest version.
- Idempotency helpers `get_idempotent` / `put_idempotent`.
- Ownership is **not** enforced here; it must be enforced in the orchestrator by
  filtering on `learner_id`.

### `llm.py` (~4.2 KB)

Optional structured calls:

- `LLMDiscoveryExtraction` and `LLMFeedbackReading` schemas.
- `available()` wraps `has_any_provider_key()`.
- `refine_discovery()` / `refine_feedback()` use `structured_call` with
  `GROUND_MODEL_CHAIN`, catch every exception and return `None`.
- Prompts explicitly treat learner text as untrusted data.

### `discovery.py` (~19.3 KB)

Staged deterministic extraction + optional LLM merge:

- Extracts topic, goal, depth, weekly hours, target weeks, prior knowledge, gaps,
  constraints, capstone idea, learning preferences.
- Handles “you decide” / “not sure” by inferring a **labelled provisional**
  syllabus (`source="inferred"`, confidence 0.35) and recording an assumption.
- Question order: topic → goal → syllabus → time → background → project → methods.
- Asks each question at most twice, then applies an explicit assumption.
- Final message summarises the brief and states that nothing is generated until
  approval.
- `greeting()` returns the first prompt.

### `research.py` (~13.1 KB)

`ResearchGateway`:

- `TUNIN_DISCOVERY_AI_URL` configured → `POST /research` with a real
  `ResearchRequest`-shaped body; converts `ResearchResponse.evidence`,
  `.claims`, `.coverage`, `.entities` into `SourceReference` / `TopicResearch`.
- Otherwise → direct retrieval:
  - 2 queries per topic, all `DEFAULT_RETRIEVERS`, semaphore-bounded,
    `asyncio.wait_for` per call.
  - Dedup by cleaned URL, relevance from token overlap, cap 6 sources/topic,
    cap 8 topics.
  - Status `complete` / `partial` / `failed`, with honest limitations.
- Progress callback `(stage, fraction, message)` for job polling.
- No retrieved snippet is converted into a supported claim.

### `curriculum.py` (~24.1 KB)

Deterministic proposal compiler:

- `LEARNING_METHODS` registry (feynman, retrieval-practice, spaced-repetition,
  interleaving, worked-examples, socratic, project-based,
  metacognitive-reflection, reading-sources).
- `select_methods()` maps learner preferences onto the registry and adds sensible
  defaults (Feynman always).
- One module per syllabus topic; structural split to ensure ≥2 modules.
- Each module: 2 lessons, MCQ + short answer + Feynman teach-back, optional
  mini-project, explicit objectives, completion criteria, evidence refs.
- Lesson bodies are structured study guides that quote **real** source
  title/URL/snippet, with an explicit “boundaries” statement.
- Capstone derived from the learner's idea/goal, or `capstone_opted_out=True`.
- Linear prerequisite order is **stated as a design decision**, not presented as a
  researched dependency graph.
- `apply_edits()` supports title/description/methods/module edits/removing an
  optional mini-project.
- `compile_proposal()` returns `status="awaiting_approval"`.

### `artifacts.py` (~11.6 KB)

Versioned Markdown generation:

- Root: `TUNIN_ARTIFACT_DIR`, default `<repo>/data/tunin_courses`.
- Directory: `<root>/<course_id>/mNN-<slug>-v<version>/`.
- Files: `README.md`, `lesson_XX.md`, `exercises.md`, `answer_key.md`,
  `rubric.md`, `sources.md`, `module.json`.
- `validate_module()` rejects thin lessons, unresolved placeholders, missing
  objectives/exercises/MCQ/completion criteria, and evidence refs not present in
  the proposal source manifest.
- `read_artifact()` is confined to the artifact root (path traversal guard).
- Every file gets a SHA-256 hash and an `ArtifactRecord`.

---

## 6. What is NOT done

### Backend

- `backend/tunin/__init__.py` — missing.
- `backend/tunin/orchestrator.py` — missing. This is the biggest gap.
- `backend/tunin/assessment.py` — missing (grading, mastery update, feedback
  classification, adaptation decision, remedial/extension module planning).
- `backend/tunin/api.py` — missing.
- `backend/tunin/curriculum.py` — remedial/extension module builders not written.
- `backend/api/app.py` — `/tunin` page route and router registration not added.
- No background research task wiring, no job resumability, no idempotent approval.

### Frontend

- `frontend/tunin.html` — missing.
- No dashboard, chat, research progress, proposal/approval, course map, module
  viewer, exercise UI, feedback form, mastery view, revision history.

### Tests

- No `tests/tunin/` unit tests.
- No `scripts/verify_tunin.py`.
- No integration test (brief → research → proposal → approval → artifacts →
  attempt → feedback → adaptation).
- No E2E browser test.
- No restart-recovery test.

### Documentation

Root-level six-document contract **not written**: `PRD.md`, `Architecture.md`,
`Rules.md`, `Phases.md`, `Design.md` (this `Memory.md` is the only one created).
`docs/Memory.md` has not been updated with Tuni'n work.

### Housekeeping

- `.gitignore` lacks `tunin.sqlite3`, `tunin.sqlite3-*`, and `data/`.
- No commit of any Tuni'n file.

---

## 7. Known issues / risks in the code written so far

These are honest defects or design weaknesses to fix before claiming the phase
works:

1. **Goal extraction can echo the topic.** For “I want to learn Rust”, the
   fallback in `discovery._extract` can set `goal` to the same sentence. It should
   require a purpose clause or ask the dedicated goal question. Currently the
   dedicated goal question exists, but the fallback can pre-empt it.
2. **Negative-phrase trigger is broad.** `_apply_defaults()` runs on any message
   containing “not sure”/“whatever”, even if the learner is only unsure about an
   optional question. It can infer a syllabus earlier than intended.
3. **MCQ answer position is fixed.** The correct option is always `a` and the
   correct objective is always `objectives[0]`. Deterministic, but gameable.
   Randomise option order deterministically from the exercise id.
4. **`store.list_modules()` hides earlier versions.** Correct for the live plan,
   but revision history needs an explicit all-versions query.
5. **`save_module()` upsert is keyed on `id`.** The table also has
   `unique(course_id, sequence, version)`. A new id with the same
   course/sequence/version would violate the constraint. Remedial modules use a
   new sequence, so this is currently safe but should be made explicit.
6. **No concurrency guard around research start.** `ResearchGateway` is safe, but
   two simultaneous `POST /research` calls could create two jobs until the
   orchestrator adds an idempotency key/lock.
7. **No ownership checks yet.** `store.py` intentionally does not filter by
   `learner_id`; every orchestrator read/write must do so.
8. **`Course.validate_plan` requires a capstone unless opted out**, but the UI must
   surface `capstone_opted_out` clearly so a learner does not accidentally approve
   a plan with no capstone.
9. **Artifact links in `README.md` are relative filenames.** The API must serve
   those files or the frontend must render lesson content from the module JSON;
   otherwise the links 404.
10. **`research._try_discovery_ai` assumes `/research` is reachable unauthenticated.**
    If the deployment enables Supabase auth, the client must send a token.
11. **No rate limiting / upload handling.** The brief allows PDF/Markdown uploads;
    not implemented.
12. **No sanitization layer yet for rendered Markdown.** The frontend must escape
    HTML and disallow raw HTML from retrieved snippets.

---

## 8. Exact next steps (resume order)

1. **Create `backend/tunin/__init__.py`** exporting the public service surface.
2. **Write `assessment.py`**:
   - `grade(exercise, answer, confidence)`:
     - MCQ deterministic; expose key only after attempt.
     - short answer / Feynman: rubric keyword coverage + word count → `PARTIAL`
       or `NEEDS_REVIEW`, never “correct” from heuristics.
     - numeric: tolerance comparison if a key exists.
     - code/project: `UNSUPPORTED` / `NEEDS_REVIEW`, `manual_only`.
   - `update_mastery(record, exercise, result, confidence)`:
     - start 0.0; diminishing gain `gain * (1 - estimate)`;
     - penalty clamped at 0; confidence calibration counters;
     - track attempts, evidence, correct, repeated errors, last success/review.
   - `classify_feedback(feedback, mastery)` with deterministic rules +
     optional `llm.refine_feedback`.
   - `decide(module, mastery, classification, attempts)` → `ADVANCE` / `PRACTICE`
     / `REMEDIATE` / `REVISIT_PREREQUISITE` / `EXTEND` /
     `REQUEST_CLARIFICATION` / `RESEARCH_GAP`, with evidence list.
3. **Add remedial/extension builders to `curriculum.py`**:
   - `build_remedial_module(...)` — different method (worked example + teach-back),
     same concepts, no fabricated facts, explicit adaptation note.
   - `build_extension_module(...)` — harder application/project task.
4. **Write `orchestrator.py`**:
   - `create_course`, `list_courses`, `get_snapshot` (ownership-filtered).
   - `post_message` → save user message, call `discovery.respond`, save assistant
     message, set `BRIEF_READY`, emit event.
   - `start_research` (idempotent; returns existing queued/running job) and
     `run_research_job` (persists stage/progress; recover `queued` jobs on startup).
   - `build_proposal` (requires research; versioned; sets `AWAITING_APPROVAL`).
   - `edit_proposal` (creates a new draft version; invalidates old approval).
   - `approve_proposal(version)` — exact-version hard gate; then
     `APPROVED → GENERATING_MODULES`, generate first two modules, publish them,
     `READY_TO_LEARN`.
   - `start_module`, `submit_attempt`, `submit_feedback`, `complete_module`.
   - `_publish_buffer` — at most 2 published/in-progress modules; generate
     artifacts before publishing; never unpublish completed work.
   - `_adapt` — classify feedback + mastery → decision; create remedial/extension
     module when required; append to plan; publish next buffer.
   - `events` audit trail for every state change and adaptation.
5. **Write `api.py`** and register it in `backend/api/app.py` **before** the
   final static mount:
   - `POST/GET /tunin/api/courses`
   - `GET /tunin/api/courses/{id}`
   - `POST /tunin/api/courses/{id}/messages`
   - `POST/GET /tunin/api/courses/{id}/research`
   - `GET /tunin/api/jobs/{job_id}`
   - `POST/PATCH /tunin/api/courses/{id}/proposal`
   - `POST /tunin/api/courses/{id}/approve`
   - `GET /tunin/api/courses/{id}/modules`
   - `GET /tunin/api/courses/{id}/modules/{module_id}`
   - `GET /tunin/api/courses/{id}/modules/{module_id}/artifacts/{artifact_id}`
   - `POST /tunin/api/courses/{id}/modules/{module_id}/start`
   - `POST /tunin/api/courses/{id}/modules/{module_id}/attempts`
   - `POST /tunin/api/courses/{id}/modules/{module_id}/feedback`
   - `GET /tunin/api/courses/{id}/mastery`
   - `GET /tunin/api/courses/{id}/events`
   - `GET /tunin` → `FileResponse(frontend/tunin.html)`
   - All routes depend on `get_current_user_id`; all course lookups compare
     `course.learner_id` and return 404 (not 403) on mismatch.
6. **Build `frontend/tunin.html`** using the existing vanilla stack and tokens from
   `frontend/course.html`:
   - course list + “new course”;
   - discovery chat (message history, brief summary, “start research”);
   - research progress (poll job; show honest stage text, not fake percentages);
   - proposal review (syllabus mapping, modules, mini-projects, capstone, methods,
     limitations, edit + approve);
   - course map with the two active modules clearly separated from the planned plan;
   - module/lesson viewer (safe Markdown rendering, no raw HTML);
   - exercise forms (MCQ, short answer, Feynman, manual-only code);
   - feedback form with the five 1–5 ratings + free text;
   - mastery panel with evidence counts and “not enough evidence yet”;
   - adaptation/revision history;
   - empty/loading/error/recovery states.
7. **Tests** (`tests/tunin/`, `scripts/verify_tunin.py`):
   - state transitions (legal + illegal);
   - brief validation + resumability (store round-trip);
   - discovery staged extraction and “you decide” inference;
   - research fallback with fake retrievers (no network);
   - curriculum coverage and mandatory-topic mapping;
   - proposal validation, edit versioning, approval gate;
   - artifact validation + version directories + path traversal guard;
   - MCQ grading, heuristic partial grading, no-code-execution;
   - mastery monotonicity, one-MCQ-not-mastery, one-wrong-not-failure;
   - adaptation decisions for weak/strong/ambiguous histories;
   - idempotent approval/research;
   - two-module buffer invariant;
   - full deterministic E2E with fake research;
   - restart recovery for a queued/running research job.
8. **Run**:
   - `python -m compileall backend/tunin`
   - targeted pytest
   - `python scripts/verify_tunin.py`
   - `scripts/run_all_verifications.py` in the background with a long timeout
   - app launch + browser walkthrough of the complete journey.
9. **Docs**: write root `PRD.md`, `Architecture.md`, `Rules.md`, `Phases.md`,
   `Design.md`; append a Tuni'n section to `docs/Memory.md`.
10. **Housekeeping**: add `tunin.sqlite3*` and `data/` to `.gitignore`; commit only
    after tests pass and after confirming the user's `chat.html` change is not
    included.

---

## 9. Resume commands

```powershell
git switch tunin
git status --porcelain=v1
python -m py_compile backend\tunin\*.py
python -c "import backend.tunin.models, backend.tunin.state, backend.tunin.store, backend.tunin.discovery, backend.tunin.research, backend.tunin.curriculum, backend.tunin.artifacts; print('ok')"
```

Neo4j / LLM checks (expected to fail locally):

```powershell
$env:PYTHONPATH='.'
python -c "from backend.questions.llm_config import has_any_provider_key; print(has_any_provider_key())"
```

Run the existing baseline (long; background it):

```powershell
$env:PYTHONPATH='.'
python scripts\run_all_verifications.py
```

---

## 10. Preservation and rollback

- Do **not** reset/delete `test-sept16-afternoon`; it holds the original checkout.
- Do **not** overwrite `frontend/chat.html`; its 3-line modification is the user's.
- `backend/questions/llm_client.py.before-gemini-mode-fix` is the user's untracked
  backup; leave it.
- All Tuni'n code is untracked. To discard it (only with explicit approval):
  `git clean -fd backend/tunin`. To keep it, commit it on `tunin`.
- Generated runtime data (once the orchestrator runs) will live at
  `tunin.sqlite3` and `data/tunin_courses/`; neither is currently gitignored.

---

## 11. Honest status summary

| Area | Status |
|---|---|
| Audit | **Complete** |
| Baseline verification | **Complete for Phase 8.1–8.6; full suite not completed** |
| Domain models | **Built, compiles, untested at runtime** |
| Lifecycle state machine | **Built, compiles, untested** |
| Persistence | **Built, compiles, untested** |
| Discovery chat | **Built (deterministic + optional LLM), untested** |
| Research gateway | **Built (Discovery.AI client + retrieval fallback), untested** |
| Curriculum compiler | **Built (deterministic), untested** |
| Artifact generator | **Built, untested** |
| Assessment / learner model | **Not started** |
| Orchestrator | **Not started** |
| API | **Not started** |
| Frontend | **Not started** |
| Tests | **Not started** |
| Six-document contract | **Only this Memory.md** |
| Browser verification | **Not possible yet** |

No phase of Tuni'n is claimed as complete or verified. The next session should
resume at step 1 of §8.
