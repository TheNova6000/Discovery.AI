from __future__ import annotations

from typing import Literal, Optional

import aiosqlite
from pydantic import BaseModel, Field

from backend.evidence import Claim
from backend.runtime import load_state
from backend.runtime.state_store import DEFAULT_DB_PATH

from .exceptions import AgentError
from .models import AgentState, AgentStatus

ProvenanceType = Literal["direct", "derived", "synthesized", "unresolved"]


class ClaimProvenance(BaseModel):
    """The derivation tree behind one resolved question's answer (docs/Memory.md's
    provenance workstream, opened by the epistemic-synthesis investigation —
    Architecture.md §0.2). Classified purely from the AgentState/GroundResult tree
    every run already persists (Rules.md rule 7) — zero new LLM calls, zero Neo4j
    writes. Deliberately built against the existing SQLite state store first, not
    Neo4j edges: the open question was whether the SEMANTICS are right, not where
    to store them.

    Classification is structural (child count), not a content/novelty judgment:
    - "direct": 0 children — answered without decomposing, optionally backed by
      gathered evidence (see `evidence`).
    - "derived": exactly 1 child — this answer narrows/builds on one investigated
      sub-question.
    - "synthesized": 2+ children — this answer combines multiple investigated
      branches.
    - "unresolved": boundary hit, or no result persisted yet — nothing to trace.

    Deliberately does NOT attempt to verify that `answer`'s actual content is
    fully backed by `derived_from` — that would require claim/concept-level
    content comparison (an open design problem, not sentence-string matching per
    the "legitimate synthesis is still synthesis" caution in Memory.md), not
    something inferable from tree shape alone. A "derived" node whose answer talks
    about far more than its one child investigated is a real, structurally
    visible gap once traced — the tool exposes the derivation graph faithfully;
    noticing that gap is a human/downstream judgment, same as it was when this
    was first spotted by hand in Session 2's raw trace.
    """

    agent_id: str
    question_text: str
    provenance_type: ProvenanceType
    answer: Optional[str] = None
    confidence: Optional[float] = None
    evidence: list[Claim] = Field(default_factory=list)
    derived_from: list["ClaimProvenance"] = Field(default_factory=list)


ClaimProvenance.model_rebuild()


async def trace_claim(agent_id: str, *, db_path: str = DEFAULT_DB_PATH) -> ClaimProvenance:
    """Walk the persisted AgentState tree rooted at `agent_id` and classify how its
    answer was derived. Read-only.
    """
    raw = await load_state(agent_id, db_path=db_path)
    if raw is None:
        raise AgentError(f"trace_claim: agent {agent_id} has no persisted state in {db_path}")
    state = AgentState.model_validate_json(raw)

    derived_from = [await trace_claim(child_id, db_path=db_path) for child_id in state.children]

    if state.result is None or state.result.status == AgentStatus.BOUNDARY_HIT:
        provenance_type: ProvenanceType = "unresolved"
    elif len(derived_from) == 0:
        provenance_type = "direct"
    elif len(derived_from) == 1:
        provenance_type = "derived"
    else:
        provenance_type = "synthesized"

    return ClaimProvenance(
        agent_id=state.agent_id,
        question_text=state.question.text,
        provenance_type=provenance_type,
        answer=state.result.answer if state.result else None,
        confidence=state.result.confidence if state.result else None,
        evidence=state.result.claims if state.result else [],
        derived_from=derived_from,
    )


async def find_root_agent_id(db_path: str) -> str:
    """Convenience for exploration/replay: the one AgentState in `db_path` with no
    parent. Every real session so far has exactly one true root; raises rather
    than silently guessing if that invariant doesn't hold.
    """
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT state_json FROM agent_state") as cursor:
            rows = await cursor.fetchall()

    roots = [
        AgentState.model_validate_json(state_json).agent_id
        for (state_json,) in rows
        if AgentState.model_validate_json(state_json).parent_id is None
    ]

    if len(roots) != 1:
        raise AgentError(f"find_root_agent_id: expected exactly 1 root in {db_path}, found {len(roots)}")
    return roots[0]
