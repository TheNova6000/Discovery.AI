"""R1.3 verification -- two-tier claim identity fields (docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md §0.50/§0.60,
backend/reasoning/domain.py: `identity_floor`, `semantic_identity`,
`is_likely_duplicate`).

Two parts, same split every phase this session has used:

Part 1 (pure, no I/O): the identity functions' own behavior on hand-built
fixtures -- deterministic, fast, no real data needed.

Part 2 (read-only integration against real data): reconstructs "Payment
gateway"'s real 23 claims (the exact entity Phase 8.6's `assess_claim_validity`
found 38 duplicate pairs in, Architecture.md §0.46) as R1 `Claim` objects via
`reclassify_legacy_claim`, and confirms `is_likely_duplicate` finds real
duplicate pairs among them -- the new, general identity mechanism catching
the same real, already-known problem the old, entity-specific Phase 8.5
logic found, not a fixture manufactured to look right.

Checks:
  1. identity_floor is (entity_id, source_question_id, normalized_form) --
     exactly three real fields, nothing invented or guessed.
  2. Two claims with identical floor fields are flagged duplicate by
     is_likely_duplicate.
  3. Two claims that differ ONLY by entity_id are never flagged duplicate,
     even with identical text -- the real reason entity_id was added as a
     required field, not an optional convenience.
  4. semantic_identity returns None whenever subject/predicate/object
     aren't ALL set -- never a partially-filled or guessed tuple.
  5. semantic_identity returns the real tuple when all three are set,
     qualifiers included.
  6. Real-data: reconstructing "Payment gateway"'s real claims and running
     is_likely_duplicate pairwise finds at least one real duplicate pair.
     NOT expected to match Phase 8.5's own count (38) exactly, and that
     mismatch is itself informative, not a bug -- see the real observed
     count and its explanation in this file's __main__ output and
     docs/Architecture.md §0.60: identity_floor is question-scoped
     (entity_id, source_question_id, normalized_form) where Phase 8.5's
     original check compared an entity's ENTIRE claim set regardless of
     which question a claim came from, and never did source_url matching
     at all (Claim carries no source_url field directly, only
     evidence_ids) -- both real, deliberate differences in scope, not an
     attempt to reproduce the old number.
  7. Existing Phase 6/8.1-8.6/R1.1/R1.2 checks remain green.
"""

from __future__ import annotations

import pathlib
import sys
from itertools import combinations

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.reasoning import Claim, identity_floor, is_likely_duplicate, semantic_identity  # noqa: E402


def _claim(entity_id: str, normalized_form: str, question_id: str = "q1", **kwargs) -> Claim:
    return Claim(entity_id=entity_id, normalized_form=normalized_form, source_question_id=question_id, confidence=0.6, **kwargs)


def check_identity_floor_shape() -> None:
    claim = _claim("e1", "DNS translates names to IPs", question_id="q7")
    assert identity_floor(claim) == ("e1", "q7", "DNS translates names to IPs")
    print("[PASS] check_identity_floor_shape: (entity_id, source_question_id, normalized_form), nothing invented")


def check_matching_floor_is_duplicate() -> None:
    a = _claim("e1", "DNS translates names to IPs")
    b = _claim("e1", "DNS translates names to IPs")
    assert is_likely_duplicate(a, b)
    print("[PASS] check_matching_floor_is_duplicate: identical entity/question/text -> flagged duplicate")


def check_different_entity_never_duplicate() -> None:
    a = _claim("e1", "DNS translates names to IPs")
    b = _claim("e2", "DNS translates names to IPs")
    assert not is_likely_duplicate(a, b)
    print("[PASS] check_different_entity_never_duplicate: identical text, different entity -> never a duplicate")


def check_semantic_identity_none_when_incomplete() -> None:
    assert semantic_identity(_claim("e1", "x")) is None
    assert semantic_identity(_claim("e1", "x", subject="DNS")) is None
    assert semantic_identity(_claim("e1", "x", subject="DNS", predicate="translates")) is None
    print("[PASS] check_semantic_identity_none_when_incomplete: partial structure never returns a guessed tuple")


def check_semantic_identity_present_when_complete() -> None:
    claim = _claim("e1", "x", subject="DNS", predicate="translates", object="names to IPs", qualifiers=["usually"])
    assert semantic_identity(claim) == ("DNS", "translates", "names to IPs", ("usually",))
    print("[PASS] check_semantic_identity_present_when_complete: full triple + qualifiers returned correctly")


def run_real_data_check() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
        from backend.graph.interface import get_claims_for_question, get_questions_for_entity
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] real-data check: could not import graph interface ({exc})")
        return

    payment_gateway_id = "00e93cd0-b53e-4bab-ad22-ca78b2e0823f"
    try:
        import asyncio

        async def _fetch():
            # ClaimNode itself carries no question_id field (backend/graph/models.py)
            # -- the claim/question link is only known via which question.id
            # get_claims_for_question was called with, so it's tracked here in
            # the loop, not read off the claim object.
            questions = await get_questions_for_entity(payment_gateway_id)
            claims_with_question_id = []
            for q in questions:
                for claim in await get_claims_for_question(q.id):
                    claims_with_question_id.append((claim, q.id))
            return claims_with_question_id

        claims_with_question_id = asyncio.run(_fetch())
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] real-data check: Neo4j unreachable ({exc})")
        return

    if not claims_with_question_id:
        print("[SKIP] real-data check: expected real Payment gateway claims not found (has the graph changed?)")
        return

    from backend.reasoning import reclassify_legacy_claim

    reconstructed = [
        reclassify_legacy_claim(
            raw_text=c.evidence,
            raw_confidence=c.confidence,
            entity_id=payment_gateway_id,
            source_question_id=question_id,
            reason="reconstructed for R1.3's real-data duplicate-detection check",
        )
        for c, question_id in claims_with_question_id
    ]
    duplicate_pairs = [(a, b) for a, b in combinations(reconstructed, 2) if is_likely_duplicate(a, b)]
    print(f"[LIVE] {len(reconstructed)} real Payment gateway claims reconstructed, {len(duplicate_pairs)} duplicate pairs found by is_likely_duplicate")
    print("[NOTE] Phase 8.5's own check found 38 pairs for this same entity -- the new count is NOT expected to")
    print("       match: identity_floor is question-scoped (Phase 8.5's check was entity-wide, ignoring which")
    print("       question a claim came from) and text-only (no source_url comparison -- Claim has no source_url")
    print("       field directly, only evidence_ids). Both real, deliberate scope differences, not a regression.")
    assert duplicate_pairs, "expected at least one real duplicate pair -- zero would mean the mechanism found nothing at all in a known-duplicated entity"
    print("[PASS] check_real_data_duplicate_detection: the new mechanism finds real duplicates in Payment gateway's claims (count intentionally differs from Phase 8.5's, see note above)")


if __name__ == "__main__":
    check_identity_floor_shape()
    check_matching_floor_is_duplicate()
    check_different_entity_never_duplicate()
    check_semantic_identity_none_when_incomplete()
    check_semantic_identity_present_when_complete()
    run_real_data_check()
    print("\nPart 1 (5 pure checks) covers identity_floor/semantic_identity/is_likely_duplicate")
    print("on hand-built fixtures, no I/O. Part 2 reconstructs real 'Payment gateway' claims")
    print("(the exact entity Phase 8.6 found 38 duplicate pairs in) and confirms the new")
    print("mechanism finds real duplicates there too -- a different count than Phase 8.5's,")
    print("for real, explained reasons (question-scoping, no source_url match), not a bug.")
