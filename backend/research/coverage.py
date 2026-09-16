from __future__ import annotations

from backend.graph.interface import get_claims_for_question, get_questions_for_entity
from backend.graph.models import ClaimNode, QuestionNode

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
# concepts, or classifies evidence by content beyond the real research_field
# tag (see below) -- purely reads what's already recorded.
#
# Phase 8.4 (docs/Architecture.md §0.44) extended this module to actually
# read `QuestionNode.research_field` (Phase 8.4's own schema addition) --
# closing the exact gap Phase 8.3 documented as "Phase 8.4's job" rather than
# leaving it as a dangling TODO. UNCLASSIFIED_FIELDS ("prerequisites",
# "examples", "misconceptions") are no longer UNCONDITIONALLY reported
# missing: a field now reads "present" if, and only if, a real Question
# tagged `research_field=<that field>` has real, non-superseded, qualifying
# evidence attached. No Question ever carries that tag unless
# backend.research.investigate (Phase 8.4) actually created it -- nothing
# here classifies existing untagged evidence after the fact, which would be
# exactly the guessing Phase 8.3 refused to do.


def _max_confidence(claims: list[ClaimNode]) -> float:
    # Superseded claims (docs/Architecture.md's epistemic layer, Post-Phase-5)
    # are no longer the live truth about this concept -- excluded from
    # "current evidence," same as the epistemic layer already treats them
    # everywhere else.
    active = [c for c in claims if c.superseded_by is None]
    return max((c.confidence for c in active), default=0.0)


def _active_count(claims: list[ClaimNode]) -> int:
    return sum(1 for c in claims if c.superseded_by is None)


def _tagged_field_confidence(
    questions: list[QuestionNode], claims_by_question: dict[str, list[ClaimNode]]
) -> dict[str, float]:
    """field_name -> best (max) confidence among non-superseded claims
    attached to a Question tagged with that research_field. A field absent
    from this dict has no tagged evidence at all yet, distinct from tagged-
    but-below-threshold -- assess_target_completeness's reason string below
    distinguishes the two rather than collapsing them into one "missing"."""
    result: dict[str, float] = {}
    for question in questions:
        if not question.research_field:
            continue
        claims = claims_by_question.get(question.id, [])
        if _active_count(claims) == 0:
            continue
        confidence = _max_confidence(claims)
        result[question.research_field] = max(result.get(question.research_field, 0.0), confidence)
    return result


def assess_target_completeness(
    target: ConceptResearchTarget,
    all_claims: list[ClaimNode],
    confidence_threshold: float,
    *,
    questions: list[QuestionNode] | None = None,
    claims_by_question: dict[str, list[ClaimNode]] | None = None,
) -> ConceptCompleteness:
    """Pure logic: given one target, its real (already-fetched) evidence, and
    the active policy's confidence bar, decide which required fields are
    satisfied. No I/O, no LLM call -- the actual thing this phase tests.

    `all_claims` drives CONFIDENCE_GATED_FIELDS exactly as Phase 8.3 shipped
    it (unchanged -- today's single-pass generic answer genuinely covers
    "what is this/how does it work" regardless of which question produced
    it). `questions`/`claims_by_question` (both optional, default empty --
    every pre-Phase-8.4 caller keeps working identically) drive
    UNCLASSIFIED_FIELDS via research_field tags (Phase 8.4).
    """
    questions = questions or []
    claims_by_question = claims_by_question or {}

    max_confidence = _max_confidence(all_claims)
    active_claim_count = _active_count(all_claims)
    has_qualifying_evidence = active_claim_count > 0 and max_confidence >= confidence_threshold

    tagged_confidence = _tagged_field_confidence(questions, claims_by_question)

    field_coverage: list[FieldCoverage] = []
    for field in sorted(target.required_fields):
        if field in CONFIDENCE_GATED_FIELDS:
            status = "present" if has_qualifying_evidence else "missing"
            reason = (
                f"{active_claim_count} active claim(s), max confidence {max_confidence:.2f} "
                f"{'meets' if has_qualifying_evidence else 'does not meet'} policy threshold {confidence_threshold:.2f}"
            )
        else:
            field_confidence = tagged_confidence.get(field)
            if field_confidence is None:
                status = "missing"
                reason = "no field-targeted question/evidence recorded yet for this field (backend.research.investigate can produce one, Phase 8.4)"
            elif field_confidence >= confidence_threshold:
                status = "present"
                reason = f"a targeted question tagged research_field={field!r} has qualifying evidence (confidence {field_confidence:.2f})"
            else:
                status = "missing"
                reason = (
                    f"a targeted question tagged research_field={field!r} exists but its evidence "
                    f"(confidence {field_confidence:.2f}) does not meet policy threshold {confidence_threshold:.2f}"
                )
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
    *,
    questions_by_entity: dict[str, list[QuestionNode]] | None = None,
    claims_by_question: dict[str, list[ClaimNode]] | None = None,
) -> ResearchReadinessReport:
    """Pure logic: rolls assess_target_completeness up across every target in
    a plan. `claims_by_entity`/`questions_by_entity`/`claims_by_question` are
    all already-fetched data (the I/O shell below does the fetching) -- an
    entity_id missing from any dict is treated as no data, not an error,
    matching planner.py's own "a gap this surfaces by omission" principle.
    """
    questions_by_entity = questions_by_entity or {}
    claims_by_question = claims_by_question or {}
    concepts = [
        assess_target_completeness(
            target,
            claims_by_entity.get(target.entity_id, []),
            plan.policy.confidence_threshold,
            questions=questions_by_entity.get(target.entity_id, []),
            claims_by_question=claims_by_question,
        )
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
    questions_by_entity: dict[str, list[QuestionNode]] = {}
    claims_by_question: dict[str, list[ClaimNode]] = {}
    for target in plan.targets:
        questions = await get_questions_for_entity(target.entity_id)
        questions_by_entity[target.entity_id] = questions
        entity_claims: list[ClaimNode] = []
        for question in questions:
            q_claims = await get_claims_for_question(question.id)
            claims_by_question[question.id] = q_claims
            entity_claims.extend(q_claims)
        claims_by_entity[target.entity_id] = entity_claims
    return assess_plan_readiness(
        plan,
        claims_by_entity,
        questions_by_entity=questions_by_entity,
        claims_by_question=claims_by_question,
    )
