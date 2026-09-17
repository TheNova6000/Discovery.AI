"""Phase 9.1 verification -- compile_course, the pure Curriculum Compiler
(docs/Phases.md's "restructuring around Discovery.AI" track,
docs/Architecture.md §0.76, docs/Rules.md rule 16, backend/dewey/curriculum/).

Pure throughout -- no LLM/retriever/Neo4j call (rule 16's own restriction).
Every fixture is a hand-built ResearchResponse (R5's own stable contract),
reusing scripts/verify_r5_2.py's fixture style: real ConceptCompleteness/
Claim/Relationship/GraphNode objects, never a fabricated fourth shape.

Checks:
  1. A known prerequisite chain (real relationship_type=="requires" edges)
     is respected: every module appears strictly after its prerequisites.
  2. A cyclic requires graph raises CourseCompilationError -- never silently
     dropped, never an infinite loop.
  3. A concept failing ConceptCompleteness.is_complete is surfaced in
     Course.incomplete_concepts, and never compiled into a Module.
  4. No requires edges present: modules fall back to coverage-list
     (discovery) order, and ordered_by_prerequisites is honestly False --
     never a fabricated/guessed teaching order.
  5. Claims are grouped into the correct module by entity_id, using the
     exact same Claim objects from ResearchResponse.claims -- no copies.
  6. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1-R5.3
     checks remain green.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.dewey.curriculum import CourseCompilationError, compile_course  # noqa: E402
from backend.graph.models import GraphNode, Relationship  # noqa: E402
from backend.reasoning import Claim  # noqa: E402
from backend.research import ConceptCompleteness, FieldCoverage  # noqa: E402
from backend.research_api import ResearchResponse  # noqa: E402

_NOW = "2026-01-01T00:00:00+00:00"


def _complete(entity_id: str, entity_name: str) -> ConceptCompleteness:
    return ConceptCompleteness(
        entity_id=entity_id, entity_name=entity_name,
        field_coverage=[FieldCoverage(field="definition", status="present", reason="x")],
        is_complete=True, missing_fields=frozenset(),
    )


def _incomplete(entity_id: str, entity_name: str) -> ConceptCompleteness:
    return ConceptCompleteness(
        entity_id=entity_id, entity_name=entity_name,
        field_coverage=[FieldCoverage(field="definition", status="missing", reason="never targeted")],
        is_complete=False, missing_fields=frozenset({"definition"}),
    )


def _claim(claim_id: str, entity_id: str) -> Claim:
    return Claim(claim_id=claim_id, entity_id=entity_id, normalized_form=f"fact about {entity_id}", source_question_id="q1", confidence=0.7)


def _node(entity_id: str, name: str) -> GraphNode:
    return GraphNode(id=entity_id, name=name, type="domain", created_at=_NOW, updated_at=_NOW)


def _response(coverage: list[ConceptCompleteness], claims: list[Claim], relationships: list[Relationship]) -> ResearchResponse:
    entities = [_node(c.entity_id, c.entity_name) for c in coverage]
    return ResearchResponse(
        investigation_id="abs-course-1", status="complete", entities=entities,
        relationships=relationships, claims=claims, coverage=coverage,
    )


def check_prerequisite_chain_respected() -> None:
    # DNS resolution requires networking basics requires nothing.
    coverage = [_complete("e-net", "Networking Basics"), _complete("e-dns", "DNS Resolution"), _complete("e-rec", "Recursive Resolver")]
    # "e-dns requires e-net" and "e-rec requires e-dns" -- source requires target.
    relationships = [
        Relationship(source_id="e-dns", target_id="e-net", relationship_type="requires"),
        Relationship(source_id="e-rec", target_id="e-dns", relationship_type="requires"),
    ]
    response = _response(coverage, claims=[], relationships=relationships)

    course = compile_course(response)
    order = [m.entity_id for m in course.modules]
    assert order.index("e-net") < order.index("e-dns") < order.index("e-rec")
    assert course.ordered_by_prerequisites is True
    print(f"[PASS] #1 known prerequisite chain respected: {order}")


def check_cycle_raises() -> None:
    coverage = [_complete("e-a", "A"), _complete("e-b", "B")]
    relationships = [
        Relationship(source_id="e-a", target_id="e-b", relationship_type="requires"),
        Relationship(source_id="e-b", target_id="e-a", relationship_type="requires"),
    ]
    response = _response(coverage, claims=[], relationships=relationships)

    try:
        compile_course(response)
        raise AssertionError("expected CourseCompilationError for a real requires-cycle")
    except CourseCompilationError as exc:
        print(f"[PASS] #2 a cyclic requires graph raises CourseCompilationError, never silently dropped or infinite-looped: {exc}")


def check_incomplete_concept_surfaced_not_compiled() -> None:
    coverage = [_complete("e-net", "Networking Basics"), _incomplete("e-dns", "DNS Resolution")]
    response = _response(coverage, claims=[], relationships=[])

    course = compile_course(response)
    module_ids = {m.entity_id for m in course.modules}
    assert "e-dns" not in module_ids, "an incomplete concept must never be compiled into a Module"
    assert "e-net" in module_ids
    assert len(course.incomplete_concepts) == 1
    assert course.incomplete_concepts[0].entity_id == "e-dns"
    assert course.incomplete_concepts[0].missing_fields == frozenset({"definition"})
    print("[PASS] #3 a concept failing completeness is surfaced in incomplete_concepts, never compiled into a module")


def check_fallback_to_discovery_order() -> None:
    coverage = [_complete("e-z", "Z Topic"), _complete("e-a", "A Topic")]
    response = _response(coverage, claims=[], relationships=[])

    course = compile_course(response)
    assert [m.entity_id for m in course.modules] == ["e-z", "e-a"], "with no real requires edges, order must match coverage's own (discovery) order, not be re-sorted"
    assert course.ordered_by_prerequisites is False
    print("[PASS] #4 no requires edges present: modules fall back to honest discovery order, ordered_by_prerequisites is False")


def check_claims_grouped_by_entity_identity() -> None:
    coverage = [_complete("e-net", "Networking Basics"), _complete("e-dns", "DNS Resolution")]
    net_claim = _claim("c-net-1", "e-net")
    dns_claim_1 = _claim("c-dns-1", "e-dns")
    dns_claim_2 = _claim("c-dns-2", "e-dns")
    response = _response(coverage, claims=[net_claim, dns_claim_1, dns_claim_2], relationships=[])

    course = compile_course(response)
    by_id = {m.entity_id: m for m in course.modules}
    assert by_id["e-net"].claims == [net_claim]
    assert by_id["e-dns"].claims == [dns_claim_1, dns_claim_2]
    assert by_id["e-dns"].claims[0] is dns_claim_1, "the exact same Claim object must be referenced, not a copy"
    print("[PASS] #5 claims are grouped into the correct module by entity_id, using the exact same Claim objects, no copies")


if __name__ == "__main__":
    check_prerequisite_chain_respected()
    check_cycle_raises()
    check_incomplete_concept_surfaced_not_compiled()
    check_fallback_to_discovery_order()
    check_claims_grouped_by_entity_identity()
    print("\nAll 5 checks passed. Pure logic only, no LLM/retriever/Neo4j call.")
    print("Acceptance #6 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1-R5.3 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
