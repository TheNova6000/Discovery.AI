"""Grounding a Ground Agent's answer in its evidence (docs/research/
Related-Work-and-Novelty.md §4 P1).

Before this, `GroundResult.answer` was the model's answer from memory and the
gathered claims were attached afterwards without ever touching it (live BST run,
2026-10-28: a confident answer backed by 0 claims). Now the memory answer is
kept only as a draft, and the final answer is either

- **grounded**: rewritten from the claims alone, citing them, then audited
  proposition by proposition (FActScore-style) by a separate call; or
- **ungrounded**: the draft, explicitly marked as not backed by retrieved
  evidence, when there are no claims or composing from them failed.

`reasoning.domain.Answer` (R1, built but never instantiated until now)
enforces the invariant: grounded <=> cites at least one claim.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from backend.main_block.reasoning_engine.evidence import Claim
from backend.main_block.reasoning_engine.llm_steps import Question, audit_synthesis, compose_grounded_answer
from backend.main_block.reasoning_engine.domain import Answer

MAX_GAP_QUERIES = 2
"""Gaps the writer lists that are re-searched before the answer is final --
bounded so one answer costs at most this many extra evidence rounds."""

SUPPORTED_CONFIDENCE = 0.5
"""Only claims at or above this may ground an answer. Weaker claims (e.g.
metadata, capped at 0.35) stay attached to the result for transparency, but an
answer built from them alone described a GitHub repo instead of BSTs (iteration
02, run 7) -- weak evidence can point somewhere, it can't be the answer."""


class Statement(BaseModel):
    """One atomic statement of the final answer, as the audit judged it."""

    text: str
    supported: bool
    claim_ids: list[str] = Field(default_factory=list)
    """Claims the audit found stating this -- verified support, not the writer's own citation."""


class Grounding(BaseModel):
    answer: Answer
    draft_answer: Optional[str] = None
    """The model's answer from memory -- kept as a hypothesis, never shown as fact."""
    evidence_gaps: list[str] = Field(default_factory=list)
    support_ratio: Optional[float] = None
    """Share of the answer's atomic statements the audit traced to the evidence.
    None when no audit ran -- unknown, not zero."""
    unsupported_statements: list[str] = Field(default_factory=list)
    statements: list[Statement] = Field(default_factory=list)
    gap_claims: list[Claim] = Field(default_factory=list)
    """Claims found by gap re-queries. The caller must keep them with its result:
    the answer may cite them, and a citation must resolve to a stored claim."""
    citations_verified: bool = False
    """True when `answer.claim_ids` came from the audit's per-statement support
    (VeriCite-style); False when they are only the writer's own citations."""
    note: Optional[str] = None


def claims_with_descendants(own: list[Claim], child_results: list) -> list[Claim]:
    """A synthesizing (master) node grounds its answer on its own claims plus
    every claim its sub-investigations gathered -- the supervisor writes from
    its sub-agents' cited findings (Open Deep Research), instead of searching
    again for the whole multi-part question and finding nothing (iteration 02,
    run 8: both children grounded at 1.0, root ungrounded with 0 claims)."""
    seen: set[str] = set()
    out: list[Claim] = []
    pending = list(child_results)
    for claim in own:
        if claim.id not in seen:
            seen.add(claim.id)
            out.append(claim)
    while pending:
        child = pending.pop(0)
        for claim in child.claims:
            if claim.id not in seen:
                seen.add(claim.id)
                out.append(claim)
        pending.extend(child.child_results)
    return out


def _evidence_text(claim: Claim) -> str:
    return f"{claim.evidence} (source: {claim.source.title})"


def _ungrounded(draft: Optional[str], note: str) -> Grounding:
    text = draft or "No answer could be produced."
    return Grounding(answer=Answer(text=text, grounded=False), draft_answer=draft, note=note)


Requery = Callable[[str], Awaitable[list[Claim]]]


async def _fill_gaps(gaps: list[str], requery: Requery, have: list[Claim], weak_seen: list[int] | None = None) -> list[Claim]:
    """Each listed gap becomes a targeted evidence need (Self-Ask decomposition;
    CRAG's "ambiguous -> reformulate"). Iteration 03, E12: the root answer
    listed "definition", "how it works" as gaps while the Archive held the full
    article -- its single compound-question search had judged every passage
    against the whole multi-part question."""
    known = {c.id for c in have}
    found: list[Claim] = []
    for gap in gaps[:MAX_GAP_QUERIES]:
        try:
            for claim in await requery(gap):
                if claim.id not in known and claim.confidence >= SUPPORTED_CONFIDENCE:
                    known.add(claim.id)
                    found.append(claim)
                elif weak_seen is not None and claim.id not in known:
                    weak_seen.append(1)
        except Exception:  # noqa: BLE001 - a failed gap search leaves that gap open, never sinks the answer
            continue
    return found


