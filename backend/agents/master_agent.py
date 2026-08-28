from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from backend.questions import Question

from .bus import MessageBus
from .ground_agent import DEFAULT_MAX_DEPTH as GROUND_DEFAULT_MAX_DEPTH
from .ground_agent import GroundAgent
from .messages import BoundaryHitMessage, ExpansionDecision, ExpansionRequestMessage
from .models import GroundResult, MasterResult

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
