from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from backend.questions import Question
from backend.reasoning import (
    ResearchTask,
    compute_runnable_tasks,
    compute_tasks_blocked_by_failed_dependency,
    detect_duplicate_task,
    transition_task,
    validate_task_graph,
)

from .bus import MessageBus
from .ground_agent import DEFAULT_MAX_DEPTH as GROUND_DEFAULT_MAX_DEPTH
from .ground_agent import GroundAgent
from .messages import BoundaryHitMessage, ExpansionDecision, ExpansionRequestMessage
from .models import AgentStatus, GroundResult, MasterResult, TaskGraphResult

DEFAULT_SPAWN_BUDGET = 3
"""Default number of top-level Ground Agents spawned for a "simple" query
(Rules.md rule 10: "default to a small fixed number... for a simple lookup")."""

DEFAULT_BROAD_SPAWN_BUDGET = 6
"""Only used when the caller passes an explicit `complexity="broad"` signal —
Rules.md rule 10 requires that signal to be explicit, never inferred."""

DEFAULT_MAX_EXPANSIONS = 2
"""How many BOUNDARY_HIT escalations this Master will ACCEPT in one run before
rejecting the rest. Phase 4 only makes and records this decision (see
ExpansionRequestMessage) — it does not yet act on an ACCEPT by spawning a new
branch (that's Phase 7's abstraction-change protocol)."""

DEFAULT_CHECKPOINT_DB_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "master_checkpoints.sqlite3"
)


class MasterState(TypedDict, total=False):
    """LangGraph state for the Master's own two-node workflow (docs/Phases.md
    Phase 4: "built on LangGraph's core engine for the state machine/
    checkpointing"). Deliberately plain JSON-shaped data — the actual GroundAgent
    objects and the MessageBus live as closures inside `MasterAgent.run()`, not in
    this state, so nothing here depends on anything LangGraph's checkpointer would
    struggle to serialize.
    """

    questions: list[dict]
    complexity: str
    spawn_budget: int
    broad_spawn_budget: int
    selected_question_ids: list[str]
    dropped_count: int
    effective_budget: int
    ground_results: list[dict]
    expansion_decisions: list[dict]
    spawned_count: int


class TaskGraphState(TypedDict, total=False):
    """LangGraph state for `MasterAgent.run_task_graph` (R3.2, docs/Architecture.md
    §0.65) — a separate state shape from `MasterState` above, not an extension of
    it: `run()`'s flat one-shot pipeline and this multi-round scheduling loop have
    different shapes for a real reason (§0.54.1's evaluation), not an oversight.
    Plain JSON-shaped data for the same checkpointing reason as `MasterState`.
    """

    tasks: list[dict]
    task_questions: dict[str, dict]
    task_budget: int
    actor: str
    executed_task_ids: list[str]
    duplicate_task_ids: dict[str, str]
    rounds_run: int
    stopped_reason: str


