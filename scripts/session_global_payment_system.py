"""The system's first real learning session, not a test (docs/Memory.md). No
expected answer is pre-registered, no structure is prescribed — this exists to
find out what actually happens when a genuinely open question is run through the
whole pipeline as built so far: no dimension, no forced abstraction, real
evidence gathering (Wikipedia/arXiv/Semantic Scholar/OpenLibrary — keyless
retrievers; Tavily/YouTube skip gracefully with no TAVILY_API_KEY/YOUTUBE_API_KEY
set), and real graph persistence, so the result is something worth actually
navigating afterward (zoom_in/explain_entity), not a throwaway.

Question: "How does a global payment system work?" Rationale kept ordinary and
lens-neutral on purpose (see verify_dimension_steering.py's rationale-leak
lesson) — this is meant to read like a real person's actual curiosity, not an
experiment description.

Run on the VM only (persist_to_graph=True needs the real Neo4j instance, which
only exists there — no local Docker per docs/Memory.md).
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

QUESTION_TEXT = "How does a global payment system work?"
ENTITY_NAME = "Global Payment System"
ABSTRACTION_NAME = "Payment Systems"
RATIONALE = "Understanding how money actually moves between people, businesses, and countries when someone pays for something."
DB_PATH = "session_global_payment_system.sqlite3"


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
