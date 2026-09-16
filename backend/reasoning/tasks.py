from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# R3, first slice (docs/Phases.md's Reasoning Engine Evolution track,
# docs/Architecture.md §0.53/§0.54/§0.54.1). Pure domain type + pure
# scheduling/duplicate-detection functions only -- no MasterAgent wiring, no
# LangGraph node, no bus, no GroundAgent call. That wiring is a later,
# separate R3 sub-slice, mirroring R1.1 -> R1.2's own "types first, wire
# into live output second" precedent, not an omission.
#
# Directly targets the two gaps §0.54's evaluation table marked "New" (no
# existing code to reuse for either): runnable/blocked states, and
# duplicate-work prevention -- the real, quantified problem Phase 6/8.6
# already found (duplicate Questions/Claims from independently-spawned,
# unaware-of-each-other GroundAgent recursion).

TaskStatus = Literal["blocked", "runnable", "running", "complete", "failed", "budget_exhausted"]

# Two families, deliberately not treated alike:
#   - "blocked"/"runnable" are structurally DERIVED from the dependency
#     graph (compute_runnable_tasks below) -- nothing asserts them, they
#     fall out of which tasks have completed.
#   - "running"/"complete"/"failed"/"budget_exhausted" are EXECUTION
#     outcomes, asserted by an actor via transition_task, same
#     reason/actor discipline as Claim's transition_claim (R1.4) -- a
#     task's fate is a stated fact, not inferred from a side effect.
_LEGAL_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    "blocked": frozenset({"runnable"}),
    "runnable": frozenset({"running"}),
    "running": frozenset({"complete", "failed"}),
    "failed": frozenset({"runnable", "budget_exhausted"}),
    "complete": frozenset(),
    "budget_exhausted": frozenset(),
}

_EXECUTION_STATUSES = frozenset({"running", "complete", "failed", "budget_exhausted"})


def _new_id() -> str:
    return str(uuid.uuid4())


class TaskTransitionRejected(Exception):
    """Raised by transition_task for any illegal, unreasoned, or
    budget-inconsistent transition attempt -- never silently coerced into
    the nearest legal status."""


class ResearchTask(BaseModel):
    """A single unit of research work in the explicit task graph
    (Architecture.md §0.53). `GroundAgent` remains the worker that executes
    it (§0.53: "this is not a GroundAgent rewrite") -- this type only makes
    the previously-invisible recursion inspectable and schedulable.
    """

    task_id: str = Field(default_factory=_new_id)
    investigation_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    research_field: Optional[str] = None
    task_type: str = Field(min_length=1)
    parent_task_id: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    status: TaskStatus = "blocked"
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)
    result_refs: list[str] = Field(default_factory=list)
    provenance_note: Optional[str] = None
    last_transition_actor: Optional[str] = None

    @model_validator(mode="after")
    def _status_consistency(self) -> "ResearchTask":
        if self.status in _EXECUTION_STATUSES and not self.provenance_note:
            raise ValueError(f"a {self.status!r} task must record provenance_note explaining why (mirrors R1.4's Claim discipline)")
        if self.status == "budget_exhausted" and self.attempt_count < self.max_attempts:
            raise ValueError("a task cannot be budget_exhausted while attempts remain")
        return self


def initial_status(dependencies: list[str]) -> TaskStatus:
    """A fresh task starts 'blocked' if it names any dependency, 'runnable'
    otherwise -- this is a structural fact about the graph shape, decided
    once at construction, not re-derived here on every scheduling pass."""
    return "blocked" if dependencies else "runnable"


def compute_runnable_tasks(tasks: list[ResearchTask]) -> list[str]:
    """Pure: returns the task_ids of every currently-'blocked' task whose
    dependencies are ALL 'complete'. Read-only -- it names which tasks are
    now ELIGIBLE for the blocked->runnable transition; actually making that
    transition is a separate, deliberate transition_task call, the same
    "compute eligibility, then commit" split MasterAgent's own
    enforce_spawn_budget node already uses for its budget decision."""
    complete_ids = {t.task_id for t in tasks if t.status == "complete"}
    return [t.task_id for t in tasks if t.status == "blocked" and all(dep in complete_ids for dep in t.dependencies)]


def detect_duplicate_task(candidate: ResearchTask, existing_tasks: list[ResearchTask]) -> Optional[str]:
    """Pure: returns the task_id of an existing, not-permanently-failed task
    that would investigate the same (investigation, entity, field, type) as
    `candidate`, or None. This is the "check before spawning" logic
    §0.53/§0.54 both call out as the concrete fix for Phase 6/8.6's real,
    observed duplicate-Question/duplicate-Claim problem -- structural
    identity comparison, the same pattern as R1.3's identity_floor, applied
    to tasks instead of claims."""
    identity = (candidate.investigation_id, candidate.target_entity_id, candidate.research_field, candidate.task_type)
    for existing in existing_tasks:
        if existing.task_id == candidate.task_id:
            continue
        if existing.status == "budget_exhausted":
            continue
        if (existing.investigation_id, existing.target_entity_id, existing.research_field, existing.task_type) == identity:
            return existing.task_id
    return None


def transition_task(task: ResearchTask, target_status: TaskStatus, *, reason: str, actor: str) -> ResearchTask:
    """Pure: the one function that moves a task between execution states.
    Mirrors transition_claim's (R1.4) discipline exactly: reason and actor
    are always required, the legal-transition graph is enforced, and the
    result is reconstructed through ResearchTask(...) rather than
    model_copy(update=...) so the model's own validator -- not just this
    function's hand-written checks -- is the actual source of truth."""
    if not reason.strip():
        raise TaskTransitionRejected("a task transition must record a non-empty reason")
    if not actor.strip():
        raise TaskTransitionRejected("a task transition must record a non-empty actor")

    legal_targets = _LEGAL_TASK_TRANSITIONS.get(task.status, frozenset())
    if target_status not in legal_targets:
        raise TaskTransitionRejected(f"{task.status!r} -> {target_status!r} is not a legal task transition")

    updates: dict = {"status": target_status, "provenance_note": reason, "last_transition_actor": actor}
    if target_status == "failed":
        updates["attempt_count"] = task.attempt_count + 1
    if target_status == "runnable" and task.status == "failed" and task.attempt_count >= task.max_attempts:
        raise TaskTransitionRejected("cannot retry a task with no attempts remaining -- transition to budget_exhausted instead")
    if target_status == "budget_exhausted" and task.attempt_count < task.max_attempts:
        raise TaskTransitionRejected("cannot mark budget_exhausted while attempts remain")

    return ResearchTask(**{**task.model_dump(), **updates})
