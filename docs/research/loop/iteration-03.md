# Iteration 03: gap-driven re-query (inner loop), coverage message

Run analysed: 9 → re-run 10 (`.scuba/logs/discovery_live_bst_run10_iter03.log`, 537 s; 27× Gemma 500 absorbed).

## 1. Scorecard (run 10)
| Layer | Items | Correct | Wrong | Notes |
|---|---|---|---|---|
| Answers | 3 | 3 grounded, verified citations; root now covers definition + mechanism + operations + costs (run 9: operations only) | 1 statement wrong: child says "a traversal (search) takes O(h)" (traversal is O(n)) | root support 0.706, children 1.0 / 0.857 |
| Claims | 4 (all Wikipedia full text) | [1], [2] | [3] frames search as "a form of traversal"; [4] reasoning says "traversal is linear in height" | evidence *texts* match the article; the distortion is in how synthesis framed them for a gap question |
| Audit | 7 unsupported statements flagged | all genuinely absent from the cited claims (search mechanics, balanced Θ(log n)) | 0 false credits seen | |
| Coverage text | — | "no active claims for this concept yet" (E9 fixed) | — | |
| Response | — | status honest | relationships 3 vs graph (E6) | |

## 2. Classification
| ID | Class | Cause in code | Research | Fix |
|---|---|---|---|---|
| E12 ✅ | Root answer missed definition/mechanism (run 9) | One compound-question search; gaps listed but never searched | Self-Ask decomposition; CRAG "ambiguous → reformulate"; IRCoT interleaving | `grounding._fill_gaps`: up to 2 listed gaps → targeted evidence needs → recompose; question itself searched as a gap when no usable evidence; gap claims returned + persisted so citations resolve |
| E9 ✅ | Self-contradictory coverage reason | Reason formatted a comparison with 0 claims | — | Message states "no active claims for this concept yet" |
| **E13 (new)** | **Claim distorts its source**: a passage about search cost becomes "traversal takes O(h)" when synthesised for the gap "time complexity of traversal" | `synthesize_claim` checks relevance to the *question*, nothing checks the claim against its *source passage*; the answer audit only checks answer ↔ claims | FActScore (verify atomic facts against the knowledge source), NLI faithfulness checks (SummaC / AlignScore family), RARR (research-and-revise attribution) | Iteration 04: verify each claim against its passage (supported / distorted), drop or downgrade distorted claims |

## 3. Tests
`verify_grounding` 20/20 (new #18–20); all 22 offline suites incl. phase 8.1–8.6 green.

## 4. Next (iteration 04)
E13 claim↔source faithfulness; E6 response scope; E5 relation schema (EDC define + canonicalise);
E4b meaning-level entity merges (Mem0) and the owner's decision on merging old duplicates;
latency (537 s, Gemma 500s).
