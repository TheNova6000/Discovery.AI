"""Third and final observation session (docs/Memory.md) before returning to
engineering. Not a test, no synthetic setup — chosen deliberately as a question
that isn't a clean technical system (unlike sessions 1-2) and could plausibly
touch economics, psychology, technology, organization, competition, network
effects, strategy, regulation, and history at once. No dimension given, no
structure prescribed, default depth/step budget (unchanged, already bounded).

Looking for exactly three things when reading the trace afterward:
  1. Does the resulting structure help understand something genuinely.
  2. Does the investigation discover something unexpected.
  3. Does the model's framing become visibly strained or self-contradictory —
     the actual case #3 event this whole observation phase has been watching
     for (children push back on the original structural assumption).

After this session: stop observing, take the accumulated evidence from all
three real sessions, and decide the next actual engineering problem.
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

QUESTION_TEXT = "Why do some companies become dominant while others fail?"
ENTITY_NAME = "Company Dominance"
ABSTRACTION_NAME = "Business Outcomes"
RATIONALE = "Understanding what actually separates the businesses that end up dominating their market from the ones that don't."
DB_PATH = "session_dominant_companies.sqlite3"


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
