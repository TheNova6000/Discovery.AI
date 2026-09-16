from __future__ import annotations

from backend.graph.interface import get_claims_for_question, get_questions_for_entity, get_subgraph
from backend.graph.models import ClaimNode, QuestionNode

from .models import Roadmap
from .ordering import order_roadmap_steps


async def generate_roadmap(abstraction_id: str) -> Roadmap:
    """PRD.md §4a / Phases.md Phase 6: `generate_roadmap(abstraction) ->
    list[Question]`, a pure read over the already-built graph, not a new agent
    tier (Architecture.md §2). This is only the I/O shell -- fetch the
    abstraction's subgraph plus each member entity's questions/claims -- around
    the real logic in `ordering.order_roadmap_steps`, which is what's actually
    unit-tested (scripts/verify_phase6.py) without needing a live Neo4j.

    Never calls an LLM or retriever (Rules.md rule 14): an entity with no
    attached questions yet just contributes zero steps -- that's a gap this
    surfaces by omission, not one it fills. Filling it means running more
    investigation first (the existing Ground Agent path), triggered
    separately.
    """
    subgraph = await get_subgraph(abstraction_id)

    questions_by_entity: dict[str, list[QuestionNode]] = {}
    claims_by_question: dict[str, list[ClaimNode]] = {}
    for node in subgraph.nodes:
        questions = await get_questions_for_entity(node.id)
        questions_by_entity[node.id] = questions
        for question in questions:
            claims_by_question[question.id] = await get_claims_for_question(question.id)

    steps = order_roadmap_steps(
        nodes=subgraph.nodes,
        relationships=subgraph.relationships,
        questions_by_entity=questions_by_entity,
        claims_by_question=claims_by_question,
    )
    return Roadmap(
        abstraction_id=subgraph.abstraction.id,
        abstraction_name=subgraph.abstraction.name,
        steps=steps,
    )
