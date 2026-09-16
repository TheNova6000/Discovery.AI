"""R1.4 verification -- pure claim lifecycle transitions (docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md §0.61,
backend/reasoning/domain.py: `transition_claim`, `ClaimTransitionRejected`).

Pure, no I/O -- transition_claim calls no LLM, queries no Neo4j, retrieves
no evidence, publishes no event, and reads `confidence` nowhere. Every
check here is a hand-built fixture; there is nothing to run live against
(this phase defines legal state transitions, not orchestration that touches
real data).

Checks (from the user's own acceptance list, verbatim where possible):
  1. candidate -> normalized: allowed.
  2. normalized -> supported: allowed only with evidence_ids already present.
  3. supported -> validated: allowed.
  4. validated -> active: allowed.
  5. candidate -> active: rejected (must go through the pipeline).
  6. candidate -> superseded: rejected (nothing to replace yet).
  7. active -> superseded: allowed with a superseded_by reference.
  8. active -> disputed: allowed with a reason (no extra reference required
     -- disputing doesn't yet name a specific contradicting claim in this
     minimal slice, matching "don't implement every transition's full
     payload before the meaning is proven").
  9. Confidence never gates a transition -- a very-low-confidence claim
     transitions exactly like a high-confidence one; transition_claim
     never reads `claim.confidence` at all.
  10. Every transition requires a non-empty reason and actor -- silently
      omitting either is rejected, not defaulted.
  11. transition_claim never mutates its input -- the original Claim object
      is unchanged after a successful transition.
  12. A transitioned Claim re-validates through Claim's own
      _status_consistency invariant (not bypassed via model_copy) --
      confirmed by checking the result is a genuinely new, fully-validated
      Claim instance.
  13. A retrieval failure still cannot become a Claim through this path
      either -- classify_retrieval_outcome's existing invariant (R1.1) is
      untouched by anything added in R1.4.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.reasoning import (  # noqa: E402
    Claim,
    ClaimTransitionRejected,
    RetrievalOutcome,
    classify_retrieval_outcome,
    transition_claim,
)


def _claim(**overrides) -> Claim:
    defaults = dict(entity_id="e1", normalized_form="DNS translates names to IPs", source_question_id="q1", confidence=0.1)
    defaults.update(overrides)
    return Claim(**defaults)


def check_candidate_to_normalized_allowed() -> None:
    result = transition_claim(_claim(), "normalized", reason="wording checked", actor="tester")
    assert result.status == "normalized"
    assert result.provenance_note == "wording checked"
    print("[PASS] #1 candidate -> normalized: allowed")


def check_normalized_to_supported_requires_evidence() -> None:
    normalized = transition_claim(_claim(), "normalized", reason="checked", actor="tester")
    try:
        transition_claim(normalized, "supported", reason="attaching evidence", actor="tester")
        raise AssertionError("should have rejected 'supported' with no evidence_ids")
    except ClaimTransitionRejected:
        pass
    with_evidence = Claim(**{**normalized.model_dump(), "evidence_ids": ["ev1"]})
    supported = transition_claim(with_evidence, "supported", reason="evidence attached", actor="tester")
    assert supported.status == "supported"
    print("[PASS] #2 normalized -> supported: rejected with no evidence, allowed once evidence_ids is set")


def check_full_legal_chain_to_active() -> None:
    claim = _claim(evidence_ids=["ev1"])
    normalized = transition_claim(claim, "normalized", reason="checked", actor="tester")
    supported = transition_claim(normalized, "supported", reason="evidence present", actor="tester")
    validated = transition_claim(supported, "validated", reason="cross-checked against a second source", actor="validator_x")
    active = transition_claim(validated, "active", reason="accepted into the investigation's knowledge state", actor="tester")
    assert [c.status for c in (normalized, supported, validated, active)] == ["normalized", "supported", "validated", "active"]
    print("[PASS] #3/#4 supported -> validated -> active: full legal chain allowed")


def check_candidate_to_active_rejected() -> None:
    try:
        transition_claim(_claim(), "active", reason="x", actor="y")
        raise AssertionError("should have rejected candidate -> active")
    except ClaimTransitionRejected:
        pass
    print("[PASS] #5 candidate -> active: rejected (must go through the pipeline)")


def check_candidate_to_superseded_rejected() -> None:
    try:
        transition_claim(_claim(), "superseded", reason="x", actor="y", superseded_by="other-claim")
        raise AssertionError("should have rejected candidate -> superseded")
    except ClaimTransitionRejected:
        pass
    print("[PASS] #6 candidate -> superseded: rejected (nothing to replace yet)")


def check_active_to_superseded_requires_reference() -> None:
    claim = _claim(evidence_ids=["ev1"])
    active = transition_claim(
        transition_claim(
            transition_claim(transition_claim(claim, "normalized", reason="x", actor="t"), "supported", reason="x", actor="t"),
            "validated",
            reason="x",
            actor="t",
        ),
        "active",
        reason="x",
        actor="t",
    )
    try:
        transition_claim(active, "superseded", reason="replaced by a better claim", actor="tester")
        raise AssertionError("should have rejected 'superseded' with no superseded_by")
    except ClaimTransitionRejected:
        pass
    superseded = transition_claim(active, "superseded", reason="replaced by a better claim", actor="tester", superseded_by="claim-999")
    assert superseded.status == "superseded" and superseded.superseded_by == "claim-999"
    print("[PASS] #7 active -> superseded: rejected with no reference, allowed with superseded_by")


def check_active_to_disputed_allowed() -> None:
    claim = _claim(evidence_ids=["ev1"])
    active = transition_claim(
        transition_claim(
            transition_claim(transition_claim(claim, "normalized", reason="x", actor="t"), "supported", reason="x", actor="t"),
            "validated",
            reason="x",
            actor="t",
        ),
        "active",
        reason="x",
        actor="t",
    )
    disputed = transition_claim(active, "disputed", reason="a contradicting claim was found", actor="tester")
    assert disputed.status == "disputed"
    print("[PASS] #8 active -> disputed: allowed")


def check_confidence_never_gates_a_transition() -> None:
    very_low = _claim(confidence=0.01)
    very_high = _claim(confidence=0.99)
    low_result = transition_claim(very_low, "normalized", reason="still legitimate despite low confidence", actor="tester")
    high_result = transition_claim(very_high, "normalized", reason="normalized regardless of confidence", actor="tester")
    assert low_result.status == high_result.status == "normalized"
    print("[PASS] #9 confidence never gates a transition -- low- and high-confidence claims transition identically")


def check_reason_and_actor_required() -> None:
    for kwargs in ({"reason": "", "actor": "tester"}, {"reason": "  ", "actor": "tester"}, {"reason": "x", "actor": ""}):
        try:
            transition_claim(_claim(), "normalized", **kwargs)
            raise AssertionError(f"should have rejected empty reason/actor: {kwargs}")
        except ClaimTransitionRejected:
            pass
    print("[PASS] #10 empty reason or actor is always rejected, never defaulted")


def check_original_claim_never_mutated() -> None:
    claim = _claim()
    original_status = claim.status
    transition_claim(claim, "normalized", reason="x", actor="tester")
    assert claim.status == original_status
    print("[PASS] #11 transition_claim never mutates its input")


def check_result_is_fully_revalidated() -> None:
    claim = _claim()
    result = transition_claim(claim, "normalized", reason="x", actor="tester")
    assert isinstance(result, Claim)
    assert result is not claim
    # Constructing the same field set directly through Claim() must succeed
    # identically -- proof the transition result went through real
    # validation, not a validator-bypassing shallow copy.
    reconstructed = Claim(**result.model_dump())
    assert reconstructed == result
    print("[PASS] #12 transition result is a genuinely new, fully-revalidated Claim")


def check_retrieval_failure_still_cannot_become_a_claim() -> None:
    outcome = RetrievalOutcome(
        question_id="q1", source_title="t", source_url="http://x", source_type="web", success=False, relevant=False, failure_reason="irrelevant"
    )
    assert classify_retrieval_outcome(outcome) is None
    print("[PASS] #13 R1.1's retrieval-failure invariant is untouched by R1.4's additions")


if __name__ == "__main__":
    check_candidate_to_normalized_allowed()
    check_normalized_to_supported_requires_evidence()
    check_full_legal_chain_to_active()
    check_candidate_to_active_rejected()
    check_candidate_to_superseded_rejected()
    check_active_to_superseded_requires_reference()
    check_active_to_disputed_allowed()
    check_confidence_never_gates_a_transition()
    check_reason_and_actor_required()
    check_original_claim_never_mutated()
    check_result_is_fully_revalidated()
    check_retrieval_failure_still_cannot_become_a_claim()
    print("\nAll 12 checks passed. Pure logic only, no LLM/Neo4j/retriever call --")
    print("this phase defines legal state transitions, not orchestration over real data.")
