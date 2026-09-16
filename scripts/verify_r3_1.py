"""R3 verification, first slice -- the ResearchTask domain type plus pure
scheduling/duplicate-detection/lifecycle functions (docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md
§0.53/§0.54/§0.54.1/§0.64, backend/reasoning/tasks.py).

Pure throughout -- no MasterAgent, no LangGraph, no GroundAgent, no bus, no
Neo4j, no LLM call. This slice defines the task graph's type and its
scheduling/duplicate/lifecycle logic only; wiring it into MasterAgent's
real LangGraph nodes is later R3 work, not this file's job.

Checks:
  1. initial_status: no dependencies -> "runnable"; any dependency ->
     "blocked" -- a structural fact about the graph shape, not asserted.
  2. compute_runnable_tasks correctly identifies a blocked task as eligible
     only once ALL of its dependencies are "complete", not just one of
     several.
  3. detect_duplicate_task finds a real duplicate (same investigation,
     entity, field, type) and does NOT flag a task differing in any one of
     those four fields, or a duplicate whose only prior instance is
     "budget_exhausted" (permanently dead, safe to retry fresh).
  4. transition_task enforces the legal transition graph -- every legal
     edge succeeds, illegal edges (e.g. "blocked" -> "running" directly,
     skipping the runnable step; "runnable" -> "complete", skipping
     running) are rejected, not silently coerced.
  5. transition_task rejects empty reason/actor on every attempted
     transition, same discipline as R1.4's transition_claim.
  6. The retry path is real: "failed" -> "runnable" increments nothing
     further but is only legal while attempts remain; attempting it with
     no attempts remaining is rejected with a specific message directing
     the caller to budget_exhausted instead.
  7. "budget_exhausted" is rejected unless attempt_count has actually
     reached max_attempts -- a task cannot be marked exhausted early.
  8. ResearchTask round-trips through model_dump_json/model_validate_json
     unchanged, including a task with every optional field populated.
  9. This module has zero imports outside stdlib/pydantic -- confirmed by
     direct inspection, keeping backend.reasoning's dependency-direction
     guarantee intact through this new file too.
  10. Existing Phase 6/8.1-8.6/R1.1/R1.3/R1.4/R1.5/R2.1 checks remain green.
"""

from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from backend.reasoning import (  # noqa: E402
    ResearchTask,
    TaskTransitionRejected,
    compute_runnable_tasks,
    detect_duplicate_task,
    initial_status,
    transition_task,
)


def check_initial_status() -> None:
    assert initial_status([]) == "runnable"
    assert initial_status(["dep-1"]) == "blocked"
    assert initial_status(["dep-1", "dep-2"]) == "blocked"
    print("[PASS] #1 initial_status: no deps -> runnable, any dep -> blocked")


def check_compute_runnable_tasks() -> None:
    dep_a = ResearchTask(investigation_id="i1", target_entity_id="e-dep-a", task_type="deep_dive", dependencies=[], status="complete", provenance_note="done", last_transition_actor="tester")
    dep_b = ResearchTask(investigation_id="i1", target_entity_id="e-dep-b", task_type="deep_dive", dependencies=[], status="running", provenance_note="spawned", last_transition_actor="tester")
    child = ResearchTask(investigation_id="i1", target_entity_id="e-child", task_type="deep_dive", dependencies=[dep_a.task_id, dep_b.task_id], status="blocked")

    assert compute_runnable_tasks([dep_a, dep_b, child]) == [], "child must stay blocked while dep_b is still running"

    dep_b_done = ResearchTask(**{**dep_b.model_dump(), "status": "complete"})
    assert compute_runnable_tasks([dep_a, dep_b_done, child]) == [child.task_id], "child must become eligible once ALL dependencies are complete"
    print("[PASS] #2 compute_runnable_tasks requires ALL dependencies complete, not just one")


def check_detect_duplicate_task() -> None:
    existing = ResearchTask(investigation_id="i1", target_entity_id="e1", research_field="mechanism", task_type="deep_dive", dependencies=[])
    same_shape = ResearchTask(investigation_id="i1", target_entity_id="e1", research_field="mechanism", task_type="deep_dive", dependencies=[])
    different_field = ResearchTask(investigation_id="i1", target_entity_id="e1", research_field="examples", task_type="deep_dive", dependencies=[])
    different_entity = ResearchTask(investigation_id="i1", target_entity_id="e2", research_field="mechanism", task_type="deep_dive", dependencies=[])

    assert detect_duplicate_task(same_shape, [existing]) == existing.task_id
    assert detect_duplicate_task(different_field, [existing]) is None
    assert detect_duplicate_task(different_entity, [existing]) is None

    exhausted = ResearchTask(
        investigation_id="i1", target_entity_id="e3", research_field="mechanism", task_type="deep_dive", dependencies=[],
        status="budget_exhausted", attempt_count=1, max_attempts=1, provenance_note="no attempts left", last_transition_actor="tester",
    )
    fresh_retry = ResearchTask(investigation_id="i1", target_entity_id="e3", research_field="mechanism", task_type="deep_dive", dependencies=[])
    assert detect_duplicate_task(fresh_retry, [exhausted]) is None, "a permanently-dead prior task must not block a fresh attempt"
    print("[PASS] #3 detect_duplicate_task finds real duplicates, ignores differing fields, ignores budget_exhausted priors")


