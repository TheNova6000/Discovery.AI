from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class CoverageStatus(str, Enum):
    """The full coverage ontology (Dewey Source Pack Experiment C.1,
    docs/Architecture.md §0.87) -- a contract for what "covered" can mean,
    written down BEFORE any semantic checker exists, per this project's own
    evaluate-before-build discipline. **No checker built as of this writing
    can honestly produce every value here** -- see
    `lexical_candidate_checker_v0.py`'s own module docstring for exactly
    which subset (`ABSENT`/`MENTIONED` only) a purely lexical checker is
    allowed to claim. `DEFINED` through `MISCONCEPTION_CORRECTED` require
    real semantic judgment and are reserved for a future v1+ checker -- they
    exist here now so that checker has a real target to be evaluated
    against, not so v0 can produce them.
    """

    ABSENT = "absent"
    """No meaningful treatment -- the concept doesn't appear, or every
    occurrence is inside a negated/excluded context."""

    MENTIONED = "mentioned"
    """The concept's name/keyword genuinely appears in the text, in a
    non-negated context -- a real, honestly lexical fact. Says nothing about
    whether the concept was actually explained. This is the ceiling of what
    `lexical_candidate_checker_v0` may ever output as a positive result."""

    DEFINED = "defined"
    """A meaning or definition is provided. Requires semantic judgment."""

    EXPLAINED = "explained"
    """A mechanism or relationship is described, not just named. Requires
    semantic judgment."""

    EXEMPLIFIED = "exemplified"
    """A concrete example is given. Requires semantic judgment."""

    BOUNDED = "bounded"
    """Limitations, conditions, or exceptions are stated. Requires semantic
    judgment."""

    CONTRASTED = "contrasted"
    """Distinguished from a related concept. Requires semantic judgment."""

    MISCONCEPTION_CORRECTED = "misconception_corrected"
    """A likely misunderstanding is explicitly addressed. Requires semantic
    judgment."""


LEXICAL_STATUSES: frozenset[CoverageStatus] = frozenset(
    {CoverageStatus.ABSENT, CoverageStatus.MENTIONED}
)
"""The only two values a purely lexical checker (any `checker` name starting
with `"lexical"`) may ever legitimately produce -- enforced structurally by
`ConceptCoverageResult`'s own validator below, not left as a convention a
future checker or downstream reader could quietly violate. A reviewer's own
explicit concern (2026-09-17): "make sure the shared checker's output is
impossible to misread downstream ... even if the current implementation is
correct, a later evaluator could accidentally treat MENTIONED as completed
coverage." This constant plus `ConceptCoverageResult.semantically_verified`
are the two concrete answers to that concern."""


class CoverageEvidence(BaseModel):
    """One real reason behind a coverage verdict -- a caller never has to
    take `status` on faith, the same "reason" discipline
    `backend.research.models.FieldCoverage` already established for a
    genuinely different axis (Phase 8.3's own per-entity field completeness,
    see this package's own `__init__.py` for why this is a separate, not a
    duplicate, concern)."""

    claim_id: Optional[str] = None
    text_span: str
    reason: str


class ConceptCoverageRequirement(BaseModel):
    """What "covered" means FOR THIS CONCEPT, in this use case -- a real,
    deliberate product decision (per the design conversation's own
    instruction: "that should be a deliberate product decision, not hidden
    inside a checker"), not something a checker infers on its own. E.g. a
    beginner C++ path might require `defined and explained and exemplified`;
    a reference-page audit might require only `defined`."""

    concept: str
    require_defined: bool = False
    require_explained: bool = False
    require_exemplified: bool = False
    require_bounded: bool = False
    require_contrasted: bool = False
    require_misconception_corrected: bool = False


class ConceptCoverageResult(BaseModel):
    """One checker's real verdict for one concept against one body of text.
    `checker` names which real implementation produced this (e.g.
    `"lexical-candidate-v0"`) -- a result's own honesty depends on knowing
    which checker's real, stated capability produced it, per this whole
    package's founding finding (Experiment C: a checker's positive claims
    are only as trustworthy as its own measured precision)."""

    concept: str
    status: CoverageStatus
    evidence: list[CoverageEvidence] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    checker: str

    @model_validator(mode="after")
    def _lexical_checker_cannot_claim_semantic_status(self) -> "ConceptCoverageResult":
        """Structural enforcement, not just a docstring promise: a checker
        whose own name says "lexical" is physically prevented from
        constructing a result claiming `DEFINED`/`EXPLAINED`/etc -- the
        exact accident a downstream evaluator could otherwise make (treating
        `MENTIONED` as "covered") is caught one level earlier, at the
        checker itself, the moment it would try to overclaim."""
        if self.checker.startswith("lexical") and self.status not in LEXICAL_STATUSES:
            raise ValueError(
                f"checker {self.checker!r} claimed status {self.status!r}, "
                f"but a lexical checker may only ever produce {sorted(s.value for s in LEXICAL_STATUSES)}"
            )
        return self

    @property
    def semantically_verified(self) -> bool:
        """True only for a status that required real semantic judgment to
        produce (`DEFINED` and beyond) -- always `False` for `ABSENT` or
        `MENTIONED`, regardless of which checker produced the result.
        Downstream code (a course-completeness check, a learner-facing
        "covered" badge, anything that matters) should read THIS, never
        `status != CoverageStatus.ABSENT`, to decide whether a concept is
        genuinely known to be covered."""
        return self.status not in (CoverageStatus.ABSENT, CoverageStatus.MENTIONED)
