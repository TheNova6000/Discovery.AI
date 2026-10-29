from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """The full agent message taxonomy (AgenticArchitecture.md §19-21, Rules.md's
    approved-libraries table). Vertical-only (Rules.md rule 9) — no lateral/peer
    message type exists here, by design, not by omission.

    Only `BOUNDARY_HIT` and `EXPANSION_REQUEST` have a concrete Pydantic payload
    class below (`BoundaryHitMessage`/`ExpansionRequestMessage`) — those are the
    only two this phase's Master+Ground tier actually produces or consumes. The
    rest of the taxonomy is declared here as the protocol surface later phases
    (Evidence Engine, abstraction-change protocol) will give dedicated classes to
    when something actually emits them.
    """

    TASK = "task"
    QUESTION = "question"
    DISCOVERY = "discovery"
    EVIDENCE = "evidence"
    HYPOTHESIS = "hypothesis"
    DEPENDENCY = "dependency"
    BOUNDARY_HIT = "boundary_hit"
    EXPANSION_REQUEST = "expansion_request"
    NEW_ENTITY = "new_entity"
    NEW_DOMAIN = "new_domain"
    CONFLICT = "conflict"
    ABSTRACTION_CHANGE = "abstraction_change"
    COMPLETION = "completion"
    FAILURE = "failure"


class ExpansionDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


def _message_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BoundaryHitMessage(BaseModel):
    """Emitted by a Ground Agent when it hits the boundary condition described in
    AgenticArchitecture.md §10-11 ("needs information outside its current
    abstraction" / "abstraction too deep for current objective"). `parent_chain`
    records the ancestor path (root-first) it travelled up through — this is
    provenance, not a routing address: the Master is the only actual consumer of
    this bus (Rules.md rule 9 — no lateral messaging), the chain just records how
    the escalation got there.
    """

    id: str = Field(default_factory=_message_id)
    type: MessageType = MessageType.BOUNDARY_HIT
    sender_id: str
    parent_chain: list[str] = Field(default_factory=list)
    question_text: str
    reason: str
    created_at: str = Field(default_factory=_now)


class ExpansionRequestMessage(BaseModel):
    """The Master's own record of a `BoundaryHitMessage` converted into a decision
    (AgenticArchitecture.md §34's `BOUNDARY_HIT -> ... -> EXPANSION_REQUEST ->
    MASTER DECISION` protocol). Phase 4 only makes and logs this decision — acting
    on an ACCEPT (spawning a new branch, actually changing the abstraction) is
    Phase 7's job (Rules.md's abstraction-change protocol), not this phase's.
    """

    id: str = Field(default_factory=_message_id)
    type: MessageType = MessageType.EXPANSION_REQUEST
    boundary_hit_id: str
    sender_chain: list[str]
    reason: str
    decision: ExpansionDecision
    created_at: str = Field(default_factory=_now)
