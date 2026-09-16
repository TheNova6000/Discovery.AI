"""Discovery.AI core reasoning domain model (R1.1-R1.5 + R2's first slice +
R3's first slice, docs/Phases.md's Reasoning Engine Evolution track,
docs/Architecture.md §0.47-§0.63).

Pure domain types with validation invariants only -- no Neo4j, no LLM, no
event bus wiring, no orchestration. See domain.py's own module docstring for
the full scope statement and the dependency-direction principle this
package exists to establish at the bottom of the stack.

The core invariant (R1): RetrievalOutcome != Evidence != Claim != Answer. A
retrieval failure cannot become Evidence or a Claim just because it has
text and a confidence-shaped number -- classify_retrieval_outcome and
reclassify_legacy_claim are the only two functions that construct Evidence
or a migration-sourced Claim, and both enforce this structurally.

R2 (events.py), first slice: typed events/commands for what R1 already
produces (RetrievalOutcome/Evidence/Claim creation, and transition_claim's
one real operation) -- types only, no bus wiring yet (that's a later R2
sub-slice, mirroring R1.1 -> R1.2). A deliberately separate vocabulary from
backend.agents.messages.MessageType (Phase 4's GroundAgent/MasterAgent
execution-internal escalation protocol, still vertical-only per Rules.md
rule 9) -- coexisting, not merged, same as this project's existing
backend.evidence.models.Claim / backend.reasoning.domain.Claim precedent.

R3 (tasks.py), first slice: the ResearchTask domain type (Architecture.md
§0.53), plus pure scheduling (compute_runnable_tasks), duplicate-detection
(detect_duplicate_task), and lifecycle (transition_task) functions -- the
two gaps §0.54's MasterAgent evaluation marked "New."

R3.2 adds validate_task_graph (missing-dependency/cycle rejection) and
compute_tasks_blocked_by_failed_dependency, still pure, still zero
cross-package imports -- MasterAgent.run_task_graph (backend/agents/
master_agent.py) is the actual wiring, kept in the orchestration layer
where it belongs rather than imported back into this package.

R4.3 (Architecture.md §0.49/§0.69): the subclaim relation, implemented
directly on Claim (parent_claim_id + relation_to_parent) -- NOT a new
class, per §0.49's own design ("a subclaim is a Claim in a relation to
another Claim"). A tree, not a general graph: one parent per claim.
subclaim_relation/is_necessary_support read the relation;
validate_subclaim_graph rejects an unknown parent or a parent-chain cycle;
find_claims_with_invalid_parent reports (never mutates) claims whose
parent is missing or discredited -- no automatic status/confidence
inheritance from a parent to its subclaims, ever.
"""

from .domain import (
    Answer,
    Claim,
    ClaimStatus,
    ClaimTransitionRejected,
    Evidence,
    IdentityFloor,
    ParentRelation,
    RetrievalOutcome,
    SemanticIdentity,
    SubclaimGraphError,
    SubclaimRelation,
    classify_retrieval_outcome,
    find_claims_with_invalid_parent,
    identity_floor,
    is_likely_duplicate,
    is_necessary_support,
    reclassify_legacy_claim,
    semantic_identity,
    subclaim_relation,
    transition_claim,
    validate_subclaim_graph,
)
from .events import (
    ClaimCreated,
    ClaimTransitioned,
    DomainEvent,
    EvidenceCollected,
    RetrievalOutcomeRecorded,
    TransitionClaimCommand,
    record_claim_created,
    record_claim_transitioned,
    record_evidence_collected,
    record_retrieval_outcome,
)
from .tasks import (
    ResearchTask,
    TaskGraphValidationError,
    TaskStatus,
    TaskTransitionRejected,
    compute_runnable_tasks,
    compute_tasks_blocked_by_failed_dependency,
    detect_duplicate_task,
    initial_status,
    transition_task,
    validate_task_graph,
)

__all__ = [
    "RetrievalOutcome",
    "Evidence",
    "Claim",
    "ClaimStatus",
    "Answer",
    "classify_retrieval_outcome",
    "reclassify_legacy_claim",
    "identity_floor",
    "semantic_identity",
    "is_likely_duplicate",
    "IdentityFloor",
    "SemanticIdentity",
    "transition_claim",
    "ClaimTransitionRejected",
    "DomainEvent",
    "RetrievalOutcomeRecorded",
    "EvidenceCollected",
    "ClaimCreated",
    "ClaimTransitioned",
    "TransitionClaimCommand",
    "record_retrieval_outcome",
    "record_evidence_collected",
    "record_claim_created",
    "record_claim_transitioned",
    "ResearchTask",
    "TaskStatus",
    "TaskTransitionRejected",
    "TaskGraphValidationError",
    "initial_status",
    "compute_runnable_tasks",
    "compute_tasks_blocked_by_failed_dependency",
    "detect_duplicate_task",
    "transition_task",
    "validate_task_graph",
    "SubclaimRelation",
    "ParentRelation",
    "subclaim_relation",
    "is_necessary_support",
    "SubclaimGraphError",
    "validate_subclaim_graph",
    "find_claims_with_invalid_parent",
]