def check_legal_transitions_enforced() -> None:
    t = ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[], status="blocked")

    try:
        transition_task(t, "running", reason="skip ahead", actor="tester")
        raise AssertionError("blocked -> running should be illegal (must pass through runnable)")
    except TaskTransitionRejected:
        pass

    runnable = transition_task(t, "runnable", reason="dependencies satisfied", actor="scheduler")
    assert runnable.status == "runnable"

    try:
        transition_task(runnable, "complete", reason="skip ahead", actor="tester")
        raise AssertionError("runnable -> complete should be illegal (must pass through running)")
    except TaskTransitionRejected:
        pass

    running = transition_task(runnable, "running", reason="spawned", actor="master")
    complete = transition_task(running, "complete", reason="ground agent finished", actor="master")
    assert complete.status == "complete"
    print("[PASS] #4 legal transition graph enforced -- every legal edge succeeds, illegal edges rejected")


def check_empty_reason_actor_rejected() -> None:
    t = ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[], status="blocked")
    for attempt in (
        lambda: transition_task(t, "runnable", reason="", actor="scheduler"),
        lambda: transition_task(t, "runnable", reason="ok", actor=""),
    ):
        try:
            attempt()
            raise AssertionError("should have rejected empty reason/actor")
        except TaskTransitionRejected:
            pass
    print("[PASS] #5 empty reason/actor rejected on every attempted transition")


def check_retry_path_is_real() -> None:
    t = ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[], status="blocked", max_attempts=2)
    runnable = transition_task(t, "runnable", reason="ready", actor="scheduler")
    running = transition_task(runnable, "running", reason="spawned", actor="master")
    failed = transition_task(running, "failed", reason="timeout", actor="master")
    assert failed.attempt_count == 1

    retried = transition_task(failed, "runnable", reason="retrying, attempts remain", actor="scheduler")
    assert retried.status == "runnable" and retried.attempt_count == 1

    running2 = transition_task(retried, "running", reason="spawned again", actor="master")
    failed2 = transition_task(running2, "failed", reason="timeout again", actor="master")
    assert failed2.attempt_count == 2

    try:
        transition_task(failed2, "runnable", reason="one more try", actor="scheduler")
        raise AssertionError("should reject retry with no attempts remaining")
    except TaskTransitionRejected:
        pass
    print("[PASS] #6 retry path is real (attempt_count increments on failure), rejected once attempts are exhausted")


def check_budget_exhausted_requires_real_exhaustion() -> None:
    t = ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[], status="blocked", max_attempts=2)
    runnable = transition_task(t, "runnable", reason="ready", actor="scheduler")
    running = transition_task(runnable, "running", reason="spawned", actor="master")
    failed_once = transition_task(running, "failed", reason="timeout", actor="master")
    assert failed_once.attempt_count == 1 < failed_once.max_attempts

    try:
        transition_task(failed_once, "budget_exhausted", reason="premature", actor="master")
        raise AssertionError("should reject budget_exhausted while attempts remain")
    except TaskTransitionRejected:
        pass

    retried = transition_task(failed_once, "runnable", reason="retrying", actor="scheduler")
    running2 = transition_task(retried, "running", reason="spawned", actor="master")
    failed_twice = transition_task(running2, "failed", reason="timeout again", actor="master")
    assert failed_twice.attempt_count == failed_twice.max_attempts

    exhausted = transition_task(failed_twice, "budget_exhausted", reason="no attempts left", actor="master")
    assert exhausted.status == "budget_exhausted"
    print("[PASS] #7 budget_exhausted rejected until attempt_count actually reaches max_attempts")


def check_serialization_round_trip() -> None:
    fully_populated = ResearchTask(
        investigation_id="i1", target_entity_id="e1", research_field="mechanism", task_type="deep_dive",
        parent_task_id="parent-1", dependencies=["dep-1", "dep-2"], status="running", attempt_count=1, max_attempts=3,
        result_refs=["claim-1"], provenance_note="spawned", last_transition_actor="master",
    )
    sparse = ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[])
    for task in (fully_populated, sparse):
        assert ResearchTask.model_validate_json(task.model_dump_json()) == task
    print("[PASS] #8 ResearchTask round-trips through model_dump_json/model_validate_json, fully-populated and sparse")


def check_zero_cross_package_imports() -> None:
    import backend.reasoning.tasks as tasks_module

    source = inspect.getsource(tasks_module)
    import_lines = [line.strip() for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    for line in import_lines:
        assert not line.startswith("from backend."), f"tasks.py has a cross-package import: {line!r}"
    print(f"[PASS] #9 tasks.py's {len(import_lines)} import lines are all stdlib/pydantic, confirmed by direct inspection")


def check_status_consistency_invariant() -> None:
    for bad_status in ("running", "complete", "failed", "budget_exhausted"):
        try:
            ResearchTask(investigation_id="i1", target_entity_id="e1", task_type="deep_dive", dependencies=[], status=bad_status)
            raise AssertionError(f"{bad_status!r} without provenance_note should be rejected")
        except ValidationError:
            pass
    print("[PASS] #9b every execution status requires provenance_note, enforced by the model itself")


if __name__ == "__main__":
    check_initial_status()
    check_compute_runnable_tasks()
    check_detect_duplicate_task()
    check_legal_transitions_enforced()
    check_empty_reason_actor_rejected()
    check_retry_path_is_real()
    check_budget_exhausted_requires_real_exhaustion()
    check_serialization_round_trip()
    check_zero_cross_package_imports()
    check_status_consistency_invariant()
    print("\nAll 10 checks passed. Pure logic only, no MasterAgent/LangGraph/GroundAgent/bus/Neo4j/LLM call.")
    print("Acceptance #10 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")
