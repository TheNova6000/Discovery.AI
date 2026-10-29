"""Live, un-mocked Discovery.AI run for HUMAN review (evaluate_* convention:
diagnostic output, not pass/fail).

Runs one real GroundAgent investigation (real LLM chain, real retrievers, real
Neo4j writes), then projects it through the real Research API
(`materialize_abstraction` -> `fetch_and_compile_research_response`) and
prints every layer so a person can judge which outputs are right:

  1. the agent's own decision trace (printed by GroundAgent itself)
  2. the GroundResult tree: answer / confidence / status / boundary per node
  3. every evidence claim with its real source (title, URL, role, confidence)
  4. what was persisted to the graph (decomposition read back from Neo4j)
  5. the final ResearchResponse (status, entities, relationships, claims,
     coverage, contradictions)

Usage: python scripts/evaluate_discovery_live.py "Binary search tree" ["question text"]
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import textwrap
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.main_block.reasoning_engine.agents.ground_agent import GroundAgent  # noqa: E402
from backend.main_block.reasoning_engine.agents.models import GroundResult  # noqa: E402
from backend.main_block.reasoning_engine.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.main_block.reasoning_engine.graph import close_driver, find_or_create_entity, get_decomposition_typed, materialize_abstraction  # noqa: E402
from backend.main_block.reasoning_engine.llm_steps.models import Question, QuestionLevel  # noqa: E402
from backend.main_block.reasoning_engine.research_api.service import fetch_and_compile_research_response  # noqa: E402


def _wrap(text: str | None, indent: str) -> str:
    if not text:
        return f"{indent}(none)"
    return textwrap.fill(" ".join(text.split()), width=110, initial_indent=indent, subsequent_indent=indent)


def _print_tree(result: GroundResult, depth: int = 0) -> int:
    pad = "  " * depth
    conf = f"{result.confidence:.2f}" if result.confidence is not None else "n/a"
    print(f"{pad}- node depth={depth} status={result.status} self-confidence={conf} claims={len(result.claims)}")
    if result.boundary_reason:
        print(_wrap(f"boundary: {result.boundary_reason}", pad + "    "))
    g = result.grounding
    if g is not None:
        label = "GROUNDED" if g.answer.grounded else "NOT GROUNDED (model memory only)"
        print(f"{pad}    [{label}] cited={len(g.answer.claim_ids)} citations_verified={g.citations_verified} "
              f"support={g.support_ratio} note={g.note!r}")
        if g.evidence_gaps:
            print(_wrap(f"evidence gaps: {g.evidence_gaps}", pad + "    "))
        if g.unsupported_statements:
            print(_wrap(f"unsupported statements: {g.unsupported_statements}", pad + "    "))
    print(_wrap(f"answer: {result.answer}", pad + "    "))
    if g is not None and g.answer.grounded and g.draft_answer:
        print(_wrap(f"(memory draft, not used: {g.draft_answer[:300]})", pad + "    "))
    count = 1
    for child in result.child_results:
        count += _print_tree(child, depth + 1)
    return count


def _collect_claims(result: GroundResult) -> list:
    claims = list(result.claims)
    for child in result.child_results:
        claims.extend(_collect_claims(child))
    return claims


async def main(topic: str, question_text: str) -> None:
    started = time.time()
    print(f"=== TOPIC: {topic}\n=== QUESTION: {question_text}\n")
    entity = await find_or_create_entity(topic)
    question = Question(
        text=question_text,
        rationale="Live human-review run (scripts/evaluate_discovery_live.py).",
        dimension_id="none",
        level=QuestionLevel.MASTER,
        entity_name=topic,
        abstraction_name=topic,
    )

    print("=== 1. AGENT DECISION TRACE (live)\n")
    agent = GroundAgent(question, gather_evidence=True, persist_to_graph=True, policy=EXPLORATORY_POLICY)
    result = await agent.run()
    print(f"\n[investigation took {time.time() - started:.0f}s]\n")

    print("=== 2. RESULT TREE\n")
    nodes = _print_tree(result)
    print(f"\n[{nodes} agent node(s)]\n")

    print("=== 3. EVIDENCE CLAIMS\n")
    claims = _collect_claims(result)
    for i, claim in enumerate(sorted(claims, key=lambda c: -c.confidence), 1):
        src = claim.source
        print(f"[{i}] confidence={claim.confidence:.2f} role={src.source_role} type={src.source_type} content={src.content_kind}")
        print(f"    source: {src.title}\n    url:    {src.url}")
        print(_wrap(f"evidence: {claim.evidence}", "    "))
        print(_wrap(f"reasoning: {claim.reasoning}", "    "))
        print()
    if not claims:
        print("(no claims)\n")

    print("=== 4. GRAPH (read back from Neo4j)\n")
    frontier, seen = [entity], {entity.id}
    for depth in range(3):
        next_frontier = []
        for node in frontier:
            for rel_type, child in await get_decomposition_typed(node.id):
                print(f"{'  ' * depth}{node.name} --{rel_type}--> {child.name}")
                if child.id not in seen:
                    seen.add(child.id)
                    next_frontier.append(child)
        frontier = next_frontier
    print()

    print("=== 5. RESEARCH API RESPONSE (what clients like Tuni'n consume)\n")
    abstraction = await materialize_abstraction(entity.id)
    if abstraction is None:
        print("materialize_abstraction returned None -- no decomposition was persisted, /research would 400.")
    else:
        response = await fetch_and_compile_research_response(abstraction.id, EXPLORATORY_POLICY)
        data = response.model_dump()
        print(f"status: {data['status']}   investigation_id: {data['investigation_id']}")
        print(f"entities: {[e.get('name') for e in data['entities']]}")
        print(f"relationships: {len(data['relationships'])}   claims: {len(data['claims'])}   subclaims: {len(data['subclaims'])}")
        for key in ("coverage", "contradictions", "unresolved_tasks"):
            if key in data:
                value = data[key]
                print(f"{key}: {value if len(str(value)) < 1500 else str(value)[:1500] + ' ...'}")
    print(f"\n[total {time.time() - started:.0f}s]")
    await close_driver()


if __name__ == "__main__":
    topic_arg = sys.argv[1] if len(sys.argv) > 1 else "Binary search tree"
    question_arg = sys.argv[2] if len(sys.argv) > 2 else f"What is a {topic_arg.lower()}, how does it work, and what are its main operations and their costs?"
    asyncio.run(main(topic_arg, question_arg))
