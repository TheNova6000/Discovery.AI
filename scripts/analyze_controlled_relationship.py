"""Controlled follow-up to the first claim-relationship experiment (docs/Memory.md
/ Architecture.md §0.5). Fixes the earlier experiment's confound (condensed,
neutral paraphrases stripped the loaded framing that made the tension visible) by
using Session 3's ORIGINAL, unparaphrased claim text verbatim, and tests whether
relationship is a property of (claim_a, claim_b) alone or of
(claim_a, claim_b, question) — by asking about the SAME two claims under TWO
different target questions.

One pair only: Network Effects vs. Regulatory Capture — chosen because this was
exactly the pair the first experiment got wrong (both times it was asked about,
regulatory capture came back "complementary" with every other claim, never
"alternative").

  Question 1 (original Session 3 question, emergence-flavored):
      "Why do some companies become dominant while others fail?"

  Question 2 (reframed, persistence-flavored):
      "How can dominant companies sustain market power?"

No Neo4j, no schema change, no new agent behavior. 2 calls.

Prediction stated before running, per the design discussion: if relationship is
contextual, Q1 (which asks what explains dominance arising/succeeding at all)
might surface network effects and regulatory capture as competing EXPLANATORY
emphases (alternative_explanation), while Q2 (which already presupposes
dominance exists and asks how it's sustained) might see them as more
complementary sustaining mechanisms. Either outcome — including "no difference
between the two" — is a real result, not a failure, per explicit instruction not
to force the result toward this prediction.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import analyze_claim_relationships  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402

QUESTION_1 = "Why do some companies become dominant while others fail?"
QUESTION_2 = "How can dominant companies sustain market power?"

# Verbatim from Session 3's actual logged output (Memory.md, 2026-08-28) — not
# paraphrased, loaded framing ("enshittification", "extract rents") preserved.
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


def _report(label: str, question: str, analysis) -> None:
    print("\n" + "=" * 70)
    print(label)
    print(f"Target question: {question}")
    print("=" * 70)
    pair = analysis.pairs[0]
    print(f"relationship: {pair.relationship}")
    print(f"confidence: {pair.confidence}")
    print(f"reasoning: {pair.reasoning}")


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    result_q1 = await analyze_claim_relationships(QUESTION_1, CLAIMS)
    _report("QUESTION 1 (emergence-flavored, original Session 3 question)", QUESTION_1, result_q1)

    result_q2 = await analyze_claim_relationships(QUESTION_2, CLAIMS)
    _report("QUESTION 2 (persistence-flavored, reframed)", QUESTION_2, result_q2)

    print("\n" + "=" * 70)
    print("Same two claims (original wording, unparaphrased), same pair, two questions.")
    print("Compare the two 'relationship' verdicts above:")
    print("  - Same label both times -> relationship may be closer to intrinsic")
    print("    for this pair, at least across these two questions.")
    print("  - Different label -> real evidence relationship is a function of")
    print("    (claim_a, claim_b, QUESTION), not the claims alone.")
    print("  - Same label but very different reasoning/confidence -> a subtler,")
    print("    still-informative partial-context-sensitivity result.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
