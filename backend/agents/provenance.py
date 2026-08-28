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


async def find_agent_id_by_question_id(question_id: str, *, db_path: str = DEFAULT_DB_PATH) -> Optional[str]:
    """Bridge from a Neo4j Question's id to the SQLite AgentState that resolved
    it (docs/Architecture.md §0.12+, "Pass 2" — re-pointing provenance onto the
    Model Graph without rewriting it). `Question.id` (backend/questions/models.py,
    a uuid set once at construction) is the SAME value in both stores — it's the
    identical Python object flowing into `AgentState.question` (SQLite) and
    `attach_question`'s `question_id` argument (Neo4j) — so no new id or schema
    is needed to connect them, just a lookup. Linear scan, not an indexed query:
    same pattern `find_root_agent_id` below already uses, fine for the small
    per-session databases this project has.
    """
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT agent_id, state_json FROM agent_state") as cursor:
            rows = await cursor.fetchall()
    for agent_id, state_json in rows:
        if AgentState.model_validate_json(state_json).question.id == question_id:
            return agent_id
    return None


async def trace_claim_from_entity(entity_name: str, *, db_path: str = DEFAULT_DB_PATH) -> list[ClaimProvenance]:
    """Start a provenance trace from a Neo4j entity instead of an already-known
    agent_id — the actual capability Pass 2 needed. Deliberately NOT a rewrite
    of `trace_claim`'s direct/derived/synthesized classification in Neo4j
    terms: that classification is a statement about how the agent investigated
    (child count), which by this project's own SQLite-vs-Neo4j split belongs on
    the investigation-trace side, not the world-model side. This is the bridge,
    not a reimplementation: find every Question Neo4j has attached to the
    entity, resolve each back to the SQLite investigation that produced it, and
    run the existing, completely unchanged `trace_claim` on each. No Neo4j
    schema change, no new relationship type, no new AgentState field.
    """
    from backend.graph import find_or_create_entity, get_questions_for_entity

    entity = await find_or_create_entity(entity_name)
    questions = await get_questions_for_entity(entity.id)

    traces: list[ClaimProvenance] = []
    for q in questions:
        agent_id = await find_agent_id_by_question_id(q.id, db_path=db_path)
        if agent_id is None:
            # Neo4j knows this question but this db_path's SQLite doesn't have
            # its investigation state — a different session/process/db_path
            # produced it. Not an error: skip, don't fabricate a trace.
            continue
        traces.append(await trace_claim(agent_id, db_path=db_path))
    return traces


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
