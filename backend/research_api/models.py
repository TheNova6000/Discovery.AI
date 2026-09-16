from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from backend.agents import ClaimProvenance, ResearchMode
from backend.graph import GraphNode, Relationship
from backend.reasoning import Claim, ResearchTask
from backend.research import (
    BASE_REQUIRED_FIELDS,
    REQUIRED_FIELD_POLICY_GATES,
    ConceptCompleteness,
    ContradictionFinding,
    EvidenceReference,
)

# R5.1 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.57/§0.73): the stable Discovery.AI Research API contract, as pure types
# only -- no compiler, no route, no orchestration. This module is a
# PROJECTION over the real, already-built models the R1-R4/Phase 8 track
# produced, never a second, competing representation of the same facts:
#
#     ClaimNode / evidence.Claim / reasoning.domain.Claim / ResearchArtifact
#                                 |
#                                 v
#                       ResearchResponse (this file)
#
# Every field below reuses a REAL existing type from the package that
# already owns that concept -- Claim from backend.reasoning, GraphNode/
# Relationship from backend.graph, EvidenceReference/ConceptCompleteness/
# ContradictionFinding from backend.research (Phase 8.2-8.6),
# ClaimProvenance from backend.agents (Post-Phase-5's epistemic layer),
# ResearchTask from backend.reasoning (R3). Nothing here is a new epistemic
# model; it is a stable boundary a client (Phase 9, first) can depend on
# without knowing about tasks, events, the bus, or Neo4j.
#
# Six required-design-check answers, recorded here rather than left
# implicit, per this slice's own instruction:
#
# 1. Source model per field -- see each field's own docstring below; every
#    one names the real type and package it comes from.
# 2. Directly mappable fields: claims, evidence, coverage, contradictions,
#    unresolved_tasks, entities, relationships -- all real types with real
#    (if not-yet-wired) producers.
# 3. Fields with NO current producer, kept honestly empty/optional:
#    subclaims (no live orchestration creates parent/subclaim relations
#    yet -- R4.3's own stated non-goal), unresolved_tasks (MasterAgent.
#    run_task_graph has zero callers in the live /chat path -- R3.2's own
#    confirmed finding), provenance (trace_claim exists and is real, but
#    requires a live SQLite agent-tree walk this pure-types slice does not
#    perform), root_entity_id (see below).
# 4. claims vs. serialized records: `claims`/`subclaims` hold REAL
#    `reasoning.domain.Claim` objects, not a fourth, flattened claim shape.
#    A subclaim is not a distinct type (R4.3: a subclaim is a Claim with
#    `parent_claim_id` set) -- `subclaims` is a convenience VIEW, every
#    entry in it is also present in `claims`, never a disjoint identity.
# 5. Round-trip serialization: every nested type here (Claim, GraphNode,
#    Relationship, EvidenceReference, ConceptCompleteness,
#    ContradictionFinding, ResearchTask, ClaimProvenance) is already a
#    plain pydantic BaseModel with no custom serializers -- no additional
#    `model_config` is needed for `model_dump_json`/`model_validate_json`
#    to round-trip correctly (confirmed by this slice's own test #6).
# 6. Package naming: no existing "API contract" package exists --
#    `backend/api/` is the HTTP-route layer (app.py/session.py), and
#    `backend/research/` already has its own documented scope (Phase
#    8.2-8.6 orchestration + R4.1/R4.2/R4.4's claim bridge/persistence).
#    `backend/research_api/` is a new, minimal top-level package for
#    exactly this one concern -- the stable client-facing contract --
#    sitting above every package it reuses types from (no cycle: none of
#    backend.reasoning/backend.graph/backend.research/backend.agents
#    import from this new package).
#
# One field with NO clean single-value source, confirmed by direct
# inspection rather than papered over with a guess: `root_entity_id`.
# `ResearchArtifact` (Phase 8.6, R5's own named "closest existing
# approximation" of ResearchResponse) is ABSTRACTION-scoped, and an
# Abstraction may legitimately contain multiple concept entities (the real
# "online payment" abstraction has 5) with no designated "root" anywhere in
# `backend.graph.models.Abstraction` or `ResearchArtifact` itself.
# Inventing a heuristic (e.g. "the first concept") would fabricate
# structure the data doesn't actually have. `root_entity_id` therefore
# stays `Optional[str] = None` -- explicitly reserved for a future model
# with a real designated root (e.g. a genuine `Investigation` object,
# still unbuilt), not populated by a guess in this slice.
#
# `investigation_id` has the same real gap -- no standalone `Investigation`
# object exists anywhere in this codebase (confirmed repeatedly across
# R0-R5's own audits). The closest real, durable, already-existing
# identifier for "a researched topic" is the Neo4j `Abstraction` id (Phase
# 6), which `ResearchArtifact.abstraction_id` already carries -- reusing
# it, not inventing a synthetic investigation id, preserves real identity.
# A genuine `Investigation` object, if ever built, would supersede this
# mapping; the field's NAME (matching Architecture.md §0.57) would not need
# to change.
#
# `status` is deliberately NOT Architecture.md §0.55's full aspirational
# 12-state investigation lifecycle (created/planning/investigating/
# waiting_on_dependency/validating/partially_complete/complete/blocked/
# uncertain/contradictory/budget_exhausted/failed) -- most of those states
# have no real producer anywhere in this codebase today (nothing computes
# "waiting_on_dependency" or "budget_exhausted" at the investigation level).
# `ResearchResponseStatus` below is the two states `ResearchArtifact.
# is_ready` can actually, honestly distinguish today; inventing the other
# ten would be exactly the "type-safety without semantic correctness" trap
# Architecture.md §0.56 already named for claim migration, applied here to
# investigation status instead.

