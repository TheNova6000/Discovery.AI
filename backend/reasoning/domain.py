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
    question_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
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
    retrieval_outcome_id: str = Field(min_length=1)
    """Provenance back to the RetrievalOutcome this was extracted from --
    always required. Evidence is never constructed without a real retrieval
    attempt behind it (see classify_retrieval_outcome below, the only
    sanctioned constructor)."""
    excerpt: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_type: str = Field(min_length=1)


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
    entity_id: str = Field(min_length=1)
    """R1.3 addition (Architecture.md §0.50/§0.60): required, not optional --
    identity_floor below is meaningless without it. Two claims with
    identical normalized_form about DIFFERENT entities must never collide
    as "the same claim" just because their text happens to match."""
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None
    qualifiers: list[str] = Field(default_factory=list)
    modality: Optional[str] = None
    conditions: list[str] = Field(default_factory=list)
    normalized_form: str = Field(min_length=1)
    source_question_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: ClaimStatus = "candidate"
    superseded_by: Optional[str] = None
    duplicate_of: Optional[str] = None
    provenance_note: Optional[str] = None
    """R1.4 (Architecture.md §0.61): required for EVERY status except the
    initial `"candidate"` default -- generalized from R1.1's narrower "only
    the exception statuses need a reason" rule. Every claim that has moved
    anywhere in its lifecycle carries an explicit, stated reason for being
    there; a status is never just a label taken on faith. Set by
    `transition_claim` below, not hand-assigned alongside a status change."""
    last_transition_actor: Optional[str] = None
    """R1.4: who/what performed the most recent transition (e.g. a specific
    validator, "human_reviewer", a migration script name) -- a single,
    most-recent record, not a full audit log (matching this module's
    existing minimalism: `superseded_by`/`duplicate_of` are single
    references too, not lists)."""

    @model_validator(mode="after")
    def _status_consistency(self) -> "Claim":
        if self.status == "superseded" and not self.superseded_by:
            raise ValueError("a superseded claim must record superseded_by")
        if self.status == "duplicate" and not self.duplicate_of:
            raise ValueError("a duplicate claim must record duplicate_of")
        if self.status != "candidate" and not self.provenance_note:
            raise ValueError(f"a {self.status!r} claim must record provenance_note explaining why (R1.4 generalization)")
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
    entity_id: str,
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
        entity_id=entity_id,
        normalized_form=raw_text.strip(),
        source_question_id=source_question_id,
        confidence=raw_confidence,
        status="requires_reclassification",
        provenance_note=reason,
    )


# R1.3 (docs/Phases.md, Architecture.md §0.50/§0.60): the two-tier identity
# model as real, callable functions -- not just fields sitting unused on
# Claim. Both are pure; neither does any I/O, matching every function in
# this module.

IdentityFloor = tuple[str, str, str]
SemanticIdentity = tuple[str, str, str, tuple[str, ...]]


def identity_floor(claim: Claim) -> IdentityFloor:
    """The mandatory, always-available deterministic floor (Architecture.md
    §0.50): (entity_id, source_question_id, normalized_form). Never raises,
    never returns partial/missing data -- every Claim has all three fields
    by construction (all required on the model). This is the real
    generalization of Phase 8.5's `assess_claim_validity` duplicate
    detection (exact source_url / exact evidence-text match) into the R1
    domain model -- same floor-first philosophy, now a named, reusable
    function instead of inline comparison logic.
    """
    return (claim.entity_id, claim.source_question_id, claim.normalized_form)


def semantic_identity(claim: Claim) -> Optional[SemanticIdentity]:
    """The optional, additive layer (Architecture.md §0.50): (subject,
    predicate, object, qualifiers) -- returned ONLY when all three of
    subject/predicate/object are set. Returns None otherwise, meaning
    "unknown," never a partially-filled or guessed tuple -- a claim with a
    subject but no predicate does not get a semantic identity with `None`
    silently standing in for the missing piece.
    """
    if claim.subject is None or claim.predicate is None or claim.object is None:
        return None
    return (claim.subject, claim.predicate, claim.object, tuple(claim.qualifiers))


def is_likely_duplicate(claim_a: Claim, claim_b: Claim) -> bool:
    """Deterministic-floor-based duplicate check -- the actual comparison
    function R4's claim-lifecycle work (docs/Phases.md) will consume to
    decide whether to mark a claim `status="duplicate"`. R1.3 defines the
    comparison only; it does not itself change any claim's status (no
    lifecycle transitions here -- that's explicitly R1.4/R4's job, not
    this function's). Two claims about different entities are never
    duplicates of each other regardless of text, by construction
    (identity_floor includes entity_id).
    """
    return identity_floor(claim_a) == identity_floor(claim_b)


