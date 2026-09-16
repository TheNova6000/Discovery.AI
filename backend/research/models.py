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
#     nothing in the ORDINARY investigation pipeline asks for or tags this
#     content specifically -- reported "missing" unless a real Question
#     exists with `research_field` set to that name (QuestionNode.research_field,
#     Phase 8.4, backend.research.investigate). Never guessed from untagged
#     prose -- only a question `investigate.py` deliberately created and
#     tagged can satisfy one of these.
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
    Before Phase 8.4's targeted investigation runs for a concept, any
    `UNCLASSIFIED_FIELDS` member in its required set is honestly `"missing"`
    -- not a bug, the accurate signal that nothing has targeted that field
    yet. `backend.research.investigate.close_coverage_gaps` (Phase 8.4) is
    what can turn a target's status from incomplete to complete, by
    producing real, field-tagged evidence and re-running this assessment.
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


class TargetedInvestigationRequest(BaseModel):
    """Phase 8.4 (docs/Phases.md, docs/Architecture.md §0.44): one bounded
    unit of targeted work -- "go find `field` for `entity_name`" -- produced
    by `investigate.plan_targeted_investigations` (pure, deterministic) and
    consumed by `investigate.run_targeted_investigation` (I/O, the one place
    an LLM call actually happens in this module). `field` is always a member
    of UNCLASSIFIED_FIELDS -- CONFIDENCE_GATED_FIELDS' gap (low-confidence
    evidence, not missing evidence) is a different problem this phase
    doesn't address (that's re-investigating the base question, already
    available via the existing "investigate_deeper" chat intent)."""

    entity_id: str
    entity_name: str
    field: str


# Phase 8.5 (docs/Phases.md, docs/Architecture.md §0.45): Evidence and
# contradiction validation. Split the same way every phase in this track has
# split real vs. LLM-shaped work: a deterministic layer (duplicate/superseded/
# weak-evidence detection -- string/field comparisons over already-fetched
# ClaimNodes, no LLM call, unit-tested with fixtures) and a bounded, OPT-IN
# LLM layer reusing the existing epistemic-layer machinery
# (backend.questions.analyze_claim_relationships, Post-Phase-5) rather than
# inventing new contradiction-detection logic. The LLM layer defaults OFF in
# the main validation entrypoint -- Architecture.md §0.5 already documents
# that analyze_claim_relationships' real-world reliability at genuine
# competing-explanation detection is not yet proven at scale (the controlled
# follow-up experiment Phase 7 itself is still waiting on); Phase 8.5 reuses
# it as-is rather than re-litigating or re-proving that here, and is honest
# that turning it on inherits that same open question.


class DuplicateClaimPair(BaseModel):
    """Two claims flagged as duplicates of the same underlying evidence --
    exact-match only (identical source_url, or identical evidence text) on
    purpose: a near-duplicate/paraphrase detector would need an LLM or
    embedding comparison, which is exactly the kind of judgment this
    deterministic layer explicitly excludes (see module-level note above)."""

    claim_id_a: str
    claim_id_b: str
    reason: str  # "identical source_url" | "identical evidence text"


class ClaimValidationReport(BaseModel):
    """Deterministic quality signals for one concept's claim set -- computed
    by `validation.assess_claim_validity`, no LLM call. Distinct from Phase
    8.3's `ConceptCompleteness` (which asks "is this field covered at all")
    -- this asks "is what's covering it actually trustworthy," surfacing
    duplicate/superseded/weak evidence Phase 8.3 either doesn't check for
    (duplicates) or silently filters without reporting (superseded)."""

    entity_id: str
    entity_name: str
    active_claim_count: int
    superseded_claim_ids: list[str] = Field(default_factory=list)
    weak_claim_ids: list[str] = Field(default_factory=list)
    """Active claims below the confidence threshold used for this check --
    individually weak, distinct from Phase 8.3's aggregate max-confidence
    gate (a concept can have one strong claim and several weak ones; this
    surfaces the weak ones specifically, Phase 8.3 doesn't)."""
    duplicate_pairs: list[DuplicateClaimPair] = Field(default_factory=list)
    distinct_source_count: int
    """Count of distinct, non-superseded source_urls -- a deterministic
    proxy for "how many independent sources actually support this," used by
    `has_independent_support` below rather than raw claim count (which
    duplicates would inflate)."""
    has_independent_support: bool
    """True iff distinct_source_count >= 2 -- a concept "supported" by three
    duplicate claims citing the same URL is NOT independently supported,
    even though Phase 8.3's confidence check alone wouldn't catch that."""


class ContradictionFinding(BaseModel):
    """One pair of claims `backend.questions.analyze_claim_relationships`
    (Post-Phase-5's epistemic layer, reused unchanged) classified as
    genuinely "contradictory" with respect to a specific question -- never
    silently resolved one way, always carries the model's own reasoning so a
    reader can judge the finding rather than trust a bare label."""

    claim_id_a: str
    claim_id_b: str
    reasoning: str
    confidence: float


class ContradictionReport(BaseModel):
    """Phase 8.5's optional LLM layer output for one concept -- `checked` is
    False whenever detect_contradictions wasn't run or was skipped (e.g. too
    many claims for the bounded max_claims cap, Architecture.md §0.45), so a
    caller can always tell "no contradictions found" apart from "never
    actually checked" -- the same empty-vs-unknown honesty bar Rules.md rule
    9 already sets for claims."""

    entity_id: str
    entity_name: str
    checked: bool
    skipped_reason: str | None = None
    findings: list[ContradictionFinding] = Field(default_factory=list)
