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


# Phase 8.3 (docs/Phases.md, docs/PRD.md §9.3a, docs/Architecture.md §0.43):
# which required fields a concept's REAL, ALREADY-RECORDED evidence actually
# satisfies -- distinct from planner.py's "which fields does this concept
# NEED" (Phase 8.2). Honesty boundary, following the exact discipline
# Phase 8.1/8.2 already set (don't claim a value is known when it isn't):
# today's Ground Agent asks one generic master-level question per entity and
# synthesizes one combined answer -- real evidence, but never tagged by which
# PRD.md §9.3a field it satisfies. So:
#   - CONFIDENCE_GATED_FIELDS ("definition", "mechanism", "evidence"): the
#     current single-pass answer genuinely does cover "what is this and how
#     does it work" -- real content, not fabricated -- so these are scored by
#     whether real, non-superseded evidence meets the policy's confidence bar.
#   - UNCLASSIFIED_FIELDS ("prerequisites", "examples", "misconceptions"):
#     nothing in the current investigation pipeline asks for or tags this
#     content specifically. Always reported "missing" -- never guessed at
#     from generic prose -- until Phase 8.4 adds field-targeted investigation
#     that can actually produce and tag this content.
CONFIDENCE_GATED_FIELDS = frozenset({"definition", "mechanism", "evidence"})
UNCLASSIFIED_FIELDS = frozenset({"prerequisites", "examples", "misconceptions"})


class FieldCoverage(BaseModel):
    """Whether ONE required field is satisfied for one concept, and why --
    `reason` exists so a caller (or a person reading a report) never has to
    take `status` on faith; it always says what real evidence was checked, or
    honestly says none exists yet for this field."""

    field: str
    status: str  # "present" | "missing"
    reason: str


class ConceptCompleteness(BaseModel):
    """One target's full field-by-field verdict plus the derived overall
    verdict (`is_complete`) -- a target is complete only when EVERY field its
    ResearchPolicy requires (Phase 8.2's `required_fields`) is `"present"`.
    Under any policy with an `UNCLASSIFIED_FIELDS` member in its required set
    (i.e. any real "learning"-shaped policy today), `is_complete` is
    honestly always False -- not a bug, the accurate signal that nothing yet
    produces classifiable prerequisite/example/misconception content
    (Phase 8.4's actual job).
    """

    entity_id: str
    entity_name: str
    field_coverage: list[FieldCoverage] = Field(default_factory=list)
    is_complete: bool
    missing_fields: frozenset[str] = Field(default_factory=frozenset)


class ResearchReadinessReport(BaseModel):
    """The whole-plan rollup `assess_plan_readiness`/`build_readiness_report`
    (coverage.py) produce -- answers "is this abstraction ready for
    curriculum use under this policy" without the caller needing to inspect
    every concept individually, while `concepts` still carries the full
    per-concept detail for anyone who does."""

    model_config = {"arbitrary_types_allowed": True}

    abstraction_id: str
    abstraction_name: str
    policy: ResearchPolicy
    concepts: list[ConceptCompleteness] = Field(default_factory=list)
    ready_count: int
    incomplete_count: int
    is_ready: bool
