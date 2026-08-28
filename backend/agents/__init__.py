"""Agent runtime: recursive `GroundAgent` (Phase 3) wrapped by `MasterAgent` (Phase
4) with a vertical-only typed message bus and a hard spawn budget. See
docs/Architecture.md and Rules.md rule 8 for why there is no fixed
Master/Domain/Subdomain/Ground class hierarchy.
"""

from .bus import MessageBus
from .exceptions import AgentError
from .ground_agent import DEFAULT_MAX_DEPTH, GroundAgent
from .master_agent import (
    DEFAULT_BROAD_SPAWN_BUDGET,
    DEFAULT_MAX_EXPANSIONS,
    DEFAULT_SPAWN_BUDGET,
    MasterAgent,
)
from .messages import (
    BoundaryHitMessage,
    ExpansionDecision,
    ExpansionRequestMessage,
    MessageType,
)
from .models import AgentState, AgentStatus, GroundResult, MasterResult
from .provenance import ClaimProvenance, ProvenanceType, find_root_agent_id, trace_claim

__all__ = [
    "ClaimProvenance",
    "ProvenanceType",
    "trace_claim",
    "find_root_agent_id",
    "GroundAgent",
    "DEFAULT_MAX_DEPTH",
    "MasterAgent",
    "DEFAULT_SPAWN_BUDGET",
    "DEFAULT_BROAD_SPAWN_BUDGET",
    "DEFAULT_MAX_EXPANSIONS",
    "MessageBus",
    "MessageType",
    "BoundaryHitMessage",
    "ExpansionRequestMessage",
    "ExpansionDecision",
    "AgentState",
    "AgentStatus",
    "GroundResult",
    "MasterResult",
    "AgentError",
]
