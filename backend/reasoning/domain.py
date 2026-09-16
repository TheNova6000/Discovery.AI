from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# R1.1 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.47/§0.49/§0.56): the core invariant this whole module exists to enforce
# STRUCTURALLY, not just document:
#
#     RetrievalOutcome != Evidence != Claim != Answer
#
# A retrieval failure must never be coercible into a Claim merely because it
# has text and a confidence-shaped number attached. This is not a hypothetical
# concern -- it is a real, observed bug in the existing pipeline: the real
# "How does DNS resolution work?" investigation (Architecture.md §0.47) has an
# entity, "Recursive Resolver," whose graph-persisted "claims" are, verbatim,
# 3 of 4: "The provided resource does not answer the question," "The resource
# does not answer the question," "The provided resource does not address DNS
# resolution or recursive resolvers." Those are retrieval outcomes, not
# propositions about DNS -- and the pre-R1 pipeline stored them as Claims with
# a confidence score anyway.
#
# Deliberately excluded from this module, per the explicit scope for R1.1
# (Phases.md): no event bus, no MasterAgent changes, no Neo4j read/write, no
# LLM/semantic extraction, no automatic deduplication, no full lifecycle
# orchestration, no API routes, no retrieval providers. These are pure
# domain representations with validation invariants -- they do not perform
# retrieval, call an LLM, query Neo4j, or publish an event. Dependency
# direction, enforced by this file having zero imports from any other
# backend package:
#
#     domain types (this file)
#         ^ pure validation / mapping (also this file: classify_retrieval_outcome,
#           reclassify_legacy_claim)
#         ^ application services (not built yet)
#         ^ agents / orchestration / API (existing backend.agents/backend.research/backend.api)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RetrievalOutcome(BaseModel):
    """What happened when a source/tool was actually used while trying to
    answer a question -- which source, what came back, whether it succeeded,
    whether it was relevant, and why not when it wasn't. NEVER a proposition
    about the world: a RetrievalOutcome has no `confidence`-about-the-subject
    field, because "this source wasn't relevant" isn't a claim that can be
    more or less true -- it's a fact about the retrieval attempt itself.
    """

    outcome_id: str = Field(default_factory=_new_id)
    question_id: str
    source_title: str
    source_url: str
    source_type: str
    success: bool
    relevant: bool
    failure_reason: Optional[str] = None
    raw_content: Optional[str] = None
    """What the source actually returned, prior to any relevance judgment --
    None when the retrieval itself failed (no response to hold content)."""
    retrieved_at: str = Field(default_factory=_now)

    @model_validator(mode="after")
    def _consistency(self) -> "RetrievalOutcome":
        if not self.success and self.relevant:
            raise ValueError("a failed retrieval cannot be marked relevant")
        if not self.success and not self.failure_reason:
            raise ValueError("a failed RetrievalOutcome must record why (failure_reason)")
        if self.success and not self.raw_content:
            raise ValueError("a successful RetrievalOutcome must carry raw_content")
        return self


class Evidence(BaseModel):
    """Material that CAN support or challenge a proposition. Existing does
    not mean it validly supports any particular Claim -- that judgment
    belongs to whichever Claim cites it (via `evidence_ids`), not to Evidence
    itself. Deliberately has no confidence field of its own (Architecture.md
    §0.49's five-way separation: confidence is a property of a Claim, not of
    the material a claim might be built from -- collapsing the two is
    exactly what let claim quality hide behind a policy's confidence
    threshold before this module existed).
    """

    evidence_id: str = Field(default_factory=_new_id)
    retrieval_outcome_id: str
    """Provenance back to the RetrievalOutcome this was extracted from --
    always required. Evidence is never constructed without a real retrieval
    attempt behind it (see classify_retrieval_outcome below, the only
    sanctioned constructor)."""
    excerpt: str = Field(min_length=1)
    source_title: str
    source_url: str
    source_type: str