class MasterAgent:
    """Wraps recursive `GroundAgent` calls (docs/Phases.md Phase 4). Two-tier by
    default (Master + Ground) — intermediate structure only ever emerges as Ground
    agents recurse (Rules.md rule 8), never as a pre-declared class.

    The spawn budget is enforced in its own LangGraph node, `enforce_spawn_budget`,
    which runs and commits to a `selected_question_ids` list *before*
    `spawn_and_run` (the only node that actually constructs a `GroundAgent`) ever
    executes — this is what "hard spawn budget enforced before any spawning"
    (Rules.md rule 10) means concretely here, not just a comment's promise.
    """

    def __init__(
        self,
        *,
        spawn_budget: int = DEFAULT_SPAWN_BUDGET,
        broad_spawn_budget: int = DEFAULT_BROAD_SPAWN_BUDGET,
        max_expansions: int = DEFAULT_MAX_EXPANSIONS,
        ground_max_depth: int = GROUND_DEFAULT_MAX_DEPTH,
        ground_db_path: str | None = None,
        ground_gather_evidence: bool = False,
        ground_persist_to_graph: bool = False,
        checkpoint_db_path: str | None = None,
    ) -> None:
        self.agent_id = str(uuid.uuid4())
        self.spawn_budget = spawn_budget
        self.broad_spawn_budget = broad_spawn_budget
        self.max_expansions = max_expansions
        self.ground_max_depth = ground_max_depth
        self.ground_db_path = ground_db_path
        # Opt-in (docs/Phases.md Phase 5) — see GroundAgent's own `gather_evidence`
        # flag for why this defaults to False.
        self.ground_gather_evidence = ground_gather_evidence
        # Opt-in (post-Phase-5 graph-persistence pass) — see GroundAgent's own
        # `persist_to_graph` flag.
        self.ground_persist_to_graph = ground_persist_to_graph
        self.checkpoint_db_path = checkpoint_db_path or DEFAULT_CHECKPOINT_DB_PATH

    async def run(
        self,
        questions: list[Question],
        *,
        complexity: Literal["simple", "broad"] = "simple",
    ) -> MasterResult:
        expansions_granted = 0

        def decide_expansion(message: BoundaryHitMessage) -> ExpansionRequestMessage:
            nonlocal expansions_granted
            decision = (
                ExpansionDecision.ACCEPT
                if expansions_granted < self.max_expansions
                else ExpansionDecision.REJECT
            )
            if decision == ExpansionDecision.ACCEPT:
                expansions_granted += 1
            return ExpansionRequestMessage(
                boundary_hit_id=message.id,
                sender_chain=[*message.parent_chain, message.sender_id],
                reason=message.reason,
                decision=decision,
            )

        async def enforce_spawn_budget(state: MasterState) -> dict:
            # This node commits to which questions will be investigated BEFORE
            # anything is spawned — Rules.md rule 10's ordering requirement lives
            # here, structurally, as a separate LangGraph node that must complete
            # (and checkpoint) before `spawn_and_run` can begin.
            budget = state["spawn_budget"] if state["complexity"] == "simple" else state["broad_spawn_budget"]
            selected = state["questions"][:budget]
            return {
                "selected_question_ids": [q["id"] for q in selected],
                "dropped_count": max(len(state["questions"]) - len(selected), 0),
                "effective_budget": budget,
            }

        async def spawn_and_run(state: MasterState) -> dict:
            selected_ids = set(state["selected_question_ids"])
            selected_questions = [Question(**q) for q in state["questions"] if q["id"] in selected_ids]

            bus = MessageBus()
            expansion_decisions: list[dict] = []

            async def consume() -> None:
                async for message in bus.messages():
                    if isinstance(message, BoundaryHitMessage):
                        expansion_decisions.append(decide_expansion(message).model_dump())

            consumer_task = asyncio.create_task(consume())
            ground_agents = [
                GroundAgent(
                    q,
                    bus=bus,
                    max_depth=self.ground_max_depth,
                    db_path=self.ground_db_path,
                    gather_evidence=self.ground_gather_evidence,
                    persist_to_graph=self.ground_persist_to_graph,
                )
                for q in selected_questions
            ]
            ground_results = await asyncio.gather(*(g.run() for g in ground_agents))
            await bus.close()
            await consumer_task

            return {
                "ground_results": [r.model_dump() for r in ground_results],
                "expansion_decisions": expansion_decisions,
                "spawned_count": len(ground_agents),
            }

        builder = StateGraph(MasterState)
        builder.add_node("enforce_spawn_budget", enforce_spawn_budget)
        builder.add_node("spawn_and_run", spawn_and_run)
        builder.add_edge(START, "enforce_spawn_budget")
        builder.add_edge("enforce_spawn_budget", "spawn_and_run")
        builder.add_edge("spawn_and_run", END)

        initial_state: MasterState = {
            "questions": [q.model_dump() for q in questions],
            "complexity": complexity,
            "spawn_budget": self.spawn_budget,
            "broad_spawn_budget": self.broad_spawn_budget,
        }

        async with AsyncSqliteSaver.from_conn_string(self.checkpoint_db_path) as saver:
            graph = builder.compile(checkpointer=saver)
            final_state = await graph.ainvoke(
                initial_state, config={"configurable": {"thread_id": self.agent_id}}
            )

        return MasterResult(
            requested_count=len(questions),
            spawned_count=final_state["spawned_count"],
            dropped_count=final_state["dropped_count"],
            effective_budget=final_state["effective_budget"],
            ground_results=[GroundResult(**r) for r in final_state["ground_results"]],
            expansion_decisions=[ExpansionRequestMessage(**d) for d in final_state["expansion_decisions"]],
        )

    async def run_task_graph(
        self,
        tasks: list[ResearchTask],
        task_questions: dict[str, Question],
        *,
        actor: str = "master_agent",
        task_budget: int | None = None,
    ) -> TaskGraphResult:
        """R3.2 (docs/Architecture.md §0.65): schedule and execute a real
        `ResearchTask` graph, `GroundAgent` remaining the worker exactly as
        §0.53 requires — this method does not change how a single
        investigation runs, only how many of them run, in what order, and
        whether a given one runs at all.

        `task_questions` maps `task_id -> Question` — `ResearchTask` (R3.1)
        deliberately carries no `Question` field (keeping `backend.reasoning`
        free of any import from `backend.questions`, per its own zero-cross-
        package-import contract), so the caller supplies the actual
        investigation payload for each task separately, at the orchestration
        layer where such a dependency is allowed.

        `task_budget` bounds how many tasks THIS call will execute in total,
        independent of `spawn_budget` (which still governs `run()`'s
        top-level width) — defaults to `spawn_budget` only because that is
        this instance's already-configured "how much work at once" number,
        not because the two concepts are the same thing.

        Validation (missing dependency ids, dependency cycles) happens
        before any LangGraph state is created — an unschedulable graph is
        rejected outright (TaskGraphValidationError), never silently
        scheduled as if every task were runnable.

        The round-robin scheduling loop is deliberately a plain Python loop
        inside ONE checkpointed LangGraph node in this first wiring slice,
        not yet a graph-level conditional-edge cycle — both are legitimate
        LangGraph usage; promoting it to real graph edges (enabling
        mid-round checkpoint resumption after a process restart) is a real,
        deferred extension, not a limitation this slice hides.
        """
        validate_task_graph(tasks)

        effective_budget = task_budget if task_budget is not None else self.spawn_budget
        safety_cap = len(tasks) + 1  # Rule: no infinite loop, ever, regardless of graph shape

        async def schedule_and_execute(state: TaskGraphState) -> dict:
            current: list[ResearchTask] = [ResearchTask(**t) for t in state["tasks"]]
            questions = {task_id: Question(**q) for task_id, q in state["task_questions"].items()}
            budget = state["task_budget"]
            actor_ = state["actor"]
            executed: list[str] = []
            duplicates: dict[str, str] = {}
            rounds = 0
            stopped_reason = "round_limit_reached"

            def replace(task_id: str, updated: ResearchTask) -> None:
                nonlocal current
                current = [updated if t.task_id == task_id else t for t in current]

            while rounds < safety_cap:
                rounds += 1

                for task_id in compute_runnable_tasks(current):
                    blocked_task = next(t for t in current if t.task_id == task_id)
                    replace(task_id, transition_task(blocked_task, "runnable", reason="dependencies satisfied", actor=actor_))

                runnable_now = [t for t in current if t.status == "runnable"]
                if not runnable_now:
                    still_blocked = [t for t in current if t.status == "blocked"]
                    stopped_reason = "complete" if not still_blocked else "no_runnable_tasks"
                    break

                to_execute: list[ResearchTask] = []
                for task in runnable_now:
                    canonical_id = detect_duplicate_task(task, current)
                    canonical = next((t for t in current if t.task_id == canonical_id), None) if canonical_id else None
                    if canonical is not None and canonical.status in ("complete", "running"):
                        duplicates[task.task_id] = canonical.task_id
                        running_dup = transition_task(task, "running", reason=f"duplicate of {canonical.task_id}, reusing its result", actor=actor_)
                        completed_dup = transition_task(running_dup, "complete", reason=f"duplicate of {canonical.task_id}, not independently executed", actor=actor_)
                        replace(task.task_id, ResearchTask(**{**completed_dup.model_dump(), "result_refs": list(canonical.result_refs)}))
                    else:
                        to_execute.append(task)

                if not to_execute:
                    continue  # this round only resolved duplicates; re-derive runnable state next round

                remaining_budget = budget - len(executed)
                if remaining_budget <= 0:
                    stopped_reason = "budget_exhausted"
                    break
                batch = to_execute[:remaining_budget]

                for task in batch:
                    replace(task.task_id, transition_task(task, "running", reason="spawned by run_task_graph's coordinator", actor=actor_))

                agents = {task.task_id: GroundAgent(
                    questions[task.task_id],
                    max_depth=self.ground_max_depth,
                    db_path=self.ground_db_path,
                    gather_evidence=self.ground_gather_evidence,
                    persist_to_graph=self.ground_persist_to_graph,
                ) for task in batch}
                results = await asyncio.gather(*(agents[task.task_id].run() for task in batch), return_exceptions=True)

                for task, result in zip(batch, results):
                    running_task = next(t for t in current if t.task_id == task.task_id)
                    if isinstance(result, BaseException):
                        replace(task.task_id, transition_task(running_task, "failed", reason=f"GroundAgent raised: {result}", actor=actor_))
                    elif result.status == AgentStatus.FAILED:
                        # AgentStatus.BOUNDARY_HIT deliberately falls through to
                        # "complete" below, matching this repo's own existing
                        # convention (scripts/verify_phase4.py's own assertion
                        # treats COMPLETE and BOUNDARY_HIT alike as "not failed").
                        # Acting on a task-graph-spawned boundary hit (escalating,
                        # spawning a new branch) is Phase 7 territory and an
                        # explicit R3.2 non-goal -- a real, stated limitation, not
                        # a silently swallowed case.
                        replace(task.task_id, transition_task(running_task, "failed", reason="GroundAgent reported AgentStatus.FAILED", actor=actor_))
                    else:
                        replace(task.task_id, transition_task(running_task, "complete", reason="GroundAgent finished", actor=actor_))
                        completed_task = next(t for t in current if t.task_id == task.task_id)
                        replace(task.task_id, ResearchTask(**{**completed_task.model_dump(), "result_refs": [agents[task.task_id].agent_id]}))
                    executed.append(task.task_id)

            return {
                "tasks": [t.model_dump() for t in current],
                "executed_task_ids": executed,
                "duplicate_task_ids": duplicates,
                "rounds_run": rounds,
                "stopped_reason": stopped_reason,
            }

        builder = StateGraph(TaskGraphState)
        builder.add_node("schedule_and_execute", schedule_and_execute)
        builder.add_edge(START, "schedule_and_execute")
        builder.add_edge("schedule_and_execute", END)

        initial_state: TaskGraphState = {
            "tasks": [t.model_dump() for t in tasks],
            "task_questions": {task_id: q.model_dump() for task_id, q in task_questions.items()},
            "task_budget": effective_budget,
            "actor": actor,
        }

        async with AsyncSqliteSaver.from_conn_string(self.checkpoint_db_path) as saver:
            graph = builder.compile(checkpointer=saver)
            final_state = await graph.ainvoke(
                initial_state, config={"configurable": {"thread_id": f"{self.agent_id}-task-graph"}}
            )

        final_tasks = [ResearchTask(**t) for t in final_state["tasks"]]
        return TaskGraphResult(
            tasks=final_tasks,
            executed_task_ids=final_state["executed_task_ids"],
            duplicate_task_ids=final_state["duplicate_task_ids"],
            blocked_by_failed_dependency=compute_tasks_blocked_by_failed_dependency(final_tasks),
            rounds_run=final_state["rounds_run"],
            stopped_reason=final_state["stopped_reason"],
        )