async def ground_answer(
    question: Question,
    draft: Optional[str],
    claims: list[Claim],
    *,
    requery: Optional[Requery] = None,
) -> Grounding:
    if not claims and requery is None:
        return _ungrounded(draft, "no evidence claims were gathered; answer comes from model memory only")
    weak = len(claims)
    claims = [c for c in claims if c.confidence >= SUPPORTED_CONFIDENCE]
    gap_searches = 0
    gap_claims: list[Claim] = []
    if not claims and requery is not None:
        # Nothing usable for the question as asked: search it as one targeted gap.
        weak_seen: list[int] = []
        gap_claims = await _fill_gaps([question.text], requery, [], weak_seen)
        claims = list(gap_claims)
        gap_searches = 1
        # The gap search's weak claims count too: the live ask said "no evidence
        # claims were gathered" when it had found one below 0.5 (iteration 05).
        weak += len(weak_seen)
    if not claims:
        if weak:
            return _ungrounded(draft, f"only weak evidence was found ({weak} claim(s) below {SUPPORTED_CONFIDENCE}, e.g. metadata)")
        return _ungrounded(draft, "no evidence claims were gathered; answer comes from model memory only")

    evidence = [_evidence_text(c) for c in claims]
    try:
        composed = await compose_grounded_answer(question.text, evidence)
        if composed.gaps and requery is not None and gap_searches == 0:
            extra = await _fill_gaps(composed.gaps, requery, claims)
            if extra:
                gap_claims += extra
                claims = claims + extra
                evidence = [_evidence_text(c) for c in claims]
                composed = await compose_grounded_answer(question.text, evidence)
    except Exception as exc:  # noqa: BLE001 - any failure degrades to an honestly-marked draft
        return _ungrounded(draft, f"composing from evidence failed: {str(exc)[:200]}")

    if not composed.answer.strip() or not composed.cited:
        grounding = _ungrounded(draft, "the gathered evidence did not answer the question")
        grounding.evidence_gaps = composed.gaps or [question.text]
        grounding.gap_claims = gap_claims
        return grounding

    writer_cited = [claims[i - 1].id for i in composed.cited]
    grounding = Grounding(
        answer=Answer(text=composed.answer, claim_ids=writer_cited, grounded=True),
        draft_answer=draft,
        evidence_gaps=composed.gaps,
        gap_claims=gap_claims,
    )
    # The audit sees ALL gathered claims, not just the ones the writer cited:
    # citations are decided by verification, not by the generator (VeriCite,
    # CiteFix -- iteration 01, E2: the writer cited [1, 2] on the very sentence
    # the audit found unsupported).
    try:
        audit = await audit_synthesis(composed.answer, evidence)
    except Exception as exc:  # noqa: BLE001 - an audit failure leaves support unknown, never assumed
        grounding.note = f"audit failed, support unknown, citations are the writer's own: {str(exc)[:160]}"
        return grounding
    if not audit.claims:
        grounding.note = "audit returned no statements, support unknown, citations are the writer's own"
        return grounding

    for atomic in audit.claims:
        supported = atomic.origin == "investigated"
        ids = [claims[i - 1].id for i in atomic.supported_by if supported and 1 <= i <= len(claims)]
        grounding.statements.append(Statement(text=atomic.text, supported=supported, claim_ids=ids))
    supported_statements = [st for st in grounding.statements if st.supported]
    grounding.support_ratio = round(len(supported_statements) / len(grounding.statements), 3)
    grounding.unsupported_statements = [st.text for st in grounding.statements if not st.supported]

    if not supported_statements:
        grounding.answer = Answer(text=composed.answer, grounded=False)
        grounding.note = "the audit traced none of the composed answer to the evidence"
        return grounding
    verified_ids = list(dict.fromkeys(cid for st in supported_statements for cid in st.claim_ids))
    if verified_ids:
        grounding.answer = Answer(text=composed.answer, claim_ids=verified_ids, grounded=True)
        grounding.citations_verified = True
    else:
        grounding.note = "audit found support but named no evidence items; citations are the writer's own"
    return grounding
