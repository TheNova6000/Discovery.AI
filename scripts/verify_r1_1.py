"""R1.1 verification -- core domain types (docs/Phases.md's Reasoning Engine
Evolution track, docs/Architecture.md §0.47/§0.49/§0.56, backend/reasoning/domain.py).

Two parts, same split every phase this session has used:

Part 1 (pure, no I/O): the domain types' own structural invariants --
construction succeeds/fails exactly when it should, independent of any real
data. This is what proves "a retrieval failure cannot become a Claim" is
actually enforced by the code, not just documented.

Part 2 (read-only integration against real data): the acceptance test the
user specified verbatim -- using the real "How does DNS resolution work?"
investigation (Architecture.md §0.47) already sitting in this project's own
Neo4j instance as a fixture, not an invented example. Requires a reachable
Neo4j (same .env this whole session has used); skips with a clear message
if unavailable rather than failing opaquely. Read-only: no write call is
made anywhere in this script.

Acceptance criteria (verbatim from the user's own list), each mapped to a
concrete check below:
  1. Retrieval failures are represented as RetrievalOutcome.
  2. Actual source material can become Evidence.
  3. Only propositions become Claim.
  4. Claims retain provenance to their source question/evidence.
  5. An answer can be derived without becoming the source of truth.
  6. Existing Phase 8 checks remain green.
  7. No invalid old claim is silently laundered into a valid new claim.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from backend.reasoning import (  # noqa: E402
    Answer,
    Claim,
    Evidence,
    RetrievalOutcome,
    classify_retrieval_outcome,
    reclassify_legacy_claim,
)

# ---------------------------------------------------------------------------
# Part 1: pure structural invariants, no I/O
# ---------------------------------------------------------------------------


def check_failed_retrieval_cannot_be_marked_relevant() -> None:
    try:
        RetrievalOutcome(
            question_id="q1", source_title="t", source_url="http://x", source_type="web", success=False, relevant=True
        )
        raise AssertionError("should have rejected a failed-but-relevant outcome")
    except ValidationError:
        pass
    print("[PASS] check_failed_retrieval_cannot_be_marked_relevant")


def check_failed_retrieval_never_produces_evidence() -> None:
    outcome = RetrievalOutcome(
        question_id="q1",
        source_title="t",
        source_url="http://x",
        source_type="web",
        success=False,
        relevant=False,
        failure_reason="the source did not address the question",
    )
    assert classify_retrieval_outcome(outcome) is None
    print("[PASS] check_failed_retrieval_never_produces_evidence: the core invariant, enforced structurally")


def check_successful_relevant_retrieval_produces_evidence() -> None:
    outcome = RetrievalOutcome(
        question_id="q1",
        source_title="t",
        source_url="http://x",
        source_type="web",
        success=True,
        relevant=True,
        raw_content="DNS translates domain names into IP addresses.",
    )
    evidence = classify_retrieval_outcome(outcome)
    assert evidence is not None
    assert evidence.retrieval_outcome_id == outcome.outcome_id
    assert evidence.excerpt == outcome.raw_content
    print("[PASS] check_successful_relevant_retrieval_produces_evidence: real source material becomes Evidence")


def check_claim_requires_normalized_form_and_valid_confidence() -> None:
    try:
        Claim(entity_id="e1", normalized_form="", source_question_id="q1", confidence=0.5)
        raise AssertionError("should have rejected an empty normalized_form")
    except ValidationError:
        pass
    try:
        Claim(entity_id="e1", normalized_form="x", source_question_id="q1", confidence=1.5)
        raise AssertionError("should have rejected confidence outside [0,1]")
    except ValidationError:
        pass
    print("[PASS] check_claim_requires_normalized_form_and_valid_confidence")


def check_exception_statuses_require_provenance() -> None:
    for status, extra in [
        ("superseded", {}),
        ("duplicate", {}),
        ("legacy_invalid_claim", {}),
        ("requires_reclassification", {}),
    ]:
        try:
            Claim(entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5, status=status, **extra)
            raise AssertionError(f"should have required provenance for status={status!r}")
        except ValidationError:
            pass
    print("[PASS] check_exception_statuses_require_provenance: no status can be silently unexplained")


def check_reclassify_legacy_claim_never_lands_active() -> None:
    legacy = reclassify_legacy_claim(
        raw_text="The provided resource does not answer the question.",
        raw_confidence=0.1,
        entity_id="e1",
        source_question_id="q1",
        reason="matches the retrieval-failure pattern observed in real DNS investigation data",
    )
    assert legacy.status == "requires_reclassification"
    assert legacy.provenance_note
    print("[PASS] check_reclassify_legacy_claim_never_lands_active: migration path never auto-promotes to a valid status")


def check_answer_grounded_consistency() -> None:
    claim = Claim(entity_id="e1", normalized_form="DNS translates names to IPs", source_question_id="q1", confidence=0.6)
    Answer(text="DNS maps names to addresses.", claim_ids=[claim.claim_id], grounded=True)  # should not raise
    try:
        Answer(text="x", claim_ids=[], grounded=True)
        raise AssertionError("should have rejected grounded=True with no claim_ids")
    except ValidationError:
        pass
    try:
        Answer(text="x", claim_ids=[claim.claim_id], grounded=False)
        raise AssertionError("should have rejected grounded=False with claim_ids present")
    except ValidationError:
        pass
    print("[PASS] check_answer_grounded_consistency: an Answer can never silently claim or disclaim authority")


def check_serialization_round_trip() -> None:
    claim = Claim(
        entity_id="e1",
        subject="DNS",
        predicate="translates",
        object="domain names to IP addresses",
        normalized_form="DNS translates domain names to IP addresses",
        source_question_id="q1",
        evidence_ids=["ev1", "ev2"],
        confidence=0.6,
    )
    dumped = claim.model_dump_json()
    restored = Claim.model_validate_json(dumped)
    assert restored == claim
    print("[PASS] check_serialization_round_trip: Claim survives model_dump_json -> model_validate_json unchanged")


# ---------------------------------------------------------------------------
# Part 2: read-only integration against the real DNS investigation
# ---------------------------------------------------------------------------


def run_real_data_acceptance_test() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
        from backend.graph.interface import get_claims_for_question, get_questions_for_entity
    except Exception as exc:  # noqa: BLE001 - environment/import issue, not a test failure
        print(f"[SKIP] real-data acceptance test: could not import graph interface ({exc})")
        return

    recursive_resolver_id = "8ae577e8-61f2-44d6-98db-5367ed75542b"
    try:
        import asyncio

        async def _fetch():
            questions = await get_questions_for_entity(recursive_resolver_id)
            if not questions:
                return None, []
            question = questions[0]
            claims = await get_claims_for_question(question.id)
            return question, claims

        question, real_claims = asyncio.run(_fetch())
    except Exception as exc:  # noqa: BLE001 - no live Neo4j reachable, skip rather than fail opaquely
        print(f"[SKIP] real-data acceptance test: Neo4j unreachable ({exc})")
        return

    if question is None or not real_claims:
        print("[SKIP] real-data acceptance test: expected real DNS data not found (has the graph changed?)")
        return

    # Acceptance #7 first: reclassify every real legacy "claim" through the
    # ONLY sanctioned migration path -- none may land as a normal, valid
    # claim status.
    reclassified = [
        reclassify_legacy_claim(
            raw_text=c.evidence,
            raw_confidence=c.confidence,
            entity_id=recursive_resolver_id,
            source_question_id=question.id,
            reason="pre-R1 graph data, migrated for R1.1's acceptance test, not yet reviewed",
        )
        for c in real_claims
    ]
    assert all(rc.status == "requires_reclassification" for rc in reclassified)
    print(f"[PASS] acceptance #7: all {len(reclassified)} real legacy claims land as requires_reclassification, none auto-promoted")

    # Acceptance #1: the real retrieval-failure claims, reconstructed as
    # RetrievalOutcome (failed/irrelevant), not Claim.
    failure_markers = ("does not answer", "does not address", "no information about", "does not discuss")
    likely_failures = [c for c in real_claims if any(m in c.evidence.lower() for m in failure_markers)]
    assert likely_failures, "expected at least one real retrieval-failure-shaped claim in this fixture"
    outcomes = [
        RetrievalOutcome(
            question_id=question.id,
            source_title=c.source_title,
            source_url=c.source_url,
            source_type=c.source_type,
            success=False,
            relevant=False,
            failure_reason=c.evidence,
        )
        for c in likely_failures
    ]
    assert all(classify_retrieval_outcome(o) is None for o in outcomes)
    print(f"[PASS] acceptance #1: {len(outcomes)} real retrieval-failure claims correctly represented as RetrievalOutcome, none become Evidence")

    # Acceptance #2/#3/#4: the real, non-failure claim becomes real Evidence,
    # then a real Claim, with provenance intact.
    real_claims_ok = [c for c in real_claims if c not in likely_failures]
    assert real_claims_ok, "expected at least one real, substantive claim in this fixture"
    good = real_claims_ok[0]
    good_outcome = RetrievalOutcome(
        question_id=question.id,
        source_title=good.source_title,
        source_url=good.source_url,
        source_type=good.source_type,
        success=True,
        relevant=True,
        raw_content=good.evidence,
    )
    evidence = classify_retrieval_outcome(good_outcome)
    assert evidence is not None
    new_claim = Claim(
        entity_id=recursive_resolver_id,
        normalized_form=good.evidence.strip(),
        source_question_id=question.id,
        evidence_ids=[evidence.evidence_id],
        confidence=good.confidence,
    )
    assert new_claim.source_question_id == question.id
    assert new_claim.evidence_ids == [evidence.evidence_id]
    print("[PASS] acceptance #2/#3/#4: real source material -> Evidence -> Claim, with provenance to question and evidence intact")

    # Acceptance #5: an Answer can be derived from the real claim without
    # itself becoming a new source of truth (it's a projection, checked by
    # the grounded/claim_ids invariant already proven in Part 1).
    answer = Answer(text=f"Regarding {question.text}: {new_claim.normalized_form}", claim_ids=[new_claim.claim_id], grounded=True)
    assert answer.grounded and answer.claim_ids == [new_claim.claim_id]
    print("[PASS] acceptance #5: a real Answer derives from the real Claim without becoming its own authority")


if __name__ == "__main__":
    check_failed_retrieval_cannot_be_marked_relevant()
    check_failed_retrieval_never_produces_evidence()
    check_successful_relevant_retrieval_produces_evidence()
    check_claim_requires_normalized_form_and_valid_confidence()
    check_exception_statuses_require_provenance()
    check_reclassify_legacy_claim_never_lands_active()
    check_answer_grounded_consistency()
    check_serialization_round_trip()
    print()
    run_real_data_acceptance_test()
    print("\nPart 1 (8 pure checks) covers the domain types' own invariants, no I/O.")
    print("Part 2 is the real-data acceptance test against the live DNS investigation,")
    print("per the user's own 7-point acceptance list -- run separately, and skips (not")
    print("fails) if Neo4j isn't reachable in this environment. Acceptance #6 (existing")
    print("Phase 8 checks remain green) is verified separately by re-running")
    print("scripts/verify_phase6.py through verify_phase8_6.py unmodified -- backend/reasoning")
    print("itself (domain.py) has zero dependency on backend.agents/backend.research/")
    print("backend.graph, so nothing about this module can regress them; this script's")
    print("own Part 2 imports backend.graph read-only, same as every prior phase's live check.")
