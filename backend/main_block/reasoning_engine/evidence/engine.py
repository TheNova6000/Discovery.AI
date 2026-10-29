from __future__ import annotations

import asyncio
import os
from typing import NamedTuple

from backend.main_block.reasoning_engine.llm_steps import Question
from backend.main_block.reasoning_engine.domain import Evidence, RetrievalOutcome, classify_retrieval_outcome

from .exceptions import EvidenceRetrievalError
from .faithfulness import check_faithfulness
from backend.main_block.research_engine.interface import DEFAULT_RETRIEVERS, Retriever, RetrievedResource

from .models import Claim, ClaimDraft
from .synthesis import synthesize_claim

DEFAULT_MAX_RESULTS_PER_RETRIEVER = 2

# R1.2 (docs/Phases.md's Reasoning Engine Evolution track, docs/Architecture.md
# §0.47/§0.49/§0.59): matches synthesize_claim's OWN documented system-prompt
# contract exactly (backend/main_block/reasoning_engine/evidence/synthesis.py: "If evidence says the
# resource does not answer the question... confidence MUST be low (below
# 0.2)") -- not a new, separately-invented judgment. This constant is the
# actual mechanism that decides whether a synthesized draft represents a
# genuine proposition or a retrieval outcome that happens to have text and a
# number attached.
NON_ANSWER_CONFIDENCE_THRESHOLD = 0.2

METADATA_CONFIDENCE_CAP = 0.35
"""Ceiling for a claim built on `content_kind == "metadata"` -- below the 0.5
"supported" threshold coverage uses, so a repo/book/video description can point
at a source but never count as support on its own (iteration 01, E1)."""

DUPLICATE_EVIDENCE_OVERLAP = 0.6


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(t) > 2}


def _dedupe_claims(claims: list[Claim]) -> list[Claim]:
    """Same source URL and near-identical evidence text -> one claim, the more
    confident (iteration 01, E3: one GitHub repo became two claims)."""
    kept: list[Claim] = []
    for claim in sorted(claims, key=lambda c: -c.confidence):
        words = _tokens(claim.evidence)
        duplicate = False
        for other in kept:
            if other.source.url != claim.source.url:
                continue
            union = words | _tokens(other.evidence)
            if union and len(words & _tokens(other.evidence)) / len(union) >= DUPLICATE_EVIDENCE_OVERLAP:
                duplicate = True
                break
        if not duplicate:
            kept.append(claim)
    return kept


def _is_non_answer(draft: ClaimDraft) -> bool:
    """R1.2's actual classifier: a draft below the threshold synthesize_claim's
    own prompt already reserves for "doesn't answer the question" is a
    RetrievalOutcome, not a Claim -- this is the real, live-path fix for the
    exact bug R0 found (Architecture.md §0.47): "Recursive Resolver"'s 3 of 4
    real claims were literally "the resource does not answer the question,"
    stored as Claims with a confidence score anyway.
    """
    return draft.confidence < NON_ANSWER_CONFIDENCE_THRESHOLD


def _retrieval_outcome_from_error(question: Question, resource: RetrievedResource, exc: EvidenceRetrievalError) -> RetrievalOutcome:
    # Previously (pre-R1.2): silently `continue`d with zero record at all
    # (see git history) -- a synthesis failure just vanished. Representing it
    # as a real RetrievalOutcome instead is a genuine improvement, not merely
    # a refactor: "what actually happened" now includes synthesis failures,
    # matching R1.1's whole premise that the system should be able to
    # represent what happened, not just what succeeded.
    return RetrievalOutcome(
        question_id=question.id,
        source_title=resource.title,
        source_url=resource.url,
        source_type=resource.source_type,
        success=False,
        relevant=False,
        failure_reason=f"synthesize_claim failed: {exc}",
    )


def _retrieval_outcome_from_draft(question: Question, resource: RetrievedResource, draft: ClaimDraft, *, relevant: bool) -> RetrievalOutcome:
    # success=True either way -- the retriever call itself worked, we got a
    # real response. `relevant` is the LLM's own judgment (via
    # NON_ANSWER_CONFIDENCE_THRESHOLD) about whether that response actually
    # answers the question. raw_content is what actually came back either
    # way -- including the model's own stated non-answer, e.g. "the resource
    # does not answer the question," when relevant=False. `failure_reason`
    # is reserved for success=False (a genuine retrieval/synthesis failure),
    # never used here -- the retrieval mechanism worked fine in both cases.
    return RetrievalOutcome(
        question_id=question.id,
        source_title=resource.title,
        source_url=resource.url,
        source_type=resource.source_type,
        success=True,
        relevant=relevant,
        raw_content=draft.evidence,
    )


