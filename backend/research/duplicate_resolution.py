from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.graph.models import ClaimNode
from backend.reasoning import ClaimTransitionRejected, transition_claim

from .claim_mapping import ClaimMappingRejected, claim_node_to_domain_claim
from .models import DuplicateClaimPair

# R4.2 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.68): the first real orchestration step that consumes R1.4's
# transition_claim from a real validation finding -- closing the gap R4.0's
# audit named (assess_claim_validity's duplicate_pairs were real but
# report-only, never consumed to change a claim's status) and finally
# resolving Phase 8.6's still-open 38-duplicate-pairs finding.
#
# Deliberately narrow, per this slice's own scope: resolves EXACTLY the
# duplicate_pairs a caller already computed via assess_claim_validity --
# does not call assess_claim_validity itself, does not fetch claims from
# Neo4j, does not persist any transition back to the graph (R4.0's R4.4,
# still deferred pending its own scoping decision), does not touch
# MasterAgent, does not build subclaim orchestration (R4.3), does not
# redesign claim_node_to_domain_claim (R4.1's contract is unchanged).
#
# Only the DUPLICATE side of each pair is ever transitioned. The canonical
# side (claim_id_a, an arbitrary-but-deterministic choice -- see
# _resolve_pair's docstring) is left untouched: this slice's job is
# "mark the non-canonical claim of a real duplicate pair as such," not "run
# the canonical claim through the rest of its own lifecycle," which would be
# a separate, much bigger judgment about evidence sufficiency this slice
# does not make.

PairOutcome = Literal[
    "resolved",
    "already_resolved",
    "skipped_incompatible_status",
    "unresolved_missing_claim",
    "unresolved_mapping_failed",
]


class DuplicatePairResolution(BaseModel):
    """What happened when this slice tried to resolve ONE real duplicate
    pair. `outcome` is always one of the five explicit values above --
    never silently absent, never inferred from whether `detail` sounds
    positive."""

    claim_id_a: str
    claim_id_b: str
    reason: str
    outcome: PairOutcome
    detail: str
    canonical_claim_id: Optional[str] = None
    duplicate_claim_id: Optional[str] = None
    duplicate_claim_final_status: Optional[str] = None


class DuplicateResolutionSummary(BaseModel):
    """The full accounting for one entity's duplicate_pairs -- every pair
    named in `total_pairs`, every one of them present exactly once in
    `resolutions`, categorized into exactly one of four counts that must
    sum to `total_pairs`. No pair is ever silently dropped."""

    entity_id: str
    total_pairs: int
    resolved_count: int
    already_resolved_count: int
    skipped_count: int
    unresolved_count: int
    resolutions: list[DuplicatePairResolution] = Field(default_factory=list)


