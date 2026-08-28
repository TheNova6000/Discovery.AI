"""Final variant of the controlled relationship experiment (docs/Memory.md /
Architecture.md §0.5). Same two claims, same original Session 3 wording, as
`scripts/analyze_controlled_relationship.py` — testing whether a question that
explicitly demands a PRIMARY causal explanation (forcing single-cause framing)
elicits "alternative_explanation" where broader "why"/"how" questions didn't.

Question A ("Why do some companies become dominant while others fail?") is NOT
re-run here — it's the exact same claims/wording/question already run in
`analyze_controlled_relationship.py`, which returned `sequential` at confidence
0.9. Re-running an identical call would just spend budget re-measuring the same
thing; its already-captured result is reused below for the comparison.

Question B is new — the one actual experiment this script runs:
    "Which factor primarily explains why some companies become dominant while
    others fail: network effects or regulatory capture?"

The classification prompt itself is UNCHANGED from the prior experiments — it
still just asks for one of the 6 categories with reasoning, never asking "are
these competing explanations" directly. Only the target question changes. That's
the deliberate constraint: a behavioral test, not a leading one.

If B produces alternative_explanation: real evidence the question's framing (not
just the claims/wording) controls whether competition-between-explanations gets
recognized -- and the next question becomes "where does a CONTEXTUAL relationship
live," not "what's the Neo4j edge type." If B still produces
sequential/complementary: stop hammering this pair, per explicit agreement --
that would be real evidence this pair isn't represented as competing by the
model, not a prompt failure to keep chasing.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import analyze_claim_relationships  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402

QUESTION_A = "Why do some companies become dominant while others fail?"
QUESTION_A_ALREADY_CAPTURED = {
    "relationship": "sequential",
    "confidence": 0.9,
    "reasoning": (
        "Claim 2 describes strategic actions, such as initial predatory or subsidized pricing, that enable "
        "companies to rapidly scale and achieve the network effects detailed in Claim 1. Once network effects are "
        "established (Claim 1), other mechanisms from Claim 2 (vertical integration, regulatory capture) then "
        "serve to sustain and reinforce the market dominance created by those network effects."
    ),
}

QUESTION_B = (
    "Which factor primarily explains why some companies become dominant while others fail: "
    "network effects or regulatory capture?"
)

# Verbatim from Session 3's actual logged output — identical to
# analyze_controlled_relationship.py's CLAIMS.
CLAIM_NETWORK_EFFECTS = (
    "Network effects create defensible moats by creating a self-reinforcing feedback loop where the value of a "
    "product or service increases for every existing and future user as more people adopt it. This dynamic "
    "generates market dominance through several specific mechanisms: (1) High Switching Costs & Lock-in: as a "
    "network grows, the utility a user derives from it often exceeds any alternative, making defection costly. "
    "(2) The 'Winner-Take-All' Dynamic: the leading platform captures the vast majority of new supply and demand "
    "because its greater scale inherently offers superior utility compared to smaller rivals, starving competitors "
    "of the critical mass needed to survive. (3) Data and Feedback Loops: increased usage generates proprietary "
    "data that improves the product, creating a compounding advantage where the dominant player becomes better "
    "simply by being larger. (4) Ecosystem & Complementary Asset Attraction: a large user base attracts "
    "third-party developers and merchants who build tools around the platform, deepening its moat."
)

CLAIM_REGULATORY_CAPTURE = (
    "Dominant platforms sustain market power and deter new entrants through a reinforcing loop of strategic "
    "pricing, vertical integration, and regulatory capture: (1) Strategic Pricing & Subsidization: dominant "
    "companies initially use predatory or subsidized pricing to rapidly scale and achieve network effects, locking "
    "in both sides of a multi-sided market. Once switching costs become prohibitive and competitive alternatives "
    "wither, they extract rents by raising fees on suppliers or end-users (the core mechanism of "
    "'enshittification'). (2) Vertical Integration: by entering adjacent markets or acquiring potential "
    "competitors, dominant firms control critical infrastructure and gatekeeping functions, favoring their own "
    "internal services and squeezing out independent competitors. (3) Regulatory Capture: armed with vast capital "
    "and entrenched market positions, dominant firms shape regulatory frameworks to protect their status, lobbying "
    "for complex compliance standards that create insurmountable regulatory moats for smaller startups."
)

CLAIMS = [CLAIM_NETWORK_EFFECTS, CLAIM_REGULATORY_CAPTURE]


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    print("=" * 70)
    print("QUESTION A (already captured, NOT re-run)")
    print(f"Target question: {QUESTION_A}")
    print("=" * 70)
    print(f"relationship: {QUESTION_A_ALREADY_CAPTURED['relationship']}")
    print(f"confidence: {QUESTION_A_ALREADY_CAPTURED['confidence']}")
    print(f"reasoning: {QUESTION_A_ALREADY_CAPTURED['reasoning']}")

    result_b = await analyze_claim_relationships(QUESTION_B, CLAIMS)
    pair = result_b.pairs[0]

    print("\n" + "=" * 70)
    print("QUESTION B (new, one call — forces primary-cause framing)")
    print(f"Target question: {QUESTION_B}")
    print("=" * 70)
    print(f"relationship: {pair.relationship}")
    print(f"confidence: {pair.confidence}")
    print(f"reasoning: {pair.reasoning}")

    print("\n" + "=" * 70)
    print("If B == alternative_explanation: the question's FRAMING (single-cause")
    print("demand), not just wording/paraphrase, controls whether competing")
    print("explanations get recognized. Real evidence for a contextual")
    print("relationship model.")
    print("If B is still sequential/complementary: stop here -- real evidence")
    print("this specific pair isn't represented as competing by the model, not")
    print("a prompt failure worth chasing further.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
