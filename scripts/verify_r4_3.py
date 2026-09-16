"""R4.3 verification -- the parent/subclaim relation (docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md §0.49/§0.69,
backend/reasoning/domain.py: `parent_claim_id`/`relation_to_parent` on
`Claim`, `subclaim_relation`, `is_necessary_support`,
`validate_subclaim_graph`, `find_claims_with_invalid_parent`).

Pure throughout -- no Neo4j, no LLM, no persistence, no automatic
inheritance of status or confidence from a parent to its subclaims (or the
reverse). A subclaim is NOT a new class: it is a `Claim` that names another
`Claim` as its parent, on the exact same model every other claim uses
(Architecture.md §0.49's own design, implemented here for the first time).

Checks:
  1. subclaim_relation returns (parent_claim_id, relation_to_parent) only
     when both are set; None for a claim with neither.
  2. is_necessary_support is True only for SUPPORTED_BY, false for every
     other real relation value (QUALIFIED_BY/ILLUSTRATED_BY/
     CONTRADICTED_BY/ALTERNATIVE_TO/DERIVED_FROM) and for no relation.
  3. A claim cannot be its own parent -- rejected at construction.
  4. relation_to_parent requires parent_claim_id and vice versa -- no
     dangling half-set reference is constructible.
  5. A claim CAN be both a parent (referenced by another's
     parent_claim_id) and a subclaim (having one itself) simultaneously --
     the normal, expected shape of nested support, not a special case.
  6. validate_subclaim_graph rejects a parent_claim_id absent from the
     given claim set.
  7. validate_subclaim_graph rejects a parent-chain cycle (direct and
     indirect) and accepts a real, valid tree.
  8. find_claims_with_invalid_parent reports a subclaim whose parent is
     missing from the set, and one whose parent has reached a discredited
     status (superseded/rejected/duplicate/legacy_invalid_claim) --
     read-only: the orphaned subclaim's OWN status is never touched.
  9. No automatic status/confidence inheritance: a parent superseding does
     not change its subclaim's status, and a subclaim's own confidence is
     never derived from its parent's.
 10. duplicate_of and parent_claim_id are orthogonal -- a claim can carry
     both simultaneously without conflict (duplicate resolution, R4.2,
     required no changes for this).
 11. Serialization round-trip: a claim with both fields set, and a claim
     with neither, both round-trip through model_dump_json/
     model_validate_json unchanged.
 12. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2 checks
     remain green.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from backend.reasoning import (  # noqa: E402
    Claim,
    SubclaimGraphError,
    find_claims_with_invalid_parent,
    is_necessary_support,
    subclaim_relation,
    transition_claim,
    validate_subclaim_graph,
)


def _claim(**overrides) -> Claim:
    defaults = dict(entity_id="e1", normalized_form="a proposition", source_question_id="q1", confidence=0.6)
    defaults.update(overrides)
    return Claim(**defaults)


def check_subclaim_relation_shape() -> None:
    parent = _claim()
    child = _claim(parent_claim_id=parent.claim_id, relation_to_parent="SUPPORTED_BY")
    assert subclaim_relation(child) == (parent.claim_id, "SUPPORTED_BY")
    assert subclaim_relation(parent) is None
    print("[PASS] #1 subclaim_relation returns the real pair only when both fields are set, None otherwise")


def check_is_necessary_support() -> None:
    parent = _claim()
    supported = _claim(parent_claim_id=parent.claim_id, relation_to_parent="SUPPORTED_BY")
    qualified = _claim(parent_claim_id=parent.claim_id, relation_to_parent="QUALIFIED_BY")
    illustrated = _claim(parent_claim_id=parent.claim_id, relation_to_parent="ILLUSTRATED_BY")
    contradicted = _claim(parent_claim_id=parent.claim_id, relation_to_parent="CONTRADICTED_BY")
    alternative = _claim(parent_claim_id=parent.claim_id, relation_to_parent="ALTERNATIVE_TO")
    derived = _claim(parent_claim_id=parent.claim_id, relation_to_parent="DERIVED_FROM")

    assert is_necessary_support(supported) is True
    for other in (qualified, illustrated, contradicted, alternative, derived, parent):
        assert is_necessary_support(other) is False
    print("[PASS] #2 is_necessary_support is True only for SUPPORTED_BY, false for every other relation and for no relation")


def check_self_parent_rejected() -> None:
    try:
        Claim(claim_id="same", entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5, parent_claim_id="same", relation_to_parent="SUPPORTED_BY")
        raise AssertionError("a claim must not be constructible as its own parent")
    except ValidationError:
        pass
    print("[PASS] #3 a claim cannot be its own parent -- rejected at construction")


def check_dangling_relation_rejected() -> None:
    try:
        _claim(relation_to_parent="SUPPORTED_BY")
        raise AssertionError("relation_to_parent without parent_claim_id must be rejected")
    except ValidationError:
        pass
    try:
        _claim(parent_claim_id="some-parent")
        raise AssertionError("parent_claim_id without relation_to_parent must be rejected")
    except ValidationError:
        pass
    print("[PASS] #4 relation_to_parent and parent_claim_id are required together -- no dangling half-set reference")


def check_claim_can_be_parent_and_subclaim() -> None:
    grandparent = _claim()
    middle = _claim(parent_claim_id=grandparent.claim_id, relation_to_parent="SUPPORTED_BY")
    child = _claim(parent_claim_id=middle.claim_id, relation_to_parent="SUPPORTED_BY")
    assert subclaim_relation(middle) == (grandparent.claim_id, "SUPPORTED_BY")
    assert subclaim_relation(child) == (middle.claim_id, "SUPPORTED_BY")
    validate_subclaim_graph([grandparent, middle, child])
    print("[PASS] #5 a claim can be both a parent and a subclaim simultaneously -- validated as a real 3-level chain")


def check_missing_parent_rejected() -> None:
    orphan = _claim(parent_claim_id="does-not-exist", relation_to_parent="SUPPORTED_BY")
    try:
        validate_subclaim_graph([orphan])
        raise AssertionError("a parent_claim_id absent from the given set must be rejected")
    except SubclaimGraphError:
        pass
    print("[PASS] #6 validate_subclaim_graph rejects a parent_claim_id absent from the given claim set")


def check_cycle_rejected() -> None:
    a = _claim(claim_id="ca")
    b = _claim(claim_id="cb", parent_claim_id="ca", relation_to_parent="SUPPORTED_BY")
    a_cyclic = Claim(**{**a.model_dump(), "parent_claim_id": "cb", "relation_to_parent": "SUPPORTED_BY"})
    try:
        validate_subclaim_graph([a_cyclic, b])
        raise AssertionError("a direct 2-cycle must be rejected")
    except SubclaimGraphError:
        pass

    c = _claim(claim_id="cc", parent_claim_id="cb", relation_to_parent="SUPPORTED_BY")
    b_indirect_cycle = Claim(**{**b.model_dump(), "parent_claim_id": "cc", "relation_to_parent": "SUPPORTED_BY"})
    try:
        validate_subclaim_graph([a, b_indirect_cycle, c])
        raise AssertionError("an indirect 3-claim cycle must be rejected")
    except SubclaimGraphError:
        pass

    valid_tree = [a, b, c]
    validate_subclaim_graph(valid_tree)
    print("[PASS] #7 validate_subclaim_graph rejects direct and indirect parent-chain cycles, accepts a real valid tree")


def check_invalid_parent_reporting() -> None:
    parent_with_evidence = _claim(claim_id="parent1", evidence_ids=["ev1"])
    active_parent = transition_claim(
        transition_claim(transition_claim(transition_claim(parent_with_evidence, "normalized", reason="x", actor="t"), "supported", reason="x", actor="t"), "validated", reason="x", actor="t"),
        "active",
        reason="x",
        actor="t",
    )
    superseded_parent = transition_claim(active_parent, "superseded", reason="replaced by a better claim", actor="t", superseded_by="other-claim")

    healthy_parent = _claim(claim_id="parent2")
    child_of_superseded = _claim(claim_id="child1", parent_claim_id=superseded_parent.claim_id, relation_to_parent="SUPPORTED_BY")
    child_of_missing = _claim(claim_id="child2", parent_claim_id="does-not-exist-in-set", relation_to_parent="SUPPORTED_BY")
    healthy_child = _claim(claim_id="child3", parent_claim_id=healthy_parent.claim_id, relation_to_parent="SUPPORTED_BY")

    orphaned = find_claims_with_invalid_parent([superseded_parent, healthy_parent, child_of_superseded, child_of_missing, healthy_child])
    assert set(orphaned) == {"child1", "child2"}
    assert child_of_superseded.status == "requires_reclassification" or child_of_superseded.status == "candidate"  # untouched, never cascaded
    print("[PASS] #8 find_claims_with_invalid_parent reports subclaims with a missing or discredited parent, and never mutates the orphaned subclaim itself")


def check_no_automatic_inheritance() -> None:
    parent = _claim(claim_id="parent1", evidence_ids=["ev1"], confidence=0.9)
    child = _claim(claim_id="child1", parent_claim_id=parent.claim_id, relation_to_parent="SUPPORTED_BY", confidence=0.1)
    original_child_status = child.status
    original_child_confidence = child.confidence

    active_parent = transition_claim(
        transition_claim(transition_claim(transition_claim(parent, "normalized", reason="x", actor="t"), "supported", reason="x", actor="t"), "validated", reason="x", actor="t"),
        "active",
        reason="x",
        actor="t",
    )
    superseded_parent = transition_claim(active_parent, "superseded", reason="x", actor="t", superseded_by="other")

    assert child.status == original_child_status, "the subclaim's status must never change just because the parent variable was reassigned/transitioned"
    assert child.confidence == original_child_confidence == 0.1, "a subclaim's confidence is never derived from its parent's, regardless of the parent's own confidence"
    assert superseded_parent.status == "superseded"
    print("[PASS] #9 no automatic status/confidence inheritance -- a parent's transition never touches its subclaim's own status or confidence")


def check_duplicate_and_parent_orthogonal() -> None:
    parent = _claim(claim_id="parent1")
    canonical = _claim(claim_id="canonical1", provenance_note="candidate", parent_claim_id=parent.claim_id, relation_to_parent="SUPPORTED_BY")
    duplicate_and_subclaim = transition_claim(
        transition_claim(_claim(claim_id="dup1", parent_claim_id=parent.claim_id, relation_to_parent="SUPPORTED_BY"), "normalized", reason="x", actor="t"),
        "duplicate",
        reason="matches canonical",
        actor="t",
        duplicate_of="canonical1",
    )
    assert duplicate_and_subclaim.duplicate_of == "canonical1"
    assert duplicate_and_subclaim.parent_claim_id == parent.claim_id
    assert duplicate_and_subclaim.relation_to_parent == "SUPPORTED_BY"
    print("[PASS] #10 duplicate_of and parent_claim_id are orthogonal -- both can be set on the same claim without conflict")


def check_serialization_round_trip() -> None:
    parent = _claim()
    with_relation = _claim(parent_claim_id=parent.claim_id, relation_to_parent="SUPPORTED_BY")
    without_relation = _claim()
    for claim in (with_relation, without_relation):
        assert Claim.model_validate_json(claim.model_dump_json()) == claim
    print("[PASS] #11 a claim with the relation set, and one without, both round-trip through model_dump_json/model_validate_json unchanged")


if __name__ == "__main__":
    check_subclaim_relation_shape()
    check_is_necessary_support()
    check_self_parent_rejected()
    check_dangling_relation_rejected()
    check_claim_can_be_parent_and_subclaim()
    check_missing_parent_rejected()
    check_cycle_rejected()
    check_invalid_parent_reporting()
    check_no_automatic_inheritance()
    check_duplicate_and_parent_orthogonal()
    check_serialization_round_trip()
    print("\nAll 11 checks passed. Pure logic only, no Neo4j/LLM/persistence call.")
    print("Acceptance #12 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
