from __future__ import annotations

from backend.agents.ground_agent import GroundAgent
from backend.agents.policy import ResearchPolicy
from backend.questions import Question, QuestionLevel

from .coverage import build_readiness_report
from .models import UNCLASSIFIED_FIELDS, ResearchPlan, ResearchReadinessReport, TargetedInvestigationRequest
from .planner import build_research_plan

# Phase 8.4 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.44):
# Deep investigation orchestration -- the piece that can actually turn a
# Phase 8.3 "missing" into a "present" for UNCLASSIFIED_FIELDS, by running
# real, field-targeted investigations and tagging their output. This is the
# first module in this whole track (8.1-8.3 were deliberately deterministic,
# no-LLM) that makes real LLM/retriever calls -- reuses the existing
# GroundAgent/Evidence Engine machinery unchanged, the same "add an
# orchestration layer, don't fork the engine" principle Phase 8.1 already
# established for ResearchPolicy.
#
# The governing constraint (explicit instruction that shaped this module):
# orchestrate targeted research for missing fields WITHOUT turning the whole
# investigation engine into an uncontrolled deep-search system. Concretely,
# three independent bounds, not one:
#   1. Every targeted investigation runs at max_depth=0, max_sequential_steps=0
#      -- confirmed against ground_agent.py's actual budget_exhausted logic
#      (Architecture.md §0.44) that this forces a single bounded answer, NEVER
#      a recursive decomposition, regardless of what the LLM would otherwise
#      choose to do. Deliberately NOT inherited from the ambient ResearchPolicy
#      (which may allow depth=2) -- a one-field targeted question must never
#      decompose, full stop, independent of what policy governs the rest of
#      the investigation.
#   2. plan_targeted_investigations caps how many CONCEPTS get processed
#      (max_targets) and how many FIELDS per concept (max_fields_per_target)
#      -- a large incomplete plan does not silently trigger dozens of LLM
#      calls in one orchestration pass.
#   3. Only UNCLASSIFIED_FIELDS are ever targeted here -- CONFIDENCE_GATED_FIELDS
#      being missing (low-confidence base evidence, not absent evidence) is a
#      different, already-solved problem (re-investigating the base question
#      via the existing "investigate_deeper" chat intent), not this module's.

_FIELD_QUESTION_TEMPLATES = {
    "prerequisites": "What must someone already understand before learning about {entity_name}?",
    "examples": "Give a concrete, worked example of {entity_name} in practice.",
    "misconceptions": "What is a common misconception people have about {entity_name}?",
}
assert set(_FIELD_QUESTION_TEMPLATES) == UNCLASSIFIED_FIELDS, "every UNCLASSIFIED_FIELDS member needs a question template"


def plan_targeted_investigations(
    report: ResearchReadinessReport,
    *,
    max_targets: int = 5,
    max_fields_per_target: int = 3,
) -> list[TargetedInvestigationRequest]:
    """Pure, deterministic: which (entity, field) pairs actually need a
    targeted investigation, bounded. No I/O, no LLM call -- the part of this
    module that's directly unit-testable (scripts/verify_phase8_4.py).
    Processes concepts and fields in the report's own existing order (already
    deterministic, per Phase 8.2/8.3 -- this function doesn't re-sort).
    """
    requests: list[TargetedInvestigationRequest] = []
    targets_processed = 0
    for concept in report.concepts:
        if concept.is_complete:
            continue
        unclassified_missing = [f for f in sorted(concept.missing_fields) if f in UNCLASSIFIED_FIELDS]
        if not unclassified_missing:
            continue  # e.g. only a CONFIDENCE_GATED_FIELDS gap -- not this module's job
        if targets_processed >= max_targets:
            break
        for field in unclassified_missing[:max_fields_per_target]:
            requests.append(
                TargetedInvestigationRequest(entity_id=concept.entity_id, entity_name=concept.entity_name, field=field)
            )
        targets_processed += 1
    return requests


async def run_targeted_investigation(request: TargetedInvestigationRequest, policy: ResearchPolicy) -> None:
    """I/O: the one place in this module an LLM/retriever call actually
    happens. Builds a field-specific Question (deterministic template above,
    not LLM-generated -- only the ANSWER is), runs it through the existing
    GroundAgent/Evidence Engine at max_depth=0/max_sequential_steps=0 (see
    module docstring for why), and persists it tagged with research_field so
    Phase 8.3's coverage model can recognize it next time.
    """
    question = Question(
        text=_FIELD_QUESTION_TEMPLATES[request.field].format(entity_name=request.entity_name),
        rationale=f"Phase 8.4 targeted investigation: closing the {request.field!r} coverage gap for {request.entity_name!r}.",
        dimension_id="none",
        level=QuestionLevel.MASTER,
        entity_name=request.entity_name,
        abstraction_name=request.entity_name,
        research_field=request.field,
    )
    agent = GroundAgent(
        question,
        persist_to_graph=True,
        gather_evidence=True,
        max_depth=0,
        max_sequential_steps=0,
        max_results_per_retriever=policy.max_results_per_retriever,
    )
    await agent.run()


async def close_coverage_gaps(
    plan: ResearchPlan,
    report: ResearchReadinessReport,
    *,
    max_targets: int = 5,
    max_fields_per_target: int = 3,
) -> ResearchReadinessReport:
    """The orchestration loop the acceptance criterion actually asks for:
    given an incomplete report, perform ONLY the required field-targeted
    work (bounded per plan_targeted_investigations above), then recompute and
    return a FRESH coverage report so the caller can see exactly what
    changed -- never mutates the report it was given.

    Deliberately re-fetches the plan/report from scratch afterward
    (build_research_plan + build_readiness_report) rather than patching the
    old report in place: the real source of truth is Neo4j, and re-reading
    it is the only way to be sure what's reported matches what's actually
    there, the same "never trust a stale in-memory copy" discipline the rest
    of this project already follows.
    """
    requests = plan_targeted_investigations(report, max_targets=max_targets, max_fields_per_target=max_fields_per_target)
    for request in requests:
        await run_targeted_investigation(request, plan.policy)

    if not requests:
        return report  # nothing to do -- avoid a needless re-fetch when already complete/unactionable

    refreshed_plan = await build_research_plan(plan.abstraction_id, plan.policy)
    return await build_readiness_report(refreshed_plan)
