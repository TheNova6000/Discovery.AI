"""Ad-hoc verification -- §0.26 relation-evidence pass (docs/Architecture.md).
Not a numbered Phases.md deliverable.

Walks the user's own acceptance table directly against real Neo4j (no LLM
calls needed -- this tests the graph-interface layer, not extraction), using
throwaway test entities so it never depends on or disturbs today's
accumulated PayPal/Payment test data.

Acceptance rows tested here (the ones the graph-interface layer alone can
prove; canonicalize_relation's active/passive handling was already verified
8/8 in §0.18 and isn't re-tested):

  1. Same relation found twice -> evidence accumulates (two claims), the
     native RELATES_TO edge is NOT duplicated.
  2. Same wording, different target -> tracked as a separate relation
     identity, doesn't inflate the first one's claim count.
  3. Contradictory evidence -> attaches under the SAME relation identity
     (competing evidence), confidence drops rather than a new edge appearing.
  4. No evidence -> get_relation_confidence reports confidence=None, not a
     fabricated default.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph import (  # noqa: E402
    attach_relation_claim,
    create_relationship,
    find_or_create_entity,
    get_relation_claims,
    get_relation_confidence,
)
from backend.graph.driver import get_driver  # noqa: E402
from backend.graph.schema import NODE_LABEL, RELATES_TO  # noqa: E402


async def count_relates_to_edges(source_id: str, target_id: str, relationship_type: str) -> int:
    """Direct Cypher count, NOT via get_neighbors -- that function's own
    `RETURN DISTINCT b` would hide a real edge-duplication bug (it always
    reports at most one reachable target regardless of how many parallel
    edges exist underneath). This is the actual proof MERGE didn't duplicate.
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"MATCH (a:{NODE_LABEL} {{id: $source_id}})"
            f"-[r:{RELATES_TO} {{relationship_type: $relationship_type}}]->"
            f"(b:{NODE_LABEL} {{id: $target_id}}) RETURN count(r) AS n",
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
        )
        record = await result.single()
        return record["n"]

SOURCE = "Verify0.26 Source"
TARGET_A = "Verify0.26 TargetA"
TARGET_B = "Verify0.26 TargetB"
REL_TYPE = "uses"


async def claim(source_id: str, target_id: str, evidence: str, stance: str = "supports") -> None:
    await attach_relation_claim(
        source_id,
        target_id,
        REL_TYPE,
        claim_id=str(uuid.uuid4()),
        evidence=evidence,
        reasoning="verify_relation_claims.py test claim",
        confidence=0.7,
        source_title="test",
        source_url="",
        source_type="test",
        valid_from=datetime.now(timezone.utc).isoformat(),
        stance=stance,
    )


async def run() -> None:
    source = await find_or_create_entity(SOURCE)
    target_a = await find_or_create_entity(TARGET_A)
    target_b = await find_or_create_entity(TARGET_B)
    await create_relationship(source.id, target_a.id, REL_TYPE)
    await create_relationship(source.id, target_b.id, REL_TYPE)

    print("=" * 70)
    print("Row 1: same relation found twice -> evidence accumulates")
    print("=" * 70)
    await claim(source.id, target_a.id, "Evidence A: first discovery.")
    await claim(source.id, target_a.id, "Evidence B: second, independent discovery.")
    claims_a = await get_relation_claims(source.id, target_a.id, REL_TYPE)
    print(f"  claims on (Source -[uses]-> TargetA): {len(claims_a)} (expected 2)")
    for stance, c in claims_a:
        print(f"    [{stance}] {c.evidence!r}")
    edge_count_to_a = await count_relates_to_edges(source.id, target_a.id, REL_TYPE)
    print(f"  native RELATES_TO edges Source->TargetA: {edge_count_to_a} (expected 1, NOT duplicated)")

    print("\n" + "=" * 70)
    print("Row 2: same wording, different target -> separate relation identity")
    print("=" * 70)
    await claim(source.id, target_b.id, "Evidence A: first discovery.")  # same wording as TargetA's first claim
    claims_a_again = await get_relation_claims(source.id, target_a.id, REL_TYPE)
    claims_b = await get_relation_claims(source.id, target_b.id, REL_TYPE)
    print(f"  TargetA claim count unchanged: {len(claims_a_again)} (expected still 2)")
    print(f"  TargetB claim count: {len(claims_b)} (expected 1, tracked separately)")

    print("\n" + "=" * 70)
    print("Row 3: contradictory evidence -> same identity, competing evidence")
    print("=" * 70)
    before = await get_relation_confidence(source.id, target_a.id, REL_TYPE)
    print(f"  confidence before contradiction: {before}")
    await claim(source.id, target_a.id, "Evidence C: a later investigation disputes this.", stance="contradicts")
    after = await get_relation_confidence(source.id, target_a.id, REL_TYPE)
    print(f"  confidence after contradiction:  {after}")
    claims_a_final = await get_relation_claims(source.id, target_a.id, REL_TYPE)
    print(f"  claim count: {len(claims_a_final)} (expected 3 -- still ONE relation identity, not a new edge)")

    print("\n" + "=" * 70)
    print("Row 4: no evidence -> confidence is None, not a fabricated default")
    print("=" * 70)
    fresh_target = await find_or_create_entity("Verify0.26 UnevidencedTarget")
    await create_relationship(source.id, fresh_target.id, REL_TYPE)
    none_confidence = await get_relation_confidence(source.id, fresh_target.id, REL_TYPE)
    print(f"  confidence for a relation with zero claims: {none_confidence}")

    print("\n" + "=" * 70)
    print("Checks to make by reading the above:")
    print("  1. Row 1: 2 claims, exactly 1 native edge (not 2).")
    print("  2. Row 2: TargetA stayed at 2, TargetB independently got 1 -- no cross-contamination.")
    print("  3. Row 3: confidence dropped after the contradiction, claim count went to 3, still one identity.")
    print("  4. Row 4: confidence is None (not 0.5 or any other fabricated number) with zero claims.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
