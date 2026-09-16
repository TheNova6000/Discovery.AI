"""R4.1 verification -- the pure ClaimNode -> reasoning.domain.Claim mapping
(docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
§0.66/§0.67, backend/research/claim_mapping.py).

Pure throughout -- no network/LLM/database/LangGraph call, no global mutable
state. This is representation conversion only; it does not validate,
promote, or persist anything (validation-orchestration is R4.2's job).

Checks:
  1. Valid forward mapping: entity identity, source question identity,
     normalized_form (from ClaimNode.evidence), confidence, and superseded_by
     are all preserved; the result is a real reasoning.domain.Claim.
  2. Required-field failure: empty/whitespace evidence, and empty
     entity_id/source_question_id, are all rejected explicitly
     (ClaimMappingRejected) -- never silently filled with "unknown" or "".
  3. No source mutation: the original ClaimNode is unchanged after mapping.
  4. No automatic promotion: a high-confidence, non-superseded ClaimNode
     still maps to "requires_reclassification" -- confidence is never a
     substitute for lifecycle status.
  5. Semantic identity unavailable: the mapped claim's subject/predicate/
     object are all None (never fabricated), so semantic_identity() returns
     None, while identity_floor() (the deterministic floor) is available.
  6. A retrieval-failure-shaped ClaimNode (R0's own real DNS non-answer
     text) is never deceived into a trusted status -- it lands at the same
     "requires_reclassification" as everything else, never "active"/
     "validated"/"supported". This mapper cannot reliably DETECT a
     retrieval failure from ClaimNode's fields alone (that information was
     never preserved for legacy persisted claims -- R0's own founding
     finding); what it guarantees instead is that nothing --  retrieval
     failure or not -- is ever promoted to a trusted status by mapping alone.
  7. Provenance across two independently-mapped ClaimNodes: distinct
     claim_ids, no cross-contamination, and confirmation that
     reasoning/source_title/source_url/source_type are intentionally NOT
     copied onto either result (a documented, tested loss, not a silent one).
  8. Status compatibility: ClaimNode expresses exactly one binary signal
     (superseded_by is None, or is not) -- both cases are enumerated and
     both map through the same documented compatibility rule
     ("requires_reclassification", with superseded_by carried through
     as real data when present).
  9. No reverse mapping exists in this module -- confirmed by inspection,
     not just by absence of a test for it. Documented why: source_title/
     source_url/source_type/reasoning/valid_from are already dropped going
     forward, so a reverse mapping would have to fabricate them.
 10. Regression: every pre-existing verify script re-run unmodified.
"""

from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph.models import ClaimNode  # noqa: E402
from backend.reasoning import identity_floor, semantic_identity  # noqa: E402
from backend.research.claim_mapping import ClaimMappingRejected, claim_node_to_domain_claim  # noqa: E402


