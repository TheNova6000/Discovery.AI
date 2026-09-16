from __future__ import annotations

from backend.graph.models import ClaimNode
from backend.reasoning import Claim

# R4.1 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.66/§0.67): the pure bridge R4.0's audit found missing -- nothing anywhere
# converts a persisted backend.graph.models.ClaimNode into a
# backend.reasoning.domain.Claim. Pure representation conversion only: no
# network/LLM/database/LangGraph call, no global mutable state, never mutates
# `node`, never mutates the returned Claim after construction (it's a pydantic
# model built once via the constructor, same immutability convention as every
# other Claim-producing function in backend.reasoning).
#
# Deliberately NOT in backend/reasoning/ -- that package has zero imports from
# any other backend package (R1.1's dependency-direction guarantee, reconfirmed
# by every R1/R2/R3 slice's own verify script), and this function necessarily
# imports ClaimNode. backend/research/ already imports ClaimNode (validation.py)
# and is the layer R4.1's own objective names ("the existing claim
# representation used by the research/validation system") -- this is the first
# time backend.research imports backend.reasoning, a new one-way edge (reasoning
# has zero imports from research; no cycle), the same shape as R3.2's
# backend.agents -> backend.reasoning addition.


class ClaimMappingRejected(Exception):
    """Raised for a mapping-logic-level rejection: an empty/whitespace-only
    proposition text, or an empty caller-supplied entity_id/source_question_id.
    Genuine field-validity issues on the constructed Claim (should any exist
    beyond what this function pre-checks) are left to `Claim`'s own
    pydantic.ValidationError, the same split `transition_claim` (R1.4) already
    uses between its own logic-level ClaimTransitionRejected and the model's
    own validator."""


def claim_node_to_domain_claim(
    node: ClaimNode,
    *,
    entity_id: str,
    source_question_id: str,
) -> Claim:
    """The one sanctioned forward mapping from a persisted `ClaimNode` to a
    `reasoning.domain.Claim`. `entity_id`/`source_question_id` are required
    caller-supplied arguments, not derived from `node` -- a `ClaimNode` alone
    does not carry either (they come from the graph traversal that fetched
    it: which entity's question was this attached to). Never fabricate them
    as "unknown" -- a caller without real values has nothing safe to map.

    **What `node.evidence` actually is (confirmed against the real
    production path, not assumed from its name, per the R4.1-review pass):**
    `ClaimDraft.evidence` (backend/evidence/models.py) is documented at its
    own definition as "a concise, direct answer to the question, grounded
    only in the given resource" -- the model's own synthesized PROPOSITION,
    not a verbatim excerpt copied from the source. `engine.py`'s
    `gather_evidence_with_outcomes` uses this exact same string for two
    purposes: it becomes `RetrievalOutcome.raw_content` (line ~72) AND,
    unchanged, `Claim.evidence` (line ~148) -- so the one and only production
    path that ever creates a `ClaimNode` (`ground_agent.py`'s `attach_claim`
    call, `evidence=claim.evidence`) confirms `ClaimNode.evidence` IS the
    asserted proposition text, despite its legacy field name. Mapping it to
    `normalized_form` (this model's own "canonical text form... the
    proposition asserted about the world") is therefore correct, not a
    guess -- and mapping it to an `Evidence.excerpt` instead would have been
    WRONG: that same text is the model's own synthesis, not independently-
    checkable raw material, so treating it as Evidence would conflate
    claim-content with evidence-content, exactly what R1.1 was built to
    stop doing (§0.49).

    Every mapped claim lands at status="requires_reclassification",
    unconditionally -- NOT because `node` is assumed invalid, but because
    `ClaimNode` carries no R1-lifecycle status information to preserve at
    all (only a binary superseded_by-or-not fact, copied through separately
    below). This is the same sanctioned status `reclassify_legacy_claim`
    (R1.1) already uses for exactly this situation: real, persisted data
    that has never been run through this model's own validation, evidence-
    sufficiency, or duplicate checks. No confidence-based promotion, no
    "high confidence therefore active" shortcut -- Rule B (R4.1's own scope):
    confidence is never a substitute for lifecycle status here either.

    **This is a uniform non-promotion safeguard, NOT retrieval-failure
    detection -- stated precisely, not conflated (R4.1-review's own
    finding):** this function has no way to tell a genuine weak claim apart
    from a retrieval-failure-shaped `ClaimNode` using `node`'s fields alone
    (that distinction lived in `RetrievalOutcome`, which is never persisted
    for a `ClaimNode` -- R0's own unrecoverable finding). It does not
    attempt to; every input, regardless of shape, lands at the identical
    `"requires_reclassification"` status, which is what actually prevents a
    disguised retrieval failure from ever being promoted -- a structural
    guarantee, not a classification the mapper is entitled to claim it made.

    Lossy by design, not by oversight -- `node.reasoning`, `node.source_title`,
    `node.source_url`, `node.source_type`, and `node.valid_from` are NOT
    copied onto the result. `reasoning.domain.Claim` has no field for raw
    source/reasoning text (that belongs on `Evidence`, a separate object this
    function deliberately does not construct: `node` carries no
    `retrieval_outcome_id` because no RetrievalOutcome was ever persisted
    behind it -- inventing one, or synthesizing an `Evidence` object from
    flat source fields, would be exactly the "ClaimNode.sources -> Evidence()
    without evidence validation" fabrication this slice's own review
    explicitly warns against. `evidence_ids` is left empty; a real Evidence
    bridge, if ever built, is separate, later work, not this mapper's job.

    **This loss is recoverable, not permanent (R4.1-review's answer to
    "where does provenance survive"):** `claim_id` is reused UNCHANGED from
    `node.id` (never regenerated), so any later step holding the mapped
    `Claim` can always re-fetch the exact original `ClaimNode` -- and every
    field this function drops -- by that same id. Provenance is not carried
    on the in-memory domain object, but nothing is deleted from the graph;
    `get_claims_for_question`/direct lookup remains the recovery path, and
    R4.2's own orchestration is expected to hold both objects side by side,
    correlated by this shared id, not the mapped `Claim` alone.
    """
    if not entity_id.strip():
        raise ClaimMappingRejected("entity_id must be a non-empty string -- never fabricated as 'unknown'")
    if not source_question_id.strip():
        raise ClaimMappingRejected("source_question_id must be a non-empty string -- never fabricated as 'unknown'")

    normalized_form = node.evidence.strip()
    if not normalized_form:
        raise ClaimMappingRejected(f"ClaimNode {node.id!r} has empty/whitespace-only evidence text -- no proposition to map")

    provenance_note = (
        f"reconstructed from graph ClaimNode {node.id!r}; ClaimNode carries no R1 lifecycle status, "
        "so this claim requires reclassification before entering the normal lifecycle"
    )
    if node.superseded_by:
        provenance_note += f" (the graph already marks it superseded_by={node.superseded_by!r})"

    return Claim(
        claim_id=node.id,
        entity_id=entity_id,
        normalized_form=normalized_form,
        source_question_id=source_question_id,
        evidence_ids=[],
        confidence=node.confidence,
        status="requires_reclassification",
        superseded_by=node.superseded_by,
        provenance_note=provenance_note,
    )
