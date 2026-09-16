from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from .domain import Claim, ClaimStatus, Evidence, RetrievalOutcome

# R2, first slice (docs/Phases.md's Reasoning Engine Evolution track,
# docs/Architecture.md §0.51/§0.52.1). Pure types only -- no bus wiring, no
# publish/subscribe mechanics, no durable log, no message broker. That's a
# deliberate, separate next sub-slice (mirroring R1.1 -> R1.2's own
# "types first, wire into live output second" precedent), not an omission.
#
# Scoped strictly to what R1 already produces -- RetrievalOutcome, Evidence,
# Claim, and transition_claim's one real operation. Deliberately does NOT
# define InvestigationCreated/TaskCreated/CoverageUpdated or any command
# beyond TransitionClaim below: those reference objects (Investigation,
# ResearchTask) that don't exist in the domain model yet (that's R3's job).
# Defining event types for objects nothing can yet produce would be exactly
# the "type-safety without semantic correctness" trap Architecture.md §0.56
# already named and rejected for claim migration -- the same discipline
# applies here.
#
# Distinct, separate vocabulary from backend.agents.messages.MessageType
# (Phase 4's GroundAgent/MasterAgent execution-internal escalation protocol)
# -- not an extension of it, not a replacement for it. Same "coexist, don't
# merge" precedent this project already established for
# backend.evidence.models.Claim vs. backend.reasoning.domain.Claim
# (Architecture.md §0.52.1).


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DomainEvent(BaseModel):
    """The shape every event in this module shares: a record that something
    has ALREADY become true -- immutable once emitted, never itself
    rejected (a Command may be; an Event, by definition, already happened).

    `correlation_id` groups events that belong to the same unit of work.
    Honestly scoped today: no `Investigation` object exists yet (R3), so
    there is no canonical value to require here -- a caller supplies
    whatever real grouping key it has (most naturally an `entity_id` or
    session id for now). Once R3 defines `Investigation`, its id becomes
    the natural value; this field's *meaning* doesn't change, only what's
    available to put in it.

    `causation_id` records what produced this event -- a command's id, or
    an earlier event's id -- so "why did this happen" stays answerable
    without needing a real event log yet (this module defines the shape;
    persisting/querying a stream of these is later R2 work).
    """

    event_id: str = Field(default_factory=_new_id)
    correlation_id: str = Field(min_length=1)
    causation_id: Optional[str] = None
    occurred_at: str = Field(default_factory=_now)


class RetrievalOutcomeRecorded(DomainEvent):
    """A RetrievalOutcome (R1.1) was produced -- regardless of whether it
    was successful, relevant, both, or neither. Recording this is not the
    same claim as "evidence was found"; see EvidenceCollected below for
    that narrower, real subset."""

    outcome: RetrievalOutcome


class EvidenceCollected(DomainEvent):
    """Real Evidence (R1.1) was produced by classify_retrieval_outcome --
    i.e. a RetrievalOutcome that was successful AND relevant. Never emitted
    for a failed or irrelevant outcome; RetrievalOutcomeRecorded above is
    the event for those."""

    evidence: Evidence


class ClaimCreated(DomainEvent):
    """A new Claim (R1.1) came into existence, in its initial `"candidate"`
    status. Not emitted for a claim reconstructed via reclassify_legacy_claim
    (Architecture.md §0.56's migration path) -- that's a distinct, honestly
    different kind of origin, not a fresh discovery."""

    claim: Claim


class ClaimTransitioned(DomainEvent):
    """A Claim (R1.4) moved from one status to another via transition_claim.
    Carries both the before/after status and the full reason/actor --
    exactly the fields transition_claim itself requires, so this event
    alone is enough to answer "why is this claim in this status" without
    needing to separately fetch the claim.
    """

    claim_id: str
    previous_status: ClaimStatus
    new_status: ClaimStatus
    reason: str
    actor: str


class TransitionClaimCommand(BaseModel):
    """The one command this slice defines -- matching the one real,
    already-implemented state-changing operation R1.4 exposes
    (transition_claim). A command is a REQUEST: unlike an event, it may be
    rejected (transition_claim already does exactly this via
    ClaimTransitionRejected) -- issuing this command is not itself a
    guarantee the transition happens.
    """

    command_id: str = Field(default_factory=_new_id)
    correlation_id: str = Field(min_length=1)
    causation_id: Optional[str] = None
    claim_id: str = Field(min_length=1)
    target_status: ClaimStatus
    reason: str
    actor: str
    superseded_by: Optional[str] = None
    duplicate_of: Optional[str] = None
    issued_at: str = Field(default_factory=_now)


def record_retrieval_outcome(outcome: RetrievalOutcome, *, correlation_id: str, causation_id: Optional[str] = None) -> RetrievalOutcomeRecorded:
    """Pure: wraps an already-produced RetrievalOutcome as an event. Does
    not call classify_retrieval_outcome or anything else -- the caller
    already has the outcome; this only names the fact of its existence."""
    return RetrievalOutcomeRecorded(correlation_id=correlation_id, causation_id=causation_id, outcome=outcome)


def record_evidence_collected(evidence: Evidence, *, correlation_id: str, causation_id: Optional[str] = None) -> EvidenceCollected:
    """Pure: wraps an already-produced Evidence as an event."""
    return EvidenceCollected(correlation_id=correlation_id, causation_id=causation_id, evidence=evidence)


def record_claim_created(claim: Claim, *, correlation_id: str, causation_id: Optional[str] = None) -> ClaimCreated:
    """Pure: wraps an already-created Claim as an event."""
    return ClaimCreated(correlation_id=correlation_id, causation_id=causation_id, claim=claim)


def record_claim_transitioned(
    *, claim_id: str, previous_status: ClaimStatus, new_status: ClaimStatus, reason: str, actor: str, correlation_id: str, causation_id: Optional[str] = None
) -> ClaimTransitioned:
    """Pure: wraps an already-completed transition as an event. Does not
    call transition_claim itself -- the caller already performed the
    transition; this only records that it happened."""
    return ClaimTransitioned(
        correlation_id=correlation_id,
        causation_id=causation_id,
        claim_id=claim_id,
        previous_status=previous_status,
        new_status=new_status,
        reason=reason,
        actor=actor,
    )
