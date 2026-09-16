from __future__ import annotations

from collections import deque

from backend.graph.models import ClaimNode, GraphNode, QuestionNode, Relationship

from .models import RoadmapStep

_LEVEL_RANK: dict[str, int] = {"master": 0, "ground": 1}
"""PRD.md §4a: master-level questions before ground-level questions. Anything
that isn't literally "master" sorts as if it were "ground" (rank 1) rather
than raising -- an unrecognized level is a real, if unexpected, input; this
function degrades it to the safer/later position instead of crashing the
whole Roadmap over one bad value (Rules.md §3's graceful-degradation spirit,
applied to a pure function instead of an external API call)."""


def _compute_zoom_depths(nodes: list[GraphNode], relationships: list[Relationship]) -> dict[str, int]:
    """BFS depth from every in-degree-0 node in this bounded subgraph (PRD.md
    §4a: "parent-abstraction questions before child-entity questions"). Edge
    direction follows `Relationship.source_id -> target_id`, the same
    outward-edge convention `get_decomposition`/`zoom_in` already use for
    parent->child discovery (backend/graph/interface.py's own note on why
    `get_neighbors`' directionless match is wrong for this).

    Multi-source BFS with a visited set terminates even when the subgraph
    contains a real cycle (this project's own mined world-model graph has
    found genuine cycles -- README) -- a node is never revisited, so a cycle
    can't loop the traversal. A pure cycle with no node reachable from any
    true root (every member has incoming edges only from inside the cycle)
    would otherwise never get a depth at all; the fallback below seeds any
    still-unvisited nodes at depth 0, in a stable (id-sorted) order so
    re-running this function on identical input always produces identical
    depths, then resumes BFS from them.
    """
    node_ids = {n.id for n in nodes}
    children: dict[str, list[str]] = {nid: [] for nid in node_ids}
    has_incoming: set[str] = set()
    for rel in relationships:
        if rel.source_id in node_ids and rel.target_id in node_ids:
            children[rel.source_id].append(rel.target_id)
            has_incoming.add(rel.target_id)

    depth: dict[str, int] = {}
    queue: deque[str] = deque()

    def _seed(nid: str) -> None:
        depth[nid] = 0
        queue.append(nid)

    def _bfs() -> None:
        while queue:
            current = queue.popleft()
            for child in children.get(current, []):
                if child not in depth:
                    depth[child] = depth[current] + 1
                    queue.append(child)

    for nid in sorted(node_ids):
        if nid not in has_incoming:
            _seed(nid)
    _bfs()

    for nid in sorted(node_ids - depth.keys()):
        if nid not in depth:
            _seed(nid)
            _bfs()

    return depth


def order_roadmap_steps(
    nodes: list[GraphNode],
    relationships: list[Relationship],
    questions_by_entity: dict[str, list[QuestionNode]],
    claims_by_question: dict[str, list[ClaimNode]] | None = None,
) -> list[RoadmapStep]:
    """The actual Roadmap Generator (PRD.md §4a). Deliberately a pure function
    over already-fetched graph data (`nodes`/`relationships` from one
    `get_subgraph` call, `questions_by_entity`/`claims_by_question` from
    `get_questions_for_entity`/`get_claims_for_question`) -- it never calls an
    LLM or a retriever itself (Rules.md rule 14). A question attached to an
    entity that isn't in `nodes` (outside this abstraction's own subgraph) is
    silently skipped, not invented a place for -- the Roadmap is a bounded view
    and stays honest about that (README's "never implies completeness"),
    exactly like the rest of this project's views already do.

    Ordering (PRD.md §4a, kept deliberately simple for v1): master-level
    questions before ground-level questions, then by zoom-chain position
    (shallower/parent entities before deeper/child entities), then a stable
    tiebreaker (entity id, then question id) so calling this twice on
    identical input always returns identical output -- required for the
    Curriculum Compiler (Architecture.md §6.3, Phase 9) to build deterministically
    on top of this later.
    """
    claims_by_question = claims_by_question or {}
    depths = _compute_zoom_depths(nodes, relationships)
    nodes_by_id = {n.id: n for n in nodes}

    steps: list[RoadmapStep] = []
    for entity_id, questions in questions_by_entity.items():
        entity = nodes_by_id.get(entity_id)
        if entity is None:
            continue
        for question in questions:
            steps.append(
                RoadmapStep(
                    entity_id=entity.id,
                    entity_name=entity.name,
                    question_id=question.id,
                    question_text=question.text,
                    question_rationale=question.rationale,
                    level=question.level,
                    zoom_depth=depths.get(entity.id, 0),
                    claims=claims_by_question.get(question.id, []),
                )
            )

    steps.sort(
        key=lambda s: (
            _LEVEL_RANK.get(s.level, 1),
            s.zoom_depth,
            s.entity_id,
            s.question_id,
        )
    )
    return steps
