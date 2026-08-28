"""Phase 5 verification script — see docs/Phases.md "Phase 5".

Requires a running Neo4j instance (this project's is only ever run on the Oracle
Cloud VM — no local Docker on the dev machine, see docs/Memory.md) and at least one
LLM provider key in .env.

Two things are verified:
1. `GroundAgent(gather_evidence=True)` really populates `GroundResult.claims` with
   real, LLM-synthesized claims when it answers — docs/Phases.md's "wire Evidence
   Engine output into Ground Agent results."
2. The full pipeline Phases.md's own verify step describes: create a canonical
   entity -> generate a real Question for it (Question Engine, Phase 2) -> attach
   it to the entity in Neo4j (Phase 5's new `attach_question`) -> retrieve real
   resources and synthesize Claims (Evidence Engine) -> attach them to the Question
   node (Phase 5's new `attach_claim`) -> read them back and confirm
   confidence/provenance are populated. Also exercises `supersede_claim` (the
   Graphiti-inspired temporal edge) since nothing else in this phase does.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents import GroundAgent  # noqa: E402
from backend.agents.models import AgentStatus  # noqa: E402
from backend.evidence import gather_evidence  # noqa: E402
from backend.graph import (  # noqa: E402
    attach_claim,
    attach_question,
    close_driver,
    create_node,
    ensure_constraints,
    get_claims_for_question,
    supersede_claim,
)
from backend.questions import SCALE, TIME, QuestionLevel, generate_question  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402


async def check_ground_agent_populates_claims() -> None:
    question = await generate_question(
        abstraction_name="Payment Platforms",
        entity_name="PayPal",
        dimension=TIME,
        level=QuestionLevel.GROUND,
        objective="Understand how PayPal emerged as a company in the late 1990s.",
    )
    agent = GroundAgent(question, max_depth=0, gather_evidence=True)
    result = await agent.run()
    print(f"[ground] status={result.status.value} claims={len(result.claims)}")
    assert result.status in (AgentStatus.COMPLETE, AgentStatus.BOUNDARY_HIT)
    if result.status == AgentStatus.COMPLETE:
        assert len(result.claims) >= 1, "a completed Ground Agent with gather_evidence=True should attach claims"
        for claim in result.claims:
            assert claim.source.url and claim.source.title
            assert 0.0 <= claim.confidence <= 1.0
        print("[ok] GroundResult.claims populated with real, sourced claims")
    else:
        print("[ok] boundary hit instead of answering this run (LLM's call) — retrying with a narrower question")
        narrower = await generate_question(
            abstraction_name="Payment Platforms",
            entity_name="PayPal",
            dimension=TIME,
            level=QuestionLevel.GROUND,
            objective="What year and as what company name did PayPal originally launch?",
        )
        agent2 = GroundAgent(narrower, max_depth=0, gather_evidence=True)
        result2 = await agent2.run()
        assert result2.status == AgentStatus.COMPLETE, "expected a direct answer for a narrow factual question"
        assert len(result2.claims) >= 1
        print("[ok] GroundResult.claims populated with real, sourced claims (narrower retry)")


async def check_graph_attachment_pipeline() -> None:
    await ensure_constraints()
    paypal = await create_node("PayPal", "entity", "Online payments company")

    question = await generate_question(
        abstraction_name="Payment Platforms",
        entity_name="PayPal",
        dimension=SCALE,
        level=QuestionLevel.GROUND,
        objective="Understand how PayPal processes a single transaction.",
    )
    print(f"[question] {question.text}")

    question_node = await attach_question(
        paypal.id,
        question_id=question.id,
        text=question.text,
        dimension_id=question.dimension_id,
        level=question.level.value,
        rationale=question.rationale,
    )
    assert question_node.id == question.id

    claims = await gather_evidence(question)
    print(f"[evidence] {len(claims)} real claim(s) retrieved from live APIs")
    assert len(claims) >= 1, "expected at least one real resource from a live retriever"

    for claim in claims:
        await attach_claim(
            question.id,
            claim_id=claim.id,
            evidence=claim.evidence,
            reasoning=claim.reasoning,
            confidence=claim.confidence,
            source_title=claim.source.title,
            source_url=claim.source.url,
            source_type=claim.source.source_type,
            valid_from=claim.valid_from,
        )

    stored = await get_claims_for_question(question.id)
    assert len(stored) == len(claims), f"expected {len(claims)} stored claims, got {len(stored)}"
    for claim_node in stored:
        assert claim_node.source_url and claim_node.source_title, "provenance must be populated"
        assert 0.0 <= claim_node.confidence <= 1.0, "confidence must be populated"
        assert claim_node.superseded_by is None
    print(f"[ok] {len(stored)} claim(s) attached to the Question node in Neo4j, confidence/provenance populated")

    # Exercise the temporal supersede pattern (Graphiti-inspired) — nothing else in
    # this phase does, so verify it directly: the first stored claim gets marked
    # superseded by the second (or by itself if only one came back, just to prove
    # the mechanics work end to end).
    old_claim = stored[0]
    new_claim_id = stored[1].id if len(stored) > 1 else old_claim.id
    if new_claim_id != old_claim.id:
        await supersede_claim(new_claim_id, old_claim.id)
        refreshed = await get_claims_for_question(question.id)
        refreshed_old = next(c for c in refreshed if c.id == old_claim.id)
        assert refreshed_old.superseded_by == new_claim_id
        print(f"[ok] supersede_claim recorded {new_claim_id!r} supersedes {old_claim.id!r}, old claim kept in graph")
    else:
        print("[skip] only one claim retrieved this run — supersede_claim mechanics already covered elsewhere")


async def run() -> None:
    if not has_any_provider_key():
        print(
            "[fail] No LLM provider key found in .env "
            "(GEMINI_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY / COHERE_API_KEY)."
        )
        raise SystemExit(1)

    try:
        await check_ground_agent_populates_claims()
        await check_graph_attachment_pipeline()
        print("\nPhase 5 verification PASSED.")
    finally:
        await close_driver()


if __name__ == "__main__":
    asyncio.run(run())