def resolve_duplicate_claims(
    entity_id: str,
    duplicate_pairs: list[DuplicateClaimPair],
    claims_by_id: dict[str, ClaimNode],
    claim_question_ids: dict[str, str],
    *,
    actor: str = "r4_2_duplicate_resolution",
) -> DuplicateResolutionSummary:
    """Resolve every real `DuplicateClaimPair` `assess_claim_validity`
    (Phase 8.5) already found for `entity_id`, by transitioning the
    non-canonical claim in each pair to `status="duplicate"` via the real,
    sanctioned `transition_claim` -- never by direct field assignment.

    `claims_by_id`/`claim_question_ids` must be supplied by the caller (the
    same real fetch loop that produced `duplicate_pairs` in the first
    place, matching R1.3's own established (claim, question_id)-tracking
    pattern) -- this function does no I/O of its own and fetches nothing.
    """
    # Tracks claim_id -> its resolved root canonical WITHIN this single run
    # (never across calls -- ClaimNode carries no status, so a fresh
    # ClaimNode-based mapping can never already be "duplicate" from a PRIOR
    # run; "already_resolved" and chain-flattening are strictly in-run
    # concerns). Two real cases this closes, both found by testing this
    # function against realistic data rather than assumed away:
    #   1. The same claim_id appears as the DUPLICATE side of more than one
    #      pair (real and likely: assess_claim_validity's combinations()
    #      over claims sharing one source_url produces exactly this for any
    #      cluster of 3+ matching claims) -- resolved once, every later
    #      pair naming the same duplicate_id is reported "already_resolved"
    #      against the SAME canonical, never re-transitioned or given a
    #      second, conflicting duplicate_of.
    #   2. A pair's "canonical" side (claim_id_a) was ITSELF already
    #      resolved as a duplicate earlier in this run (a duplicate chain,
    #      e.g. (A,B) then (B,C)) -- flattened one hop so C points at A
    #      (the real root), never left pointing at B, a claim this same run
    #      already demoted.
    resolved_root_canonical: dict[str, str] = {}
    resolutions: list[DuplicatePairResolution] = []
    for pair in duplicate_pairs:
        duplicate_id = pair.claim_id_b
        if duplicate_id in resolved_root_canonical:
            resolutions.append(
                DuplicatePairResolution(
                    claim_id_a=pair.claim_id_a,
                    claim_id_b=pair.claim_id_b,
                    reason=pair.reason,
                    outcome="already_resolved",
                    canonical_claim_id=resolved_root_canonical[duplicate_id],
                    duplicate_claim_id=duplicate_id,
                    detail=(
                        f"{duplicate_id} was already resolved as duplicate_of={resolved_root_canonical[duplicate_id]!r} "
                        "earlier in this same run -- this claim appears in more than one duplicate pair"
                    ),
                    duplicate_claim_final_status="duplicate",
                )
            )
            continue

        effective_canonical_id = resolved_root_canonical.get(pair.claim_id_a, pair.claim_id_a)
        result = _resolve_pair(pair, effective_canonical_id, entity_id, claims_by_id, claim_question_ids, actor)
        if result.outcome == "resolved" and result.canonical_claim_id is not None:
            resolved_root_canonical[duplicate_id] = result.canonical_claim_id
        resolutions.append(result)

    counts = {"resolved": 0, "already_resolved": 0, "skipped_incompatible_status": 0, "unresolved_missing_claim": 0, "unresolved_mapping_failed": 0}
    for r in resolutions:
        counts[r.outcome] += 1

    return DuplicateResolutionSummary(
        entity_id=entity_id,
        total_pairs=len(duplicate_pairs),
        resolved_count=counts["resolved"],
        already_resolved_count=counts["already_resolved"],
        skipped_count=counts["skipped_incompatible_status"],
        unresolved_count=counts["unresolved_missing_claim"] + counts["unresolved_mapping_failed"],
        resolutions=resolutions,
    )


