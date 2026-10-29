# Implementation ↔ Analysis ↔ Research Loop (main block)

Standing method set by the project owner on 2026-10-28. It applies to the main block:
**Discovery.AI** (reasoning), **Dewey** (research engine + Archive), and the
orchestration between them.

## Each iteration

1. **Run.** Take the latest live output (`scripts/evaluate_discovery_live.py`,
   log in `.scuba/logs/`).
2. **Score.** Count correct vs wrong for every output layer: answers, claims,
   graph entities/edges, research response.
3. **Classify with causes.** Every item gets a class and a *why*, linked to the
   code or issue that produced it (file:line or module).
4. **Research.** For each wrong class, find real research papers on that
   problem and pick the method that fits our constraints (free-tier LLMs, no
   training, SQLite/Neo4j).
5. **Implement.** Change the code, write an offline test first, keep every
   existing suite green.
6. **Loop.** Re-run live on the same topic(s), compare scorecards, repeat.

Alongside the loop, the remaining research-engine and orchestration steps are
built (docs/research/Reasoning-Research-Orchestration.md §8).

## Ledger
| Iteration | Run analysed | Main classes fixed | Result |
|---|---|---|---|
| [01](iteration-01.md) | run 5 (BST) | E1 metadata over-trust, E2 citation precision, E3 duplicate evidence, E8 junk gate | run 6: 0 bad citations, 0 metadata over-trust, 0 duplicates; thin evidence now dominant |
| [02](iteration-02.md) | runs 6–9 (BST) | E8 full-page fetch/extract, E10 weak-evidence answers + rerank pool, E11 synthesis on children's claims, E4 entity canonicalisation | run 9: 2/2 grounded, 0 new duplicate nodes, 167 s |
| [03](iteration-03.md) | run 9 → 10 | E12 gap re-query (inner loop), E9 message | run 10: 3/3 grounded, root complete, 1 wrong statement (traversal) |
| [04](iteration-04.md) | run 10 | E13 claim↔source faithfulness, E6 response scope | relationships 3→24; exposed E14/E15 |
| [05](iteration-05.md) | BST 11-12, Photosynthesis 1-3, TCP 1, Mitosis 1 | E14 synthesis path, E15/E16 fetch+stemming, E17 Groq schema rejections, E19 section-aware retrieval (benchmark hit@4 0.69→1.00), E20 search queries | Photosynthesis 3/3, TCP 4/4 grounded; Mitosis re-run pending |
