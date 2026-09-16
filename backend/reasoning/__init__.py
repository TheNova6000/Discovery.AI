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
two gaps §0.54's MasterAgent evaluation marked "New." No MasterAgent/
LangGraph/GroundAgent/bus wiring yet -- that's a later R3 sub-slice,
mirroring R1.1 -> R1.2's own "types first, wire second" precedent.
"""

from .domain import (
    Answer,
    Claim,
    ClaimStatus,
    ClaimTransitionRejected,
    Evidence,
    IdentityFloor,
    RetrievalOutcome,
    SemanticIdentity,
    classify_retrieval_outcome,
    identity_floor,
    is_likely_duplicate,
    reclassify_legacy_claim,
    semantic_identity,
    transition_claim,
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
    TaskStatus,
    TaskTransitionRejected,
    compute_runnable_tasks,
    detect_duplicate_task,
    initial_status,
    transition_task,
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
    "initial_status",
    "compute_runnable_tasks",
    "detect_duplicate_task",
    "transition_task",
]