ClaimStatus = Literal[
    "candidate",
    "normalized",
    "attached",
    "supported",
    "validated",
    "active",
    "rejected",
    "superseded",
    "disputed",
    "duplicate",
    "legacy_invalid_claim",
    "requires_reclassification",
]
"""The last two are migration-only statuses (Architecture.md §0.56): where an
old, pre-R1 graph object that was never a valid Claim in the first place
lands, so it can be inspected and eventually resolved -- never silently
promoted to "active" just because it has the Claim shape now."""


class Claim(BaseModel):
    """A proposition asserted about the world, sourced from Evidence. Not
    every claim fits a clean (subject, predicate, object) triple (causal,
    conditional claims) -- `normalized_form` is the one field every claim
    must resolve to regardless, for identity/deduplication (Architecture.md
    §0.50's deterministic floor) even when the structured fields don't apply.
    """

    claim_id: str = Field(default_factory=_new_id)
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    qualifiers: list[str] = Field(default_factory=list)
    modality: Optional[str] = None
    conditions: list[str] = Field(default_factory=list)
    normalized_form: str = Field(min_length=1)
    source_question_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: ClaimStatus = "candidate"
    superseded_by: Optional[str] = None
    duplicate_of: Optional[str] = None
    provenance_note: Optional[str] = None
    """Required whenever status explains an exception to the normal
    lifecycle (superseded/duplicate/legacy_invalid_claim/
    requires_reclassification) -- a status alone never has to be taken on
    faith; there is always a stated reason attached."""

    @model_validator(mode="after")
    def _status_consistency(self) -> "Claim":
        if self.status == "superseded" and not self.superseded_by:
            raise ValueError("a superseded claim must record superseded_by")
        if self.status == "duplicate" and not self.duplicate_of:
            raise ValueError("a duplicate claim must record duplicate_of")
        if self.status in ("legacy_invalid_claim", "requires_reclassification") and not self.provenance_note:
            raise ValueError(f"a {self.status!r} claim must record provenance_note explaining why")
        return self


class Answer(BaseModel):
    """A human-readable synthesis -- a PROJECTION of claims (Architecture.md
    §0.47's canonical-output principle), never the source of truth itself.
    `grounded` and `claim_ids` must agree: an answer citing claims IS
    grounded by definition, and a grounded answer must actually cite at
    least one -- no answer can silently claim authority with nothing behind
    it, and no answer can carry claim references while pretending it isn't
    making a grounded assertion.
    """

    answer_id: str = Field(default_factory=_new_id)
    text: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    grounded: bool

    @model_validator(mode="after")
    def _grounded_consistency(self) -> "Answer":
        if self.grounded and not self.claim_ids:
            raise ValueError("an Answer marked grounded=True must reference at least one claim")
        if not self.grounded and self.claim_ids:
            raise ValueError("an Answer referencing claims must be marked grounded=True")
        return self


def classify_retrieval_outcome(outcome: RetrievalOutcome) -> Optional[Evidence]:
    """The actual mechanism that enforces "a retrieval failure cannot become
    Evidence" -- not a comment, a function every caller must go through.
    Returns None for anything that wasn't a successful, relevant retrieval;
    never fabricates an Evidence object to paper over a failed attempt.
    """
    if not outcome.success or not outcome.relevant or not outcome.raw_content:
        return None
    return Evidence(
        retrieval_outcome_id=outcome.outcome_id,
        excerpt=outcome.raw_content,
        source_title=outcome.source_title,
        source_url=outcome.source_url,
        source_type=outcome.source_type,
    )


def reclassify_legacy_claim(
    *,
    raw_text: str,
    raw_confidence: float,
    source_question_id: str,
    reason: str,
) -> Claim:
    """The ONLY sanctioned way pre-R1 graph data enters this model
    (Architecture.md §0.56's migration-mapping discipline). Never lands as
    "active" or any other normal-lifecycle status -- always
    "requires_reclassification," with `provenance_note` stating why, so a
    later, deliberate migration rule (not this function) decides whether it
    becomes a real Claim, a RetrievalOutcome, or something else. This is
    what "no invalid old claim is silently laundered into a valid new
    claim" actually means as code, not just as a stated principle.
    """
    return Claim(
        normalized_form=raw_text.strip(),
        source_question_id=source_question_id,
        confidence=raw_confidence,
        status="requires_reclassification",
        provenance_note=reason,
    )
