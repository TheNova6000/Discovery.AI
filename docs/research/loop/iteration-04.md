# Iteration 04: claim ↔ source faithfulness, research-response scope

Runs analysed: 10 (BST). Re-runs: 11 (BST), Photosynthesis run 1 (first non-CS topic).

## Classification and fixes
| ID | Class | Cause in code | Research | Fix |
|---|---|---|---|---|
| E13 | Claim distorts its source ("traversal takes O(h)" from a passage about search cost) | `synthesize_claim` judged relevance to the question; nothing checked claim ↔ its own passage | FActScore (verify atomic facts against the knowledge source); NLI faithfulness checks (SummaC / AlignScore family) | (a) prevention: synthesis prompt forbids relabelling the source to fit the question; (b) detection: `evidence/faithfulness.py` checks every claim against its passage in ONE batched call (supported / distorted / unsupported); non-supported claims are dropped and kept visible as RetrievalOutcomes; checker failure keeps claims marked unverified (`faithfulness_checked=False`); `EVIDENCE_FAITHFULNESS=off` switch |
| E6 | Research response covered only the topic's members: relationships 3 vs 30+ edges, root claims missing | `fetch_and_compile_research_response` scoped to abstraction members; the topic entity is not a member of its own abstraction | — (scope bug) | Read-only `graph.get_root_entity` + `get_relationships_among`; response now includes the topic entity, its questions/claims and all edges among topic + members. Live: relationships 3 → 24, claims 7 → 14 |

Tests: new `verify_faithfulness` 5/5; all 27 suites incl. live r5_3 / phase9_2 green.

## Re-run results
| Run | Grounded answers | Claims | Notes |
|---|---|---|---|
| BST run 11 | 2/4 grounded at 1.0; algorithms child 0 claims; **root printed no grounding at all** | 2 (0.95, 0.90, full text) | root answered through the budget-exhausted synthesis path → E14 |
| Photosynthesis run 1 | **0/3** (all honestly NOT GROUNDED) | 0 | Wikipedia article stored as summary only, never read in full → E15/E16 |

New stale-data observation (for the final DB evaluation): the response's 14 claims include earlier
runs' claims (e.g. run 5's GitHub-metadata claim rated 0.70 before the cap) — persisted claims do
not expire or get re-checked. → candidate for claim lifecycle use (supersede on re-verification).
