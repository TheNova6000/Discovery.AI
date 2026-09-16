from __future__ import annotations

from datetime import datetime, timezone

from backend.agents.policy import ResearchPolicy
from backend.graph.interface import get_claims_for_question, get_questions_for_entity
from backend.graph.models import ClaimNode

from .coverage import build_readiness_report
from .models import ConceptResearchArtifact, ContradictionReport, EvidenceReference, ResearchArtifact, ResearchPlan, ResearchReadinessReport
from .planner import build_research_plan
from .validation import assess_claim_validity

# Phase 8.6 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.46):
# Research-complete graph artifact. The crucial rule this module follows,
# verbatim from the instruction that shaped it: package and expose the
# research state -- do not perform new research, do not compile curriculum.
#
# Concretely: `compile_research_artifact` makes ZERO LLM calls of its own,
# not even optionally behind a flag. It calls Phase 8.2's
# build_research_plan and Phase 8.3's build_readiness_report (both already
# LLM-free reads), plus the same get_questions_for_entity/get_claims_for_question
# reads coverage.py already does, and Phase 8.5's assess_claim_validity
# (deterministic, no LLM). Phase 8.5's OTHER function, detect_contradictions,
# is the one real LLM call anywhere in this whole 8.1-8.6 track that this
# module deliberately never invokes on its own -- a caller who wants
# contradiction findings folded into the artifact runs detect_contradictions
# themselves (a separate, deliberate, bounded step, exactly as Phase 8.5
# scoped it) and passes the results in via `contradiction_reports_by_entity`.
# This isn't a missing feature; it's the one design choice that makes "this
# module performs no new research" an unambiguous, mechanically-true
# property instead of a flag someone could accidentally flip.


def assemble_research_artifact(
    plan: ResearchPlan,
    report: ResearchReadinessReport,
    claims_by_entity: dict[str, list[ClaimNode]],
    *,
    contradiction_reports_by_entity: dict[str, ContradictionReport] | None = None,
) -> ResearchArtifact:
    """Pure logic: assembles everything Phase 8.1-8.5 already computed into
    one artifact. No I/O, no LLM call -- literally cannot make one, since
    every input is already-fetched data passed in by the caller. This is
    the part scripts/verify_phase8_6.py actually tests.
    """
    contradiction_reports_by_entity = contradiction_reports_by_entity or {}
    concepts: list[ConceptResearchArtifact] = []
    for target, completeness in zip(plan.targets, report.concepts):
        claims = claims_by_entity.get(target.entity_id, [])
        active = [c for c in claims if c.superseded_by is None]
        validity = assess_claim_validity(target.entity_id, target.entity_name, claims)
        evidence_refs = [
            EvidenceReference(
                claim_id=c.id,
                source_title=c.source_title,
                source_url=c.source_url,
                source_type=c.source_type,
                confidence=c.confidence,
            )
            for c in active
        ]
        concepts.append(
            ConceptResearchArtifact(
                entity_id=target.entity_id,
                entity_name=target.entity_name,
                required_fields=target.required_fields,
                field_coverage=completeness.field_coverage,
                is_complete=completeness.is_complete,
                missing_fields=completeness.missing_fields,
                claim_validity=validity,
                contradictions=contradiction_reports_by_entity.get(target.entity_id),
                evidence_refs=evidence_refs,
            )
        )

    return ResearchArtifact(
        abstraction_id=plan.abstraction_id,
        abstraction_name=plan.abstraction_name,
        policy=plan.policy,
        concepts=concepts,
        ready_count=report.ready_count,
        incomplete_count=report.incomplete_count,
        is_ready=report.is_ready,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


async def compile_research_artifact(
    abstraction_id: str,
    policy: ResearchPolicy,
    *,
    contradiction_reports_by_entity: dict[str, ContradictionReport] | None = None,
) -> ResearchArtifact:
    """I/O shell: fetches the plan/report/claims from Neo4j by calling the
    existing Phase 8.2/8.3 functions unchanged, then hands off to the pure
    assembler above. Rules.md rule 14, same constraint every phase in this
    track follows for its own I/O shell -- reads only. See this module's
    docstring for why contradiction findings are never fetched here.
    """
    plan = await build_research_plan(abstraction_id, policy)
    report = await build_readiness_report(plan)

    claims_by_entity: dict[str, list[ClaimNode]] = {}
    for target in plan.targets:
        questions = await get_questions_for_entity(target.entity_id)
        claims: list[ClaimNode] = []
        for question in questions:
            claims.extend(await get_claims_for_question(question.id))
        claims_by_entity[target.entity_id] = claims

    return assemble_research_artifact(
        plan, report, claims_by_entity, contradiction_reports_by_entity=contradiction_reports_by_entity
    )