def _resolve_pair(
    pair: DuplicateClaimPair,
    canonical_id: str,
    entity_id: str,
    claims_by_id: dict[str, ClaimNode],
    claim_question_ids: dict[str, str],
    actor: str,
) -> DuplicatePairResolution:
    # `canonical_id` is passed in by the caller, not derived from
    # `pair.claim_id_a` directly -- it may be a FLATTENED root canonical
    # (resolve_duplicate_claims's chain-handling, above) rather than
    # `pair.claim_id_a` itself. The original arbitrary-but-deterministic
    # tie-break is still `pair.claim_id_a` treated as canonical and
    # `pair.claim_id_b` as the duplicate -- this adds no NEW judgment beyond
    # what assess_claim_validity's own combinations()-based pair order
    # already implied; it is not a confidence- or quality-based selection
    # (Rule: confidence never controls lifecycle legality applies here too,
    # at the orchestration level, not just inside transition_claim itself).
    duplicate_id = pair.claim_id_b

    canonical_node = claims_by_id.get(canonical_id)
    duplicate_node = claims_by_id.get(duplicate_id)
    missing_ids = [cid for cid, node in ((canonical_id, canonical_node), (duplicate_id, duplicate_node)) if node is None]
    if missing_ids or duplicate_id not in claim_question_ids:
        if duplicate_id not in claim_question_ids and duplicate_id not in missing_ids:
            missing_ids = [*missing_ids, f"{duplicate_id} (no source_question_id supplied)"]
        return DuplicatePairResolution(
            claim_id_a=pair.claim_id_a,
            claim_id_b=pair.claim_id_b,
            reason=pair.reason,
            outcome="unresolved_missing_claim",
            detail=f"claim id(s) not resolvable from the claims/question-id maps supplied: {missing_ids}",
        )

    try:
        duplicate_claim = claim_node_to_domain_claim(duplicate_node, entity_id=entity_id, source_question_id=claim_question_ids[duplicate_id])
    except ClaimMappingRejected as exc:
        return DuplicatePairResolution(
            claim_id_a=pair.claim_id_a,
            claim_id_b=pair.claim_id_b,
            reason=pair.reason,
            outcome="unresolved_mapping_failed",
            detail=f"mapping the duplicate-side claim failed: {exc}",
        )

    if duplicate_claim.status == "duplicate":
        # Defensive, not currently reachable via real ClaimNode data: R4.1's
        # mapper always lands a fresh ClaimNode at "requires_reclassification"
        # (it carries no lifecycle status to preserve), so this branch never
        # fires from claims_by_id alone within a single call -- the actual
        # in-run "seen this claim_id before" case is handled one level up,
        # in resolve_duplicate_claims's own resolved_root_canonical tracking.
        # Kept here anyway as a real safeguard, not dead code removed for
        # tidiness: if a future caller or mapper ever produces a claim that
        # is already "duplicate", this must still be reported, never
        # silently re-transitioned.
        return DuplicatePairResolution(
            claim_id_a=pair.claim_id_a,
            claim_id_b=pair.claim_id_b,
            reason=pair.reason,
            outcome="already_resolved",
            canonical_claim_id=duplicate_claim.duplicate_of,
            duplicate_claim_id=duplicate_id,
            detail=f"already marked duplicate_of={duplicate_claim.duplicate_of!r} -- not re-transitioned",
            duplicate_claim_final_status="duplicate",
        )

    if duplicate_claim.status == "requires_reclassification":
        try:
            duplicate_claim = transition_claim(
                duplicate_claim,
                "normalized",
                reason=f"reclassified for duplicate resolution against canonical claim {canonical_id}",
                actor=actor,
            )
        except ClaimTransitionRejected as exc:
            return DuplicatePairResolution(
                claim_id_a=pair.claim_id_a,
                claim_id_b=pair.claim_id_b,
                reason=pair.reason,
                outcome="skipped_incompatible_status",
                detail=f"could not reclassify to 'normalized': {exc}",
                duplicate_claim_final_status="requires_reclassification",
            )

    if duplicate_claim.status != "normalized":
        return DuplicatePairResolution(
            claim_id_a=pair.claim_id_a,
            claim_id_b=pair.claim_id_b,
            reason=pair.reason,
            outcome="skipped_incompatible_status",
            detail=f"current status {duplicate_claim.status!r} has no legal path to 'duplicate' -- not forced",
            duplicate_claim_final_status=duplicate_claim.status,
        )

    try:
        duplicate_claim = transition_claim(
            duplicate_claim,
            "duplicate",
            reason=f"{pair.reason} -- matches canonical claim {canonical_id}",
            actor=actor,
            duplicate_of=canonical_id,
        )
    except ClaimTransitionRejected as exc:
        return DuplicatePairResolution(
            claim_id_a=pair.claim_id_a,
            claim_id_b=pair.claim_id_b,
            reason=pair.reason,
            outcome="skipped_incompatible_status",
            detail=f"could not mark 'duplicate': {exc}",
            duplicate_claim_final_status="normalized",
        )

    return DuplicatePairResolution(
        claim_id_a=pair.claim_id_a,
        claim_id_b=pair.claim_id_b,
        reason=pair.reason,
        outcome="resolved",
        canonical_claim_id=canonical_id,
        duplicate_claim_id=duplicate_id,
        detail=f"transitioned {duplicate_id} to status='duplicate', duplicate_of={canonical_id}",
        duplicate_claim_final_status="duplicate",
    )
