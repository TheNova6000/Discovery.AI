from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.graph import ClaimLifecyclePersistResult, GraphInterfaceError, persist_claim_lifecycle
from backend.reasoning import Claim

# R4.4 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.70/§0.71): the research-layer bridge from a real, already-transitioned
# reasoning.domain.Claim to graph persistence -- the FIRST function in this
# whole track that writes to Neo4j. Everything from R1 through R4.3 was
# pure/in-memory/read-only by explicit scope; this is the deliberate,
# narrowly-scoped first exception, per the R4.4 decision record (§0.70).
#
# Deliberately narrow, matching the decision record's own first-slice scope
# exactly: persists status/duplicate_of/provenance_note/last_transition_actor
# onto an EXISTING ClaimNode by id -- never creates a claim, never persists
# parent_claim_id/relation_to_parent (R4.3 has no real producer of those from
# live data yet), never touches assess_claim_validity's own exclusion filter
# (flagged as a real, separate Phase 8.5 follow-up in §0.70's Q3, not
# resolved here), never implements run-level transactions or versioning.
#
# Deliberately independent of backend.research.duplicate_resolution -- this
# function takes any already-transitioned Claim, not a DuplicatePairResolution
# specifically. No concrete conflict was found requiring a change to
# duplicate_resolution.py, so it remains untouched (per this slice's own
# guardrail).

PersistenceOutcome = Literal["applied", "rejected_missing_claim"]


class ClaimPersistenceResult(BaseModel):
    """What `persist_domain_claim_lifecycle` returns -- always names the
    claim, always says whether the write was applied, and always carries
    enough of a before/after picture to make a changed decision visible
    (the R4.4 decision record's own "old-vs-new visibility on every write"
    requirement, §0.70's Q6/Q7) without needing a separate lookup."""

    claim_id: str
    outcome: PersistenceOutcome
    applied: bool
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    previous_duplicate_of: Optional[str] = None
    canonical_claim_id: Optional[str] = None
    detail: str
    changed: bool = Field(
        default=False,
        description="True iff this write actually changed status or duplicate_of from what was already there -- "
        "distinct from 'applied', which is true even for a no-op re-write of an identical value.",
    )


async def persist_domain_claim_lifecycle(claim: Claim) -> ClaimPersistenceResult:
    """Persist `claim`'s computed lifecycle fields onto the real,
    already-existing `ClaimNode` sharing its id (R4.1's own recovery-by-id
    guarantee, §0.67.1's Question C, is exactly what makes this correct: the
    domain `Claim`'s `claim_id` IS the real graph node's `id`, unchanged
    since the mapping happened).

    Never creates a claim -- if `claim.claim_id` doesn't already exist in
    Neo4j (or `claim.duplicate_of`, when set, doesn't), this is reported as
    `"rejected_missing_claim"`, never silently escalated into creating one.
    """
    try:
        result: ClaimLifecyclePersistResult = await persist_claim_lifecycle(
            claim.claim_id,
            status=claim.status,
            duplicate_of=claim.duplicate_of,
            provenance_note=claim.provenance_note,
            last_transition_actor=claim.last_transition_actor,
        )
    except GraphInterfaceError as exc:
        return ClaimPersistenceResult(
            claim_id=claim.claim_id,
            outcome="rejected_missing_claim",
            applied=False,
            detail=f"persistence rejected: {exc}",
        )

    status_changed = result.previous_status != result.claim.status
    duplicate_changed = claim.duplicate_of is not None and result.previous_duplicate_of != result.claim.duplicate_of
    detail = f"status {result.previous_status!r} -> {result.claim.status!r}"
    if claim.duplicate_of is not None:
        detail += f", duplicate_of {result.previous_duplicate_of!r} -> {result.claim.duplicate_of!r}"

    return ClaimPersistenceResult(
        claim_id=claim.claim_id,
        outcome="applied",
        applied=True,
        previous_status=result.previous_status,
        new_status=result.claim.status,
        previous_duplicate_of=result.previous_duplicate_of,
        canonical_claim_id=result.claim.duplicate_of,
        detail=detail,
        changed=status_changed or duplicate_changed,
    )
