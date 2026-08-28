"""Ad-hoc research pass — empirical revision-signal battery (docs/Memory.md). Not
a numbered Phases.md deliverable; a diagnostic, not a feature.

Purpose: before writing any "should this decomposition be kept, collapsed, or
restructured?" mechanism, find out whether the CURRENT system's investigation
already produces enough information to make that judgment — or whether new
machinery (an explicit coupling signal) is actually needed. We are not grading
right/wrong answers here. We're reading whether the raw investigation trace (the
sequence of sub-questions actually chosen and their answers) gives a human — or a
future synthesis step — enough to say "these parts turned out independent" vs.
"these parts turned out entangled."

Deliberately no `gather_evidence` (keep this fast, no external API calls) and no
`persist_to_graph` (this is pure observation of already-verified investigation
machinery, not a session whose structure is worth keeping — consistent with the
project's own "session is a playground, persistence is a decision" principle).

Three cases, chosen to plausibly land in three different buckets:

  STAY                 "How does a website request travel through the Internet?"
                        Expected: DNS / TCP-TLS / routing are genuinely
                        independently-investigable mechanisms.

  COLLAPSE              "Why does money have value?"
                        Expected: economic/psychological/historical/institutional
                        facets of one phenomenon, not separable mechanisms.

  RESTRUCTURE-CANDIDATE "How does PayPal work?"
                        Expected: ambiguous — PayPal is simultaneously a company,
                        a technical platform, and a network participant, and the
                        "right" decomposition depends on which of those the
                        investigation actually follows.

The rationale strings are deliberately neutral, ordinary framings of each
question — NOT hints about this being a revision/collapse experiment. Question
rationale text is included verbatim in decide_next_step's prompt
(backend/questions/decision.py's "Rationale it was asked" line), and an earlier
pass in this project (verify_dimension_steering.py) found that a meta-flavored
rationale leaks straight into the model's reasoning and contaminates the result.
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

CASES = [
    (
        "STAY",
        "How does a website request travel through the Internet?",
        "Internet Infrastructure",
        "Website Request",
        "Understanding the technical path data takes from a browser to a server and back.",
    ),
    (
        "COLLAPSE",
        "Why does money have value?",
        "Economic Systems",
        "Money",
        "Understanding why paper and digital currency function as accepted stores of value.",
    ),
    (
        "RESTRUCTURE-CANDIDATE",
        "How does PayPal work?",
        "Payment Systems",
        "PayPal",
        "Understanding what PayPal actually is and how it functions.",
    ),
]


async def _dump_tree(agent_id: str, db_path: str, indent: int = 0) -> None:
    raw = await load_state(agent_id, db_path=db_path)
    state = AgentState.model_validate_json(raw)
    pad = "  " * indent
    q = state.question
    print(f"{pad}[{q.level.value}] {q.text}")
    if state.result is not None:
        if state.result.status == AgentStatus.COMPLETE:
            print(f"{pad}   -> answer ({state.result.confidence}): {state.result.answer}")
        elif state.result.status == AgentStatus.BOUNDARY_HIT:
            print(f"{pad}   -> boundary_hit: {state.result.boundary_reason}")
        else:
            print(f"{pad}   -> status: {state.result.status.value}")
    for child_id in state.children:
        await _dump_tree(child_id, db_path, indent + 1)


async def _run_case(label: str, text: str, abstraction: str, entity: str, rationale: str) -> None:
    db_path = f"scratch_revision_{label.lower().replace('-', '_')}.sqlite3"
    pathlib.Path(db_path).unlink(missing_ok=True)

    question = Question(
        text=text,
        rationale=rationale,
        dimension_id="none",
        level=QuestionLevel.MASTER,
        entity_name=entity,
        abstraction_name=abstraction,
    )
    agent = GroundAgent(question, db_path=db_path)

    print("\n" + "=" * 70)
    print(f"CASE: {label} — {text}")
    print("=" * 70)
    await agent.run()

    print("\n--- full investigation tree ---")
    await _dump_tree(agent.agent_id, db_path)

    pathlib.Path(db_path).unlink(missing_ok=True)


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    for label, text, abstraction, entity, rationale in CASES:
        await _run_case(label, text, abstraction, entity, rationale)

    print("\n" + "=" * 70)
    print("Read each tree above. For each case, ask:")
    print("  - Do the sub-questions read as independent mechanisms, or as")
    print("    interacting facets of one thing?")
    print("  - Does the final synthesized answer (at the root) ITSELF ever")
    print("    say something like 'these turned out to be the same underlying")
    print("    thing' — i.e. does today's system already produce that signal")
    print("    in prose, just not as a structured decision?")
    print("  - Or is the signal simply absent — the tree completes and reports")
    print("    an answer with no view at all on whether its own structure was")
    print("    the right one?")
    print("That distinction determines what dynamic abstraction revision")
    print("actually needs to build: a NEW judgment call, or a way to SURFACE")
    print("and ACT ON a judgment the system already implicitly makes.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
