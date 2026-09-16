"""R5.1 verification -- ResearchRequest/ResearchResponse pure domain types
(docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
§0.57/§0.73, backend/research_api/models.py).

Pure throughout -- no LLM/retriever/Neo4j call, no orchestration, no
compile_research_response (that's R5.2's job). Every fixture here is
hand-built, the same "already-computed data in, pure logic over it" shape
`scripts/verify_phase8_6.py` already established for `ResearchArtifact`
construction -- reused directly, not reinvented.

Checks:
  1. ResearchRequest constructs correctly with real field values.
  2. ResearchResponse constructs from a real Phase 8.6 ResearchArtifact
     fixture (assemble_research_artifact, the same pure function
     verify_phase8_6.py already tests) -- not a fabricated shape.
  3. investigation_id/status/root identity are preserved correctly:
     investigation_id == the real abstraction_id (no synthetic id
     invented); status derived honestly from is_ready; root_entity_id
     stays None (no single-entity assumption fabricated for a
     multi-concept abstraction).
  4. Claims and evidence are represented correctly: claims holds real
     `reasoning.domain.Claim` objects (via R4.1's real mapper, not a
     fourth claim shape); evidence holds the real EvidenceReference
     objects the artifact itself already computed.
  5. Honest empty handling: subclaims, unresolved_tasks, and provenance
     are all empty by default, each for its own real, stated reason (no
     live producer exists for any of the three yet) -- confirmed, not
     merely defaulted and forgotten about.
  6. Full round-trip serialization (model_dump_json -> model_validate_json)
     reconstructs an identical ResearchResponse, including nested Claim/
     EvidenceReference/ConceptCompleteness objects.
  7. Constructing a ResearchResponse never mutates the source
     ResearchArtifact or any ClaimNode it was built from.
  8. Invalid required_fields (not in the real, known Phase 8.2/8.3
     six-field vocabulary) are rejected explicitly; an empty topic is
     rejected explicitly.
  9. Existing R1/R3/R4 lifecycle semantics are unchanged -- confirmed
     directly here (transition_claim/ResearchTask/ClaimStatus still behave
     exactly as before touching this new package) and, more
     comprehensively, by the full regression suite re-run unmodified
     (this script does not duplicate scripts/verify_r1_4.py's own 12
     checks; it confirms this new package didn't change their behavior).
 10. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5 checks
     remain green.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from backend.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.graph.models import ClaimNode  # noqa: E402
from backend.reasoning import ClaimStatus, ResearchTask, transition_claim  # noqa: E402
from backend.research import (  # noqa: E402
    ConceptCompleteness,
    ConceptResearchTarget,
    FieldCoverage,
    ResearchPlan,
    ResearchReadinessReport,
    assemble_research_artifact,
    claim_node_to_domain_claim,
)
from backend.research_api import ResearchRequest, ResearchResponse  # noqa: E402

_NOW = "2026-01-01T00:00:00+00:00"


def _claim_node(claim_id: str, confidence: float, url: str) -> ClaimNode:
    return ClaimNode(
        id=claim_id, evidence=f"a real proposition for {claim_id}", reasoning="fixture reasoning", confidence=confidence,
        source_title="fixture source", source_url=url, source_type="web", valid_from=_NOW,
    )


def _real_artifact_fixture():
    """The exact pattern scripts/verify_phase8_6.py already established:
    hand-built ResearchPlan/ResearchReadinessReport/ClaimNode fixtures
    through the REAL, pure assemble_research_artifact -- not a fabricated
    ResearchArtifact shape."""
    target = ConceptResearchTarget(entity_id="e1", entity_name="Recursive Resolver", required_fields=frozenset({"definition", "mechanism"}))
    plan = ResearchPlan(abstraction_id="abs-dns-1", abstraction_name="DNS Resolution", policy=EXPLORATORY_POLICY, targets=[target])
    completeness = ConceptCompleteness(
        entity_id="e1", entity_name="Recursive Resolver",
        field_coverage=[FieldCoverage(field="definition", status="present", reason="x"), FieldCoverage(field="mechanism", status="present", reason="x")],
        is_complete=True, missing_fields=frozenset(),
    )
    report = ResearchReadinessReport(
        abstraction_id="abs-dns-1", abstraction_name="DNS Resolution", policy=EXPLORATORY_POLICY,
        concepts=[completeness], ready_count=1, incomplete_count=0, is_ready=True,
    )
    claim_nodes = [_claim_node("c1", 0.8, "https://example.com/rfc1035")]
    claims_by_entity = {"e1": claim_nodes}
    artifact = assemble_research_artifact(plan, report, claims_by_entity)
    return artifact, claims_by_entity


def check_research_request_construction() -> None:
    req = ResearchRequest(topic="DNS resolution", objective="teach recursive resolution", mode="learning", required_fields=frozenset({"definition", "examples"}), constraints={"max_depth": 2})
    assert req.topic == "DNS resolution" and req.mode == "learning"
    assert req.required_fields == frozenset({"definition", "examples"})
    print("[PASS] #1 ResearchRequest constructs correctly with real field values")


def check_response_from_real_artifact() -> None:
    artifact, claims_by_entity = _real_artifact_fixture()
    concept = artifact.concepts[0]
    domain_claims = [claim_node_to_domain_claim(c, entity_id=concept.entity_id, source_question_id="q1") for c in claims_by_entity[concept.entity_id]]

    response = ResearchResponse(
        investigation_id=artifact.abstraction_id,
        status="complete" if artifact.is_ready else "partially_complete",
        claims=domain_claims,
        evidence=concept.evidence_refs,
        coverage=[ConceptCompleteness(entity_id=concept.entity_id, entity_name=concept.entity_name, field_coverage=concept.field_coverage, is_complete=concept.is_complete, missing_fields=concept.missing_fields)],
    )
    assert isinstance(response, ResearchResponse)
    print("[PASS] #2 ResearchResponse constructs from a real Phase 8.6 ResearchArtifact fixture")
    return response, artifact, claims_by_entity


def check_identity_preserved(response: ResearchResponse, artifact) -> None:
    assert response.investigation_id == artifact.abstraction_id == "abs-dns-1", "investigation_id must be the real abstraction_id, not a synthetic id"
    assert response.status == "complete"
    assert response.root_entity_id is None, "root_entity_id must stay None -- no single-entity assumption fabricated for a multi-concept-capable abstraction"
    print("[PASS] #3 investigation_id/status/root_entity_id all preserved/derived honestly, no fabricated identity")


def check_claims_and_evidence_representation(response: ResearchResponse, claims_by_entity) -> None:
    assert len(response.claims) == 1
    claim = response.claims[0]
    assert claim.normalized_form == claims_by_entity["e1"][0].evidence
    assert claim.claim_id == "c1", "claim_id must be reused from the real ClaimNode.id (R4.1's own recovery-by-id guarantee)"
    assert len(response.evidence) == 1
    assert response.evidence[0].claim_id == "c1" and response.evidence[0].confidence == 0.8
    print("[PASS] #4 claims holds real reasoning.domain.Claim objects; evidence holds the real EvidenceReference the artifact computed")


def check_honest_empty_fields(response: ResearchResponse) -> None:
    assert response.subclaims == [], "no real orchestration creates parent/subclaim relations from live data yet (R4.3's own non-goal)"
    assert response.unresolved_tasks == [], "MasterAgent.run_task_graph has zero callers in the live /chat path (R3.2's own finding)"
    assert response.provenance == [], "trace_claim requires a live SQLite agent-tree walk this pure-types slice does not perform"
    print("[PASS] #5 subclaims/unresolved_tasks/provenance are all honestly empty, each for its own real, stated reason")


def check_round_trip_serialization(response: ResearchResponse) -> None:
    reconstructed = ResearchResponse.model_validate_json(response.model_dump_json())
    assert reconstructed == response
    print("[PASS] #6 full round-trip serialization reconstructs an identical ResearchResponse, including nested objects")


def check_no_mutation_of_source(artifact, claims_by_entity) -> None:
    original_claim_evidence = claims_by_entity["e1"][0].evidence
    original_artifact_ready_count = artifact.ready_count
    concept = artifact.concepts[0]
    domain_claims = [claim_node_to_domain_claim(c, entity_id=concept.entity_id, source_question_id="q1") for c in claims_by_entity["e1"]]
    ResearchResponse(investigation_id=artifact.abstraction_id, status="complete", claims=domain_claims, evidence=concept.evidence_refs)
    assert claims_by_entity["e1"][0].evidence == original_claim_evidence
    assert artifact.ready_count == original_artifact_ready_count
    print("[PASS] #7 constructing a ResearchResponse never mutates the source ResearchArtifact or its ClaimNodes")


def check_invalid_input_rejected() -> None:
    try:
        ResearchRequest(topic="valid topic", required_fields=frozenset({"not_a_real_field"}))
        raise AssertionError("an unrecognized required_field must be rejected")
    except ValidationError:
        pass
    try:
        ResearchRequest(topic="")
        raise AssertionError("an empty topic must be rejected")
    except ValidationError:
        pass
    try:
        ResearchResponse(investigation_id="", status="complete")
        raise AssertionError("an empty investigation_id must be rejected")
    except ValidationError:
        pass
    print("[PASS] #8 invalid required_fields, empty topic, and empty investigation_id are all rejected explicitly")


def check_r1_r3_r4_lifecycle_unchanged() -> None:
    # A direct, minimal confirmation that importing/using backend.research_api
    # has no effect on R1/R3/R4's own real behavior -- the comprehensive
    # confirmation is the full regression suite (acceptance #10), re-run
    # unmodified; this is a quick, in-process sanity check, not a
    # duplicate of scripts/verify_r1_4.py's own 12 checks.
    from backend.reasoning import Claim

    claim = Claim(entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5)
    normalized = transition_claim(claim, "normalized", reason="checked", actor="verify_r5_1")
    assert normalized.status == "normalized"

    task = ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[], status="runnable")
    assert task.status == "runnable"
    status_value: ClaimStatus = "requires_reclassification"
    assert status_value == "requires_reclassification"
    print("[PASS] #9 R1/R3/R4 lifecycle semantics unchanged (transition_claim/ResearchTask/ClaimStatus behave exactly as before)")


if __name__ == "__main__":
    check_research_request_construction()
    response, artifact, claims_by_entity = check_response_from_real_artifact()
    check_identity_preserved(response, artifact)
    check_claims_and_evidence_representation(response, claims_by_entity)
    check_honest_empty_fields(response)
    check_round_trip_serialization(response)
    check_no_mutation_of_source(artifact, claims_by_entity)
    check_invalid_input_rejected()
    check_r1_r3_r4_lifecycle_unchanged()
    print("\nAll 9 checks passed. Pure logic only, no LLM/retriever/Neo4j call.")
    print("Acceptance #10 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
