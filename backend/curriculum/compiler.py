from __future__ import annotations

from backend.curriculum.models import Course, IncompleteConcept, Module
from backend.graph import Relationship
from backend.research_api import ResearchResponse

# Phase 9.1 (docs/Phases.md, docs/Rules.md rule 16): compile_course is PURE --
# it reads only the fields a real, already-compiled ResearchResponse (R5)
# carries, calls no LLM/retriever/Neo4j (rule 16's own restriction), and
# never fabricates ordering or content a concept doesn't actually have.
#
# Two real, honestly-recorded limitations (Architecture.md §0.76), not bugs:
#   1. No producer in this codebase creates relationship_type=="requires"
#      edges today (confirmed by direct inspection of every Relationship
#      producer: Phase 1's extraction pipeline, Phase 6's materialization,
#      Phase 8's investigation loop -- none assign "requires"). When such
#      edges exist, they are honored for real prerequisite ordering; when
#      they don't, modules fall back to ResearchResponse.coverage's own
#      order -- discovery order, not a fabricated teaching order.
#   2. A concept whose ConceptCompleteness.is_complete is False is never
#      compiled into a Module -- it is surfaced in incomplete_concepts
#      instead, per rule 16's "a concept missing a lesson or exercise is a
#      gap it surfaces, not one it fills inline."


class CourseCompilationError(Exception):
    """Raised for a real requires-cycle among modules. Mirrors
    reasoning.dag.validate_task_graph (R3.2) and
    reasoning.domain.validate_subclaim_graph (R4.3)'s own DFS
    cycle-detection pattern -- a cycle is surfaced as an error, never
    silently dropped or infinite-looped."""


def compile_course(response: ResearchResponse) -> Course:
    coverage_by_entity = {c.entity_id: c for c in response.coverage}

    claims_by_entity: dict[str, list] = {}
    for claim in response.claims:
        claims_by_entity.setdefault(claim.entity_id, []).append(claim)

    complete_ids = [eid for eid, c in coverage_by_entity.items() if c.is_complete]

    incomplete_concepts = [
        IncompleteConcept(
            entity_id=eid,
            entity_name=c.entity_name,
            missing_fields=frozenset(fc.field for fc in c.field_coverage if fc.status == "missing"),
        )
        for eid, c in coverage_by_entity.items()
        if not c.is_complete
    ]

    complete_id_set = set(complete_ids)
    requires_edges = [
        r
        for r in response.relationships
        if r.relationship_type == "requires" and r.source_id in complete_id_set and r.target_id in complete_id_set
    ]

    if requires_edges:
        ordered_ids = _topological_sort(complete_ids, requires_edges)
        ordered_by_prerequisites = True
    else:
        ordered_ids = list(complete_ids)
        ordered_by_prerequisites = False

    modules = [
        Module(
            entity_id=eid,
            entity_name=coverage_by_entity[eid].entity_name,
            claims=claims_by_entity.get(eid, []),
        )
        for eid in ordered_ids
    ]

    return Course(
        investigation_id=response.investigation_id,
        modules=modules,
        incomplete_concepts=incomplete_concepts,
        ordered_by_prerequisites=ordered_by_prerequisites,
    )


def _topological_sort(entity_ids: list[str], requires_edges: list[Relationship]) -> list[str]:
    """`source_id requires target_id` -- target_id (the prerequisite) is
    ordered before source_id (the dependent). Post-order DFS naturally
    yields a dependencies-first order, same technique as
    reasoning.dag.validate_task_graph / reasoning.domain.validate_subclaim_graph."""

    prerequisites: dict[str, list[str]] = {eid: [] for eid in entity_ids}
    for r in requires_edges:
        prerequisites[r.source_id].append(r.target_id)

    UNVISITED, IN_PROGRESS, DONE = 0, 1, 2
    state = {eid: UNVISITED for eid in entity_ids}
    order: list[str] = []

    def visit(eid: str, path: list[str]) -> None:
        state[eid] = IN_PROGRESS
        for dep in prerequisites.get(eid, []):
            if dep not in state:
                continue
            if state[dep] == IN_PROGRESS:
                cycle = path[path.index(dep):] + [dep]
                raise CourseCompilationError(f"requires-cycle detected: {' -> '.join(cycle)}")
            if state[dep] == UNVISITED:
                visit(dep, [*path, dep])
        state[eid] = DONE
        order.append(eid)

    for eid in entity_ids:
        if state[eid] == UNVISITED:
            visit(eid, [eid])

    return order
