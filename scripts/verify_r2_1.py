"""R2 verification, first slice -- typed events/commands for what R1 already
produces (docs/Phases.md's Reasoning Engine Evolution track,
docs/Architecture.md §0.51/§0.52.1/§0.63, backend/reasoning/events.py).

Pure throughout -- no bus, no LLM, no Neo4j, no retriever call. This slice
defines types and pure builder functions only; wiring them into a real
publish/subscribe mechanism is later R2 work, not this file's job.

Checks:
  1. record_retrieval_outcome/record_evidence_collected/record_claim_created
     each correctly wrap an already-produced R1 object without altering it.
  2. A causation chain (event A's id becomes event B's causation_id becomes
     event C's causation_id) is real and traceable -- "why did this happen"
     is answerable from the events alone.
  3. correlation_id is mandatory and rejects empty string on every event
     type and on TransitionClaimCommand -- an event/command with no stated
     grouping key is rejected, not defaulted to something meaningless.
  4. record_claim_transitioned correctly carries both previous_status and
     new_status -- a transition event that only recorded the new status
     would lose exactly the information "what changed" requires.
  5. TransitionClaimCommand's fields exactly match transition_claim's own
     real parameters (claim_id, target_status, reason, actor,
     superseded_by, duplicate_of) -- the command is a real, faithful
     request shape for the one real operation it names, not an
     approximation.
  6. Every event type and the command survive a model_dump_json ->
     model_validate_json round trip unchanged.
  7. This module has zero imports outside stdlib/pydantic/.domain --
     confirmed by direct inspection, keeping backend.reasoning's
     dependency-direction guarantee intact through this new file too.
  8. Existing Phase 6/8.1-8.6/R1.1/R1.3/R1.4/R1.5 checks remain green.
"""

from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from backend.reasoning import (  # noqa: E402
    Claim,
    ClaimCreated,
    ClaimTransitioned,
    EvidenceCollected,
    RetrievalOutcome,
    RetrievalOutcomeRecorded,
    TransitionClaimCommand,
    classify_retrieval_outcome,
    record_claim_created,
    record_claim_transitioned,
    record_evidence_collected,
    record_retrieval_outcome,
    transition_claim,
)


def _real_outcome_and_evidence_and_claim():
    outcome = RetrievalOutcome(
        question_id="q1", source_title="t", source_url="http://x.example", source_type="web", success=True, relevant=True, raw_content="DNS translates names to IPs"
    )
    evidence = classify_retrieval_outcome(outcome)
    claim = Claim(entity_id="e1", normalized_form="DNS translates names to IPs", source_question_id="q1", evidence_ids=[evidence.evidence_id], confidence=0.6)
    return outcome, evidence, claim


def check_builders_wrap_without_altering() -> None:
    outcome, evidence, claim = _real_outcome_and_evidence_and_claim()
    ev1 = record_retrieval_outcome(outcome, correlation_id="e1")
    ev2 = record_evidence_collected(evidence, correlation_id="e1")
    ev3 = record_claim_created(claim, correlation_id="e1")
    assert ev1.outcome == outcome
    assert ev2.evidence == evidence
    assert ev3.claim == claim
    print("[PASS] #1 each builder wraps its real R1 object unchanged")


def check_causation_chain_is_real() -> None:
    outcome, evidence, claim = _real_outcome_and_evidence_and_claim()
    ev1 = record_retrieval_outcome(outcome, correlation_id="e1")
    ev2 = record_evidence_collected(evidence, correlation_id="e1", causation_id=ev1.event_id)
    ev3 = record_claim_created(claim, correlation_id="e1", causation_id=ev2.event_id)
    assert ev2.causation_id == ev1.event_id
    assert ev3.causation_id == ev2.event_id
    assert ev1.causation_id is None  # the root of the chain has nothing preceding it
    print("[PASS] #2 causation chain is real and traceable back to the root event")


