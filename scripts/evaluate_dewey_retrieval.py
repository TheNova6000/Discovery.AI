"""Retrieval benchmark for Dewey's passage ranking (loop iteration 05, E18/E19)
— offline, uses the real archive (dewey_archive.sqlite3), no LLM, no network.

Each case: a question and the marker(s) a correct passage contains (usually its
section header). Reports hit@4 (a correct passage among the 4 handed to the
LLM) and MRR, for the current ranking and for a small grid of variants, so a
ranking change is chosen by measurement instead of by eyeballing a few queries.

Usage: python scripts/evaluate_dewey_retrieval.py [--grid]
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.main_block.research_engine.engine as eng  # noqa: E402
from backend.main_block.research_engine.interface import ArchiveStore, InformationNeed  # noqa: E402

CASES = [
    ("What is a binary search tree?", ["In computer science, a binary search tree", "Section: Overview"]),
    ("How does insertion work in a binary search tree?", ["Section: Insertion"]),
    ("How are nodes deleted from a binary search tree?", ["Section: Deletion"]),
    ("How does searching a binary search tree work?", ["Section: Searching", "Section: Recursive search", "Section: Iterative search"]),
    ("What is the time complexity of traversal in a binary search tree?", ["Section: Traversal"]),
    ("Why do binary search trees need balancing?", ["Section: Balanced binary search trees", "Section: Height-balanced trees"]),
    ("What is photosynthesis?", ["Section: Photosynthesis", "Photosynthesis is a"]),
    ("What are the light-dependent reactions of photosynthesis?", ["Section: Light-dependent reactions"]),
    ("What are the inputs and outputs of the Calvin cycle?", ["Section: Calvin cycle", "Section: Steps"]),
    ("How does water photolysis work in photosynthesis?", ["Section: Water photolysis"]),
    ("How does slow start work in TCP congestion control?", ["Section: Slow start"]),
    ("How does fast retransmit work in TCP?", ["Section: Fast retransmit"]),
    ("What is additive increase multiplicative decrease in TCP congestion control?", ["Section: Additive increase/multiplicative decrease", "AIMD"]),
]


async def score(archive: ArchiveStore) -> tuple[float, float, list[str]]:
    hits4, rr, misses = 0, 0.0, []
    for question, markers in CASES:
        need = InformationNeed(text=question, need_kind="general", max_passages=4)
        pool, idf = await eng._candidate_pool(archive, need)
        need_wide = need.model_copy(update={"max_passages": 20})
        ranked = eng._deliverable(need_wide, pool, idf)
        rank = next((i + 1 for i, h in enumerate(ranked) if any(m in h.text for m in markers)), None)
        if rank is not None and rank <= 4:
            hits4 += 1
        else:
            misses.append(f"{question} (rank {rank})")
        rr += 1 / rank if rank else 0.0
    return hits4 / len(CASES), rr / len(CASES), misses


async def main() -> int:
    async with ArchiveStore() as archive:
        h, m, misses = await score(archive)
        print(f"current: hit@4={h:.2f}  MRR={m:.2f}")
        for miss in misses:
            print(f"   miss: {miss}")
        if "--grid" in sys.argv:
            base = (eng.HEADING_BONUS, eng.KEY_TERMS, eng.TITLE_BONUS)
            results = []
            for heading in (0.0, 1.0, 2.0, 3.0):
                for key in (1, 2, 3, 10):
                    for title in (0.0, 1.0, 2.0):
                        eng.HEADING_BONUS, eng.KEY_TERMS, eng.TITLE_BONUS = heading, key, title
                        h, m, _ = await score(archive)
                        results.append((h, m, heading, key, title))
            eng.HEADING_BONUS, eng.KEY_TERMS, eng.TITLE_BONUS = base
            for h, m, heading, key, title in sorted(results, reverse=True)[:8]:
                print(f"   heading={heading} key_terms={key} title={title}: hit@4={h:.2f} MRR={m:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