_KNOWN_REQUIRED_FIELDS: frozenset[str] = BASE_REQUIRED_FIELDS | frozenset(REQUIRED_FIELD_POLICY_GATES)
"""The real, already-established six-field vocabulary (Phase 8.2/8.3) --
not a new enum invented for this slice. `ResearchRequest.required_fields`
is validated against this exact set, reusing it rather than duplicating
the literal field names a third time."""

ResearchResponseStatus = Literal["complete", "partially_complete"]


class ResearchRequest(BaseModel):
    """What a client asks Discovery.AI to research (Architecture.md §0.57).
    Pure request data -- no orchestration, no route, no LLM call lives here.
    """

    topic: str = Field(min_length=1)
    objective: Optional[str] = None
    """Free-form: no structured "objective" vocabulary exists anywhere in
    this codebase yet (PRD.md §10.4 names this as one example of a
    client-specified objective, not a fixed enum) -- kept as a plain,
    honestly-unconstrained string rather than a fabricated Literal."""
    mode: ResearchMode = "exploratory"
    """Reuses `backend.agents.policy.ResearchMode` (Phase 8.1) directly --
    not a new mode vocabulary. The real, only two values that exist:
    "exploratory" | "learning"."""
    required_fields: frozenset[str] = Field(default_factory=frozenset)
    """Reuses Phase 8.2's own six-field vocabulary (`ConceptResearchTarget.
    required_fields` has the identical type and meaning) -- validated
    below against `_KNOWN_REQUIRED_FIELDS`, not a free-form string set."""
    learner_level: Optional[str] = None
    """No learner-level concept exists anywhere in this codebase (Phase 13
    -- the Learner Model -- has not started; confirmed by directory
    listing). Honestly `None`-only until a real producer exists; never a
    fabricated default like `"beginner"`."""
    constraints: dict[str, Any] = Field(default_factory=dict)
    """No single unified "budget/constraints" object exists in this
    codebase today -- `MasterAgent.spawn_budget`, `ResearchTask.
    max_attempts`, and `ResearchPolicy`'s various fields are each their own,
    separately-typed real budget concept. A generic, honestly-empty-by-
    default mapping, not a fabricated structured type collapsing three
    different real budget concepts into one that doesn't actually exist."""

    @model_validator(mode="after")
    def _required_fields_known(self) -> "ResearchRequest":
        unknown = self.required_fields - _KNOWN_REQUIRED_FIELDS
        if unknown:
            raise ValueError(
                f"required_fields contains unrecognized field name(s) {sorted(unknown)} -- "
                f"must be a subset of the known vocabulary {sorted(_KNOWN_REQUIRED_FIELDS)}"
            )
        return self


