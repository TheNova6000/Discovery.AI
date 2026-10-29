from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.main_block.research_engine.interface import RetrievedResource


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimDraft(BaseModel):
    """The only shape the LLM is asked to produce when synthesizing a `Claim` from
    one `RetrievedResource` (mirrors `QuestionDraft`/`GroundDecision`'s pattern in
    backend/main_block/reasoning_engine/llm_steps — the model never sets provenance fields like `question_id`
    or `source`, so those can't be hallucinated; the engine fills them in from the
    caller's actual arguments after generation).
    """

    evidence: str = Field(
        description="A concise, direct answer to the question, grounded only in the given resource."
    )
    reasoning: str = Field(
        description="One or two sentences on why (or why not) this resource supports that answer."
    )
    confidence: float = Field(
        description="0-1: how confident that this resource genuinely answers the question."
    )


class Claim(BaseModel):
    """A single evidence-backed answer to a Question (AgenticArchitecture.md §30,
    docs/Rules.md rule 4: every claim must carry evidence, confidence, and
    provenance). Assembled by the Evidence Engine from a `ClaimDraft` plus the
    `RetrievedResource` it came from — never constructed directly from raw LLM
    output.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_id: str
    evidence: str
    reasoning: str
    confidence: float
    source: RetrievedResource
    contradictions: list[str] = Field(default_factory=list)
    """Ids of other Claims this one contradicts — populated by Phase 7's conflict
    resolution, not by this phase; empty here is the honest default, not a gap."""
    valid_from: str = Field(default_factory=_now)
    superseded_by: Optional[str] = None
    """Graphiti-inspired valid-time/superseded pattern: a superseded Claim is kept,
    never deleted — this field just marks it non-current."""
