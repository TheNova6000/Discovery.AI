"""Phase 6 verification -- Roadmap Generator ordering logic (PRD.md §4a,
Phases.md Phase 6, backend/roadmap/ordering.py).

Deliberately scoped to pure logic: `order_roadmap_steps` and
`_compute_zoom_depths` are pure functions over already-fetched graph data
(GraphNode/Relationship/QuestionNode/ClaimNode -- all pydantic-only, no neo4j
package required), so they're testable here with hand-built fixtures and no
live Neo4j -- fast, deterministic, no external dependency. This script alone
only ever earns [BUILT] for the ordering logic, not end-to-end [VERIFIED];
`generator.generate_roadmap`'s own I/O shell (the `get_subgraph`/
`get_questions_for_entity`/`get_claims_for_question` calls) is intentionally
NOT exercised here.

The live path (Docker is NOT required -- a free Neo4j Aura instance works
fine, see README.md's "point at an existing Neo4j/Aura instance instead") was
run and passed 2026-09-16 (Architecture.md §0.39.2, docs/Memory.md): a real
`/chat` investigation, `backend.graph.interface.zoom_in()` to materialize an
`Abstraction`, `GET /roadmap?abstraction_id=...`, and `frontend/roadmap.html`
rendered in an actual browser -- all against real Neo4j data, no fixtures.
That session also found and fixed a real Windows Unicode-encoding crash bug
(backend/__init__.py) and found, but left open, a real gap: nothing in the
live app currently calls `zoom_in`, so a real user has no path to a working
`abstraction_id` yet (Phases.md Phase 6's "[GAP, found this session]" entry).

Five checks:
  1. Basic ordering matches PRD.md §4a: master-level before ground-level,
     then shallower zoom-chain depth before deeper, then a stable tiebreak.
  2. A pure cycle (no node reachable from an external root) still gets every
     node a depth, and `_compute_zoom_depths` terminates -- doesn't hang.
  3. A question attached to an entity outside the given `nodes` list is
     skipped, not invented a place for (bounded-view honesty, README's "never
     implies completeness").
  4. Determinism: running `order_roadmap_steps` twice on identical input
     produces identical output -- required for the Curriculum Compiler
     (Phase 9) to build deterministically on top of this later.
  5. An unrecognized `level` value degrades to the ground/later rank instead
     of raising.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph.models import GraphNode, QuestionNode, Relationship  # noqa: E402
from backend.roadmap.ordering import _compute_zoom_depths, order_roadmap_steps  # noqa: E402


def _node(node_id: str, name: str) -> GraphNode:
    return GraphNode(
        id=node_id,
        name=name,
        type="entity",
        created_at="2026-09-16T00:00:00Z",
        updated_at="2026-09-16T00:00:00Z",
    )


def _question(qid: str, text: str, level: str) -> QuestionNode:
    return QuestionNode(
        id=qid,
        text=text,
        dimension_id="scale",
        level=level,
        rationale="test fixture",
        created_at="2026-09-16T00:00:00Z",
    )


def check_basic_ordering() -> None:
    # A (root/depth 0) -> B (depth 1), A -> C (depth 1). A and B each have a
    # master + ground question; C only has a ground question.
    nodes = [_node("A", "Payment Platforms"), _node("B", "PayPal"), _node("C", "Stripe")]
    relationships = [
        Relationship(source_id="A", target_id="B", relationship_type="decomposes_into"),
        Relationship(source_id="A", target_id="C", relationship_type="decomposes_into"),
    ]
    questions_by_entity = {
        "A": [_question("qA_m", "How does the payments ecosystem fit together?", "master")],
        "B": [
            _question("qB_m", "How does PayPal fit into the ecosystem?", "master"),
            _question("qB_g", "How does PayPal process a single transaction?", "ground"),
        ],
        "C": [_question("qC_g", "How does Stripe process a single transaction?", "ground")],
    }
    steps = order_roadmap_steps(nodes, relationships, questions_by_entity)

    assert [s.question_id for s in steps] == ["qA_m", "qB_m", "qB_g", "qC_g"], (
        "expected all master-level questions (by depth) before all ground-level "
        f"questions (by depth); got {[s.question_id for s in steps]}"
    )
    assert steps[0].zoom_depth == 0 and steps[1].zoom_depth == 1
    print("[PASS] check_basic_ordering: master-before-ground, then zoom-chain depth, matches PRD.md section 4a")


def check_cycle_terminates_and_covers_every_node() -> None:
    nodes = [_node("X", "X"), _node("Y", "Y")]
    relationships = [
        Relationship(source_id="X", target_id="Y", relationship_type="depends_on"),
        Relationship(source_id="Y", target_id="X", relationship_type="depends_on"),
    ]
    depths = _compute_zoom_depths(nodes, relationships)  # would hang here if buggy
    assert set(depths.keys()) == {"X", "Y"}, f"expected both cycle members to get a depth, got {depths}"
    print(f"[PASS] check_cycle_terminates_and_covers_every_node: depths={depths}, no infinite loop")


def check_question_outside_subgraph_is_skipped() -> None:
    nodes = [_node("A", "Payment Platforms")]
    relationships: list[Relationship] = []
    questions_by_entity = {
        "A": [_question("qA_g", "real question", "ground")],
        "OUTSIDE": [_question("qOut_g", "orphaned question", "ground")],
    }
    steps = order_roadmap_steps(nodes, relationships, questions_by_entity)
    assert [s.question_id for s in steps] == ["qA_g"], (
        f"expected the orphaned entity's question to be silently skipped, got {[s.question_id for s in steps]}"
    )
    print("[PASS] check_question_outside_subgraph_is_skipped: bounded view stays honest, no invented placement")


def check_determinism() -> None:
    nodes = [_node("A", "A"), _node("B", "B")]
    relationships = [Relationship(source_id="A", target_id="B", relationship_type="decomposes_into")]
    questions_by_entity = {
        "A": [_question("qA_g", "a", "ground")],
        "B": [_question("qB_g", "b", "ground")],
    }
    first = order_roadmap_steps(nodes, relationships, questions_by_entity)
    second = order_roadmap_steps(nodes, relationships, questions_by_entity)
    assert [s.question_id for s in first] == [s.question_id for s in second]
    print("[PASS] check_determinism: identical input -> identical output, required for Phase 9's Curriculum Compiler")


def check_unrecognized_level_degrades_gracefully() -> None:
    nodes = [_node("A", "A")]
    relationships: list[Relationship] = []
    questions_by_entity = {"A": [_question("qA_x", "weird level", "unknown_level")]}
    steps = order_roadmap_steps(nodes, relationships, questions_by_entity)  # would raise here if buggy
    assert len(steps) == 1
    print("[PASS] check_unrecognized_level_degrades_gracefully: no crash on an unexpected level value")


if __name__ == "__main__":
    check_basic_ordering()
    check_cycle_terminates_and_covers_every_node()
    check_question_outside_subgraph_is_skipped()
    check_determinism()
    check_unrecognized_level_degrades_gracefully()
    print("\nAll 5 checks passed. This covers the ordering logic only -- the live end-to-end path")
    print("(real investigation -> real Neo4j -> /roadmap -> frontend) was separately run and passed")
    print("2026-09-16; see this file's module docstring and Architecture.md §0.39.2.")
