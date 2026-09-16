from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.evidence import Claim
from backend.questions import Question
from backend.reasoning import ResearchTask

from .messages import ExpansionRequestMessage


class AgentStatus(str, Enum):
    """Where a single Ground Agent is in its lifecycle (AgenticArchitecture.md §23).
    Persisted as part of `AgentState` so a resumed process knows exactly which
    lifecycle step to re-enter (docs/Rules.md rule 7).
    """

    PENDING = "pending"
    """Created, not yet decided what to do with its question."""

    DECOMPOSING = "decomposing"
    """Decided to decompose; children exist (persisted) but not all complete yet."""

    COMPLETE = "complete"
    """Produced a final answer, either directly or by synthesizing its children."""

    BOUNDARY_HIT = "boundary_hit"
    """Escalation condition detected (AgenticArchitecture.md §10-11) — no Master to
    escalate to yet in Phase 3, so this is a terminal, typed result for now."""

    FAILED = "failed"


class GroundResult(BaseModel):
    """The typed result a Ground Agent produces (docs/Phases.md Phase 3: "produce a
    typed result"). `confidence` is still the model's own self-assessed confidence
    in its `answer` — that's a distinct thing from `claims`, each of which carries
    its own independently evidence-derived confidence (docs/Rules.md rule 4). A
    Ground Agent only populates `claims` when constructed with
    `gather_evidence=True` (docs/Phases.md Phase 5) — real external API calls are
    opt-in, not automatic on every answer, so Phase 3/4's existing behavior and
    free-tier API usage are unaffected by default.
    """

    status: AgentStatus
    answer: Optional[str] = None
    confidence: Optional[float] = None
    boundary_reason: Optional[str] = None
    child_results: list["GroundResult"] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)


class AgentState(BaseModel):
    """The full checkpointed record for one Ground Agent (AgenticArchitecture.md
    §21-22's `AgentState`, scoped to what Phase 3 needs: identity, parent, question,
    depth, status, children, result — evidence/uncertainty/dependencies arrive with
    the Evidence Engine and Master in later phases).
    """

    agent_id: str
    parent_id: Optional[str] = None
    question: Question
    depth: int
    max_depth: int
    status: AgentStatus = AgentStatus.PENDING
    children: list[str] = Field(default_factory=list)
    result: Optional[GroundResult] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MasterResult(BaseModel):
    """What `MasterAgent.run()` returns (docs/Phases.md Phase 4): how many
    top-level Ground Agents were requested vs. actually spawned (the hard spawn
    budget, Rules.md rule 10, enforced before any spawning happened), their
    results, and every boundary-escalation decision made along the way.
    """

    requested_count: int
    spawned_count: int
    dropped_count: int
    effective_budget: int
    ground_results: list[GroundResult]
    expansion_decisions: list[ExpansionRequestMessage] = Field(default_factory=list)


class TaskGraphResult(BaseModel):
    """What `MasterAgent.run_task_graph()` returns (R3.2, docs/Architecture.md
    §0.65) -- the first real consumer of `backend.reasoning.ResearchTask`
    from the orchestration layer. `tasks` is the full graph's final state
    (every `ResearchTask`, whatever status it ended in) -- a caller re-runs
    with this same list to resume (R3.2's idempotent-re-entry guarantee:
    already-'complete'/'failed'/'budget_exhausted' tasks are never
    re-selected for execution).
    """

    tasks: list[ResearchTask]
    executed_task_ids: list[str] = Field(default_factory=list)
    duplicate_task_ids: dict[str, str] = Field(default_factory=dict)
    """Maps a duplicate task's id -> the canonical task id it reused a result
    from, instead of being independently executed."""
    blocked_by_failed_dependency: list[str] = Field(default_factory=list)
    """Task ids that can never become runnable in this graph's current state
    because a dependency reached 'budget_exhausted' (permanently failed, no
    retries left) -- distinct from ordinary 'blocked' (still legitimately
    waiting on a dependency that may yet succeed)."""
    rounds_run: int
    stopped_reason: Literal["complete", "no_runnable_tasks", "budget_exhausted", "round_limit_reached"]