class ResearchResponse(BaseModel):
    """The stable boundary a client consumes (Architecture.md §0.57) --
    entities/claims/subclaims/evidence/coverage/contradictions/provenance,
    never raw agent internals (AgentState, LangGraph state, the message
    bus). A PROJECTION over real, already-computed Discovery.AI state; see
    this module's own header comment for the full field-by-field source
    mapping and every honestly-empty field's real reason.

    Populating this from a real, already-compiled `ResearchArtifact` (and
    the other real sources named above) is R5.2's job (`compile_research_
    response`), explicitly not this type's -- this class only defines the
    shape, with no logic beyond field-level validation.
    """

    investigation_id: str = Field(min_length=1)
    """The real Neo4j `Abstraction.id` (Phase 6) `ResearchArtifact.
    abstraction_id` already carries -- no standalone Investigation object
    exists in this codebase (confirmed across R0-R5's own audits)."""
    status: ResearchResponseStatus
    """Derived from `ResearchArtifact.is_ready` (Phase 8.6) -- deliberately
    only the two states that field can actually, honestly distinguish
    today, not Architecture.md §0.55's full aspirational lifecycle (see
    this module's header comment for why)."""
    root_entity_id: Optional[str] = None
    """`None` by default -- `ResearchArtifact` is abstraction-scoped and may
    cover multiple concept entities with no designated root anywhere in the
    current data model (see this module's header comment). Reserved for a
    future model with a real designated root, never populated by a guess."""
    entities: list[GraphNode] = Field(default_factory=list)
    """`backend.graph.models.GraphNode` (Phase 1) directly -- the real
    entity/domain node type, not a re-shaped copy."""
    relationships: list[Relationship] = Field(default_factory=list)
    """`backend.graph.models.Relationship` (Phase 1) directly."""
    claims: list[Claim] = Field(default_factory=list)
    """`backend.reasoning.domain.Claim` (R1) directly -- the real,
    lifecycle-bearing canonical claim type this whole R1-R4 track exists to
    provide, not a fourth claim shape invented for this API boundary."""
    subclaims: list[Claim] = Field(default_factory=list)
    """Every entry here is ALSO present in `claims` -- R4.3 established
    that a subclaim is a `Claim` with `parent_claim_id`/`relation_to_parent`
    set, not a separate object or a separate identity. This field is a
    convenience pre-filtered view (`c for c in claims if subclaim_relation(c)
    is not None`), never a disjoint list; populating it is R5.2's job, not
    this type's. Empty in every fixture in this slice -- no real
    orchestration creates parent/subclaim relations from live data yet
    (R4.3's own stated non-goal, still true)."""
    evidence: list[EvidenceReference] = Field(default_factory=list)
    """`backend.research.models.EvidenceReference` (Phase 8.6) directly --
    already exactly this: a lightweight, real provenance pointer back to a
    non-superseded `Claim`."""
    coverage: list[ConceptCompleteness] = Field(default_factory=list)
    """`backend.research.models.ConceptCompleteness` (Phase 8.3) directly,
    one per researched concept -- reused rather than re-deriving a new
    "Coverage" shape from `ResearchArtifact`'s own `ConceptResearchArtifact`
    (which already embeds the identical `field_coverage`/`is_complete`/
    `missing_fields` fields `ConceptCompleteness` has)."""
    contradictions: list[ContradictionFinding] = Field(default_factory=list)
    """`backend.research.models.ContradictionFinding` (Phase 8.5) directly,
    flattened across whichever concepts actually ran `detect_contradictions`
    -- that call remains bounded and opt-in (Phase 8.5's own design), so
    this list is honestly empty for any concept it was never run against."""
    unresolved_tasks: list[ResearchTask] = Field(default_factory=list)
    """`backend.reasoning.ResearchTask` (R3) directly. Honestly empty in
    every real case today: `MasterAgent.run_task_graph` (R3.2) has zero
    callers anywhere in the live `/chat` path (confirmed by repo-wide
    search, R3.2's own finding, still true) -- there is no real task graph
    behind any live investigation yet to report as unresolved."""
    provenance: list[ClaimProvenance] = Field(default_factory=list)
    """`backend.agents.provenance.ClaimProvenance` (Post-Phase-5's epistemic
    layer) directly -- the real, existing derivation-tree provenance type
    (direct/derived/synthesized/unresolved), distinct from `evidence`'s
    source-citation provenance. Populating this requires a live SQLite
    agent-tree walk (`trace_claim`/`trace_claim_from_entity`) this
    pure-types slice does not perform -- honestly empty here, a real I/O
    call for a future compiler step."""
