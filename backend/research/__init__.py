"""Learning Research Planner + Coverage/Completeness model + targeted
investigation orchestration (Phases 8.2-8.4, docs/PRD.md §9.3a, docs/Phases.md).

Phase 8.2 (planner.py): turns an already-investigated abstraction's subgraph
plus an active ResearchPolicy (Phase 8.1, backend.agents.policy) into a
ResearchPlan -- one ConceptResearchTarget per already-discovered entity, each
carrying which research fields that policy requires ("what SHOULD this
concept contain"). Deterministic, no LLM/retriever call (Rules.md rule 14) --
never decides what concepts SHOULD exist, only what's required of the ones
that already do.

Phase 8.3 (coverage.py): given a plan, reads each target's REAL, already-
recorded evidence and decides which required fields are actually satisfied
("what DOES this concept contain, and is that enough"). Also deterministic,
no LLM call -- honestly reports the three content-classification fields
(prerequisites/examples/misconceptions) as missing unless a real, tagged
targeted question already covers them (models.py's UNCLASSIFIED_FIELDS note).

Phase 8.4 (investigate.py): the first module in this track that makes real
LLM/retriever calls. plan_targeted_investigations (pure, bounded) decides
which (entity, field) gaps to close; run_targeted_investigation (I/O) runs
one bounded, non-recursive GroundAgent investigation per gap and tags its
Question with research_field; close_coverage_gaps orchestrates both and
returns a fresh coverage report. Curriculum compilation and lesson/exercise
generation are explicitly later phases, not this module's job.
"""

from .coverage import assess_plan_readiness, assess_target_completeness, build_readiness_report
from .investigate import close_coverage_gaps, plan_targeted_investigations, run_targeted_investigation
from .models import (
    BASE_REQUIRED_FIELDS,
    CONFIDENCE_GATED_FIELDS,
    REQUIRED_FIELD_POLICY_GATES,
    UNCLASSIFIED_FIELDS,
    ConceptCompleteness,
    ConceptResearchTarget,
    FieldCoverage,
    ResearchPlan,
    ResearchReadinessReport,
    TargetedInvestigationRequest,
)
from .planner import build_research_plan, plan_targets

__all__ = [
    "build_research_plan",
    "plan_targets",
    "ResearchPlan",
    "ConceptResearchTarget",
    "BASE_REQUIRED_FIELDS",
    "REQUIRED_FIELD_POLICY_GATES",
    "assess_plan_readiness",
    "assess_target_completeness",
    "build_readiness_report",
    "CONFIDENCE_GATED_FIELDS",
    "UNCLASSIFIED_FIELDS",
    "ConceptCompleteness",
    "FieldCoverage",
    "ResearchReadinessReport",
    "plan_targeted_investigations",
    "run_targeted_investigation",
    "close_coverage_gaps",
    "TargetedInvestigationRequest",
]
