"""Course lifecycle state machine (docs/Rules.md rule 12, Architecture.md).

The transition table is the only place that decides whether a lifecycle move is
legal.  Routes and the orchestrator call `transition()` instead of assigning
`course.state` directly, so an invalid move is rejected rather than silently
persisted.
"""

from __future__ import annotations

from .models import CourseState


class InvalidTransition(Exception):
    """Raised when a caller attempts a lifecycle move the table does not allow."""


# A hard approval gate means APPROVED is reachable only from AWAITING_APPROVAL.
# Module publication is reachable only after approval, which is why
# GENERATING_MODULES has exactly one inbound edge.
TRANSITIONS: dict[CourseState, frozenset[CourseState]] = {
    CourseState.DISCOVERY: frozenset(
        {CourseState.BRIEF_READY, CourseState.PAUSED, CourseState.FAILED}
    ),
    CourseState.BRIEF_READY: frozenset(
        {CourseState.DISCOVERY, CourseState.RESEARCH_PLANNING, CourseState.PAUSED, CourseState.FAILED}
    ),
    CourseState.RESEARCH_PLANNING: frozenset(
        {CourseState.RESEARCH_RUNNING, CourseState.BRIEF_READY, CourseState.FAILED}
    ),
    CourseState.RESEARCH_RUNNING: frozenset(
        {CourseState.RESEARCH_REVIEW, CourseState.FAILED, CourseState.PAUSED}
    ),
    CourseState.RESEARCH_REVIEW: frozenset(
        {
            CourseState.CURRICULUM_DRAFT,
            CourseState.RESEARCH_RUNNING,
            CourseState.RESEARCH_PLANNING,
            CourseState.FAILED,
        }
    ),
    CourseState.CURRICULUM_DRAFT: frozenset(
        {CourseState.AWAITING_APPROVAL, CourseState.RESEARCH_REVIEW, CourseState.FAILED}
    ),
    CourseState.AWAITING_APPROVAL: frozenset(
        {
            CourseState.APPROVED,
            CourseState.CURRICULUM_DRAFT,
            CourseState.RESEARCH_RUNNING,
            CourseState.DISCOVERY,
            CourseState.PAUSED,
            CourseState.FAILED,
        }
    ),
    CourseState.APPROVED: frozenset(
        {CourseState.GENERATING_MODULES, CourseState.AWAITING_APPROVAL, CourseState.FAILED}
    ),
    CourseState.GENERATING_MODULES: frozenset(
        {CourseState.READY_TO_LEARN, CourseState.FAILED, CourseState.PAUSED}
    ),
    CourseState.READY_TO_LEARN: frozenset(
        {
            CourseState.MODULE_IN_PROGRESS,
            CourseState.ADAPTATION_PENDING,
            CourseState.COMPLETED,
            CourseState.PAUSED,
            CourseState.FAILED,
        }
    ),
    CourseState.MODULE_IN_PROGRESS: frozenset(
        {
            CourseState.ASSESSMENT_PENDING,
            CourseState.READY_TO_LEARN,
            CourseState.PAUSED,
            CourseState.FAILED,
        }
    ),
    CourseState.ASSESSMENT_PENDING: frozenset(
        {
            CourseState.FEEDBACK_PENDING,
            CourseState.MODULE_IN_PROGRESS,
            CourseState.PAUSED,
            CourseState.FAILED,
        }
    ),
    CourseState.FEEDBACK_PENDING: frozenset(
        {CourseState.ADAPTATION_PENDING, CourseState.PAUSED, CourseState.FAILED}
    ),
    CourseState.ADAPTATION_PENDING: frozenset(
        {
            CourseState.BUFFER_READY,
            CourseState.READY_TO_LEARN,
            CourseState.AWAITING_APPROVAL,
            CourseState.COMPLETED,
            CourseState.FAILED,
        }
    ),
    CourseState.BUFFER_READY: frozenset(
        {
            CourseState.MODULE_IN_PROGRESS,
            CourseState.READY_TO_LEARN,
            CourseState.ADAPTATION_PENDING,
            CourseState.COMPLETED,
            CourseState.PAUSED,
            CourseState.FAILED,
        }
    ),
    CourseState.COMPLETED: frozenset(
        {CourseState.READY_TO_LEARN, CourseState.ADAPTATION_PENDING, CourseState.PAUSED}
    ),
    CourseState.PAUSED: frozenset(
        {
            CourseState.DISCOVERY,
            CourseState.BRIEF_READY,
            CourseState.RESEARCH_RUNNING,
            CourseState.RESEARCH_REVIEW,
            CourseState.CURRICULUM_DRAFT,
            CourseState.AWAITING_APPROVAL,
            CourseState.GENERATING_MODULES,
            CourseState.READY_TO_LEARN,
            CourseState.MODULE_IN_PROGRESS,
            CourseState.ASSESSMENT_PENDING,
            CourseState.FEEDBACK_PENDING,
            CourseState.ADAPTATION_PENDING,
            CourseState.BUFFER_READY,
        }
    ),
    # FAILED is recoverable: the orchestrator can retry the stage that failed.
    # It is never a terminal dead end that loses an approved plan.
    CourseState.FAILED: frozenset(
        {
            CourseState.DISCOVERY,
            CourseState.BRIEF_READY,
            CourseState.RESEARCH_PLANNING,
            CourseState.RESEARCH_RUNNING,
            CourseState.CURRICULUM_DRAFT,
            CourseState.AWAITING_APPROVAL,
            CourseState.GENERATING_MODULES,
            CourseState.READY_TO_LEARN,
            CourseState.ADAPTATION_PENDING,
            CourseState.PAUSED,
        }
    ),
}


def can_transition(current: CourseState, target: CourseState) -> bool:
    return target in TRANSITIONS[current]


def validate_transition(current: CourseState, target: CourseState) -> CourseState:
    if not can_transition(current, target):
        raise InvalidTransition(f"illegal course transition: {current.value} -> {target.value}")
    return target