def _node(**overrides) -> ClaimNode:
    defaults = dict(
        id="claim-1",
        evidence="DNS translates human-readable domain names into IP addresses.",
        reasoning="Directly stated by the resource, matches the question.",
        confidence=0.8,
        source_title="RFC 1035",
        source_url="https://example.com/rfc1035",
        source_type="web",
        valid_from="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return ClaimNode(**defaults)


def check_valid_forward_mapping() -> None:
    node = _node()
    claim = claim_node_to_domain_claim(node, entity_id="entity-dns", source_question_id="q-dns")
    assert claim.entity_id == "entity-dns"
    assert claim.source_question_id == "q-dns"
    assert claim.normalized_form == node.evidence
    assert claim.confidence == node.confidence
    assert claim.superseded_by is None
    assert claim.claim_id == node.id
    assert claim.__class__.__module__.endswith("reasoning.domain")
    print("[PASS] #1 valid forward mapping preserves entity/question identity, normalized_form, confidence; result is a real reasoning.domain.Claim")


def check_required_field_failure() -> None:
    for attempt, label in (
        (lambda: claim_node_to_domain_claim(_node(evidence=""), entity_id="e1", source_question_id="q1"), "empty evidence"),
        (lambda: claim_node_to_domain_claim(_node(evidence="   "), entity_id="e1", source_question_id="q1"), "whitespace-only evidence"),
        (lambda: claim_node_to_domain_claim(_node(), entity_id="", source_question_id="q1"), "empty entity_id"),
        (lambda: claim_node_to_domain_claim(_node(), entity_id="e1", source_question_id=""), "empty source_question_id"),
    ):
        try:
            attempt()
            raise AssertionError(f"should have rejected: {label}")
        except ClaimMappingRejected:
            pass
    print("[PASS] #2 required-field failures (empty evidence, empty entity_id, empty source_question_id) all rejected explicitly, nothing fabricated")


def check_no_source_mutation() -> None:
    node = _node()
    snapshot = node.model_copy(deep=True)
    claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert node == snapshot
    print("[PASS] #3 the original ClaimNode is unchanged after mapping")


def check_no_automatic_promotion() -> None:
    node = _node(confidence=0.99, superseded_by=None)
    claim = claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert claim.status == "requires_reclassification", f"a high-confidence claim must NOT be promoted, got {claim.status!r}"
    print("[PASS] #4 a high-confidence ClaimNode still maps to 'requires_reclassification' -- confidence never substitutes for lifecycle status")


def check_semantic_identity_unavailable() -> None:
    node = _node()
    claim = claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert claim.subject is None and claim.predicate is None and claim.object is None
    assert semantic_identity(claim) is None
    assert identity_floor(claim) == ("e1", "q1", node.evidence)
    print("[PASS] #5 semantic identity is unavailable (never fabricated); deterministic identity_floor remains available")


def check_retrieval_failure_never_promoted() -> None:
    # R0's own real, documented non-answer text (Architecture.md §0.47's DNS
    # example) -- a genuine retrieval-failure-shaped ClaimNode, if one were
    # ever persisted (exactly what R0 found for 3 of 4 "claims" on
    # Recursive Resolver, pre-R1.2's fix).
    node = _node(evidence="The provided resource does not answer the question.", confidence=0.1)
    claim = claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert claim.status == "requires_reclassification"
    assert claim.status not in ("active", "validated", "supported", "normalized")
    print("[PASS] #6 a retrieval-failure-shaped ClaimNode is never promoted to a trusted status -- lands at 'requires_reclassification' like everything else")


def check_provenance_no_cross_contamination() -> None:
    node_a = _node(id="claim-a", evidence="Claim A's proposition.", source_title="Source A", source_url="https://a.example", reasoning="Reasoning A")
    node_b = _node(id="claim-b", evidence="Claim B's proposition.", source_title="Source B", source_url="https://b.example", reasoning="Reasoning B")
    claim_a = claim_node_to_domain_claim(node_a, entity_id="e1", source_question_id="q1")
    claim_b = claim_node_to_domain_claim(node_b, entity_id="e1", source_question_id="q1")

    assert claim_a.claim_id != claim_b.claim_id
    assert claim_a.normalized_form == "Claim A's proposition."
    assert claim_b.normalized_form == "Claim B's proposition."
    # Intentional, documented loss -- confirmed here, not just asserted in
    # a docstring: reasoning/source_title/source_url/source_type never
    # reach the resulting Claim at all (no field exists to hold them).
    for claim in (claim_a, claim_b):
        assert not hasattr(claim, "reasoning")
        assert not hasattr(claim, "source_title")
        assert not hasattr(claim, "source_url")
        assert not hasattr(claim, "source_type")
        assert claim.evidence_ids == [], "no Evidence object is fabricated from flat ClaimNode source fields"
    print("[PASS] #7 two independently-mapped claims show no cross-contamination; reasoning/source_* fields are confirmed absent from the result (documented loss, not silent)")


def check_status_compatibility_enumeration() -> None:
    # ClaimNode expresses exactly one status-relevant signal: superseded_by
    # is None, or is not. Both are enumerated; neither collapses into the
    # other, and both map through the SAME documented rule.
    not_superseded = claim_node_to_domain_claim(_node(superseded_by=None), entity_id="e1", source_question_id="q1")
    superseded = claim_node_to_domain_claim(_node(id="claim-2", superseded_by="claim-1"), entity_id="e1", source_question_id="q1")

    assert not_superseded.status == "requires_reclassification" and not_superseded.superseded_by is None
    assert superseded.status == "requires_reclassification" and superseded.superseded_by == "claim-1"
    assert "requires reclassification" in (not_superseded.provenance_note or "")
    assert "superseded_by" in (superseded.provenance_note or ""), "the superseded fact must be visible in the reason, not just the field"
    print("[PASS] #8 both of ClaimNode's real status signals (superseded_by None / not None) map through the same documented rule -- neither silently collapsed nor conflated")


def check_no_reverse_mapping_exists() -> None:
    import backend.research.claim_mapping as claim_mapping_module

    assert not hasattr(claim_mapping_module, "domain_claim_to_claim_node"), (
        "reverse mapping must not exist in this slice -- source_title/source_url/source_type/reasoning/valid_from "
        "are already dropped in the forward direction, so a reverse mapping would have to fabricate them"
    )
    source = inspect.getsource(claim_mapping_module)
    import_lines = [line.strip() for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    assert any("backend.graph" in line for line in import_lines)
    assert any("backend.reasoning" in line for line in import_lines)
    print("[PASS] #9 no reverse mapping exists (confirmed by inspection); forward-only is the honest choice given the fields already dropped going forward")


if __name__ == "__main__":
    check_valid_forward_mapping()
    check_required_field_failure()
    check_no_source_mutation()
    check_no_automatic_promotion()
    check_semantic_identity_unavailable()
    check_retrieval_failure_never_promoted()
    check_provenance_no_cross_contamination()
    check_status_compatibility_enumeration()
    check_no_reverse_mapping_exists()
    print("\nAll 9 checks passed. Pure logic only, no network/LLM/database/LangGraph call.")
    print("Acceptance #10 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
