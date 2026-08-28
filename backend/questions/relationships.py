from __future__ import annotations

from itertools import combinations
from typing import Literal

from pydantic import BaseModel, Field

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import MASTER_MODEL_CHAIN

_SYSTEM_PROMPT = """\
You are analyzing the RELATIONSHIP between pairs of already-established claims, \
relative to a specific TARGET QUESTION. Every claim given to you has ALREADY been \
independently investigated and grounded (provenance is not being questioned here \
— assume every claim is a real, supported finding). Your only job is to judge how \
each PAIR of claims relates to each other AS EXPLANATIONS FOR THE GIVEN QUESTION.

The relationship is NOT an intrinsic property of the two claims alone — it depends \
on the target question. The same two claims can be complementary mechanisms with \
respect to one question and competing explanatory emphases with respect to a \
different question about the same subject. Judge the relationship strictly \
relative to the question given, not in the abstract.

Classify each pair into exactly one of:

- "complementary": both claims can be true together and jointly contribute to \
answering THIS question — accepting one does not reduce the need for, or compete \
with, the other. They stack.
- "alternative_explanation": the two claims offer MATERIALLY DIFFERENT causal or \
normative accounts of the same outcome, with respect to THIS question. Both may be \
entirely true and real — this is NOT a truth judgment — but presenting them as \
simply additive, equally-weighted contributors would understate that they compete \
to explain WHY/WHAT PRIMARILY drives the outcome this question asks about, not \
just contribute different pieces of it. A pair can be causally connected in \
reality (see "sequential" below) and STILL be alternative explanations with \
respect to a question asking "what primarily explains X" — don't rule this out \
just because the claims also interact causally.
- "contradictory": accepting both claims together, under the same assumptions, is \
logically or practically inconsistent — one being fully true would actually \
undermine or contradict the other. This is rare. Do not use this just because two \
claims are different or emphasize different mechanisms — that is \
"alternative_explanation," not "contradictory."
- "conditional": each claim explains the outcome only under a different \
condition/context (e.g. claim A applies in market X, claim B applies in market Y) \
— they are not really competing OR simply stacking, they're each true in their own \
scope.
- "sequential": one claim is a causal precursor or consequence of the other with \
respect to this question (A leads to B, or enables B, which then produces the \
outcome) — a causal chain, not a set of parallel contributors or competitors.
- "unrelated": the two claims don't meaningfully bear on each other with respect \
to THIS question.

CRITICAL:
- "alternative_explanation" does not mean either claim is false. Competing \
explanations can both operate in reality at once, and can even be causally linked \
(see above) while still competing to explain what this specific question is \
really asking about.
- Do not default to "contradictory" merely because two claims are different — that \
is the single most important mistake to avoid here. Reserve "contradictory" for \
genuine logical or practical inconsistency.
- If your honest answer is nuanced — e.g. "these are complementary mechanisms in \
reality, but competing explanatory emphases for what this specific question is \
asking" — say exactly that in `reasoning`, then pick whichever single label is the \
closest primary fit and set `confidence` low to signal the classification is a \
simplification of a more nuanced judgment. Do not force a clean single label by \
suppressing real nuance — the nuance IS the finding.
- Always give `reasoning` — a relationship classification with no stated reason is \
not usable by anyone trying to inspect why the judgment was made.

Keep `reasoning` concise (2-3 sentences per pair) — do not quote the claims back \
at length.
"""


class ClaimPairRelationship(BaseModel):
    claim_a_index: int = Field(description="1-based index of the first claim in this pair, per the input list.")
    claim_b_index: int = Field(description="1-based index of the second claim in this pair, per the input list.")
    relationship: Literal[
        "complementary", "alternative_explanation", "contradictory", "conditional", "sequential", "unrelated"
    ]
    reasoning: str = Field(description="2-3 sentences on why this classification, relative to the question.")
    confidence: float = Field(
        description="0-1: how cleanly the pair fits the single chosen label, relative to this specific question. "
        "Lower when the honest judgment is nuanced or mixed (see the nuance guidance above)."
    )


class RelationshipAnalysis(BaseModel):
    pairs: list[ClaimPairRelationship]


def _build_user_prompt(question: str, claims: list[str]) -> str:
    lines = [f"Question: {question}", "", "Claims (already established/grounded):"]
    for i, claim in enumerate(claims, start=1):
        lines.append(f"{i}. {claim}")
    pairs = list(combinations(range(1, len(claims) + 1), 2))
    lines.append("\nClassify EVERY one of the following pairs (by index): " + ", ".join(f"({a},{b})" for a, b in pairs))
    return "\n".join(lines)


async def analyze_claim_relationships(
    question: str,
    claims: list[str],
    *,
    model_chain: list[str] | None = None,
) -> RelationshipAnalysis:
    """One isolated experiment (docs/Memory.md's claim-relationship design pass):
    given a TARGET QUESTION and a list of already-grounded claims (provenance
    assumed, not re-examined here), classify every pair's relationship as
    complementary/alternative_explanation/contradictory/conditional/sequential/
    unrelated, with reasoning and confidence. The question is load-bearing, not
    incidental — relationship is modeled as a function of (claim_a, claim_b,
    question), not an intrinsic property of the two claims alone (see the
    same-claims-different-question controlled experiment in Architecture.md
    §0.5/Memory.md). No Neo4j, no new graph schema, no change to the agent loop —
    this is purely testing whether the judgment itself is even makeable before
    earning the right to represent it anywhere.

    Lives in `backend/questions` per Rules.md rule 2 (LLM calls confined to
    `backend/evidence` and `backend/questions`).
    """
    chain = model_chain or MASTER_MODEL_CHAIN
    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(question, claims),
            response_model=RelationshipAnalysis,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(
            f"analyze_claim_relationships failed on every provider in {chain}: {exc}"
        ) from exc
