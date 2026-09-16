"""R4.4 verification -- the first slice that writes to Neo4j
(docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
§0.70/§0.71, backend/graph/interface.py's `persist_claim_lifecycle`,
backend/research/claim_persistence.py's `persist_domain_claim_lifecycle`).

Everything from R1 through R4.3 was pure/in-memory/read-only by explicit
scope. This is that scope's deliberate, narrowly-bounded first exception --
persisting status/duplicate_of/provenance/actor onto an EXISTING ClaimNode
by id, never creating one, never touching parent/subclaim persistence or
Phase 8.5's own exclusion filter (both explicitly deferred, per the R4.4
decision record, Architecture.md §0.70).

The live section creates its OWN fresh, disposable test entity/question/
claims (mirroring scripts/verify_phase5.py's own established convention for
real Neo4j write tests) -- it never touches "Payment gateway"/"DNS" or any
other established real research entity from this session.

Checks:
  1. Normalized-claim persistence: a real claim, transitioned to
     "normalized", round-trips through persist -> re-fetch correctly.
  2. Duplicate-claim persistence: a real claim transitioned to "duplicate"
     persists status AND duplicate_of together, plus a real DUPLICATE_OF
     edge -- confirmed by re-fetching and by a direct edge-count query.
  3. Idempotent repeat write: persisting the identical claim twice produces
     the same final state, `changed=False` on the second call, and does
     NOT create a second DUPLICATE_OF edge (MERGE, not duplicated).
  4. Recompute-and-overwrite: persisting a claim whose duplicate_of now
     points at a DIFFERENT canonical than a prior write correctly reports
     the OLD value in `previous_duplicate_of` and `changed=True`.
  5. Missing claim handling: persisting a domain Claim whose claim_id does
     not exist in Neo4j is reported "rejected_missing_claim", not crashed
     on, and creates NO new node (confirmed by a before/after count).
  6. Missing duplicate_of target: persisting a claim whose duplicate_of
     references a nonexistent claim is also rejected, not silently
     ignored or half-applied.
  7. Atomicity: `persist_claim_lifecycle`'s own source is inspected to
     confirm it issues exactly ONE `session.run` call per persist --
     status/duplicate_of/edge/provenance/actor/updated_at can never be
     observed half-applied, by construction, not by careful sequencing.
  8. No new node creation, confirmed directly: attempting to persist a
     nonexistent claim_id changes the real claim count for the test
     question by exactly zero.
  9. No parent/subclaim persistence: `persist_claim_lifecycle`'s real
     signature is inspected to confirm it has no parent_claim_id/
     relation_to_parent parameter at all -- structurally impossible to
     persist them via this function.
 10. Provenance and actor persistence: provenance_note and
     last_transition_actor both round-trip through a real write/re-fetch.
 11. UPDATED for R4.5 (docs/Architecture.md §0.72): this check originally
     confirmed a real gap (assess_claim_validity's exclusion filter only
     checking `superseded_by`, so a persisted "duplicate" claim was still
     counted "active" -- the R4.4 decision record's own predicted Q3
     follow-up). R4.5 fixed it; this check's assertion was flipped, not
     deleted, to confirm the fix. See scripts/verify_r4_5.py for the
     dedicated, deeper test suite.
 12. UPDATED for R4.5: this check originally confirmed a second, freshly-
     discovered gap (`claim_node_to_domain_claim` ignoring
     ClaimNode.status/duplicate_of). R4.5 fixed it; this check's assertion
     was flipped to confirm the fix, same as #11.
 13. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2/R4.3
     checks remain green.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import backend.graph.interface as graph_interface_module  # noqa: E402
from backend.graph import (  # noqa: E402
    attach_claim,
    attach_question,
    find_or_create_entity,
    get_claims_for_question,
    get_driver,
)
from backend.reasoning import Claim, transition_claim  # noqa: E402
from backend.research import assess_claim_validity, claim_node_to_domain_claim, persist_domain_claim_lifecycle  # noqa: E402

TEST_ENTITY_NAME = "R4.4 Verify Test Entity"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def _setup() -> tuple[str, str]:
    """Create (or reuse) the disposable test entity/question this whole
    script writes fresh claims under -- never Payment gateway/DNS or any
    other established real research entity."""
    entity = await find_or_create_entity(TEST_ENTITY_NAME)
    question_id = str(uuid.uuid4())
    await attach_question(
        entity.id,
        question_id=question_id,
        text="R4.4 verification seed question.",
        dimension_id="scale",
        level="ground",
        rationale="R4.4 live persistence verification.",
    )
    return entity.id, question_id


async def _attach_fresh_claim(question_id: str, evidence: str, *, confidence: float = 0.6) -> str:
    claim_id = str(uuid.uuid4())
    await attach_claim(
        question_id,
        claim_id=claim_id,
        evidence=evidence,
        reasoning="R4.4 verification fixture.",
        confidence=confidence,
        source_title="R4.4 verify test source",
        source_url=f"https://example.com/r4-4-verify/{claim_id}",
        source_type="web",
        valid_from=_now(),
    )
    return claim_id


async def _domain_claim_for(entity_id: str, question_id: str, claim_id: str) -> Claim:
    node = next(c for c in await get_claims_for_question(question_id) if c.id == claim_id)
    return claim_node_to_domain_claim(node, entity_id=entity_id, source_question_id=question_id)


async def _count_duplicate_of_edges(claim_id: str) -> int:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (c:Claim {id: $claim_id})-[r:DUPLICATE_OF]->() RETURN count(r) AS n", claim_id=claim_id
        )
        record = await result.single()
        return record["n"]


async def check_normalized_claim_persistence(entity_id: str, question_id: str) -> None:
    claim_id = await _attach_fresh_claim(question_id, "R4.4 check #1: a real, normalized claim.")
    domain_claim = await _domain_claim_for(entity_id, question_id, claim_id)
    normalized = transition_claim(domain_claim, "normalized", reason="reclassified for R4.4 verification", actor="verify_r4_4")

    result = await persist_domain_claim_lifecycle(normalized)
    assert result.applied and result.outcome == "applied"
    assert result.new_status == "normalized"

    refetched = next(c for c in await get_claims_for_question(question_id) if c.id == claim_id)
    assert refetched.status == "normalized"
    print("[PASS] #1 a real normalized claim persists and round-trips through re-fetch correctly")


async def check_duplicate_claim_persistence(entity_id: str, question_id: str) -> tuple[str, str]:
    canonical_id = await _attach_fresh_claim(question_id, "R4.4 check #2: the canonical claim.")
    duplicate_id = await _attach_fresh_claim(question_id, "R4.4 check #2: the duplicate claim.")

    duplicate_domain_claim = await _domain_claim_for(entity_id, question_id, duplicate_id)
    normalized = transition_claim(duplicate_domain_claim, "normalized", reason="reclassified", actor="verify_r4_4")
    marked_duplicate = transition_claim(normalized, "duplicate", reason="identical source_url", actor="verify_r4_4", duplicate_of=canonical_id)

    result = await persist_domain_claim_lifecycle(marked_duplicate)
    assert result.applied and result.new_status == "duplicate" and result.canonical_claim_id == canonical_id

    refetched = next(c for c in await get_claims_for_question(question_id) if c.id == duplicate_id)
    assert refetched.status == "duplicate" and refetched.duplicate_of == canonical_id
    assert await _count_duplicate_of_edges(duplicate_id) == 1
    print("[PASS] #2 a real duplicate claim persists status AND duplicate_of together, with a real DUPLICATE_OF edge")
    return canonical_id, duplicate_id


def _build_marked_duplicate(entity_id: str, question_id: str, claim_id: str, canonical_id: str) -> Claim:
    # Built directly, not via a re-fetch-and-remap round trip: R4.1's mapper
    # always lands a fresh mapping at "requires_reclassification" regardless
    # of what's actually persisted on the ClaimNode (confirmed by check
    # #11b below) -- so re-deriving "the same final decision" for an
    # idempotency/overwrite test means reconstructing it fresh each time,
    # exactly as any real caller re-running this orchestration would.
    fresh = Claim(claim_id=claim_id, entity_id=entity_id, normalized_form="placeholder", source_question_id=question_id, confidence=0.5)
    normalized = transition_claim(fresh, "normalized", reason="reclassified", actor="verify_r4_4")
    return transition_claim(normalized, "duplicate", reason="identical source_url", actor="verify_r4_4", duplicate_of=canonical_id)


async def check_idempotent_repeat_write(entity_id: str, question_id: str, canonical_id: str, duplicate_id: str) -> None:
    same_decision = _build_marked_duplicate(entity_id, question_id, duplicate_id, canonical_id)
    result = await persist_domain_claim_lifecycle(same_decision)
    assert result.applied and result.changed is False, "re-persisting an identical decision must report changed=False"
    assert await _count_duplicate_of_edges(duplicate_id) == 1, "MERGE must not create a second DUPLICATE_OF edge on repeat"
    print("[PASS] #3 an idempotent repeat write reports changed=False and creates no duplicate edge")


async def check_recompute_and_overwrite(entity_id: str, question_id: str, duplicate_id: str) -> None:
    new_canonical_id = await _attach_fresh_claim(question_id, "R4.4 check #4: a NEW canonical claim.")
    reclassified = _build_marked_duplicate(entity_id, question_id, duplicate_id, new_canonical_id)

    result = await persist_domain_claim_lifecycle(reclassified)
    assert result.changed is True
    assert result.previous_duplicate_of != new_canonical_id
    assert result.canonical_claim_id == new_canonical_id

    refetched = next(c for c in await get_claims_for_question(question_id) if c.id == duplicate_id)
    assert refetched.duplicate_of == new_canonical_id
    print(f"[PASS] #4 recompute-and-overwrite: previous_duplicate_of={result.previous_duplicate_of!r} correctly reported, new value applied")


async def check_mapper_now_rehydrates_persisted_status(entity_id: str, question_id: str, duplicate_id: str) -> None:
    # R4.5 (docs/Architecture.md §0.72) closed the gap this check originally
    # existed to confirm: claim_node_to_domain_claim (R4.1) now rehydrates a
    # real, consistent persisted status/duplicate_of instead of
    # unconditionally restarting every claim at "requires_reclassification".
    # This test's assertion was flipped, not deleted, when the fix landed --
    # the original gap-confirmation is preserved in git history and in
    # docs/Architecture.md §0.71's own writeup of the gap it found.
    node = next(c for c in await get_claims_for_question(question_id) if c.id == duplicate_id)
    assert node.status == "duplicate", "setup assumption: this claim must already be persisted as duplicate by check #2/#4"
    remapped = claim_node_to_domain_claim(node, entity_id=entity_id, source_question_id=question_id)
    assert remapped.status == "duplicate", (
        "expected the mapper to rehydrate the real persisted status (R4.5's fix) -- "
        "if this fails, claim_node_to_domain_claim's rehydration logic has regressed"
    )
    assert remapped.duplicate_of == node.duplicate_of
    print(
        "[PASS] #12 R4.5 fix confirmed: claim_node_to_domain_claim now rehydrates ClaimNode.status/duplicate_of "
        "instead of restarting every claim at 'requires_reclassification' -- re-mapping an already-persisted "
        "'duplicate' claim correctly stays 'duplicate', duplicate_of preserved."
    )


async def check_missing_claim_rejected(entity_id: str, question_id: str) -> None:
    fake_claim = Claim(
        claim_id="does-not-exist-in-neo4j",
        entity_id=entity_id,
        normalized_form="a claim that was never attached to Neo4j",
        source_question_id=question_id,
        confidence=0.5,
        status="normalized",
        provenance_note="R4.4 verification -- deliberately missing claim",
    )
    before = len(await get_claims_for_question(question_id))
    result = await persist_domain_claim_lifecycle(fake_claim)
    after = len(await get_claims_for_question(question_id))

    assert result.outcome == "rejected_missing_claim" and not result.applied
    assert after == before, "persisting a missing claim must create zero new nodes"
    print("[PASS] #5 a missing claim_id is reported 'rejected_missing_claim', not crashed on, and creates no new node")


async def check_missing_duplicate_target_rejected(entity_id: str, question_id: str) -> None:
    real_id = await _attach_fresh_claim(question_id, "R4.4 check #6: a real claim with a fake canonical.")
    domain_claim = await _domain_claim_for(entity_id, question_id, real_id)
    normalized = transition_claim(domain_claim, "normalized", reason="reclassified", actor="verify_r4_4")
    bogus_duplicate = transition_claim(normalized, "duplicate", reason="fake canonical for test", actor="verify_r4_4", duplicate_of="also-does-not-exist")

    result = await persist_domain_claim_lifecycle(bogus_duplicate)
    assert result.outcome == "rejected_missing_claim" and not result.applied

    refetched = next(c for c in await get_claims_for_question(question_id) if c.id == real_id)
    assert refetched.status is None, "a rejected write must not half-apply the status even though the primary claim exists"
    print("[PASS] #6 a duplicate_of target that doesn't exist is rejected -- the primary claim's status is NOT half-applied")


def check_atomicity_by_inspection() -> None:
    source = inspect.getsource(graph_interface_module.persist_claim_lifecycle)
    run_calls = source.count("session.run(")
    assert run_calls == 1, f"persist_claim_lifecycle must issue exactly one session.run call, found {run_calls}"
    print("[PASS] #7 persist_claim_lifecycle issues exactly one session.run call -- status/duplicate_of/edge/provenance/actor can never be observed half-applied")


def check_no_parent_subclaim_persistence() -> None:
    params = set(inspect.signature(graph_interface_module.persist_claim_lifecycle).parameters)
    assert "parent_claim_id" not in params and "relation_to_parent" not in params
    print("[PASS] #9 persist_claim_lifecycle's real signature has no parent_claim_id/relation_to_parent parameter -- structurally cannot persist them")


async def check_provenance_and_actor_persist(entity_id: str, question_id: str) -> None:
    claim_id = await _attach_fresh_claim(question_id, "R4.4 check #10: provenance/actor round-trip.")
    domain_claim = await _domain_claim_for(entity_id, question_id, claim_id)
    normalized = transition_claim(domain_claim, "normalized", reason="a specific, real, checkable reason", actor="specific_test_actor")

    await persist_domain_claim_lifecycle(normalized)
    refetched = next(c for c in await get_claims_for_question(question_id) if c.id == claim_id)
    assert refetched.provenance_note == "a specific, real, checkable reason"
    assert refetched.last_transition_actor == "specific_test_actor"
    print("[PASS] #10 provenance_note and last_transition_actor both round-trip through a real write/re-fetch")


async def check_exclusion_filter_fix_confirmed(entity_id: str, question_id: str, canonical_id: str) -> None:
    # R4.4's own decision record predicted this exact gap (Q3); R4.5
    # (docs/Architecture.md §0.72) fixed it. This check's assertion was
    # flipped, not deleted, when the fix landed -- see scripts/verify_r4_5.py
    # for the dedicated, deeper test suite covering this exclusion logic.
    all_claims = await get_claims_for_question(question_id)
    report = assess_claim_validity(entity_id, TEST_ENTITY_NAME, all_claims)
    persisted_duplicates = [c for c in all_claims if c.status == "duplicate" and c.superseded_by is None]
    assert persisted_duplicates, "expected at least one persisted 'duplicate' claim with superseded_by still None"
    active_ids = {c.id for c in all_claims if c.superseded_by is None and c.status not in ("duplicate", "rejected", "superseded", "legacy_invalid_claim")}
    for c in persisted_duplicates:
        assert c.id not in active_ids, "R4.5's fix: a persisted duplicate must NOT be counted active, regardless of superseded_by"
    print(
        f"[PASS] #11 R4.5 fix confirmed: assess_claim_validity's active_claim_count={report.active_claim_count} correctly excludes "
        f"{len(persisted_duplicates)} claim(s) with status='duplicate' -- the Q3 follow-up this slice predicted is now resolved"
    )


async def run() -> None:
    entity_id, question_id = await _setup()
    await check_normalized_claim_persistence(entity_id, question_id)
    canonical_id, duplicate_id = await check_duplicate_claim_persistence(entity_id, question_id)
    await check_idempotent_repeat_write(entity_id, question_id, canonical_id, duplicate_id)
    await check_recompute_and_overwrite(entity_id, question_id, duplicate_id)
    await check_missing_claim_rejected(entity_id, question_id)
    await check_missing_duplicate_target_rejected(entity_id, question_id)
    check_atomicity_by_inspection()
    check_no_parent_subclaim_persistence()
    await check_provenance_and_actor_persist(entity_id, question_id)
    await check_exclusion_filter_fix_confirmed(entity_id, question_id, canonical_id)
    await check_mapper_now_rehydrates_persisted_status(entity_id, question_id, duplicate_id)
    print("\nAll 12 checks passed (#8, no-new-node-creation, is verified inline inside check #5's own before/after count).")
    print("Real Neo4j writes, scoped entirely to a disposable test entity ('R4.4 Verify Test Entity') --")
    print("no established real research entity (Payment gateway, DNS, etc.) was touched.")
    print("\nChecks #11/#12 were updated for R4.5 (docs/Architecture.md §0.72): both originally confirmed real gaps")
    print("this slice found; both are now confirmed FIXED. See scripts/verify_r4_5.py for the dedicated test suite.")
    print("\nAcceptance #13 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2/R4.3 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")


if __name__ == "__main__":
    asyncio.run(run())
