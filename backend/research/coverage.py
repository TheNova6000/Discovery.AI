from __future__ import annotations

from backend.graph.interface import get_claims_for_question, get_questions_for_entity
from backend.graph.models import ClaimNode

from .models import (
    CONFIDENCE_GATED_FIELDS,
    ConceptCompleteness,
    ConceptResearchTarget,
    FieldCoverage,
    ResearchPlan,
    ResearchReadinessReport,
)

# Phase 8.3 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.43):
# the Coverage / Completeness model. Answers "what does this concept
# ALREADY contain, and is that enough" -- distinct from planner.py's "what
# SHOULD this concept contain" (Phase 8.2). Same split discipline as
# generate_roadmap (Phase 6) and build_research_plan (Phase 8.2): a pure
# function (assess_target_completeness / assess_plan_readiness) doing the
# actual logic over already-fetched data, unit-tested directly with no
# LLM/Neo4j call, wrapped by a thin I/O shell (build_readiness_report) for
# the one live-graph-reading part. Never performs deep research, invents new
# concepts, or classifies evidence by content (see models.py's
# UNCLASSIFIED_FIELDS note) -- purely reads what's already recorded.


def _max_confidence(claims: list[ClaimNode]) -> float:
    # Superseded claims (docs/Architecture.md's epistemic layer, Post-Phase-5)
    # are no longer the live truth about this concept -- excluded from
    # "current evidence," same as the epistemic layer already treats them
    # everywhere else.
    active = [c for c in claims if c.superseded_by is None]
    return max((c.confidence for c in active), default=0.0)


def assess_target_completeness(
    target: ConceptResearchTarget,
    claims: list[ClaimNode],
    confidence_threshold: float,
) -> ConceptCompleteness:
    """Pure logic: given one target, its real (already-fetched) claims, and
    the active policy's confidence bar, decide which required fields are
    satisfied. No I/O, no LLM call -- the actual thing this phase tests.
    """
    max_confidence = _max_confidence(claims)
    active_claim_count = sum(1 for c in claims if c.superseded_by is None)
    has_qualifying_evidence = active_claim_count > 0 and max_confidence >= confidence_threshold

    field_coverage: list[FieldCoverage] = []
    for field in sorted(target.required_fields):
        if field in CONFIDENCE_GATED_FIELDS:
            status = "present" if has_qualifying_evidence else "missing"
            reason = (
                f"{active_claim_count} active claim(s), max confidence {max_confidence:.2f} "
                f"{'meets' if has_qualifying_evidence else 'does not meet'} policy threshold {confidence_threshold:.2f}"
            )
        else:
            status = "missing"
            reason = "no evidence-to-field classification exists yet for this field (Phase 8.4) -- reported missing, not guessed"
        field_coverage.append(FieldCoverage(field=field, status=status, reason=reason))

    missing = frozenset(fc.field for fc in field_coverage if fc.status == "missing")
    return ConceptCompleteness(
        entity_id=target.entity_id,
        entity_name=target.entity_name,
        field_coverage=field_coverage,
        is_complete=not missing,
        missing_fields=missing,
    )


def assess_plan_readiness(
    plan: ResearchPlan,
    claims_by_entity: dict[str, list[ClaimNode]],
) -> ResearchReadinessReport:
    """Pure logic: rolls assess_target_completeness up across every target in
    a plan. `claims_by_entity` is already-fetched data (the I/O shell below
    does the fetching) -- an entity_id missing from the dict is treated as
    zero claims, not an error, matching planner.py's own "a gap this
    surfaces by omission" principle.
    """
    concepts = [
        assess_target_completeness(target, claims_by_entity.get(target.entity_id, []), plan.policy.confidence_threshold)
        for target in plan.targets
    ]
    ready_count = sum(1 for c in concepts if c.is_complete)
    return ResearchReadinessReport(
        abstraction_id=plan.abstraction_id,
        abstraction_name=plan.abstraction_name,
        policy=plan.policy,
        concepts=concepts,
        ready_count=ready_count,
        incomplete_count=len(concepts) - ready_count,
        is_ready=ready_count == len(concepts),
    )


async def build_readiness_report(plan: ResearchPlan) -> ResearchReadinessReport:
    """I/O shell: fetch each target's real questions/claims from Neo4j, then
    hand off to the pure logic above. Rules.md rule 14: reads only, no LLM or
    retriever call, same constraint generate_roadmap/build_research_plan
    already follow.
    """
    claims_by_entity: dict[str, list[ClaimNode]] = {}
    for target in plan.targets:
        questions = await get_questions_for_entity(target.entity_id)
        claims: list[ClaimNode] = []
        for question in questions:
            claims.extend(await get_claims_for_question(question.id))
        claims_by_entity[target.entity_id] = claims
    return assess_plan_readiness(plan, claims_by_entity)
