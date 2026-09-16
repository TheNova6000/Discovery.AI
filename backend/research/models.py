from __future__ import annotations

from pydantic import BaseModel, Field

from backend.agents.policy import ResearchPolicy

# Phase 8.2 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.42):
# the five research-completeness fields PRD.md §9.3a lists, minus the two
# that have no ResearchPolicy require_* toggle because they're unconditional
# -- every concept needs a definition and a mechanism to count as researched
# at all, regardless of mode. The other four are gated by their matching
# ResearchPolicy field (Phase 8.1) one-to-one.
BASE_REQUIRED_FIELDS = frozenset({"definition", "mechanism"})

REQUIRED_FIELD_POLICY_GATES = {
    "prerequisites": "require_prerequisites",
    "examples": "require_examples",
    "misconceptions": "require_misconceptions",
    "evidence": "require_evidence_validation",
}
"""Maps each optional research field to the exact ResearchPolicy attribute
name that gates it -- a single source of truth `planner.py`'s
`_required_fields_for_policy` reads via getattr, so adding a new gated field
later means adding one dict entry, not a new if-branch."""


class ConceptResearchTarget(BaseModel):
    """One already-discovered entity this plan says needs research, and
    exactly which fields that research must cover under the active policy.
    Deliberately does NOT carry prerequisite-entity edges yet -- the
    `requires`/`prerequisite_of` relation type this would read doesn't exist
    in the graph until Phase 8.4 (docs/Phases.md) adds it; a field with
    nothing behind it yet would misrepresent what this phase actually reads,
    the same "don't pretend a value is controlled when it isn't" rule
    Phase 8.1's ResearchPolicy already followed.
    """

    entity_id: str
    entity_name: str
    required_fields: frozenset[str]


class ResearchPlan(BaseModel):
    """What `build_research_plan(abstraction_id, policy)` (planner.py)
    produces: one `ConceptResearchTarget` per entity already in the
    abstraction's subgraph (same source `backend.graph.get_subgraph` already
    gives `generate_roadmap` -- Phase 6/Rules.md rule 14's "pure function
    reading an already-built graph" pattern, reused here). Never invents a
    concept that isn't already discovered -- deciding "what concepts SHOULD
    exist for this topic that aren't here yet" is an LLM-shaped judgment
    explicitly out of scope for this deterministic planning phase (see
    planner.py's module docstring).
    """

    model_config = {"arbitrary_types_allowed": True}

    abstraction_id: str
    abstraction_name: str
    policy: ResearchPolicy
    targets: list[ConceptResearchTarget] = Field(default_factory=list)
