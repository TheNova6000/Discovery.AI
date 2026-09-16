from __future__ import annotations

from itertools import combinations

from backend.graph.models import ClaimNode
from backend.questions import QuestionEngineError, analyze_claim_relationships

from .models import ClaimValidationReport, ContradictionFinding, ContradictionReport, DuplicateClaimPair

# Phase 8.5 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.45):
# Evidence and contradiction validation. Same split discipline as every prior
# phase in this track: `assess_claim_validity` is pure and deterministic (no
# LLM call, unit-tested with fixtures); `detect_contradictions` is the one
# place in this module with a real LLM call, and it's bounded and OPT-IN --
# never invoked as part of the deterministic path, never run against an
# unbounded claim set.

DEFAULT_WEAK_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_MAX_CLAIMS_FOR_CONTRADICTION_CHECK = 5


def assess_claim_validity(
    entity_id: str,
    entity_name: str,
    claims: list[ClaimNode],
    *,
    weak_confidence_threshold: float = DEFAULT_WEAK_CONFIDENCE_THRESHOLD,
) -> ClaimValidationReport:
    """Pure logic: deterministic quality signals over an already-fetched
    claim set. No I/O, no LLM call -- unit-tested directly
    (scripts/verify_phase8_5.py).

    Duplicate detection is exact-match only (identical source_url, or
    identical evidence text) -- a real, motivated check, not hypothetical:
    this project has already observed duplicate Question nodes for the same
    entity from repeated decomposition/retry passes (docs/Memory.md, Phase
    6's live verification) -- the same failure mode plausibly produces
    duplicate Claims too, and Phase 8.3's coverage model has no way to catch
    it (raw claim count would look fine even if every claim cites the same
    source).
    """
    active = [c for c in claims if c.superseded_by is None]
    superseded_ids = [c.id for c in claims if c.superseded_by is not None]
    weak_ids = [c.id for c in active if c.confidence < weak_confidence_threshold]

    duplicate_pairs: list[DuplicateClaimPair] = []
    for a, b in combinations(active, 2):
        if a.source_url and a.source_url == b.source_url:
            duplicate_pairs.append(DuplicateClaimPair(claim_id_a=a.id, claim_id_b=b.id, reason="identical source_url"))
        elif a.evidence and a.evidence == b.evidence:
            duplicate_pairs.append(DuplicateClaimPair(claim_id_a=a.id, claim_id_b=b.id, reason="identical evidence text"))

    distinct_source_count = len({c.source_url for c in active if c.source_url})

    return ClaimValidationReport(
        entity_id=entity_id,
        entity_name=entity_name,
        active_claim_count=len(active),
        superseded_claim_ids=superseded_ids,
        weak_claim_ids=weak_ids,
        duplicate_pairs=duplicate_pairs,
        distinct_source_count=distinct_source_count,
        has_independent_support=distinct_source_count >= 2,
    )


async def detect_contradictions(
    entity_id: str,
    entity_name: str,
    question_text: str,
    claims: list[ClaimNode],
    *,
    max_claims: int = DEFAULT_MAX_CLAIMS_FOR_CONTRADICTION_CHECK,
) -> ContradictionReport:
    """I/O: the one real LLM call in this module, reusing
    `backend.questions.analyze_claim_relationships` (Post-Phase-5's
    epistemic layer) completely unchanged rather than inventing new
    contradiction-detection logic. Deliberately NOT called from
    `assess_claim_validity` or any deterministic path -- always an explicit,
    separate, opt-in call.

    Bounded, and honest about being skipped rather than silently no-op'ing:
    fewer than 2 active claims means nothing to compare (checked=False, not
    an empty findings list that could be misread as "checked, found
    nothing"); more than `max_claims` active claims is skipped outright
    rather than running an O(n^2) pairwise LLM prompt against an unbounded
    set -- the same "bounded, not an uncontrolled deep-search system"
    discipline Phase 8.4 already established, applied here to prompt/cost
    size instead of investigation depth.

    Reliability caveat this phase inherits rather than re-litigates
    (Architecture.md §0.5, §0.45): analyze_claim_relationships' real-world
    accuracy at genuine competing-explanation/contradiction detection is not
    yet proven at scale -- the controlled follow-up experiment Phase 7 is
    itself still waiting on. Findings from this function are real model
    output, carried with their own reasoning so a reader can judge them, not
    presented as an infallible oracle.
    """
    active = [c for c in claims if c.superseded_by is None]
    if len(active) < 2:
        return ContradictionReport(
            entity_id=entity_id,
            entity_name=entity_name,
            checked=False,
            skipped_reason="fewer than 2 active claims -- nothing to compare",
        )
    if len(active) > max_claims:
        return ContradictionReport(
            entity_id=entity_id,
            entity_name=entity_name,
            checked=False,
            skipped_reason=f"{len(active)} active claims exceeds max_claims={max_claims} -- skipped to bound pairwise LLM cost",
        )

    try:
        analysis = await analyze_claim_relationships(question_text, [c.evidence for c in active])
    except QuestionEngineError as exc:
        return ContradictionReport(
            entity_id=entity_id, entity_name=entity_name, checked=False, skipped_reason=f"analyze_claim_relationships failed: {exc}"
        )

    findings = [
        ContradictionFinding(
            claim_id_a=active[pair.claim_a_index - 1].id,
            claim_id_b=active[pair.claim_b_index - 1].id,
            reasoning=pair.reasoning,
            confidence=pair.confidence,
        )
        for pair in analysis.pairs
        if pair.relationship == "contradictory"
    ]
    return ContradictionReport(entity_id=entity_id, entity_name=entity_name, checked=True, findings=findings)