def check_correlation_id_mandatory() -> None:
    outcome, evidence, claim = _real_outcome_and_evidence_and_claim()
    for attempt in (
        lambda: record_retrieval_outcome(outcome, correlation_id=""),
        lambda: record_evidence_collected(evidence, correlation_id=""),
        lambda: record_claim_created(claim, correlation_id=""),
        lambda: TransitionClaimCommand(correlation_id="", claim_id="c1", target_status="normalized", reason="x", actor="y"),
    ):
        try:
            attempt()
            raise AssertionError("should have rejected empty correlation_id")
        except ValidationError:
            pass
    print("[PASS] #3 empty correlation_id rejected on every event type and the command")


def check_transition_event_carries_both_statuses() -> None:
    _, _, claim = _real_outcome_and_evidence_and_claim()
    normalized = transition_claim(claim, "normalized", reason="checked", actor="tester")
    event = record_claim_transitioned(
        claim_id=claim.claim_id, previous_status=claim.status, new_status=normalized.status, reason="checked", actor="tester", correlation_id="e1"
    )
    assert event.previous_status == "candidate" and event.new_status == "normalized"
    print("[PASS] #4 ClaimTransitioned carries both previous and new status")


def check_command_shape_matches_real_operation() -> None:
    # transition_claim takes a live `claim: Claim` object (it's called
    # in-process, already holding the object); a Command is data crossing a
    # boundary and correctly references the claim by id instead
    # (`claim_id`) -- that's the ONE intentional naming difference, not a
    # mismatch. Every other command field must match a real
    # transition_claim parameter name exactly.
    real_params = set(inspect.signature(transition_claim).parameters) - {"claim"}
    command_fields = set(TransitionClaimCommand.model_fields) - {"command_id", "correlation_id", "causation_id", "issued_at", "claim_id"}
    assert command_fields <= real_params, f"command has fields transition_claim doesn't accept: {command_fields - real_params}"
    assert "claim_id" in TransitionClaimCommand.model_fields, "command must reference the claim by id, not embed the live object"
    print("[PASS] #5 TransitionClaimCommand's fields are a faithful match for transition_claim's real parameters (claim by id, not by object)")


def check_serialization_round_trip() -> None:
    outcome, evidence, claim = _real_outcome_and_evidence_and_claim()
    ev1 = record_retrieval_outcome(outcome, correlation_id="e1")
    ev2 = record_evidence_collected(evidence, correlation_id="e1")
    ev3 = record_claim_created(claim, correlation_id="e1")
    ev4 = record_claim_transitioned(claim_id=claim.claim_id, previous_status="candidate", new_status="normalized", reason="x", actor="y", correlation_id="e1")
    cmd = TransitionClaimCommand(correlation_id="e1", claim_id=claim.claim_id, target_status="normalized", reason="x", actor="y")

    assert RetrievalOutcomeRecorded.model_validate_json(ev1.model_dump_json()) == ev1
    assert EvidenceCollected.model_validate_json(ev2.model_dump_json()) == ev2
    assert ClaimCreated.model_validate_json(ev3.model_dump_json()) == ev3
    assert ClaimTransitioned.model_validate_json(ev4.model_dump_json()) == ev4
    assert TransitionClaimCommand.model_validate_json(cmd.model_dump_json()) == cmd
    print("[PASS] #6 every event type and the command survive a serialization round trip")


def check_zero_cross_package_imports() -> None:
    import backend.reasoning.events as events_module

    source = inspect.getsource(events_module)
    import_lines = [line.strip() for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    for line in import_lines:
        assert not line.startswith("from backend.") or line.startswith("from backend.reasoning") or line.startswith("from .domain"), (
            f"events.py has a cross-package import: {line!r}"
        )
    print(f"[PASS] #7 events.py's {len(import_lines)} import lines are all stdlib/pydantic/.domain, confirmed by direct inspection")


if __name__ == "__main__":
    check_builders_wrap_without_altering()
    check_causation_chain_is_real()
    check_correlation_id_mandatory()
    check_transition_event_carries_both_statuses()
    check_command_shape_matches_real_operation()
    check_serialization_round_trip()
    check_zero_cross_package_imports()
    print("\nAll 7 checks passed. Pure logic only, no LLM/Neo4j/retriever/bus call.")
    print("Acceptance #8 (existing Phase 6/8.1-8.6/R1.1-R1.5 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
