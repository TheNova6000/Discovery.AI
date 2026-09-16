"""Learning Research Planner (Phase 8.2, docs/PRD.md §9.3a, docs/Phases.md).

Turns an already-investigated abstraction's subgraph plus an active
ResearchPolicy (Phase 8.1, backend.agents.policy) into a ResearchPlan: one
ConceptResearchTarget per already-discovered entity, each carrying which
research fields that policy requires. Deterministic, no LLM/retriever call
(Rules.md rule 14, same constraint backend.roadmap already follows) -- it
does not decide what concepts SHOULD exist, only what's required of the ones
that already do. Deep investigation to actually fill those fields (Phase
8.4), checking whether they're already filled (Phase 8.3's completeness
model), and everything downstream of that are explicitly later phases.
"""

from .models import BASE_REQUIRED_FIELDS, REQUIRED_FIELD_POLICY_GATES, ConceptResearchTarget, ResearchPlan
from .planner import build_research_plan, plan_targets

__all__ = [
    "build_research_plan",
    "plan_targets",
    "ResearchPlan",
    "ConceptResearchTarget",
    "BASE_REQUIRED_FIELDS",
    "REQUIRED_FIELD_POLICY_GATES",
]
