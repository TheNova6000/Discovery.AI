"""Phase 8.6 verification -- Research-complete graph artifact, the pure
assembly logic only (docs/Phases.md Phase 8.6, docs/PRD.md §9.3a,
docs/Architecture.md §0.46, backend/research/artifact.py).

Same split as every prior phase in this track: `assemble_research_artifact`
is a pure function over already-computed Phase 8.1-8.5 data (ResearchPlan,
ResearchReadinessReport, ClaimNode lists, optional ContradictionReports --
all pydantic-only), so it's testable here with hand-built fixtures and zero
LLM/retriever/Neo4j calls. `compile_research_artifact`'s own I/O shell (the
get_subgraph/get_questions_for_entity/get_claims_for_question calls, via
build_research_plan/build_readiness_report) is NOT exercised by this script,
same scoping every phase in this track has used.

Six checks:
  1. Basic assembly: one target + matching completeness -> one
     ConceptResearchArtifact with the right identity/fields carried through.
  2. Evidence refs are built from real (non-superseded) claims only, with
     correct provenance fields (claim_id/source_url/confidence).
  3. Superseded claims are excluded from evidence_refs -- this module must
     not resurface stale evidence as if it were live.
  4. contradictions is None when the caller supplies no
     contradiction_reports_by_entity entry for that concept -- distinct from
     a ContradictionReport with checked=False (Phase 8.5's own distinction,
     preserved through assembly, not collapsed into one "nothing" value).
  5. A supplied ContradictionReport is passed through unchanged when present
     for that entity.
  6. prerequisite_entity_ids is always empty (the honest, documented gap --
     this module invents no relation data that doesn't exist in the graph).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.graph.models import ClaimNode  # noqa: E402
from backend.research import (  # noqa: E402
    ConceptCompleteness,
    ConceptResearchTarget,
    ContradictionReport,
    FieldCoverage,
    ResearchPlan,
    ResearchReadinessReport,
    assemble_research_artifact,
)

_NOW = "2026-01-01T00:00:00+00:00"


def _claim(claim_id: str, confidence: float, url: str, superseded_by: str | None = None) -> ClaimNode:
    return ClaimNode(
        id=claim_id,
        evidence=f"evidence for {claim_id}",
        reasoning="fixture",
        confidence=confidence,
        source_title="fixture source",
        source_url=url,
        source_type="web",
        valid_from=_NOW,
        superseded_by=superseded_by,
    )


def _plan_and_report():
    target = ConceptResearchTarget(entity_id="e1", entity_name="Pointers", required_fields=frozenset({"definition", "mechanism"}))
    plan = ResearchPlan(abstraction_id="a1", abstraction_name="Fixture", policy=EXPLORATORY_POLICY, targets=[target])
    fc = [FieldCoverage(field="definition", status="present", reason="ok"), FieldCoverage(field="mechanism", status="present", reason="ok")]
    completeness = ConceptCompleteness(entity_id="e1", entity_name="Pointers", field_coverage=fc, is_complete=True, missing_fields=frozenset())
    report = ResearchReadinessReport(
        abstraction_id="a1", abstraction_name="Fixture", policy=EXPLORATORY_POLICY, concepts=[completeness], ready_count=1, incomplete_count=0, is_ready=True
    )
    return plan, report


def check_basic_assembly_identity() -> None:
    plan, report = _plan_and_report()
    artifact = assemble_research_artifact(plan, report, {"e1": [_claim("c1", 0.8, "http://a.example")]})
    assert artifact.abstraction_name == "Fixture"
    assert artifact.is_ready is True
    assert len(artifact.concepts) == 1
    c = artifact.concepts[0]
    assert c.entity_id == "e1" and c.entity_name == "Pointers"
    assert c.required_fields == frozenset({"definition", "mechanism"})
    assert c.is_complete is True
    print("[PASS] check_basic_assembly_identity: target+completeness -> one correctly-identified ConceptResearchArtifact")


def check_evidence_refs_have_correct_provenance() -> None:
    plan, report = _plan_and_report()
    artifact = assemble_research_artifact(plan, report, {"e1": [_claim("c1", 0.8, "http://a.example")]})
    refs = artifact.concepts[0].evidence_refs
    assert len(refs) == 1
    assert refs[0].claim_id == "c1"
    assert refs[0].source_url == "http://a.example"
    assert refs[0].confidence == 0.8
    print("[PASS] check_evidence_refs_have_correct_provenance: claim_id/source_url/confidence carried through correctly")


def check_superseded_claims_excluded_from_evidence_refs() -> None:
    plan, report = _plan_and_report()
    claims = [_claim("c1", 0.9, "http://a.example"), _claim("c2", 0.95, "http://b.example", superseded_by="c1")]
    artifact = assemble_research_artifact(plan, report, {"e1": claims})
    refs = artifact.concepts[0].evidence_refs
    assert [r.claim_id for r in refs] == ["c1"]
    print("[PASS] check_superseded_claims_excluded_from_evidence_refs: superseded claim not resurfaced as live evidence")


def check_no_contradiction_report_supplied_is_none() -> None:
    plan, report = _plan_and_report()
    artifact = assemble_research_artifact(plan, report, {"e1": [_claim("c1", 0.8, "http://a.example")]})
    assert artifact.concepts[0].contradictions is None
    print("[PASS] check_no_contradiction_report_supplied_is_none: no report supplied -> None, distinct from checked=False")


def check_supplied_contradiction_report_passed_through() -> None:
    plan, report = _plan_and_report()
    supplied = ContradictionReport(entity_id="e1", entity_name="Pointers", checked=True, findings=[])
    artifact = assemble_research_artifact(
        plan, report, {"e1": [_claim("c1", 0.8, "http://a.example")]}, contradiction_reports_by_entity={"e1": supplied}
    )
    assert artifact.concepts[0].contradictions is supplied
    print("[PASS] check_supplied_contradiction_report_passed_through: caller-supplied report preserved unchanged")


def check_prerequisite_entity_ids_always_empty() -> None:
    plan, report = _plan_and_report()
    artifact = assemble_research_artifact(plan, report, {"e1": [_claim("c1", 0.8, "http://a.example")]})
    assert artifact.concepts[0].prerequisite_entity_ids == []
    print("[PASS] check_prerequisite_entity_ids_always_empty: honest gap, no relation data invented")


if __name__ == "__main__":
    check_basic_assembly_identity()
    check_evidence_refs_have_correct_provenance()
    check_superseded_claims_excluded_from_evidence_refs()
    check_no_contradiction_report_supplied_is_none()
    check_supplied_contradiction_report_passed_through()
    check_prerequisite_entity_ids_always_empty()
    print("\nAll 6 checks passed. This covers assemble_research_artifact's pure logic")
    print("only -- no LLM, retriever, or Neo4j call was made. compile_research_artifact's")
    print("own I/O shell is not exercised here, same scoping as every prior phase's script.")
