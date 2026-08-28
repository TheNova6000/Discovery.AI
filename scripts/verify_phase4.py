"""Phase 4 verification script — see docs/Phases.md "Phase 4".

Three things are verified:
1. A live smoke test: `MasterAgent.run()` really spawns real `GroundAgent`s (real
   LLM calls) through the LangGraph state machine and returns a coherent result.
2. Boundary-hit propagation + Master decision (Phases.md's check #1): a Ground
   Agent decomposes once, its two children each hit a boundary, and we confirm (a)
   both `ExpansionRequestMessage`s share the same root ancestor in their
   `sender_chain` but come from different senders — proof the message really
   travelled up a multi-level parent chain, not just a single hop — and (b) the
   Master's accept/reject decisions respect `max_expansions`. `decide_next_step` is
   monkeypatched here to force the boundary condition deterministically — a live
   LLM won't reliably choose to hit a boundary on command, so this isolates the
   propagation *mechanism* from LLM judgment, the same approach
   `scripts/verify_phase3.py` used for its mid-decomposition-crash check.
3. Spawn budget enforcement (Phases.md's check #2): feed the Master more questions
   than its default budget for a "simple" query and confirm it spawns (and calls
   the LLM for) no more than the budget — not just that the final count looks
   right after the fact, but that the excess questions were dropped *before* any
   LLM call was made for them (checked via a call counter).

Requires at least one LLM provider key in .env (GEMINI_API_KEY, GROQ_API_KEY, or
CEREBRAS_API_KEY) — see Implimentation-Research/Free-LLM-APIs.md.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.agents.ground_agent as ground_agent_module  # noqa: E402
from backend.agents import ExpansionDecision, MasterAgent  # noqa: E402
from backend.agents.models import AgentStatus  # noqa: E402
from backend.questions import GroundDecision, QuestionLevel  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question  # noqa: E402

GROUND_DB_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "verify_phase4_ground.sqlite3")
CHECKPOINT_DB_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "verify_phase4_checkpoints.sqlite3")


def _make_question(text: str) -> Question:
    return Question(
        text=text,
        rationale="Phase 4 verification seed question.",
        dimension_id="scale",
        level=QuestionLevel.GROUND,
        entity_name="PayPal",
        abstraction_name="Payment Platforms",
    )


async def check_live_smoke() -> None:
    master = MasterAgent(ground_max_depth=0, ground_db_path=GROUND_DB_PATH, checkpoint_db_path=CHECKPOINT_DB_PATH)
    questions = [
        _make_question("How does PayPal verify a phone number at signup?"),
        _make_question("How does PayPal issue a refund for a completed payment?"),
    ]
    result = await master.run(questions, complexity="simple")
    print(
        f"[live] requested={result.requested_count} spawned={result.spawned_count} "
        f"dropped={result.dropped_count} budget={result.effective_budget}"
    )
    assert result.spawned_count == 2
    assert result.dropped_count == 0
    assert len(result.ground_results) == 2
    for r in result.ground_results:
        assert r.status in (AgentStatus.COMPLETE, AgentStatus.BOUNDARY_HIT)
    print("[ok] live MasterAgent run through LangGraph produced a coherent result")


async def check_boundary_propagation_and_expansion_decision() -> None:
    """Force: parent asks 2 sequential sub-questions (decomposition is one-at-a-time
    post-Phase-5, see docs/Memory.md) -> each child hits a boundary -> parent
    concludes on the 3rd round. `decide_next_step` is monkeypatched to make this
    deterministic; everything else (GroundAgent recursion, the message bus,
    MasterAgent's LangGraph nodes) is real.
    """

    top_level_calls = 0

    async def fake_decide_next_step(question: Question, *, known=None, model_chain=None) -> GroundDecision:
        nonlocal top_level_calls
        if question.rationale.startswith("Sub-question of:"):
            return GroundDecision(
                action="boundary_hit",
                reasoning="forced for test determinism",
                boundary_reason=f"forced boundary: {question.text}",
            )
        top_level_calls += 1
        if top_level_calls == 1:
            return GroundDecision(
                action="decompose",
                reasoning="forced for test determinism",
                sub_question_texts=[f"{question.text} (part A)"],
            )
        if top_level_calls == 2:
            return GroundDecision(
                action="decompose",
                reasoning="forced for test determinism",
                sub_question_texts=[f"{question.text} (part B)"],
            )
        return GroundDecision(
            action="answer",
            reasoning="forced for test determinism",
            answer="Best-effort answer despite two unresolved sub-questions.",
            confidence=0.3,
        )

    real_decide = ground_agent_module.decide_next_step
    ground_agent_module.decide_next_step = fake_decide_next_step
    try:
        master = MasterAgent(
            max_expansions=1,
            ground_max_depth=1,
            ground_db_path=GROUND_DB_PATH,
            checkpoint_db_path=CHECKPOINT_DB_PATH,
        )
        result = await master.run(
            [_make_question("How does the PayPal payment platform work end to end?")],
            complexity="simple",
        )
    finally:
        ground_agent_module.decide_next_step = real_decide

    assert result.spawned_count == 1
    assert len(result.ground_results) == 1
    top_result = result.ground_results[0]
    assert top_result.status == AgentStatus.COMPLETE  # parent synthesizes its children
    assert len(top_result.child_results) == 2
    assert all(c.status == AgentStatus.BOUNDARY_HIT for c in top_result.child_results)

    decisions = result.expansion_decisions
    print(f"[boundary] {len(decisions)} expansion decision(s): {[d.decision.value for d in decisions]}")
    assert len(decisions) == 2, "each of the 2 children's boundary hits should produce one decision"

    # Multi-hop propagation proof: both decisions trace back to the SAME root
    # ancestor (the top-level Ground Agent) but were sent by DIFFERENT children —
    # this is only possible if the message actually carried the parent chain up
    # through an intermediate agent, not a single flat hop.
    root_ancestors = {d.sender_chain[0] for d in decisions}
    senders = {d.sender_chain[-1] for d in decisions}
    assert len(d_chain := decisions[0].sender_chain) >= 2, f"expected a multi-hop chain, got {d_chain}"
    assert len(root_ancestors) == 1, f"both children should share one root ancestor, got {root_ancestors}"
    assert len(senders) == 2, f"the two boundary hits should come from two distinct children, got {senders}"
    print(f"[ok] both boundary hits share root ancestor {next(iter(root_ancestors))!r}, sent by 2 distinct children")

    # Spawn-budget-style enforcement applied to expansions too (max_expansions=1):
    # first ACCEPT, the rest REJECT — Master decides, it doesn't act on ACCEPT yet
    # (that's Phase 7), it just needs to log the right decision.
    assert decisions[0].decision == ExpansionDecision.ACCEPT
    assert decisions[1].decision == ExpansionDecision.REJECT
    print("[ok] Master accepted the first expansion request and rejected the second (max_expansions=1)")


async def check_spawn_budget_enforced_before_spawning() -> None:
    call_count = 0
    real_decide = ground_agent_module.decide_next_step

    async def counting_decide(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_decide(*args, **kwargs)

    ground_agent_module.decide_next_step = counting_decide
    try:
        master = MasterAgent(
            spawn_budget=3,
            ground_max_depth=0,  # 1 LLM call per spawned agent, no recursion
            ground_db_path=GROUND_DB_PATH,
            checkpoint_db_path=CHECKPOINT_DB_PATH,
        )
        questions = [_make_question(f"How does PayPal handle case #{i} of a disputed charge?") for i in range(5)]
        result = await master.run(questions, complexity="simple")
    finally:
        ground_agent_module.decide_next_step = real_decide

    print(
        f"[budget] requested={result.requested_count} spawned={result.spawned_count} "
        f"dropped={result.dropped_count} LLM calls made={call_count}"
    )
    assert result.requested_count == 5
    assert result.effective_budget == 3
    assert result.spawned_count == 3, "simple complexity must not exceed the default spawn budget"
    assert result.dropped_count == 2
    assert call_count == 3, (
        f"expected exactly 3 LLM calls (one per spawned agent), got {call_count} — "
        "the budget must be enforced BEFORE spawning, not after"
    )
    print("[ok] spawn budget enforced before any Ground Agent (and therefore any LLM call) was created")


async def run() -> None:
    if not has_any_provider_key():
        print(
            "[fail] No LLM provider key found in .env "
            "(GEMINI_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY / COHERE_API_KEY)."
        )
        raise SystemExit(1)

    for path_str in (GROUND_DB_PATH, CHECKPOINT_DB_PATH):
        path = pathlib.Path(path_str)
        if path.exists():
            path.unlink()

    await check_live_smoke()
    await check_boundary_propagation_and_expansion_decision()
    await check_spawn_budget_enforced_before_spawning()

    print("\nPhase 4 verification PASSED.")


if __name__ == "__main__":
    asyncio.run(run())
