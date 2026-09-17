from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Phase 10 (docs/Phases.md, docs/PRD.md §9.6.3, docs/Rules.md rules 16/19):
# Lesson Authoring's own types -- a projection over a real, already-compiled
# `dewey.curriculum.Module` (Phase 9.1), never a rewrite of it.
# `backend/dewey/lessons` itself never calls an LLM (that stays confined to
# `backend/questions`, Rules.md rule 2) -- this module only defines the shape.


class LessonSentence(BaseModel):
    """One atomic proposition from the composed explanation, with its real
    traceability verdict from `audit_synthesis` (Post-Phase-5 epistemic
    layer, reused unchanged per Rules.md rule 19 -- not a new trust
    mechanism)."""

    text: str
    origin: Literal["investigated", "uninvestigated"]


class Lesson(BaseModel):
    """`compile_lesson`'s (compiler.py) real output. `status` distinguishes a
    genuinely composed-and-audited lesson from the one real, expected case
    where composition never happens at all -- a module with zero real claims
    (Rules.md rule 9's "empty must be distinguishable from unknown," applied
    here rather than fabricating a lesson from nothing)."""

    entity_id: str
    entity_name: str
    status: Literal["composed", "insufficient_claims"]
    explanation: str = ""
    """The composed explanation text. Empty when status=="insufficient_claims"
    -- never a placeholder sentence standing in for real content."""
    examples: list[str] = Field(default_factory=list)
    sentences: list[LessonSentence] = Field(default_factory=list)
    """Every atomic proposition of `explanation`, each independently audited.
    Empty when status=="insufficient_claims" (nothing was ever composed to
    audit)."""
    fully_traceable: Optional[bool] = None
    """True iff every sentence in `sentences` audited as "investigated" --
    None (not False) when status=="insufficient_claims", since "not fully
    traceable" and "never composed at all" are different, real facts (Rules.md
    rule 9's honesty discipline again: a lesson that was never attempted is
    not the same as one that was attempted and found partially ungrounded)."""
    source_claim_ids: list[str] = Field(default_factory=list)
    """The real `Claim.claim_id`s this lesson was composed from -- identity
    preserved, never a copy or a re-synthesized claim shape."""