class GatherEvidenceResult(NamedTuple):
    """R1.2's richer return shape -- `gather_evidence` below stays byte-for-byte
    backward compatible (still returns bare `list[Claim]`, both existing call
    sites -- ground_agent.py, scripts/verify_phase5.py -- are unchanged) by
    wrapping this function rather than replacing it. `evidence` and
    `retrieval_outcomes` are new, additive information no prior caller had
    access to at all.
    """

    claims: list[Claim]
    retrieval_outcomes: list[RetrievalOutcome]
    evidence: list[Evidence]
    provider_reports: tuple = ()
    """Dewey path only: one `backend.main_block.research_engine.ProviderReport` per source consulted
    (empty when the Archive already covered the question -- nothing was called)."""
    evidence_source: str = "retrievers"
    faithfulness_checked: bool = False
    """True when every returned claim was checked against its own passage
    (supported); False when the check was off or failed -- claims unverified."""
    """Dewey's `EvidenceBatch.source` (archive / research / known_gap /
    unavailable), or "retrievers" for the direct legacy path."""


async def _keep_faithful(question: Question, claims: list[Claim]) -> tuple[list[Claim], list[RetrievalOutcome], bool]:
    """Drop claims their own passage doesn't support (iteration 04, E13). A
    dropped claim becomes a RetrievalOutcome (relevant=False) so it stays visible.
    EVIDENCE_FAITHFULNESS=off skips the check (tests, quota emergencies)."""
    if not claims or os.environ.get("EVIDENCE_FAITHFULNESS", "on").lower() == "off":
        return claims, [], False
    try:
        verdicts = await check_faithfulness(claims)
    except Exception as exc:  # noqa: BLE001 - an unavailable checker leaves claims unverified, never dropped
        print(f"[evidence] faithfulness check failed, claims kept unverified: {str(exc)[:160]}")
        return claims, [], False
    kept: list[Claim] = []
    dropped: list[RetrievalOutcome] = []
    for i, claim in enumerate(claims):
        verdict = verdicts.get(i)
        if verdict is None or verdict.verdict == "supported":
            kept.append(claim)
            continue
        dropped.append(
            RetrievalOutcome(
                question_id=question.id,
                source_title=claim.source.title,
                source_url=claim.source.url,
                source_type=claim.source.source_type,
                success=True,
                relevant=False,
                raw_content=f"[faithfulness: {verdict.verdict} -- {verdict.note}] {claim.evidence}",
            )
        )
    return kept, dropped, len(verdicts) == len(claims)


def _use_dewey() -> bool:
    # Default: Discovery.AI asks Dewey, the research engine, instead of calling
    # sources itself (docs/research/Reasoning-Research-Orchestration.md §2b).
    # EVIDENCE_SOURCE=retrievers restores the direct path.
    return os.environ.get("EVIDENCE_SOURCE", "dewey").lower() != "retrievers"


async def _resources_from_dewey(question: Question, limit: int):
    # The one connector from the reasoning engine to the research engine:
    # InformationNeed in, EvidenceBatch out, through the research engine's interface.
    from backend.main_block.research_engine.interface import ArchiveStore, DeweyEngine, InformationNeed

    async with ArchiveStore() as archive:
        batch = await DeweyEngine(archive).find(
            InformationNeed(text=question.text, need_kind="general", max_passages=limit)
        )
    resources = [
        RetrievedResource(
            title=hit.title,
            url=hit.url,
            snippet=hit.text,
            source_type=hit.source_type,
            source_role=hit.source_role,
            retrieved_at=hit.retrieved_at,
            content_kind=hit.content_kind,
        )
        for hit in batch.passages
    ]
    return resources, tuple(batch.reports), batch.source


