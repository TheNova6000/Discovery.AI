"""One isolated experiment (docs/Memory.md's claim-relationship design pass):
run `analyze_claim_relationships` against Session 3's actual question and its 4
already-grounded claims (provenance already verified — this experiment does not
re-examine that). No Neo4j, no new graph schema, no change to the agent loop.
6 pairs (C(4,2)), one call.

This is NOT graded as "did it produce the relationships we expected." It's graded
against the actual capability in question:

  1. Did it distinguish complementary mechanisms from competing explanations
     without inventing conflict where there's just difference?
  2. Did it avoid calling merely-different claims "conflicting"?
  3. Did it give a defensible reason for every pair?
  4. Did it preserve genuine uncertainty rather than forcing false confidence?

Deliberately uncertain expectation, stated before running (per the design
discussion): network effects/economies of scale look plausibly complementary;
regulatory capture looks like it could be "alternative" relative to the others
(a different explanatory register: extraction vs. genuine value creation); the
rest is genuinely unclear and that's fine.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import analyze_claim_relationships  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402

QUESTION = "Why do some companies become dominant while others fail?"

CLAIMS = [
    "Network effects create self-reinforcing feedback loops (switching costs, winner-take-all dynamics, data "
    "advantages) that generate and sustain market dominance.",
    "Economies of scale drive down unit costs as production volume increases, creating cost advantages and "
    "barriers to entry that sustain market dominance.",
    "Dominant firms sustain market power and deter new entrants through strategic pricing, vertical integration, "
    "and regulatory capture.",
    "Superior organizational culture, agile execution, and dynamic capital allocation distinguish companies that "
    "successfully scale and dominate from those that fail or stagnate.",
]


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    analysis = await analyze_claim_relationships(QUESTION, CLAIMS)

    print("=" * 70)
    print(f"Question: {QUESTION}")
    print("=" * 70)
    for i, c in enumerate(CLAIMS, start=1):
        print(f"{i}. {c}")

    print("\n" + "=" * 70)
    print("PAIRWISE RELATIONSHIPS")
    print("=" * 70)
    for pair in analysis.pairs:
        a_text = CLAIMS[pair.claim_a_index - 1]
        b_text = CLAIMS[pair.claim_b_index - 1]
        print(f"\n({pair.claim_a_index}) {a_text[:60]}...")
        print(f"({pair.claim_b_index}) {b_text[:60]}...")
        print(f"  relationship: {pair.relationship}")
        print(f"  reasoning: {pair.reasoning}")

    print("\n" + "=" * 70)
    print("Grade by hand against:")
    print("  1. Complementary vs. competing distinguished, not conflated?")
    print("  2. Any pair wrongly called 'conflicting' just for being different?")
    print("  3. Every pair has a defensible reason?")
    print("  4. Genuine uncertainty preserved where warranted, not forced?")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
