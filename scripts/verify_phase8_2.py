"""Phase 8.2 verification -- Learning Research Planner, planning logic only
(docs/Phases.md Phase 8.2, docs/PRD.md §9.3a, docs/Architecture.md §0.42,
backend/research/planner.py).

Same split as Phase 6's scripts/verify_phase6.py and Phase 8.1's
scripts/verify_phase8_1.py: `plan_targets` is a pure function over
already-fetched graph data (GraphNode -- pydantic-only, no neo4j package
required) and a ResearchPolicy (Phase 8.1, also pydantic/dataclass-only), so
it's testable here with hand-built fixtures and zero LLM/retriever/Neo4j
calls. `planner.build_research_plan`'s own I/O shell (the `get_subgraph`
call) is NOT exercised by this script, same scoping note Phase 6's own
verify script made for itself.

Five checks:
  1. EXPLORATORY_POLICY (every require_* flag False) produces the base
     required-field set only: {"definition", "mechanism"}.
  2. A "learning"-shaped policy with every require_* flag True produces all
     six fields -- the four gated ones plus the two unconditional base ones.
  3. One target is produced per input node, with entity_id/entity_name
     carried through unchanged (not reshaped, not dropped).
  4. Determinism: calling plan_targets twice on identical input produces
     identical output -- required for whatever Phase 8.4 builds on top of
     this to behave predictably.
  5. An empty node list produces an empty plan, not an error -- bounded-view
     honesty, the same principle Phase 6's ordering.py already holds to for
     a question attached to an entity outside the given subgraph.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents.policy import EXPLORATORY_POLICY, ResearchPolicy  # noqa: E402
from backend.graph.models import GraphNode  # noqa: E402
from backend.research import plan_targets  # noqa: E402

_NOW = "2026-01-01T00:00:00+00:00"


def _node(node_id: str, name: str) -> GraphNode:
    return GraphNode(id=node_id, name=name, type="entity", created_at=_NOW, updated_at=_NOW)


_LEARNING_POLICY = ResearchPolicy(
    mode="learning",
    max_depth=2,
    max_sequential_steps=3,
    gather_evidence=True,
    max_results_per_retriever=2,
    require_prerequisites=True,
    require_examples=True,
    require_misconceptions=True,
    require_evidence_validation=True,
    confidence_threshold=0.8,
)


def check_exploratory_policy_yields_base_fields_only() -> None:
    targets = plan_targets([_node("e1", "Pointers")], EXPLORATORY_POLICY)
    assert len(targets) == 1
    assert targets[0].required_fields == frozenset({"definition", "mechanism"})
    print("[PASS] check_exploratory_policy_yields_base_fields_only: exploratory -> {definition, mechanism} only")


def check_learning_policy_yields_all_six_fields() -> None:
    targets = plan_targets([_node("e1", "Pointers")], _LEARNING_POLICY)
    assert targets[0].required_fields == frozenset(
        {"definition", "mechanism", "prerequisites", "examples", "misconceptions", "evidence"}
    )
    print("[PASS] check_learning_policy_yields_all_six_fields: every require_* flag True -> all six fields present")


def check_one_target_per_node_identity_preserved() -> None:
    nodes = [_node("e1", "Pointers"), _node("e2", "References"), _node("e3", "Dynamic Allocation")]
    targets = plan_targets(nodes, EXPLORATORY_POLICY)
    assert len(targets) == 3
    assert [t.entity_id for t in targets] == ["e1", "e2", "e3"]
    assert [t.entity_name for t in targets] == ["Pointers", "References", "Dynamic Allocation"]
    print("[PASS] check_one_target_per_node_identity_preserved: 3 nodes -> 3 targets, ids/names carried through unchanged")


def check_determinism() -> None:
    nodes = [_node("e1", "Pointers"), _node("e2", "References")]
    first = plan_targets(nodes, _LEARNING_POLICY)
    second = plan_targets(nodes, _LEARNING_POLICY)
    assert [(t.entity_id, t.required_fields) for t in first] == [(t.entity_id, t.required_fields) for t in second]
    print("[PASS] check_determinism: identical input -> identical output")


def check_empty_subgraph_yields_empty_plan_not_error() -> None:
    targets = plan_targets([], EXPLORATORY_POLICY)
    assert targets == []
    print("[PASS] check_empty_subgraph_yields_empty_plan_not_error: no nodes -> empty target list, no exception")


if __name__ == "__main__":
    check_exploratory_policy_yields_base_fields_only()
    check_learning_policy_yields_all_six_fields()
    check_one_target_per_node_identity_preserved()
    check_determinism()
    check_empty_subgraph_yields_empty_plan_not_error()
    print("\nAll 5 checks passed. This covers plan_targets' pure logic only -- no LLM,")
    print("retriever, or Neo4j call was made. build_research_plan's own I/O shell (the")
    print("get_subgraph call) is not exercised here, same scoping as verify_phase6.py.")
