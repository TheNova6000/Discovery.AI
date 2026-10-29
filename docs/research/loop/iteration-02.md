# Iteration 02: thin evidence, weak-evidence answers, synthesis grounding, entity duplicates

Runs analysed: 6 (start), 7, 8, 9 (re-runs inside the iteration). Logs in `.scuba/logs/`.

## 1. Scorecard across the iteration

| Metric | Run 6 (start) | Run 7 | Run 8 | Run 9 (end) |
|---|---|---|---|---|
| Claims from full page text | 0 | 1 | 2 | 1 (+ children's reused) |
| Answers GROUNDED / nodes | 1/2 | 2/2 (one wrongly, on metadata) | 2/3 (root ungrounded) | **2/2** |
| Answers grounded on metadata only | 0 | **1 (E10)** | 0 | 0 |
| Root grounded on children's evidence | n/a | n/a | no (E11) | **yes** (own 0, cited child's 1, support 1.0) |
| New duplicate graph nodes created | — | — | +3 ("BST", "BST operations", "Key") | **0** |
| Run time | 232 s | 319 s | 288 s | **167 s** |

## 2. Classification

| ID | Seen in | Class | Cause in code | Research | Fix |
|---|---|---|---|---|---|
| E8 | run 6 | **Thin evidence**: every listed gap was in the body of a page whose summary we had | Only snippets/summaries were ever read | GPT-Researcher scrape-and-filter; Open Deep Research sub-agents read sources | `backend/dewey/fetch.py`: safe fetch (SSRF incl. redirects, RFC 9309 robots, size/type caps, per-host spacing), trafilatura → BeautifulSoup; Wikipedia via the MediaWiki extracts API with section headings and inline LaTeX; engine reads the best 2 results in full; a summary needs a full/excerpt passage before it counts as coverage; a poorer copy never supersedes a richer stored version |
| E10 | run 7 | **Answer grounded on weak evidence**: the root answer described a GitHub repo | `ground_answer` let any claim ground an answer, including capped metadata (0.35) | Reliability-prior reranking (arXiv 2607.22584), CrAM | Only claims ≥ 0.5 may ground; weak ones stay attached for transparency |
| E10b | run 7 | **Shallow candidate pool**: junk passages crowded out relevant sections | Archive queried for exactly `max_passages` before gating | Standard retrieve-then-rerank (wide pool → rerank) | Pool = 4× output, then gate + rerank (test proven to fail on the old pool) |
| E11 | run 8 | **Synthesis not grounded on sub-findings**: root ungrounded while both children grounded at 1.0 | The master searched afresh for its whole multi-part question | Open Deep Research: supervisor writes from sub-agents' cited findings | `claims_with_descendants`: a node grounds on own + all descendants' claims |
| E4 | runs 5–8 | **Entity duplicates** ("BST" vs "Binary search tree", "BST Property"/"the BST property", "BinarySearchTreeOperations"/"BST operations") | Exact-name matching only | EDC (EMNLP 2024) Canonicalize; Mem0 MERGE | Stage-1 deterministic canonicalisation: canonical key (camelCase, articles, plurals) + acronym expansion against existing multi-word entities; lazy backfill |
| bug | test | file:// / ftp:// refusals mislabelled "robots_denied" | Scheme checked only inside the robots lookup | — | Scheme checked first |

## 3. Tests
New: `verify_dewey_fetch` 10/10, `verify_canonical_entities` 8/8 (incl. live Neo4j, test nodes deleted).
Extended: `verify_grounding` 17/17, `verify_dewey_engine` 11/11. All 18 suites green.

## 4. Still wrong (to iteration 03)
| ID | Seen in | Problem | Planned fix (research) |
|---|---|---|---|
| E12 | run 9 | Root answer covers operations only; its gaps list "definition", "how it works", although the Archive holds the full Wikipedia article. The master stopped after one child, and the root's own retrieval for the compound question yielded 0 claims (synthesis judges a passage against the whole multi-part question). | **Gap-driven re-query**: each gap the writer lists becomes a targeted InformationNeed, evidence is gathered, the answer is re-composed once (Self-Ask decomposition, CRAG "ambiguous → reformulate", IRCoT-style interleaving). This is the inner loop from the orchestration design. |
| E4b | runs 5–9 | Old duplicates still in the graph; meaning-level duplicates ("root" vs "root node", "BST Invariant" vs "BST Property") | LLM merge decision (Mem0 ADD/MERGE/NOOP) for near candidates; merging existing nodes needs the owner's OK (data change) |
| E5 | runs 5–9 | Free-form, redundant relation types | EDC Define + Canonicalize for relations; one edge per (pair, relation family) |
| E6 | all | ResearchResponse: relationships 3, claims scoped to member concepts | Include the root entity's questions/claims and its decomposition edges |
| E9 | all | "max confidence 0.00 does not meet policy threshold 0.00" | Message fix |
| infra | all | Gemma 31B 500/503 (12–21 per run) absorbed by fallback | Watch; Groq first |