async def gather_evidence_with_outcomes(
    question: Question,
    *,
    retrievers: list[Retriever] | None = None,
    max_results_per_retriever: int = DEFAULT_MAX_RESULTS_PER_RETRIEVER,
) -> GatherEvidenceResult:
    """The actual R1.2 integration point: wires RetrievalOutcome -> Evidence ->
    Claim into the live investigation path (previously: `retrieved_result ->
    Claim` unconditionally, regardless of whether the resource answered
    anything). Every resource produces exactly one RetrievalOutcome, always
    -- this is what makes "retrieval outcomes > 0" a real, checkable fact
    about a live run, not just about reconstructed historical data (R1.1's
    scope). Only resources classified as genuine answers ever become a
    `Claim` -- a retrieval failure or a synthesis failure can no longer
    reach the claim graph via this path, structurally, not by convention.

    Deliberately does NOT change `Claim`'s own schema, does not persist
    `RetrievalOutcome`/`Evidence` to Neo4j, does not introduce automatic
    deduplication (R1.3/R4), and does not touch the claim lifecycle (R1.4) --
    scoped exactly to "does live investigation produce the distinction
    correctly," nothing more.
    """
    provider_reports: tuple = ()
    evidence_source = "retrievers"
    if retrievers is None and _use_dewey():
        # Archive passages, at most 2x the per-retriever budget in total -- the
        # LLM synthesises a handful of ranked passages, not every search hit.
        resources, provider_reports, evidence_source = await _resources_from_dewey(
            question, limit=max(2, 2 * max_results_per_retriever)
        )
    else:
        active_retrievers = retrievers if retrievers is not None else DEFAULT_RETRIEVERS
        results_per_retriever = await asyncio.gather(
            *(retriever.search(question.text, max_results=max_results_per_retriever) for retriever in active_retrievers)
        )
        resources = []
        for retriever, results in zip(active_retrievers, results_per_retriever):
            for resource in results:
                if resource.content_kind is None:
                    resource.content_kind = getattr(retriever, "content_kind", None)
                resources.append(resource)

    draft_results = await asyncio.gather(
        *(synthesize_claim(question, resource) for resource in resources),
        return_exceptions=True,
    )

    claims: list[Claim] = []
    retrieval_outcomes: list[RetrievalOutcome] = []
    evidence_list: list[Evidence] = []

    for resource, result in zip(resources, draft_results):
        if isinstance(result, EvidenceRetrievalError):
            retrieval_outcomes.append(_retrieval_outcome_from_error(question, resource, result))
            continue
        if isinstance(result, BaseException):
            raise result

        if _is_non_answer(result):
            retrieval_outcomes.append(_retrieval_outcome_from_draft(question, resource, result, relevant=False))
            continue

        outcome = _retrieval_outcome_from_draft(question, resource, result, relevant=True)
        retrieval_outcomes.append(outcome)
        evidence = classify_retrieval_outcome(outcome)
        assert evidence is not None, "a success=True/relevant=True/raw_content-set outcome always yields Evidence by construction"
        evidence_list.append(evidence)

        confidence = result.confidence
        if resource.content_kind == "metadata":
            confidence = min(confidence, METADATA_CONFIDENCE_CAP)
        claims.append(
            Claim(
                question_id=question.id,
                evidence=result.evidence,
                reasoning=result.reasoning,
                confidence=confidence,
                source=resource,
            )
        )

    candidates = len(claims)
    claims, unfaithful, faithfulness_checked = await _keep_faithful(question, _dedupe_claims(claims))
    retrieval_outcomes.extend(unfaithful)
    # One line per evidence step, so a live run shows WHERE evidence was lost
    # (loop iteration 05: "0 claims" runs could not be diagnosed from the log).
    failed = sum(1 for o in retrieval_outcomes if not o.success)
    non_answers = sum(1 for o in retrieval_outcomes if o.success and not o.relevant) - len(unfaithful)
    sources = ",".join(f"{r.provider}:{r.status}" for r in provider_reports) or "-"
    print(
        f"[evidence] {question.text[:70]!r} source={evidence_source} passages={len(resources)} "
        f"non_answers={non_answers} synth_failed={failed} candidates={candidates} "
        f"unfaithful={len(unfaithful)} claims={len(claims)} checked={faithfulness_checked} reports=[{sources}]"
    )
    return GatherEvidenceResult(
        claims=claims,
        faithfulness_checked=faithfulness_checked,
        retrieval_outcomes=retrieval_outcomes,
        evidence=evidence_list,
        provider_reports=provider_reports,
        evidence_source=evidence_source,
    )


async def gather_evidence(
    question: Question,
    *,
    retrievers: list[Retriever] | None = None,
    max_results_per_retriever: int = DEFAULT_MAX_RESULTS_PER_RETRIEVER,
) -> list[Claim]:
    """Retrieve real resources for `question` from every configured retriever, then
    synthesize each into a typed `Claim` (evidence/reasoning/confidence/provenance
    — docs/Rules.md rule 4). Only ever called for a specific question something is
    actively investigating (docs/Rules.md rule 11's laziness applies here too —
    never precomputed for a whole abstraction upfront).

    A retriever that returns nothing (missing key, API failure, no matches)
    contributes nothing to the result — docs/Rules.md §3's graceful degradation,
    not an error this function raises. Likewise, one resource's synthesis failing
    doesn't sink the others.

    R1.2 (docs/Phases.md): the actual claim-construction work now lives in
    `gather_evidence_with_outcomes` above -- this function is an unchanged-
    signature, unchanged-behavior-for-genuine-answers wrapper over it, kept
    for every existing caller (backend/main_block/reasoning_engine/agents/ground_agent.py,
    scripts/verify_phase5.py). The one real behavior change, intentional and
    the whole point of R1.2: a resource whose synthesized draft reads as "this
    doesn't answer the question" (confidence < 0.2, matching synthesize_claim's
    own documented contract) no longer becomes a Claim at all -- it did before.
    """
    result = await gather_evidence_with_outcomes(
        question, retrievers=retrievers, max_results_per_retriever=max_results_per_retriever
    )
    return result.claims
