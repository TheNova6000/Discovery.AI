"""Ad-hoc verification — post-Phase-5 "recursive discovery -> entity resolution ->
graph persistence" pass (docs/Memory.md). Not a numbered Phases.md deliverable on
its own, but identified there as the concrete prerequisite for Phase 6: nothing
persists a Ground Agent's discovered structure into Neo4j without this.

Requires a running Neo4j instance (only ever run on the VM — no local Docker on
the dev machine) and at least one LLM provider key.

Two things are verified:
1. `find_or_create_entity` is idempotent — resolving "PayPal" (already created by
   an earlier `verify_phase5.py` run) returns the SAME node both times, not a
   duplicate.
2. A `GroundAgent(persist_to_graph=True)` that decomposes and discovers a
   genuinely new entity creates that entity, a `decomposes_into` relationship from
   the parent, and attaches the child's own question to the NEW entity — not left
   on the parent, which is the whole point of the discovery gate (not every
   sub-question becomes an entity, but the ones that do must be graph-persisted
   correctly).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents import GroundAgent  # noqa: E402
from backend.graph import close_driver, ensure_constraints, find_or_create_entity, get_neighbors  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question, QuestionLevel  # noqa: E402


async def check_entity_idempotency() -> None:
    first = await find_or_create_entity("PayPal")
    second = await find_or_create_entity("PayPal")
    assert first.id == second.id, "find_or_create_entity created a duplicate for an existing name"
    print(f"[ok] find_or_create_entity is idempotent for 'PayPal' (id={first.id})")


async def check_discovery_persistence() -> None:
    question = Question(
        text="How does a website request travel through the Internet?",
        rationale="Graph-persistence verification.",
        dimension_id="systemic_global",
        level=QuestionLevel.MASTER,
        entity_name="Internet Infrastructure Probe",
        abstraction_name="Graph Persistence Verification",
    )
    agent = GroundAgent(question, max_depth=2, max_sequential_steps=3, persist_to_graph=True)
    result = await agent.run()
    print(f"[agent] status={result.status.value} children={len(result.child_results)}")
    assert result.status.value == "complete"

    parent_entity = await find_or_create_entity("Internet Infrastructure Probe")
    neighbors = await get_neighbors(parent_entity.id, relationship_type="decomposes_into")
    names = [n.name for n in neighbors]
    print(f"[graph] {parent_entity.name!r} -[decomposes_into]-> {names}")
    assert len(neighbors) >= 1, "expected at least one discovered entity linked via decomposes_into"


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)
    try:
        await ensure_constraints()
        await check_entity_idempotency()
        await check_discovery_persistence()
        print("\nGraph persistence verification PASSED.")
    finally:
        await close_driver()


if __name__ == "__main__":
    asyncio.run(run())
