# Iteration 01: analysis of live run 5 (Binary search tree)

Log: `.scuba/logs/discovery_live_bst_run5_wikifix.log` (325 s, Groq first,
Dewey evidence path, grounding on).

## 1. Scorecard

| Layer | Items | Correct | Wrong / defective | Notes |
|---|---|---|---|---|
| Answers (agent nodes) | 4 | 4 behaved correctly (2 grounded + correct, 2 honestly marked ungrounded) | 1 citation defect (root) | 2 of 4 still lack evidence |
| Evidence claims | 4 | 2 ([1], [4] Wikipedia) | 2 ([2] metadata over-trusted, [3] duplicate of [2]) | |
| Graph edges | 33 | 19 correct, non-redundant | 11 duplicate entity/edge, 3 wrong relation | |
| Research response | claims / relationships / coverage text | status honest | claims 1 vs 4, relationships 3 vs 33, nonsense coverage reason | |
| Infrastructure | — | Wikipedia fixed; Groq-first 325 s | Semantic Scholar 1× 429; Gemma 6× 500, 8× 503 (absorbed) | |

## 2. Classification, with the cause in code

### Correct
| ID | Item | Why it's correct | Linked implementation |
|---|---|---|---|
| C1 | Child "definition + search" answer, GROUNDED, support 1.0 | Every statement traced to the Wikipedia claim | `agents/grounding.py` + `questions/grounded_answer.py` + `audit_synthesis` |
| C2 | Root answer marked GROUNDED with 2 statements flagged unsupported (O(n), O(log n)) | The Wikipedia text says only "linear in height"; the audit refused to credit facts from memory | `audit_synthesis` atomic-claim audit |
| C3 | Two answers marked NOT GROUNDED with listed gaps | No evidence, or none covering the question; the system said so instead of pretending | `ground_answer` ungrounded paths |
| C4 | Claim [1] Wikipedia, conf 0.90; claim [4] Wikipedia, conf 0.40 | Real definition text; [4] rightly rated lower (it doesn't list operations) | UA fix (`retrievers/base.py`), `synthesize_claim` |
| C5 | Junk sources (arXiv physics, book titles) produced no claims | The non-answer filter worked | `evidence/engine.py _is_non_answer` (R1.2) |
| C6 | 19 graph edges (e.g. Search STARTS_AT root, Insertion REPEATS_UNTIL null child pointer) | Accurate mechanism relations | `relation_extraction` |

### Wrong
| ID | Class | Item | Why it's wrong | Cause in code |
|---|---|---|---|---|
| E1 | Metadata over-trust | Claims [2]/[3]: "the repository includes the time complexities" at conf 0.70/0.60 | A README description is a statement *about a repo*, not evidence about BSTs | Every `RetrievedResource` is treated alike; nothing records that GitHub/Open Library/YouTube give **metadata**, not content (`evidence/models.py`, `synthesize_claim`) |
| E2 | Citation imprecision | Root answer cites [1, 2] on the O(n)/O(log n) sentence that the audit marked unsupported; cites the GitHub repo for "operations are implemented in typical libraries" | The writer chooses its own citations; the audit's verdict never changes them | `ground_answer` takes `composed.cited` as truth; the audit only computes a ratio |
| E3 | Duplicate evidence | [2] and [3] are the same GitHub repo, the same fact | No dedupe of claims within one evidence batch | `gather_evidence_with_outcomes` |
| E8 | Thin / junk retrieval | Insertion and operations nodes got no usable evidence; arXiv returned physics papers for "binary search tree" | Snippets/summaries only (Wikipedia summary lacks the insertion section); with the `general` route every provider is asked; no relevance gate before LLM synthesis | `dewey/engine.py` (no gate), no page fetch (Dewey step 3 not built) |
| E4 | Entity duplication | BST Property / the BST property / BST Invariant / BST structural properties; Operations / BinarySearchTreeOperations; root / root node / binary search tree root; new node / new node containing key | No canonicalisation at write time | `graph.find_or_create_entity` exact-ish match only; `merge_entity` never called on write |
| E5 | Relation drift / errors | 3 synonyms for BST→Search; `Operations --PERFORM--> BST` (direction wrong); `Insertion --OPERATES_ON--> BinarySearchTreeOperations` | Free-form relation names, no schema | `questions/relation_extraction.py` |
| E6 | Projection mismatch | Response claims=1 vs 4, relationships=3 vs 33 | The response gathers only abstraction *member* concepts, not the root entity's own questions/claims | `research_api/service.py` + `compile_research_artifact` scope |
| E7 | Source refusal | Semantic Scholar 429 | Keyless shared rate limit | provider; ledger retry |
| E9 | Message bug | "max confidence 0.00 does not meet policy threshold 0.00" | Reason text formats a 0 threshold as if it were compared | `research/coverage.py` reason string |

## 3. Research applied

| Issue | Paper / method | What we take |
|---|---|---|
| E2 | **VeriCite** (verify each statement with NLI; keep a citation only if the passage entails it; removing verification "severely" hurts citation quality), **CiteFix** (post-processing citation correction, up to +15.46% relative accuracy), ALCE citation precision/recall | **Citations come from the audit, not the writer.** The audit returns which evidence items support each atomic statement; the Answer's `claim_ids` = verified supports only; statements are kept with per-statement support for the UI. |
| E1 | **Source-aware reranking with a reliability prior** (arXiv 2607.22584: P@5 0.48→0.72 in their setup), **RA-RAG** (estimate source reliability), **CrAM** (weight documents by credibility) | Each resource declares a **`content_kind`** (full_text / excerpt / summary / abstract / metadata). Claims from *metadata* are capped below the "supported" threshold (0.5); metadata passages are ranked last in the evidence batch. |
| E3 | Standard dedupe (and R4.2's own duplicate resolution in this repo) | Same canonical URL + near-identical evidence → keep the higher-confidence claim. |
| E8 | CRAG's retrieval evaluator (grade before use); SAAS over-search | A cheap **relevance gate** in Dewey: passages that cover < ⅓ of the need's terms aren't sent to the LLM (still archived). Full fetch = Dewey step 3, next iterations. |
| E4/E5 | **EDC** (Extract, Define, Canonicalize; EMNLP 2024): define each relation/entity in words, retrieve nearest existing ones, LLM decides whether to map. Note: EDC itself has no entity de-dup; **Mem0**'s ADD/MERGE/NOOP covers that | Iteration 02. |
| E6, E9 | (bug fixes, no research needed) | Iteration 02. |

## 4. Changes in this iteration
| Fix | Change | Files |
|---|---|---|
| E2 | Audit returns `supported_by` per atomic statement; the Answer's `claim_ids` = audit-verified supports only (`citations_verified`); per-statement `Statement` records; audit sees ALL claims; audit traces nothing → grounded=False | `questions/audit.py`, `agents/grounding.py` |
| E1 | `content_kind` on every resource (fixed per retriever: summary / abstract / excerpt / metadata); metadata claims capped at 0.35 (< 0.5 supported); metadata ranked last; **metadata never counts as coverage** (found in the re-run) | `evidence/models.py`, `retrievers/*`, `evidence/engine.py`, `dewey/*` |
| E3 | Same URL + ≥0.6 token overlap → one claim (highest confidence) | `evidence/engine.py _dedupe_claims` |
| E8 | Relevance gate: passages covering < ⅓ of the need's terms aren't sent to the LLM (still archived) | `dewey/engine.py _deliverable` |
| infra | Archive migration adds `content_kind`, exact backfill of old rows by provider | `dewey/archive.py` |

Tests: `verify_grounding` 15/15, `verify_dewey_engine` 10/10, all 15 offline suites green.

## 5. Results: live run 6 (`.scuba/logs/discovery_live_bst_run6_iter01.log`, 232 s)
| Metric | Run 5 | Run 6 |
|---|---|---|
| Citations on unsupported sentences | yes (root cited [1,2] on unsupported O(n)/O(log n)) | **none**: `citations_verified=True`, cites only the claim the audit matched |
| Metadata claims rated ≥0.5 | 2 (0.70, 0.60) | **0** |
| Duplicate claims | 1 pair | **0** |
| Honest gaps listed | 2 | root lists 4 precise gaps ("exact algorithmic steps…", "cost per operation…") |
| Answers grounded | 2 / 4 | 1 / 2 (root, support 0.5; the 3 unsupported statements are genuinely not in the evidence) |
| Web calls | many | **0 new documents**: the Archive served everything from run 5 (evolving archive working) |

**Found during the re-run (fixed same iteration):** the ops sub-question was
ledgered "found" because GitHub/Open Library *metadata* counted as coverage →
`_covered` now ignores metadata; ledger reset.

**Still wrong (carried to iteration 02):**
- **E8 thin evidence is now the dominant failure.** Every gap the system lists
  ("exact steps for search/insert/delete", "cost per operation") is in the
  *body* of the Wikipedia article, but we only read its 2-sentence summary.
  → Dewey step 3: fetch + extract full pages, split into section passages.
- E4/E5 graph duplicates (new: "BST operations") → EDC define-and-canonicalise + Mem0 merge.
- E6 response scope (claims 1, relationships 3), E9 coverage message.
