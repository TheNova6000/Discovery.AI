from __future__ import annotations

from typing import Optional

from backend.agents import ClaimProvenance
from backend.graph.models import Subgraph
from backend.reasoning import Claim
from backend.research import ConceptCompleteness, ContradictionFinding, EvidenceReference, ResearchArtifact

from .models import ResearchResponse

# R5.2 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.73/§0.74): the pure projection compiler --
#
#     ResearchArtifact (Phase 8.6, the existing research-domain artifact)
#                             |
#                             v
#                   compile_research_response (this file)
#                             |
#                             v
#                   ResearchResponse (R5.1, the stable API projection)
#
# No new epistemic objects are created, no lifecycle transitions occur, no
# confidence gating occurs, no persistence occurs, no orchestration occurs.
# Deterministic and side-effect free: no Neo4j/LLM/retriever/HTTP call, no
# mutation of any input.
#
# A real, load-bearing finding from inspecting the actual repository before
# writing this, not assumed from the R5.2 prompt's own suggested shape:
# **`ResearchArtifact`/`ConceptResearchArtifact` do not embed real
# `reasoning.domain.Claim` objects at all.** They embed `EvidenceReference`
# (`backend/research/models.py`) -- a lightweight citation pointer
# (`claim_id`, `source_title`, `source_url`, `source_type`, `confidence`),
# with NO `normalized_form`/`entity_id`/`source_question_id`/`status`. A
# real `Claim` cannot be honestly constructed from an `EvidenceReference`
# alone -- doing so would mean fabricating `normalized_form` (from what?
# the source title? that would misrepresent a citation as if it were the
# claim's own asserted proposition, exactly the "RetrievalOutcome ->
# Claim" collapse this whole track exists to prevent, R1.1's own founding
# invariant). So `claims`/`subclaims` are populated ONLY from a real,
# already-mapped `list[Claim]` the CALLER supplies (e.g. produced
# elsewhere via R4.1's `claim_node_to_domain_claim`, run separately, out
# of this pure function's scope) -- never fabricated here. Omitted, they
# are honestly empty, not silently backed by manufactured claim content.
#
# The same real-vs-artifact-shape gap applies to `entities`/`relationships`
# (no `Subgraph` is embedded in `ResearchArtifact` either -- Phase 6's
# `get_subgraph` is a separate, live I/O call this pure function does not
# make) and to `provenance` (`trace_claim` requires a live SQLite
# agent-tree walk). Both are accepted as optional, already-fetched
# parameters for the same reason `claims` is -- reuse real data the caller
# already has, never fetch it here, never fabricate it absent.
#
# `evidence`, `coverage`, and `contradictions`, by contrast, ARE fully,
# honestly derivable directly from `ResearchArtifact` alone -- it already
# embeds real `EvidenceReference`/`ConceptResearchArtifact` (which carries
# the identical fields `ConceptCompleteness` has)/`ContradictionReport`
# objects. No external parameter is needed for these three.


def compile_research_response(
    artifact: ResearchArtifact,
    *,
    claims: Optional[list[Claim]] = None,
    subgraph: Optional[Subgraph] = None,
    provenance: Optional[list[ClaimProvenance]] = None,
) -> ResearchResponse:
    """Pure: compiles a real, already-assembled `ResearchArtifact` (Phase
    8.6) into a `ResearchResponse` (R5.1). Reuses this repository's own
    objects unchanged wherever a real one exists on the artifact;
    everything else stays at R5.1's own honest default rather than being
    guessed at here.

    `claims`/`subgraph`/`provenance` are optional, real, already-fetched
    data a caller may already have -- this function never calls Neo4j, an
    LLM, a retriever, or SQLite itself to obtain them. Omitting any of them
    is a legitimate, honest input, not an error.
    """
    status = "complete" if artifact.is_ready else "partially_complete"

    coverage: list[ConceptCompleteness] = [
        ConceptCompleteness(
            entity_id=concept.entity_id,
            entity_name=concept.entity_name,
            field_coverage=list(concept.field_coverage),
            is_complete=concept.is_complete,
            missing_fields=concept.missing_fields,
        )
        for concept in artifact.concepts
    ]

    evidence: list[EvidenceReference] = [ref for concept in artifact.concepts for ref in concept.evidence_refs]

    # Preserves Phase 8.5's own real distinction (ContradictionReport.checked
    # vs. concept.contradictions is None) rather than collapsing it: only a
    # concept that was ACTUALLY checked (checked=True) contributes findings.
    # A concept never checked, or checked-but-skipped, contributes none --
    # honestly, not because it had zero contradictions.
    contradictions: list[ContradictionFinding] = [
        finding
        for concept in artifact.concepts
        if concept.contradictions is not None and concept.contradictions.checked
        for finding in concept.contradictions.findings
    ]

    resolved_claims = list(claims) if claims is not None else []
    # R4.3: a subclaim is a Claim with parent_claim_id/relation_to_parent
    # set -- never a separate object, never a separate identity. Exactly
    # the filtered view the R5.2 spec itself requires, nothing more.
    resolved_subclaims = [c for c in resolved_claims if c.parent_claim_id is not None]

    entities = list(subgraph.nodes) if subgraph is not None else []
    relationships = list(subgraph.relationships) if subgraph is not None else []
    resolved_provenance = list(provenance) if provenance is not None else []

    return ResearchResponse(
        investigation_id=artifact.abstraction_id,
        status=status,
        root_entity_id=None,  # R5.1's own decision, unchanged here: no designated root exists in the current data model
        entities=entities,
        relationships=relationships,
        claims=resolved_claims,
        subclaims=resolved_subclaims,
        evidence=evidence,
        coverage=coverage,
        contradictions=contradictions,
        unresolved_tasks=[],  # MasterAgent.run_task_graph has zero callers in the live path (R3.2's own confirmed finding) -- no real producer to draw from, no parameter added for one that doesn't exist
        provenance=resolved_provenance,
    )
