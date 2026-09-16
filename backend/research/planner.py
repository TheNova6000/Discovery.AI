from __future__ import annotations

from backend.agents.policy import ResearchPolicy
from backend.graph.interface import get_subgraph
from backend.graph.models import GraphNode

from .models import BASE_REQUIRED_FIELDS, REQUIRED_FIELD_POLICY_GATES, ConceptResearchTarget, ResearchPlan

# Phase 8.2 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.42):
# the Learning Research Planner. Deliberately scoped to planning only --
# "topic -> ResearchPlan -> concept targets -> required research fields ->
# completion requirements" stops at "required fields," this phase's actual
# deliverable. It does NOT perform deep investigation (Phase 8.4), call new
# retrievers (Phase 8.4), check whether a target's fields are actually FILLED
# yet (Phase 8.3's completeness model -- a different question from "which
# fields does this concept need"), or generate lessons/compile a curriculum
# (Phase 9/10). And -- the one place this phase's actual constraints changed
# the shape Phases.md originally sketched (see this module's own note in
# docs/Architecture.md §0.42) -- it never calls an LLM: a topic's required
# CONCEPT LIST is not invented here, only read from whatever's already been
# discovered by investigation (get_subgraph, same source generate_roadmap
# already reads -- Phase 6, Rules.md rule 14). "What concepts SHOULD exist
# for this topic that aren't in the graph yet" is a real, separate, LLM-shaped
# question this phase deliberately does not answer.


def _required_fields_for_policy(policy: ResearchPolicy) -> frozenset[str]:
    """Pure function: a policy's require_* flags -> the field set every
    concept target under that policy must cover. Same for every target in a
    given plan (it depends only on the policy, not per-concept data) --
    that's expected, not a bug: Phase 8.3's completeness model is what later
    checks whether a SPECIFIC concept's data actually satisfies these fields.
    """
    fields = set(BASE_REQUIRED_FIELDS)
    for field_name, policy_attr in REQUIRED_FIELD_POLICY_GATES.items():
        if getattr(policy, policy_attr):
            fields.add(field_name)
    return frozenset(fields)


def plan_targets(nodes: list[GraphNode], policy: ResearchPolicy) -> list[ConceptResearchTarget]:
    """The actual planning logic -- pure, no I/O, unit-tested directly
    (scripts/verify_phase8_2.py) without needing a live Neo4j, same split as
    backend/roadmap/generator.py's I/O shell around ordering.py's pure logic.
    One target per node, in the order given (stable -- `get_subgraph` already
    returns nodes in a consistent order; this function does not itself sort).
    """
    required_fields = _required_fields_for_policy(policy)
    return [
        ConceptResearchTarget(
            entity_id=node.id,
            entity_name=node.name,
            required_fields=required_fields,
        )
        for node in nodes
    ]


async def build_research_plan(abstraction_id: str, policy: ResearchPolicy) -> ResearchPlan:
    """I/O shell: fetch the abstraction's already-discovered subgraph, then
    hand it to the pure `plan_targets` above. Never calls an LLM or retriever
    (Rules.md rule 14, same constraint `generate_roadmap` already follows) --
    an abstraction with no members yet just produces an empty plan, not an
    error; that's a gap this surfaces by omission, the same honesty Phase 6's
    generator.py already documents for itself.
    """
    subgraph = await get_subgraph(abstraction_id)
    targets = plan_targets(subgraph.nodes, policy)
    return ResearchPlan(
        abstraction_id=subgraph.abstraction.id,
        abstraction_name=subgraph.abstraction.name,
        policy=policy,
        targets=targets,
    )
