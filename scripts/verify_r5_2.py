"""R5.2 verification -- compile_research_response, the pure projection
compiler (docs/Phases.md's Reasoning Engine Evolution track,
docs/Architecture.md §0.74, backend/research_api/compiler.py).

Pure throughout -- no LLM/retriever/Neo4j/HTTP call, no orchestration, no
lifecycle transitions, no confidence gating, no persistence, no new
epistemic objects. Every fixture is hand-built, reusing
scripts/verify_phase8_6.py's own established assemble_research_artifact
fixture pattern.

A real, load-bearing finding this slice's own design confirmed by direct
inspection, not assumed from the R5.2 prompt's suggested shape:
ResearchArtifact/ConceptResearchArtifact embed no real Claim objects, only
EvidenceReference citation pointers -- claims/subgraph/provenance are
therefore optional, caller-supplied parameters (real, already-fetched
data), never fabricated from the artifact alone. Every test below reflects
this: "claim identity/lifecycle preservation" checks supply real Claim
objects explicitly, since the compiler has nothing to preserve when none
are given.

Checks:
  1. Minimal artifact (zero concepts, zero claims supplied): compiles
     successfully, preserves investigation_id, invents nothing.
  2. Real Phase 8.6 fixture: compiles successfully, preserves investigation
     identity, evidence, and coverage directly from the artifact.
  3. Subclaim projection: a parent Claim and a child Claim (parent_claim_id
     set) both appear in `claims`; only the child appears in `subclaims`;
     the exact same object (identity, not a copy) is referenced in both.
  4. Lifecycle preservation: rejected/superseded/duplicate/
     legacy_invalid_claim/disputed claims all retain their exact status
     when supplied -- the compiler never reclassifies, filters, or
     deduplicates them.
  5. Unavailable data stays honest: root_entity_id is None,
     unresolved_tasks is empty, provenance is empty when not supplied --
     never fabricated, never silently populated with invented structure.
  6. Serialization: the compiled response round-trips through
     model_dump_json/model_validate_json unchanged, including nested
     Claim/EvidenceReference/ConceptCompleteness objects.
  7. No mutation: the source ResearchArtifact, its ConceptResearchArtifact
     entries, and every supplied Claim are all unchanged after compiling
     once and twice.
  8. Determinism: compiling the same artifact+claims twice produces
     equivalent (==) responses, same ordering, same content.
  9. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1
     checks remain green.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.graph.models import ClaimNode  # noqa: E402
from backend.reasoning import Claim, transition_claim  # noqa: E402
from backend.research import (  # noqa: E402
    ConceptCompleteness,
    ConceptResearchTarget,
    ContradictionFinding,
    ContradictionReport,
    FieldCoverage,
    ResearchPlan,
    ResearchReadinessReport,
    assemble_research_artifact,
)
from backend.research_api import ResearchResponse, compile_research_response  # noqa: E402

_NOW = "2026-01-01T00:00:00+00:00"


def _claim_node(claim_id: str, confidence: float = 0.7) -> ClaimNode:
    return ClaimNode(
        id=claim_id, evidence=f"a real proposition for {claim_id}", reasoning="fixture reasoning", confidence=confidence,
        source_title="fixture source", source_url=f"https://example.com/{claim_id}", source_type="web", valid_from=_NOW,
    )


def _minimal_artifact():
    plan = ResearchPlan(abstraction_id="abs-empty", abstraction_name="Empty Abstraction", policy=EXPLORATORY_POLICY, targets=[])
    report = ResearchReadinessReport(abstraction_id="abs-empty", abstraction_name="Empty Abstraction", policy=EXPLORATORY_POLICY, concepts=[], ready_count=0, incomplete_count=0, is_ready=True)
    return assemble_research_artifact(plan, report, {})


def _real_fixture(with_contradictions: bool = False):
    target = ConceptResearchTarget(entity_id="e1", entity_name="Recursive Resolver", required_fields=frozenset({"definition", "mechanism"}))
    plan = ResearchPlan(abstraction_id="abs-dns-1", abstraction_name="DNS Resolution", policy=EXPLORATORY_POLICY, targets=[target])
    completeness = ConceptCompleteness(
        entity_id="e1", entity_name="Recursive Resolver",
        field_coverage=[FieldCoverage(field="definition", status="present", reason="x"), FieldCoverage(field="mechanism", status="present", reason="x")],
        is_complete=True, missing_fields=frozenset(),
    )
    report = ResearchReadinessReport(abstraction_id="abs-dns-1", abstraction_name="DNS Resolution", policy=EXPLORATORY_POLICY, concepts=[completeness], ready_count=1, incomplete_count=0, is_ready=True)
    node = _claim_node("c1", 0.8)
    claims_by_entity = {"e1": [node]}
    contradiction_reports = None
    if with_contradictions:
        finding = ContradictionFinding(claim_id_a="c1", claim_id_b="c2", reasoning="fixture contradiction", confidence=0.6)
        contradiction_reports = {"e1": ContradictionReport(entity_id="e1", entity_name="Recursive Resolver", checked=True, findings=[finding])}
    artifact = assemble_research_artifact(plan, report, claims_by_entity, contradiction_reports_by_entity=contradiction_reports)
    return artifact, claims_by_entity


def check_minimal_artifact() -> None:
    artifact = _minimal_artifact()
    response = compile_research_response(artifact)
    assert response.investigation_id == "abs-empty"
    assert response.claims == [] and response.evidence == [] and response.coverage == []
    assert response.root_entity_id is None and response.unresolved_tasks == [] and response.provenance == []
    print("[PASS] #1 a minimal (zero-concept) artifact compiles successfully, preserves identity, invents nothing")


def check_real_fixture_compiles() -> None:
    artifact, claims_by_entity = _real_fixture()
    response = compile_research_response(artifact)
    assert response.investigation_id == artifact.abstraction_id == "abs-dns-1"
    assert len(response.evidence) == 1 and response.evidence[0].claim_id == "c1"
    assert len(response.coverage) == 1 and response.coverage[0].is_complete is True
    assert response.claims == [], "claims must stay empty when the caller supplies none -- never fabricated from EvidenceReference alone"
    print("[PASS] #2 the real Phase 8.6 fixture compiles successfully, preserving investigation identity, evidence, and coverage directly from the artifact")


def check_subclaim_projection() -> None:
    artifact = _minimal_artifact_with_one_target()
    parent = Claim(claim_id="parent1", entity_id="e1", normalized_form="parent claim", source_question_id="q1", confidence=0.7)
    child = Claim(claim_id="child1", entity_id="e1", normalized_form="child claim", source_question_id="q1", confidence=0.6, parent_claim_id="parent1", relation_to_parent="SUPPORTED_BY")

    response = compile_research_response(artifact, claims=[parent, child])
    assert [c.claim_id for c in response.claims] == ["parent1", "child1"]
    assert [c.claim_id for c in response.subclaims] == ["child1"]
    assert response.subclaims[0] is child, "the exact same Claim object must be referenced, not a copy"
    print("[PASS] #3 subclaim projection: parent stays in claims only, child appears in both claims and subclaims via the same object identity")


def _minimal_artifact_with_one_target():
    target = ConceptResearchTarget(entity_id="e1", entity_name="X", required_fields=frozenset({"definition"}))
    plan = ResearchPlan(abstraction_id="abs-1", abstraction_name="X", policy=EXPLORATORY_POLICY, targets=[target])
    completeness = ConceptCompleteness(entity_id="e1", entity_name="X", field_coverage=[FieldCoverage(field="definition", status="present", reason="x")], is_complete=True, missing_fields=frozenset())
    report = ResearchReadinessReport(abstraction_id="abs-1", abstraction_name="X", policy=EXPLORATORY_POLICY, concepts=[completeness], ready_count=1, incomplete_count=0, is_ready=True)
    return assemble_research_artifact(plan, report, {})


def check_lifecycle_preservation() -> None:
    artifact = _minimal_artifact_with_one_target()

    active = Claim(claim_id="a1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.7, evidence_ids=["ev1"])
    normalized = transition_claim(active, "normalized", reason="checked", actor="tester")
    supported = transition_claim(normalized, "supported", reason="evidence attached", actor="tester")
    validated = transition_claim(supported, "validated", reason="cross-checked", actor="tester")
    active_claim = transition_claim(validated, "active", reason="accepted", actor="tester")
    disputed = transition_claim(active_claim, "disputed", reason="a contradicting claim was found", actor="tester")

    rejected = transition_claim(Claim(claim_id="r1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.3), "rejected", reason="not a real proposition", actor="tester")
    superseded_base = transition_claim(
        transition_claim(transition_claim(Claim(claim_id="s1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.7, evidence_ids=["ev1"]), "normalized", reason="x", actor="t"), "supported", reason="x", actor="t"),
        "validated", reason="x", actor="t",
    )
    superseded_active = transition_claim(superseded_base, "active", reason="x", actor="t")
    superseded = transition_claim(superseded_active, "superseded", reason="replaced", actor="tester", superseded_by="newer-claim")

    duplicate = transition_claim(
        transition_claim(Claim(claim_id="d1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5), "normalized", reason="x", actor="t"),
        "duplicate", reason="identical source_url", actor="tester", duplicate_of="canonical-1",
    )
    # legacy_invalid_claim has no sanctioned constructor call site anywhere in
    # this codebase (reclassify_legacy_claim always produces
    # requires_reclassification) -- constructed directly here, a legal status
    # per ClaimStatus itself, purely to confirm the compiler doesn't special-
    # case it.
    legacy = Claim(claim_id="l1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.1, status="legacy_invalid_claim", provenance_note="pre-R1 migration artifact")

    all_claims = [disputed, rejected, superseded, duplicate, legacy]
    response = compile_research_response(artifact, claims=all_claims)

    statuses_by_id = {c.claim_id: c.status for c in response.claims}
    assert statuses_by_id["a1"] == "disputed"
    assert statuses_by_id["r1"] == "rejected"
    assert statuses_by_id["s1"] == "superseded"
    assert statuses_by_id["d1"] == "duplicate"
    assert statuses_by_id["l1"] == "legacy_invalid_claim"
    assert len(response.claims) == 5, "no claim was filtered out merely because of its status, including 'disputed'"
    print("[PASS] #4 rejected/superseded/duplicate/legacy/disputed claims all retain their exact existing status -- none reclassified or filtered")


def check_unavailable_data_honest() -> None:
    artifact, _ = _real_fixture()
    response = compile_research_response(artifact)
    assert response.root_entity_id is None
    assert response.unresolved_tasks == []
    assert response.provenance == []
    assert response.subclaims == [], "no claims were supplied, so there is nothing to derive a subclaim view from"
    print("[PASS] #5 root_entity_id/unresolved_tasks/provenance/subclaims all stay honestly empty when not supplied -- never fabricated")


def check_serialization_round_trip() -> None:
    artifact, _ = _real_fixture(with_contradictions=True)
    parent = Claim(claim_id="p1", entity_id="e1", normalized_form="parent", source_question_id="q1", confidence=0.7)
    child = Claim(claim_id="c2", entity_id="e1", normalized_form="child", source_question_id="q1", confidence=0.6, parent_claim_id="p1", relation_to_parent="SUPPORTED_BY")
    response = compile_research_response(artifact, claims=[parent, child])

    reconstructed = ResearchResponse.model_validate_json(response.model_dump_json())
    assert reconstructed == response
    assert len(reconstructed.contradictions) == 1
    print("[PASS] #6 the compiled response round-trips through model_dump_json/model_validate_json unchanged, including nested contradiction findings")


def check_no_mutation() -> None:
    artifact, claims_by_entity = _real_fixture()
    original_evidence_text = claims_by_entity["e1"][0].evidence
    original_ready_count = artifact.ready_count
    original_concept_snapshot = artifact.concepts[0].model_dump()

    claim = Claim(claim_id="c1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5)
    original_claim_snapshot = claim.model_dump()

    compile_research_response(artifact, claims=[claim])
    compile_research_response(artifact, claims=[claim])  # twice, to catch any accumulation

    assert claims_by_entity["e1"][0].evidence == original_evidence_text
    assert artifact.ready_count == original_ready_count
    assert artifact.concepts[0].model_dump() == original_concept_snapshot
    assert claim.model_dump() == original_claim_snapshot
    print("[PASS] #7 the source ResearchArtifact, its concepts, and every supplied Claim remain unchanged after compiling once and twice")


def check_determinism() -> None:
    artifact, _ = _real_fixture(with_contradictions=True)
    claim = Claim(claim_id="c1", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5)

    first = compile_research_response(artifact, claims=[claim])
    second = compile_research_response(artifact, claims=[claim])
    assert first == second
    print("[PASS] #8 compiling the same artifact+claims twice produces equivalent responses -- same ordering, same content")


if __name__ == "__main__":
    check_minimal_artifact()
    check_real_fixture_compiles()
    check_subclaim_projection()
    check_lifecycle_preservation()
    check_unavailable_data_honest()
    check_serialization_round_trip()
    check_no_mutation()
    check_determinism()
    print("\nAll 8 checks passed. Pure logic only, no LLM/retriever/Neo4j call.")
    print("Acceptance #9 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
