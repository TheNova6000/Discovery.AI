from __future__ import annotations

from backend.agents.policy import ResearchPolicy
from backend.graph import get_claims_for_question, get_questions_for_entity, get_subgraph
from backend.reasoning import Claim
from backend.research import ClaimMappingRejected, claim_node_to_domain_claim, compile_research_artifact

from .compiler import compile_research_response
from .models import ResearchResponse

# R5.3 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.75): the I/O shell around R5.2's pure compile_research_response --
# fetches everything the pure logic needs from Neo4j, then hands off. The
# same "I/O shell wraps pure logic" split every phase in this track uses
# (R1.2's gather_evidence_with_outcomes, Phase 8.2's build_research_plan,
# Phase 8.6's compile_research_artifact itself).
#
# Deliberately re-fetches claims independently rather than modifying
# compile_research_artifact (Phase 8.6, already tested/working) to also
# return its own internal claims_by_entity -- a small, redundant I/O cost,
# not a change to already-completed, working code.
#
# Deliberately does NOT fetch provenance (trace_claim's own separate SQLite
# agent-tree walk) in this first real route pass -- a real, stated
# deferral: doing it for every claim on every request has a real,
# unmeasured cost this slice doesn't have data to justify yet, and R5.2's
# own pure compiler already handles an omitted `provenance` honestly (stays
# empty, never fabricated). A future slice can add it once there's a real
# reason to pay that cost on every request rather than speculatively now.


async def fetch_and_compile_research_response(abstraction_id: str, policy: ResearchPolicy) -> ResearchResponse:
    """Fetches the real `ResearchArtifact` (Phase 8.6), each concept's real
    claims (mapped through R4.1's `claim_node_to_domain_claim`, the same
    (claim, question_id) tuple-tracking pattern R1.3 established), and the
    abstraction's real `Subgraph` (Phase 1) -- then compiles them via R5.2's
    pure `compile_research_response`. Raises `GraphInterfaceError` (from
    `compile_research_artifact`/`get_subgraph`) if `abstraction_id` doesn't
    exist -- the same client-error shape every other route in this
    codebase already surfaces as a 404, not swallowed here.
    """
    artifact = await compile_research_artifact(abstraction_id, policy)

    claims: list[Claim] = []
    for concept in artifact.concepts:
        questions = await get_questions_for_entity(concept.entity_id)
        for question in questions:
            for node in await get_claims_for_question(question.id):
                try:
                    claims.append(claim_node_to_domain_claim(node, entity_id=concept.entity_id, source_question_id=question.id))
                except ClaimMappingRejected:
                    # A real, malformed legacy claim (e.g. empty evidence
                    # text) -- skip it rather than fail the whole request;
                    # R4.1's own mapper already rejects it for a real,
                    # stated reason, not an error in this service.
                    continue

    subgraph = await get_subgraph(abstraction_id)

    return compile_research_response(artifact, claims=claims, subgraph=subgraph)
