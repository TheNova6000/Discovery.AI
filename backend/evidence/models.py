from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RetrievedResource(BaseModel):
    """One real result from a retriever (docs/Phases.md Phase 5) — a paper, book,
    web page, or video that might answer a Question. Whatever the source's own API
    returns is normalized into this shape; nothing here is LLM-generated.
    """

    title: str
    url: str
    snippet: str = ""
    source_type: str  # "web" | "paper" | "book" | "video" | "code"
    published: Optional[str] = None
    retrieved_at: str = Field(default_factory=_now)
    source_role: Optional[str] = None
    """Dewey Source Pack research (docs/Memory.md, 2026-09-17): what KIND of
    evidence this retriever structurally produces -- "entity_discovery" /
    "explanation" / "technical_reference" / "implementation" / "evidence" /
    "reference". A fixed, honest property of the retriever itself (e.g. GitHub
    results are always "implementation"), never an LLM guess per result. `None`
    for any retriever that hasn't been classified yet -- an old value reading
    back as `None`, not a fabricated default, per this project's own established
    "empty must be distinguishable from unknown" discipline."""
    acquisition_mode: Optional[str] = None
    """How this resource was actually obtained: "api" (a real, documented,
    officially-sanctioned API call) / "controlled_document" (a small, curated,
    individually-verified set of known pages, not free-text search over an
    entire site) / "archive" (a downloaded, officially-distributed bulk archive,
    no live request per lookup). Recorded so a caller can tell a live API result
    apart from a fetch against a small, hand-verified page list -- these are not
    the same kind of evidence, even when they end up in the same list."""


class ClaimDraft(BaseModel):
    """The only shape the LLM is asked to produce when synthesizing a `Claim` from
    one `RetrievedResource` (mirrors `QuestionDraft`/`GroundDecision`'s pattern in
    backend/questions — the model never sets provenance fields like `question_id`
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
