"""Unit test for `trace_claim`/`find_root_agent_id` (docs/Memory.md's provenance
workstream). Zero LLM calls, zero Neo4j — constructs a synthetic AgentState tree
directly via the SQLite state store and asserts the structural classification
(direct/derived/synthesized/unresolved) is correct, before ever pointing the tool
at a real session's data.

Tree shape under `root` (2 children -> synthesized):
    root
    ├── child_a (1 child -> derived)
    │   └── grandchild (0 children, has evidence -> direct)
    └── child_b (0 children, no evidence -> direct)

Plus a separate, unrelated root (`boundary_root`) that is a bare boundary hit with
no children, to check the "unresolved" case.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents import ClaimProvenance, find_root_agent_id, trace_claim  # noqa: E402
from backend.agents.models import AgentState, AgentStatus, GroundResult  # noqa: E402
from backend.evidence.models import Claim, RetrievedResource  # noqa: E402
from backend.questions.models import Question, QuestionLevel  # noqa: E402
from backend.runtime import init_db, save_state  # noqa: E402

DB_PATH = "scratch_verify_trace_claim.sqlite3"


def _question(text: str) -> Question:
    return Question(
        text=text,
        rationale="test fixture",
        dimension_id="none",
        level=QuestionLevel.GROUND,
        entity_name="Test Entity",
        abstraction_name="Test Abstraction",
    )


async def _write(agent_id: str, *, parent_id: str | None, children: list[str], result: GroundResult) -> None:
    state = AgentState(
        agent_id=agent_id,
        parent_id=parent_id,
        question=_question(f"question for {agent_id}"),
        depth=0,
        max_depth=2,
        status=result.status,
        children=children,
        result=result,
    )
    await save_state(agent_id, state.model_dump_json(), state.updated_at, db_path=DB_PATH)


async def run() -> None:
    pathlib.Path(DB_PATH).unlink(missing_ok=True)
    await init_db(db_path=DB_PATH)

    evidence_claim = Claim(
        question_id="grandchild",
        evidence="Test evidence text.",
        reasoning="Directly answers the test question.",
        confidence=0.9,
        source=RetrievedResource(title="Test Source", url="https://example.com", source_type="web"),
    )

    # Leaves first (children must exist before a parent references them, though
    # trace_claim itself doesn't require write order — this just mirrors how a
    # real run would checkpoint children before the parent).
    await _write(
        "grandchild",
        parent_id="child_a",
        children=[],
        result=GroundResult(status=AgentStatus.COMPLETE, answer="Grandchild answer.", confidence=0.9, claims=[evidence_claim]),
    )
    await _write(
        "child_b",
        parent_id="root",
        children=[],
        result=GroundResult(status=AgentStatus.COMPLETE, answer="Child B answer.", confidence=0.8),
    )
    await _write(
        "child_a",
        parent_id="root",
        children=["grandchild"],
        result=GroundResult(status=AgentStatus.COMPLETE, answer="Child A answer, built on grandchild.", confidence=0.85),
    )
    await _write(
        "root",
        parent_id=None,
        children=["child_a", "child_b"],
        result=GroundResult(status=AgentStatus.COMPLETE, answer="Root synthesis of A and B.", confidence=0.95),
    )
    await _write(
        "boundary_root",
        parent_id=None,
        children=[],
        result=GroundResult(status=AgentStatus.BOUNDARY_HIT, boundary_reason="test boundary"),
    )

    failures: list[str] = []

    def check(label: str, condition: bool) -> None:
        status = "ok" if condition else "FAIL"
        print(f"[{status}] {label}")
        if not condition:
            failures.append(label)

    # This DB deliberately has two top-level agents (root, boundary_root), so
    # find_root_agent_id's "exactly one root" invariant is checked separately,
    # below, as an expected-failure case — trace_claim itself is called directly
    # by agent_id here instead.
    root_trace: ClaimProvenance = await trace_claim("root", db_path=DB_PATH)
    check("root classified as synthesized (2 children)", root_trace.provenance_type == "synthesized")
    check("root has 2 derived_from entries", len(root_trace.derived_from) == 2)

    child_a_trace = next(c for c in root_trace.derived_from if c.agent_id == "child_a")
    check("child_a classified as derived (1 child)", child_a_trace.provenance_type == "derived")

    grandchild_trace = child_a_trace.derived_from[0]
    check("grandchild classified as direct (0 children)", grandchild_trace.provenance_type == "direct")
    check("grandchild carries its evidence claim", len(grandchild_trace.evidence) == 1)
    check(
        "grandchild's evidence is the actual Claim object",
        grandchild_trace.evidence[0].evidence == "Test evidence text.",
    )

    child_b_trace = next(c for c in root_trace.derived_from if c.agent_id == "child_b")
    check("child_b classified as direct (0 children, answered)", child_b_trace.provenance_type == "direct")
    check("child_b has no evidence (none was attached)", len(child_b_trace.evidence) == 0)

    boundary_trace = await trace_claim("boundary_root", db_path=DB_PATH)
    check("boundary_root classified as unresolved", boundary_trace.provenance_type == "unresolved")
    check("boundary_root has no answer", boundary_trace.answer is None)

    raised = False
    try:
        await find_root_agent_id(DB_PATH)
    except Exception:
        raised = True
    check("find_root_agent_id raises when >1 true root exists (root + boundary_root)", raised)

    pathlib.Path(DB_PATH).unlink(missing_ok=True)

    if failures:
        print(f"\n{len(failures)} check(s) FAILED: {failures}")
        raise SystemExit(1)
    print("\nAll trace_claim checks PASSED.")


if __name__ == "__main__":
    asyncio.run(run())
