"""Second real learning session (docs/Memory.md), not a test. Chosen because it's
genuinely something worth understanding better, not because it's likely to break
anything — per the explicit instruction not to go hunting for failure.

Question: "How does a central bank control interest rates?" No dimension, no
prescribed structure. Unlike the payment-rails session (extremely well-documented,
structurally uncontroversial), this one has a real seam worth watching for: the
MECHANICS of how a central bank moves a policy rate (open market operations,
reserve mechanics, standing facilities) are well-established, but the
TRANSMISSION of that rate change into inflation/employment/lending is genuinely
debated in real economics — a natural place for "children confirm the framing" to
instead turn into "children expose that the mechanism and its effect are not the
same kind of question."

Same recipe as the payment-rails session: real evidence gathering (keyless
retrievers only — Tavily/YouTube skip gracefully), real graph persistence. Run on
the VM (Neo4j only exists there).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents.ground_agent import GroundAgent  # noqa: E402
from backend.agents.models import AgentState, AgentStatus  # noqa: E402
from backend.questions import Question, QuestionLevel  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.runtime import load_state  # noqa: E402

QUESTION_TEXT = "How does a central bank control interest rates?"
ENTITY_NAME = "Central Bank"
ABSTRACTION_NAME = "Monetary Policy"
RATIONALE = "Understanding what a central bank actually does when it 'raises' or 'lowers' rates, and why that matters for the rest of the economy."
DB_PATH = "session_central_bank_rates.sqlite3"


async def _dump_tree(agent_id: str, db_path: str, indent: int = 0) -> None:
    raw = await load_state(agent_id, db_path=db_path)
    state = AgentState.model_validate_json(raw)
    pad = "  " * indent
    q = state.question
    print(f"{pad}[{q.level.value}] {q.text}")
    if state.result is not None:
        if state.result.status == AgentStatus.COMPLETE:
            print(f"{pad}   -> confidence: {state.result.confidence}")
            print(f"{pad}   -> answer: {state.result.answer}")
            if state.result.claims:
                print(f"{pad}   -> claims gathered: {len(state.result.claims)}")
                for claim in state.result.claims:
                    print(
                        f"{pad}      - [{claim.confidence}] {claim.source.title!r} "
                        f"({claim.source.url})"
                    )
        elif state.result.status == AgentStatus.BOUNDARY_HIT:
            print(f"{pad}   -> boundary_hit: {state.result.boundary_reason}")
        else:
            print(f"{pad}   -> status: {state.result.status.value}")
    for child_id in state.children:
        await _dump_tree(child_id, db_path, indent + 1)


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    pathlib.Path(DB_PATH).unlink(missing_ok=True)

    question = Question(
        text=QUESTION_TEXT,
        rationale=RATIONALE,
        dimension_id="none",
        level=QuestionLevel.MASTER,
        entity_name=ENTITY_NAME,
        abstraction_name=ABSTRACTION_NAME,
    )
    agent = GroundAgent(question, db_path=DB_PATH, gather_evidence=True, persist_to_graph=True)

    print("=" * 70)
    print(f"SESSION: {QUESTION_TEXT}")
    print("=" * 70)
    await agent.run()

    print("\n" + "=" * 70)
    print("FULL INVESTIGATION TREE")
    print("=" * 70)
    await _dump_tree(agent.agent_id, DB_PATH)


if __name__ == "__main__":
    asyncio.run(run())