# R1.4 (docs/Phases.md, Architecture.md §0.61): pure claim lifecycle
# transitions. The question this section answers, verbatim from the scoping
# that shaped it: "given a Claim object, which statuses may it move
# between, and what conditions are required?" -- not orchestration, not
# automatic validation, not an LLM/Neo4j-driven decision about WHEN to
# transition. transition_claim never reads `confidence` at all -- status is
# an explicit fact someone asserts with a reason, never a threshold
# derived from a number (the exact R0 problem this whole track exists to
# prevent, recreated one layer up if status were confidence-gated here).
#
# "active" means EPISTEMICALLY active (Option A, not B): a claim currently
# accepted as part of the investigation's own knowledge state. Not "the
# Portal is using it" -- a downstream consumer filtering claims for its own
# purpose is that consumer's concern, not a fact about the claim itself.
#
# Deliberately not implemented, per explicit scope: every theoretically
# possible transition (only the ones below are legal), any automatic
# transition triggered by an LLM/retriever/confidence value, any
# transition-history log beyond the single most-recent
# provenance_note/last_transition_actor, any Neo4j persistence of a
# transition, any event publication (that's the bus, R2).

_LEGAL_TRANSITIONS: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    "candidate": frozenset({"normalized", "rejected", "requires_reclassification"}),
    "normalized": frozenset({"supported", "duplicate", "disputed"}),
    "supported": frozenset({"validated", "superseded"}),
    "validated": frozenset({"active", "disputed"}),
    "active": frozenset({"superseded", "disputed"}),
    # No legal outgoing transition defined yet for these -- not because one
    # could never exist, but because inventing it now would be exactly the
    # "implement every possible transition before the meanings are proven"
    # mistake this phase was explicitly scoped to avoid.
    "attached": frozenset(),
    "rejected": frozenset(),
    "duplicate": frozenset(),
    "disputed": frozenset(),
    "superseded": frozenset(),
    "legacy_invalid_claim": frozenset(),
    "requires_reclassification": frozenset(),
}


class ClaimTransitionRejected(Exception):
    """Raised by transition_claim for any illegal transition or any legal
    transition missing a required condition -- never a bare `None` a caller
    could forget to check, and never a silent no-op."""


def transition_claim(
    claim: Claim,
    target_status: ClaimStatus,
    *,
    reason: str,
    actor: str,
    superseded_by: Optional[str] = None,
    duplicate_of: Optional[str] = None,
) -> Claim:
    """Pure: returns a NEW Claim with the transition applied (claims are
    treated as immutable here -- `claim` itself is never mutated), or
    raises ClaimTransitionRejected. Calls no LLM, queries no Neo4j,
    retrieves no evidence, publishes no event, and reads `claim.confidence`
    nowhere in this function -- status is asserted by `reason`/`actor`, not
    derived from a number.
    """
    if not reason.strip():
        raise ClaimTransitionRejected("a transition always requires a non-empty reason")
    if not actor.strip():
        raise ClaimTransitionRejected("a transition always requires a non-empty actor")

    legal_targets = _LEGAL_TRANSITIONS.get(claim.status, frozenset())
    if target_status not in legal_targets:
        raise ClaimTransitionRejected(
            f"{claim.status!r} -> {target_status!r} is not a legal transition "
            f"(legal targets from {claim.status!r}: {sorted(legal_targets) or 'none'})"
        )

    if target_status == "superseded" and not superseded_by:
        raise ClaimTransitionRejected("transitioning to 'superseded' requires superseded_by")
    if target_status == "duplicate" and not duplicate_of:
        raise ClaimTransitionRejected("transitioning to 'duplicate' requires duplicate_of")
    if target_status == "supported" and not claim.evidence_ids:
        raise ClaimTransitionRejected("transitioning to 'supported' requires at least one evidence_id already present on the claim")

    updates: dict = {"status": target_status, "provenance_note": reason, "last_transition_actor": actor}
    if superseded_by is not None:
        updates["superseded_by"] = superseded_by
    if duplicate_of is not None:
        updates["duplicate_of"] = duplicate_of
    # Constructed via Claim(...), not claim.model_copy(update=...) -- model_copy
    # does NOT re-run validators, so it could silently produce a Claim that
    # violates _status_consistency if this function's own checks above ever
    # drifted out of sync with that validator. Re-validating through the
    # constructor makes the model's own invariant the actual source of
    # truth, not a second, hand-maintained copy of the same logic.
    return Claim(**{**claim.model_dump(), **updates})
