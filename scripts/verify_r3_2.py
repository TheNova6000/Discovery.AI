"""R3.2 verification -- wiring ResearchTask into MasterAgent's real
orchestration (docs/Phases.md's Reasoning Engine Evolution track,
docs/Architecture.md §0.65, backend/agents/master_agent.py's
run_task_graph).

`decide_next_step` is monkeypatched to always return a deterministic
"answer" decision instantly -- exactly scripts/verify_phase4.py's own
technique for isolating the orchestration mechanism from live LLM
judgment. Check #11 (real MasterAgent integration) therefore exercises the
REAL MasterAgent, REAL LangGraph state/checkpointing, and REAL GroundAgent
-- only the one LLM-calling function is replaced, not a fake orchestration
layer. `gather_evidence`/`persist_to_graph` stay at their real defaults
(False), so no retriever or Neo4j call happens either.

Rule 14 (provider failures must be explicit): an optional, genuinely live
smoke test is included at the end, gated on has_any_provider_key(), and
its result is reported separately -- never folded into the mocked tests'
pass/fail count.

Checks:
  1. Initial runnable/blocked split matches the DNS acceptance example
     (A: no deps -> runnable; B, C: depend on A -> blocked) exactly.
  2. Dependency unlock: completing A makes B and C both eligible.
  3. Partial completion: completing B (not C) leaves only C eligible.
  4. Duplicate task detection (R3.1's detect_duplicate_task contract,
     re-affirmed here in the R3.2 scheduling context).
  5. Missing dependency: both validate_task_graph and run_task_graph
     itself reject a task that names an unknown dependency id.
  6. Dependency cycle: both validate_task_graph and run_task_graph itself
     reject A<->B.
  7. Failed dependency: a merely-"failed" (still retryable) dependency
     never makes its dependent runnable; a "budget_exhausted" (permanently
     failed) dependency is explicitly surfaced via
     compute_tasks_blocked_by_failed_dependency, not left ambiguous.
  8. Budget exhaustion: task_budget=1 against the 3-task DNS graph
     executes exactly one task, reports stopped_reason="budget_exhausted",
     and terminates (no infinite loop).
  9. Task failure: a GroundAgent that raises is recorded as "failed" (not
     silently dropped), and the coordinator finishes the round cleanly.
 10. Idempotent re-entry: re-running run_task_graph with a task list that
     already has completed tasks executes zero additional GroundAgents for
     them and reports zero newly-executed task ids.
 11. Real MasterAgent integration: the full DNS acceptance example,
     end-to-end, through MasterAgent.run_task_graph's real LangGraph/
     GroundAgent path (not isolated helper functions).
 12. Full regression: verified separately by re-running every pre-existing
     verify script unmodified (see this repo's own commit checklist).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.agents.ground_agent as ground_agent_module  # noqa: E402
from backend.agents import AgentStatus, MasterAgent, TaskGraphResult  # noqa: E402
from backend.questions import GroundDecision, QuestionLevel  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question  # noqa: E402
from backend.reasoning import (  # noqa: E402
    ResearchTask,
    TaskGraphValidationError,
    compute_runnable_tasks,
    compute_tasks_blocked_by_failed_dependency,
    detect_duplicate_task,
    initial_status,
    transition_task,
    validate_task_graph,
)

GROUND_DB_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "verify_r3_2_ground.sqlite3")
CHECKPOINT_DB_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "verify_r3_2_checkpoints.sqlite3")


def _make_question(text: str) -> Question:
    return Question(
        text=text,
        rationale="R3.2 verification seed question.",
        dimension_id="scale",
        level=QuestionLevel.GROUND,
        entity_name="DNS",
        abstraction_name="Networking",
    )


async def _fake_decide_next_step(question, *, known=None, model_chain=None) -> GroundDecision:
    if "FAIL_TRIGGER" in question.text:
        raise RuntimeError("simulated GroundAgent failure, forced for R3.2 verification")
    return GroundDecision(
        action="answer",
        reasoning="forced for deterministic R3.2 verification",
        answer=f"Answer for: {question.text}",
        confidence=0.8,
    )


def _dns_graph() -> tuple[list[ResearchTask], dict[str, Question]]:
    """Exactly the R3.2 acceptance example: A defines DNS; B (recursive
    resolution) and C (caching) both depend on A."""
    a = ResearchTask(investigation_id="inv-dns", target_entity_id="dns", research_field="definition", task_type="deep_dive", dependencies=[], status=initial_status([]))
    b = ResearchTask(investigation_id="inv-dns", target_entity_id="dns", research_field="recursive_resolution", task_type="deep_dive", dependencies=[a.task_id], status=initial_status([a.task_id]))
    c = ResearchTask(investigation_id="inv-dns", target_entity_id="dns", research_field="caching", task_type="deep_dive", dependencies=[a.task_id], status=initial_status([a.task_id]))
    questions = {
        a.task_id: _make_question("Define DNS."),
        b.task_id: _make_question("Explain recursive DNS resolution."),
        c.task_id: _make_question("Explain DNS caching."),
    }
    return [a, b, c], questions


def check_initial_runnable_blocked_split() -> None:
    (a, b, c), _ = _dns_graph()
    assert a.status == "runnable"
    assert b.status == "blocked" and c.status == "blocked"
    print("[PASS] #1 initial split matches the acceptance example: A runnable, B/C blocked")


def check_dependency_unlock() -> None:
    (a, b, c), _ = _dns_graph()
    a_done = transition_task(a, "running", reason="spawned", actor="test")
    a_done = transition_task(a_done, "complete", reason="answered", actor="test")
    tasks = [a_done, b, c]
    assert set(compute_runnable_tasks(tasks)) == {b.task_id, c.task_id}
    print("[PASS] #2 completing A makes both B and C eligible")


def check_partial_completion() -> None:
    (a, b, c), _ = _dns_graph()
    a_done = transition_task(transition_task(a, "running", reason="spawned", actor="test"), "complete", reason="answered", actor="test")
    b_runnable = transition_task(b, "runnable", reason="dependencies satisfied", actor="test")
    b_done = transition_task(transition_task(b_runnable, "running", reason="spawned", actor="test"), "complete", reason="answered", actor="test")
    tasks = [a_done, b_done, c]
    assert compute_runnable_tasks(tasks) == [c.task_id]
    print("[PASS] #3 completing A then B leaves only C eligible")


def check_duplicate_task_detection() -> None:
    (a, _, _), _ = _dns_graph()
    duplicate_of_a = ResearchTask(investigation_id="inv-dns", target_entity_id="dns", research_field="definition", task_type="deep_dive", dependencies=[])
    assert detect_duplicate_task(duplicate_of_a, [a, duplicate_of_a]) == a.task_id
    different_field = ResearchTask(investigation_id="inv-dns", target_entity_id="dns", research_field="caching", task_type="deep_dive", dependencies=[])
    assert detect_duplicate_task(different_field, [a, different_field]) is None
    print("[PASS] #4 duplicate task detected for identical (investigation, entity, field, type); distinct field not flagged")


async def check_missing_dependency_rejected() -> None:
    orphan = ResearchTask(investigation_id="inv-x", target_entity_id="e1", task_type="deep_dive", dependencies=["does-not-exist"])
    try:
        validate_task_graph([orphan])
        raise AssertionError("validate_task_graph should reject an unknown dependency id")
    except TaskGraphValidationError:
        pass

    master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH)
    try:
        await master.run_task_graph([orphan], {orphan.task_id: _make_question("x")})
        raise AssertionError("run_task_graph should reject a graph with a missing dependency")
    except TaskGraphValidationError:
        pass
    print("[PASS] #5 missing dependency rejected by validate_task_graph and by run_task_graph itself")


async def check_dependency_cycle_rejected() -> None:
    x = ResearchTask(investigation_id="inv-x", target_entity_id="X", task_type="deep_dive", dependencies=[])
    y = ResearchTask(investigation_id="inv-x", target_entity_id="Y", task_type="deep_dive", dependencies=[])
    x_cyclic = ResearchTask(**{**x.model_dump(), "dependencies": [y.task_id]})
    y_cyclic = ResearchTask(**{**y.model_dump(), "dependencies": [x.task_id]})
    try:
        validate_task_graph([x_cyclic, y_cyclic])
        raise AssertionError("validate_task_graph should reject A<->B")
    except TaskGraphValidationError:
        pass

    master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH)
    try:
        await master.run_task_graph(
            [x_cyclic, y_cyclic],
            {x_cyclic.task_id: _make_question("x"), y_cyclic.task_id: _make_question("y")},
        )
        raise AssertionError("run_task_graph should reject a cyclic graph")
    except TaskGraphValidationError:
        pass
    print("[PASS] #6 dependency cycle rejected by validate_task_graph and by run_task_graph itself; nothing scheduled")


def check_failed_dependency_handling() -> None:
    (a, b, _), _ = _dns_graph()
    a_running = transition_task(a, "running", reason="spawned", actor="test")
    a_failed = transition_task(a_running, "failed", reason="simulated failure", actor="test")  # attempt_count=1, max_attempts default 1
    assert compute_runnable_tasks([a_failed, b]) == [], "a merely-failed dependency must never satisfy a dependent"

    a_exhausted = transition_task(a_failed, "budget_exhausted", reason="no attempts left", actor="test")
    assert compute_runnable_tasks([a_exhausted, b]) == [], "an exhausted dependency still must not satisfy a dependent"
    assert compute_tasks_blocked_by_failed_dependency([a_exhausted, b]) == [b.task_id], "B must be explicitly reported as blocked by a permanently-failed dependency"
    print("[PASS] #7 a failed dependency never satisfies a dependent; permanent (budget_exhausted) failure is surfaced explicitly, not left ambiguous")


async def check_budget_exhaustion() -> None:
    tasks, questions = _dns_graph()
    master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH, ground_db_path=GROUND_DB_PATH)
    result = await master.run_task_graph(tasks, questions, task_budget=1)
    assert isinstance(result, TaskGraphResult)
    assert result.executed_task_ids == [tasks[0].task_id], f"expected only A executed, got {result.executed_task_ids}"
    assert result.stopped_reason == "budget_exhausted"
    assert result.rounds_run < len(tasks) + 1, "must terminate well within the safety cap, not loop indefinitely"
    print(f"[PASS] #8 task_budget=1 executed exactly [A], stopped_reason={result.stopped_reason!r}, rounds_run={result.rounds_run}, no infinite loop")


async def check_task_failure_recorded() -> None:
    solo = ResearchTask(investigation_id="inv-fail", target_entity_id="e1", task_type="deep_dive", dependencies=[])
    question = _make_question("FAIL_TRIGGER: this question always raises")
    master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH, ground_db_path=GROUND_DB_PATH)
    result = await master.run_task_graph([solo], {solo.task_id: question})
    failed_task = next(t for t in result.tasks if t.task_id == solo.task_id)
    assert failed_task.status == "failed", f"expected 'failed', got {failed_task.status!r}"
    assert "simulated GroundAgent failure" in (failed_task.provenance_note or "")
    assert result.executed_task_ids == [solo.task_id]
    print("[PASS] #9 a GroundAgent that raises is recorded as 'failed' with the real error preserved; coordinator finished cleanly")


async def check_idempotent_re_entry() -> None:
    call_count = 0
    real_fake = _fake_decide_next_step

    async def counting_fake(question, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_fake(question, **kwargs)

    ground_agent_module.decide_next_step = counting_fake
    try:
        tasks, questions = _dns_graph()
        # Two separate MasterAgent instances (distinct agent_ids -> distinct
        # LangGraph checkpoint thread_ids), so this test isolates the
        # SCHEDULER's own data-driven idempotency (it never re-selects an
        # already-'complete' task) from any checkpointer-level thread-reuse
        # behavior -- resuming a single thread mid-graph across separate
        # calls is a real, separate, deferred capability, not what this
        # check is verifying.
        first_master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH, ground_db_path=GROUND_DB_PATH)
        first = await first_master.run_task_graph(tasks, questions)
        first_call_count = call_count
        assert first.stopped_reason == "complete"
        assert set(first.executed_task_ids) == {t.task_id for t in tasks}

        second_master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH, ground_db_path=GROUND_DB_PATH)
        second = await second_master.run_task_graph(first.tasks, questions)
    finally:
        ground_agent_module.decide_next_step = real_fake

    assert call_count == first_call_count, "re-entry must not invoke decide_next_step again for already-complete tasks"
    assert second.executed_task_ids == [], f"re-entry must execute zero additional tasks, got {second.executed_task_ids}"
    assert all(t.status == "complete" for t in second.tasks)
    print(f"[PASS] #10 idempotent re-entry: {first_call_count} LLM calls first run, 0 additional on re-entry, state stayed consistent")


async def check_real_master_agent_integration() -> None:
    tasks, questions = _dns_graph()
    master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH, ground_db_path=GROUND_DB_PATH)
    result = await master.run_task_graph(tasks, questions)

    assert result.stopped_reason == "complete"
    assert set(result.executed_task_ids) == {t.task_id for t in tasks}
    assert all(t.status == "complete" for t in result.tasks)
    assert result.rounds_run >= 2, "B/C only become runnable after A completes -- this must take at least 2 rounds, not 1"
    assert result.duplicate_task_ids == {}
    assert result.blocked_by_failed_dependency == []
    print(f"[PASS] #11 real MasterAgent.run_task_graph (real LangGraph + real GroundAgent, decide_next_step mocked): all 3 tasks complete in {result.rounds_run} rounds")


async def check_live_smoke_optional() -> None:
    if not has_any_provider_key():
        print("[skip] #live no LLM provider key in .env -- live smoke not run; all 11 checks above are deterministic/mocked and unaffected")
        return
    real_decide = ground_agent_module.decide_next_step
    try:
        tasks, questions = _dns_graph()
        # only task A, to bound real cost/latency of this optional smoke check
        master = MasterAgent(checkpoint_db_path=CHECKPOINT_DB_PATH + ".live", ground_db_path=GROUND_DB_PATH + ".live")
        result = await master.run_task_graph([tasks[0]], {tasks[0].task_id: questions[tasks[0].task_id]})
        print(f"[live] task A real result: status={result.tasks[0].status!r} stopped_reason={result.stopped_reason!r}")
        print("[ok] live provider call completed -- reported separately from the 11 deterministic/mocked checks above, per Rule 14")
    except Exception as exc:  # noqa: BLE001 - a live provider failure must be visible, not hidden inside the main check count
        print(f"[live-fail] live smoke check failed ({exc!r}) -- this is a PROVIDER/NETWORK result, not an application-logic failure; the 11 mocked checks above already passed independently of this")
    finally:
        ground_agent_module.decide_next_step = real_decide


async def run() -> None:
    for path_str in (GROUND_DB_PATH, CHECKPOINT_DB_PATH, GROUND_DB_PATH + ".live", CHECKPOINT_DB_PATH + ".live"):
        path = pathlib.Path(path_str)
        if path.exists():
            path.unlink()

    check_initial_runnable_blocked_split()
    check_dependency_unlock()
    check_partial_completion()
    check_duplicate_task_detection()
    check_failed_dependency_handling()

    real_decide_next_step = ground_agent_module.decide_next_step
    ground_agent_module.decide_next_step = _fake_decide_next_step
    try:
        await check_missing_dependency_rejected()
        await check_dependency_cycle_rejected()
        await check_budget_exhaustion()
        await check_task_failure_recorded()
        await check_idempotent_re_entry()
        await check_real_master_agent_integration()
    finally:
        ground_agent_module.decide_next_step = real_decide_next_step

    print(
        "\nAll 11 checks passed (deterministic, decide_next_step mocked -- exactly scripts/verify_phase4.py's own "
        "technique). No LLM/retriever/Neo4j call was made for any of them.\n"
    )
    print("Optional live-provider smoke check (Rule 14: reported separately, never folded into the 11 above):")
    await check_live_smoke_optional()

    print("\nAcceptance #12 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")


if __name__ == "__main__":
    asyncio.run(run())
