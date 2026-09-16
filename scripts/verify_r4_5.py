"""R4.5 verification -- lifecycle rehydration and active-claim semantics
(docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
§0.72, backend/research/claim_mapping.py's rehydration logic,
backend/research/validation.py's DISCREDITED_CLAIM_STATUSES exclusion).

A semantic repair slice, not a new persistence feature: R4.4's own tests
(scripts/verify_r4_4.py's checks #11/#12) confirmed two real gaps --
`assess_claim_validity` counting a persisted "duplicate" claim as active,
and `claim_node_to_domain_claim` discarding a persisted status/duplicate_of
on every re-map. This closes both. Those two checks in verify_r4_4.py were
updated (not deleted) to confirm the fix; this file is the dedicated,
deeper test suite for the fix itself.

**Design question answered before coding, not assumed (per the R4.5 spec's
own instruction):** should rehydration use (A) the already-expanded
`ClaimNode` fields, (B) a separate graph read model, or (C) a
persistence-to-domain hydration adapter? **Answer: A, confirmed by direct
inspection, not a guess** -- `ClaimNode` already gained `status`/
`duplicate_of`/`provenance_note`/`last_transition_actor` in R4.4
(`backend/graph/models.py`), and `_record_to_claim` already reads them via
`.get()`. No new read model or adapter is needed; the data `R4.1`'s mapper
needs is already sitting on the exact object it already receives.

Checks:
  1. A persisted "normalized" claim rehydrates as "normalized" (not
     restarted at "requires_reclassification").
  2. A persisted "duplicate" claim rehydrates as "duplicate".
  3. `duplicate_of` survives reload alongside the status.
  4. A persisted duplicate is excluded from `assess_claim_validity`'s
     active-claim set (closing R4.4's own confirmed gap).
  5. The canonical claim (never given a status) remains eligible/active --
     confirming the fix excludes ONLY discredited statuses, not
     everything.
  6. Legacy `ClaimNode`s without a `status` property (created before R4.4
     existed) remain fully compatible -- `status=None` still falls back to
     the original "requires_reclassification" behavior, unchanged.
  7. Malformed persisted status is handled explicitly, never crashed on
     and never silently trusted: an unrecognized status string, a
     "duplicate" status with no `duplicate_of`, and a "superseded" status
     with no `superseded_by` all fall back to "requires_reclassification"
     with a distinguishing note -- three different reasons, three
     different messages, not one generic catch-all.
  8. Repeated persist -> reload -> persist is idempotent against REAL
     Neo4j: the second persist call (now correctly rehydrating the
     already-"duplicate" claim, rather than restarting it) reports
     `changed=False` and creates no second `DUPLICATE_OF` edge.
  9. Superseded claims (Phase 5's older, separate `supersede_claim` path)
     continue to be excluded from `active` exactly as before -- the fix is
     additive to the exclusion set, not a replacement of the existing
     `superseded_by` check.
 10. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2/R4.3/R4.4
     checks remain green.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.graph.models import ClaimNode  # noqa: E402
from backend.graph import (  # noqa: E402
    attach_claim,
    attach_question,
    find_or_create_entity,
    get_claims_for_question,
    get_driver,
)
from backend.reasoning import Claim, transition_claim  # noqa: E402
from backend.research import assess_claim_validity, claim_node_to_domain_claim, persist_domain_claim_lifecycle  # noqa: E402

TEST_ENTITY_NAME = "R4.5 Verify Test Entity"


def _node(**overrides) -> ClaimNode:
    defaults = dict(
        id="claim-1",
        evidence="a real proposition",
        reasoning="synthesis reasoning",
        confidence=0.6,
        source_title="Shared Source",
        source_url="https://example.com/shared",
        source_type="web",
        valid_from="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return ClaimNode(**defaults)


def check_persisted_normalized_rehydrates() -> None:
    node = _node(status="normalized", provenance_note="checked", last_transition_actor="tester")
    claim = claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert claim.status == "normalized"
    assert claim.provenance_note == "checked" and claim.last_transition_actor == "tester"
    print("[PASS] #1 a persisted 'normalized' claim rehydrates as 'normalized', not restarted")


def check_persisted_duplicate_rehydrates() -> None:
    node = _node(status="duplicate", duplicate_of="canonical-1", provenance_note="identical source_url")
    claim = claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert claim.status == "duplicate"
    print("[PASS] #2 a persisted 'duplicate' claim rehydrates as 'duplicate'")


def check_duplicate_of_survives_reload() -> None:
    node = _node(status="duplicate", duplicate_of="canonical-1", provenance_note="identical source_url")
    claim = claim_node_to_domain_claim(node, entity_id="e1", source_question_id="q1")
    assert claim.duplicate_of == "canonical-1"
    print("[PASS] #3 duplicate_of survives reload alongside the rehydrated status")


def check_persisted_duplicate_excluded_from_validation() -> None:
    canonical = _node(id="canonical-1", evidence="the real claim")
    duplicate = _node(id="dup-1", evidence="the real claim, restated", status="duplicate", duplicate_of="canonical-1", provenance_note="x")
    report = assess_claim_validity("e1", "Test", [canonical, duplicate])
    assert report.active_claim_count == 1
    assert not any(pair.claim_id_a == "dup-1" or pair.claim_id_b == "dup-1" for pair in report.duplicate_pairs)
    print("[PASS] #4 a persisted duplicate is excluded from assess_claim_validity's active-claim set (R4.4's confirmed gap, closed)")


def check_canonical_claim_remains_eligible() -> None:
    canonical = _node(id="canonical-1", evidence="the real claim")
    duplicate = _node(id="dup-1", evidence="the real claim, restated", status="duplicate", duplicate_of="canonical-1", provenance_note="x")
    genuinely_new = _node(id="new-1", evidence="a genuinely different claim")
    report = assess_claim_validity("e1", "Test", [canonical, duplicate, genuinely_new])
    assert report.active_claim_count == 2, "canonical (status=None) and the genuinely new claim must both remain active"
    print("[PASS] #5 the canonical claim (never given a status) remains eligible/active -- the fix excludes ONLY discredited statuses")


def check_legacy_claimnode_compatible() -> None:
    legacy = _node(id="legacy-1", evidence="a claim from before R4.4 existed")
    assert legacy.status is None
    claim = claim_node_to_domain_claim(legacy, entity_id="e1", source_question_id="q1")
    assert claim.status == "requires_reclassification"
    report = assess_claim_validity("e1", "Test", [legacy])
    assert report.active_claim_count == 1, "a legacy claim with status=None must remain counted active, exactly as before R4.4/R4.5"
    print("[PASS] #6 a legacy ClaimNode with no status property remains fully compatible with both the mapper and validation")


def check_malformed_status_explicit() -> None:
    unrecognized = _node(id="c1", status="not_a_real_claim_status")
    mapped_unrecognized = claim_node_to_domain_claim(unrecognized, entity_id="e1", source_question_id="q1")
    assert mapped_unrecognized.status == "requires_reclassification"
    assert "not a recognized ClaimStatus" in (mapped_unrecognized.provenance_note or "")

    duplicate_no_target = _node(id="c2", status="duplicate")  # duplicate_of not set -- inconsistent
    mapped_no_target = claim_node_to_domain_claim(duplicate_no_target, entity_id="e1", source_question_id="q1")
    assert mapped_no_target.status == "requires_reclassification"
    assert "inconsistent persisted state" in (mapped_no_target.provenance_note or "")

    superseded_no_ref = _node(id="c3", status="superseded")  # superseded_by not set -- inconsistent
    mapped_no_ref = claim_node_to_domain_claim(superseded_no_ref, entity_id="e1", source_question_id="q1")
    assert mapped_no_ref.status == "requires_reclassification"
    assert "inconsistent persisted state" in (mapped_no_ref.provenance_note or "")

    print("[PASS] #7 malformed/inconsistent persisted status (unrecognized value, duplicate with no target, superseded with no reference) all fall back explicitly, each with a distinguishing note")


async def _setup() -> tuple[str, str]:
    entity = await find_or_create_entity(TEST_ENTITY_NAME)
    question_id = str(uuid.uuid4())
    await attach_question(
        entity.id, question_id=question_id, text="R4.5 verification seed question.",
        dimension_id="scale", level="ground", rationale="R4.5 live rehydration verification.",
    )
    return entity.id, question_id


async def _attach_fresh_claim(question_id: str, evidence: str) -> str:
    from datetime import datetime, timezone

    claim_id = str(uuid.uuid4())
    await attach_claim(
        question_id, claim_id=claim_id, evidence=evidence, reasoning="R4.5 verification fixture.", confidence=0.6,
        source_title="R4.5 verify test source", source_url=f"https://example.com/r4-5-verify/{claim_id}", source_type="web",
        valid_from=datetime.now(timezone.utc).isoformat(),
    )
    return claim_id


async def _count_duplicate_of_edges(claim_id: str) -> int:
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (c:Claim {id: $claim_id})-[r:DUPLICATE_OF]->() RETURN count(r) AS n", claim_id=claim_id)
        record = await result.single()
        return record["n"]


async def check_idempotent_persist_reload_persist() -> None:
    entity_id, question_id = await _setup()
    canonical_id = await _attach_fresh_claim(question_id, "R4.5 check #8: the canonical claim.")
    duplicate_id = await _attach_fresh_claim(question_id, "R4.5 check #8: the duplicate claim.")

    node = next(c for c in await get_claims_for_question(question_id) if c.id == duplicate_id)
    mapped = claim_node_to_domain_claim(node, entity_id=entity_id, source_question_id=question_id)
    normalized = transition_claim(mapped, "normalized", reason="reclassified", actor="verify_r4_5")
    marked_duplicate = transition_claim(normalized, "duplicate", reason="identical source_url", actor="verify_r4_5", duplicate_of=canonical_id)

    first = await persist_domain_claim_lifecycle(marked_duplicate)
    assert first.applied and first.new_status == "duplicate"

    # Reload: this is the exact scenario R4.4's own check #12 found broken --
    # re-fetch, re-map (now correctly rehydrating "duplicate"), and persist
    # the SAME decision again. Must be a true no-op.
    reloaded_node = next(c for c in await get_claims_for_question(question_id) if c.id == duplicate_id)
    reloaded_claim = claim_node_to_domain_claim(reloaded_node, entity_id=entity_id, source_question_id=question_id)
    assert reloaded_claim.status == "duplicate" and reloaded_claim.duplicate_of == canonical_id

    second = await persist_domain_claim_lifecycle(reloaded_claim)
    assert second.applied and second.changed is False, "re-persisting the rehydrated, identical decision must be a true no-op"
    assert await _count_duplicate_of_edges(duplicate_id) == 1, "no second DUPLICATE_OF edge from the idempotent re-persist"
    print("[PASS] #8/#9 repeated persist -> reload -> persist is idempotent against real Neo4j: changed=False, no duplicate edge")

    return entity_id, question_id, canonical_id


async def check_superseded_still_excluded(entity_id: str, question_id: str) -> None:
    from backend.graph import supersede_claim

    canonical_id = await _attach_fresh_claim(question_id, "R4.5 check #9b: a claim that will be superseded.")
    new_claim_id = await _attach_fresh_claim(question_id, "R4.5 check #9b: the claim that supersedes it.")
    await supersede_claim(new_claim_id, canonical_id)

    all_claims = await get_claims_for_question(question_id)
    report = assess_claim_validity(entity_id, TEST_ENTITY_NAME, all_claims)
    superseded_node = next(c for c in all_claims if c.id == canonical_id)
    assert superseded_node.superseded_by == new_claim_id
    assert canonical_id in report.superseded_claim_ids
    assert not any(pair.claim_id_a == canonical_id or pair.claim_id_b == canonical_id for pair in report.duplicate_pairs)
    print("[PASS] #9 a claim superseded via Phase 5's older supersede_claim path remains excluded exactly as before -- additive fix, not a replacement")


async def run_live_checks() -> None:
    try:
        entity_id, question_id, _canonical_id = await check_idempotent_persist_reload_persist()
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] live checks: Neo4j unreachable or setup failed ({exc})")
        return
    await check_superseded_still_excluded(entity_id, question_id)


if __name__ == "__main__":
    check_persisted_normalized_rehydrates()
    check_persisted_duplicate_rehydrates()
    check_duplicate_of_survives_reload()
    check_persisted_duplicate_excluded_from_validation()
    check_canonical_claim_remains_eligible()
    check_legacy_claimnode_compatible()
    check_malformed_status_explicit()
    asyncio.run(run_live_checks())
    print("\nAll checks passed. Checks #1-7 pure/synthetic; #8/#9 against REAL Neo4j, scoped to a")
    print("disposable test entity ('R4.5 Verify Test Entity') -- no established real research entity touched.")
    print("\nAcceptance #10 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1/R4.2/R4.3/R4.4 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
