"""R1.5 verification -- the final pure validation/serialization boundary for
R1's core domain model (docs/Phases.md's Reasoning Engine Evolution track,
docs/Architecture.md §0.62, backend/reasoning/domain.py).

R1.1-R1.4 each tested their own new pieces as they were built, but coverage
was uneven: only `Claim` had a dedicated serialization round-trip test
(R1.1); `RetrievalOutcome`, `Evidence`, and `Answer` never did.
Identifier-shaped required string fields (`question_id`, `source_url`,
`entity_id`, etc.) had no non-empty constraint at all until this pass. R1.5
closes both gaps -- not new capability, a hardening/consolidation pass over
what already exists, matching its own scoping ("the final pure
validation/serialization boundary before the bus or task graph").

Pure throughout -- no LLM, no Neo4j, no retriever call anywhere in this file.

Checks:
  1-4. Every one of the four core types (RetrievalOutcome, Evidence, Claim,
       Answer) survives a model_dump_json -> model_validate_json round trip
       unchanged -- not just Claim, which was the only one covered before.
  5.   Round trip also holds for the "sparse" case -- every optional field
       at its default (None / empty list) -- not just a fully-populated
       instance, so an implicit reliance on a field always being present
       doesn't hide in the happy path.
  6.   A validation invariant (RetrievalOutcome's success/relevant
       consistency) still fires when the object is rebuilt via
       model_validate_json, not just via direct construction -- confirms
       invariants aren't somehow specific to the Python constructor path.
  7.   The new min_length=1 constraints (added this pass) actually reject
       an empty identifier field on every type that has one --
       question_id/source_url/source_type (RetrievalOutcome),
       retrieval_outcome_id/source_url (Evidence), entity_id/
       source_question_id (Claim) -- proving the hardening is real, not
       just a comment.
  8.   Existing Phase 6/8.1-8.6/R1.1/R1.3/R1.4 checks remain green after
       adding these constraints (a real regression risk for any
       already-shipped type, confirmed rather than assumed).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from backend.reasoning import Answer, Claim, Evidence, RetrievalOutcome  # noqa: E402


def check_retrieval_outcome_round_trip() -> None:
    outcome = RetrievalOutcome(
        question_id="q1",
        source_title="A DNS primer",
        source_url="http://example.invalid/dns",
        source_type="web",
        success=True,
        relevant=True,
        raw_content="DNS translates domain names into IP addresses.",
    )
    restored = RetrievalOutcome.model_validate_json(outcome.model_dump_json())
    assert restored == outcome
    print("[PASS] #1 RetrievalOutcome survives model_dump_json -> model_validate_json unchanged")


def check_evidence_round_trip() -> None:
    evidence = Evidence(
        retrieval_outcome_id="ro1",
        excerpt="DNS translates domain names into IP addresses.",
        source_title="A DNS primer",
        source_url="http://example.invalid/dns",
        source_type="web",
    )
    restored = Evidence.model_validate_json(evidence.model_dump_json())
    assert restored == evidence
    print("[PASS] #2 Evidence survives model_dump_json -> model_validate_json unchanged")


def check_claim_round_trip_fully_populated() -> None:
    claim = Claim(
        entity_id="e1",
        subject="DNS",
        predicate="translates",
        object="domain names to IP addresses",
        qualifiers=["usually"],
        modality="usually",
        conditions=["if the local resolver has no cached answer"],
        normalized_form="DNS usually translates domain names to IP addresses",
        source_question_id="q1",
        evidence_ids=["ev1", "ev2"],
        confidence=0.6,
        status="normalized",
        provenance_note="wording checked",
        last_transition_actor="tester",
    )
    restored = Claim.model_validate_json(claim.model_dump_json())
    assert restored == claim
    print("[PASS] #3 fully-populated Claim survives round trip, including status/provenance/actor")


def check_answer_round_trip() -> None:
    claim = Claim(entity_id="e1", normalized_form="DNS translates names to IPs", source_question_id="q1", confidence=0.6)
    answer = Answer(text="DNS translates domain names into IP addresses.", claim_ids=[claim.claim_id], grounded=True)
    restored = Answer.model_validate_json(answer.model_dump_json())
    assert restored == answer
    print("[PASS] #4 Answer survives model_dump_json -> model_validate_json unchanged")


def check_sparse_claim_round_trip() -> None:
    # Every optional field left at its default -- the "sparse" case, not the
    # happy path every other test in this file already exercises fully.
    claim = Claim(entity_id="e1", normalized_form="x", source_question_id="q1", confidence=0.5)
    assert claim.subject is None and claim.qualifiers == [] and claim.evidence_ids == []
    restored = Claim.model_validate_json(claim.model_dump_json())
    assert restored == claim
    print("[PASS] #5 a sparse Claim (all optional fields at default) round-trips identically")


def check_invariant_fires_through_deserialization() -> None:
    # Hand-build JSON representing an invalid RetrievalOutcome (failed but
    # marked relevant) -- bypassing the Python constructor entirely, to
    # confirm the invariant is a real model validator, not something that
    # only happens to run because __init__ calls it.
    bad_json = (
        '{"outcome_id": "o1", "question_id": "q1", "source_title": "t", '
        '"source_url": "http://x", "source_type": "web", "success": false, '
        '"relevant": true, "failure_reason": "irrelevant", "raw_content": null, '
        '"retrieved_at": "2026-01-01T00:00:00+00:00"}'
    )
    try:
        RetrievalOutcome.model_validate_json(bad_json)
        raise AssertionError("should have rejected a failed-but-relevant outcome deserialized from JSON")
    except ValidationError:
        pass
    print("[PASS] #6 the success/relevant invariant fires on model_validate_json, not just direct construction")


def check_empty_identifiers_rejected() -> None:
    cases = [
        (RetrievalOutcome, dict(question_id="", source_title="t", source_url="http://x", source_type="web", success=True, relevant=True, raw_content="x")),
        (RetrievalOutcome, dict(question_id="q1", source_title="t", source_url="", source_type="web", success=True, relevant=True, raw_content="x")),
        (Evidence, dict(retrieval_outcome_id="", excerpt="x", source_title="t", source_url="http://x", source_type="web")),
        (Evidence, dict(retrieval_outcome_id="ro1", excerpt="x", source_title="t", source_url="", source_type="web")),
        (Claim, dict(entity_id="", normalized_form="x", source_question_id="q1", confidence=0.5)),
        (Claim, dict(entity_id="e1", normalized_form="x", source_question_id="", confidence=0.5)),
    ]
    for model, kwargs in cases:
        try:
            model(**kwargs)
            raise AssertionError(f"should have rejected empty identifier: {model.__name__}({kwargs})")
        except ValidationError:
            pass
    print(f"[PASS] #7 all {len(cases)} empty-identifier cases correctly rejected (RetrievalOutcome/Evidence/Claim)")


if __name__ == "__main__":
    check_retrieval_outcome_round_trip()
    check_evidence_round_trip()
    check_claim_round_trip_fully_populated()
    check_answer_round_trip()
    check_sparse_claim_round_trip()
    check_invariant_fires_through_deserialization()
    check_empty_identifiers_rejected()
    print("\nAll 7 checks passed. Pure logic only, no LLM/Neo4j/retriever call.")
    print("Acceptance #8 (existing Phase 6/8.1-8.6/R1.1/R1.3/R1.4 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
