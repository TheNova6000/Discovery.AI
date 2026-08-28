"""Phase 3 verification script — see docs/Phases.md "Phase 3".

Two things are verified:
1. A fresh Ground Agent run really calls the LLM, produces a typed result (possibly
   after real recursive decomposition), and checkpoints it — then calling run()
   again for the same agent_id (simulating a restarted process re-attaching to a
   finished agent) returns the identical result WITHOUT calling the LLM again.
2. A Ground Agent that has decomposed but whose children haven't run yet (the exact
   "process died mid-run" point Phase 3 asks about) is reconstructed from nothing
   but its on-disk checkpoint and correctly resumes by running only the
   not-yet-complete children, rather than re-deciding to decompose from scratch.

We simulate "kill the process mid-run" by writing the checkpoint state directly
(literally killing this process would also kill the verification script) and then
constructing a brand-new GroundAgent object from only that on-disk state — exactly
what a real restarted process would do, since GroundAgent.run() always starts by
reading the state store, never from in-memory state.

Requires at least one LLM provider key in .env (GEMINI_API_KEY, GROQ_API_KEY, or
CEREBRAS_API_KEY) — see Implimentation-Research/Free-LLM-APIs.md.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.agents.ground_agent as ground_agent_module  # noqa: E402
from backend.agents import AgentStatus, GroundAgent  # noqa: E402
from backend.agents.models import AgentState  # noqa: E402
from backend.questions import QuestionLevel  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question  # noqa: E402
from backend.runtime import init_db, load_state, save_state  # noqa: E402

VERIFY_DB_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "verify_phase3_state.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_question(text: str) -> Question:
    return Question(
        text=text,
        rationale="Phase 3 verification seed question.",
        dimension_id="scale",
        level=QuestionLevel.GROUND,
        entity_name="PayPal",
        abstraction_name="Payment Platforms",
    )


async def check_terminal_agent_does_not_recompute() -> None:
    question = _make_question("How does PayPal verify a user's identity at signup?")
    # max_depth=1 bounds real LLM usage for this live run (children, if any, can't
    # decompose again) while still exercising the real decision path end to end.
    agent = GroundAgent(question, max_depth=1, db_path=VERIFY_DB_PATH)
    first_result = await agent.run()
    print(f"[run 1] status={first_result.status.value} answer={str(first_result.answer)[:80]!r}")
    assert first_result.status in (AgentStatus.COMPLETE, AgentStatus.BOUNDARY_HIT)

    call_count = 0
    real_decide = ground_agent_module.decide_next_step

    async def counting_decide(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await real_decide(*args, **kwargs)

    ground_agent_module.decide_next_step = counting_decide
    try:
        resumed_agent = GroundAgent(question, agent_id=agent.agent_id, max_depth=1, db_path=VERIFY_DB_PATH)
        second_result = await resumed_agent.run()
    finally:
        ground_agent_module.decide_next_step = real_decide

    assert second_result == first_result, "resumed terminal agent returned a different result"
    assert call_count == 0, f"resumed terminal agent made {call_count} LLM call(s) instead of 0"
    print("[ok] terminal agent resume returned cached result with zero LLM calls")


async def check_mid_decomposition_crash_resume() -> None:
    parent_question = _make_question(
        "How does the PayPal payment platform work end to end, from checkout to settlement?"
    )
    parent_id = "verify-parent-mid-crash"
    child_a_id = "verify-child-a"
    child_b_id = "verify-child-b"

    child_a_question = _make_question("How does PayPal authorize a single card payment?")
    child_b_question = _make_question("How does PayPal settle funds with a receiving bank?")

    # Hand-write exactly the on-disk state a real process would have left behind
    # right after deciding to decompose and persisting its children, but before
    # running any of them — the literal "killed mid-run" point.
    for child_id, child_question in ((child_a_id, child_a_question), (child_b_id, child_b_question)):
        await save_state(
            child_id,
            AgentState(
                agent_id=child_id, parent_id=parent_id, question=child_question,
                depth=1, max_depth=2, status=AgentStatus.PENDING,
            ).model_dump_json(),
            _now(),
            db_path=VERIFY_DB_PATH,
        )
    await save_state(
        parent_id,
        AgentState(
            agent_id=parent_id, parent_id=None, question=parent_question,
            depth=0, max_depth=2, status=AgentStatus.DECOMPOSING,
            children=[child_a_id, child_b_id],
        ).model_dump_json(),
        _now(),
        db_path=VERIFY_DB_PATH,
    )

    # This is what a *restarted process* does: construct a brand-new GroundAgent
    # object knowing only the parent's agent_id, with no in-memory knowledge that a
    # decomposition ever happened.
    resumed_parent = GroundAgent(parent_question, agent_id=parent_id, db_path=VERIFY_DB_PATH)
    result = await resumed_parent.run()

    print(f"[resume] parent status={result.status.value}, {len(result.child_results)} child result(s)")
    assert result.status == AgentStatus.COMPLETE
    # >= 2, not == 2: decomposition is sequential post-Phase-5 (see docs/Memory.md)
    # — after resuming and completing the two hand-crafted children, the agent
    # re-decides whether a real answer is possible yet and may adaptively add more
    # sub-questions before concluding. The behavior this test actually targets is
    # that the two ALREADY-DECLARED children are resumed and reused, not recreated.
    assert len(result.child_results) >= 2

    final_raw = await load_state(parent_id, db_path=VERIFY_DB_PATH)
    assert final_raw is not None
    final_state = AgentState.model_validate_json(final_raw)
    assert final_state.status == AgentStatus.COMPLETE
    assert {child_a_id, child_b_id}.issubset(set(final_state.children)), (
        "the two hand-crafted children must have been resumed and reused, not recreated"
    )
    print(
        f"[ok] parent resumed from DECOMPOSING checkpoint, reused the 2 pending children "
        f"(final total: {len(final_state.children)}), reached COMPLETE"
    )


async def run() -> None:
    if not has_any_provider_key():
        print(
            "[fail] No LLM provider key found in .env "
            "(GEMINI_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY / COHERE_API_KEY)."
        )
        raise SystemExit(1)

    verify_db = pathlib.Path(VERIFY_DB_PATH)
    if verify_db.exists():
        verify_db.unlink()
    await init_db(VERIFY_DB_PATH)

    await check_terminal_agent_does_not_recompute()
    await check_mid_decomposition_crash_resume()

    print("\nPhase 3 verification PASSED.")


if __name__ == "__main__":
    asyncio.run(run())
