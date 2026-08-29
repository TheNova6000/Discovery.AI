from __future__ import annotations

import asyncio

from backend.questions import Question

from .exceptions import EvidenceRetrievalError
from .models import Claim
from .retrievers import DEFAULT_RETRIEVERS, Retriever
from .synthesis import synthesize_claim

DEFAULT_MAX_RESULTS_PER_RETRIEVER = 2


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
    """
    active_retrievers = retrievers if retrievers is not None else DEFAULT_RETRIEVERS

    results_per_retriever = await asyncio.gather(
        *(retriever.search(question.text, max_results=max_results_per_retriever) for retriever in active_retrievers)
    )
    resources = [resource for results in results_per_retriever for resource in results]

    # Each synthesize_claim call is a full LLM fallback chain (up to 3 providers x
    # 2 passes, each with its own 30s timeout -- see structured_call) on its own,
    # independent budget. Running these one at a time, as this used to, meant a
    # dozen resources (2 per retriever x ~6 retrievers) each potentially paying
    # that worst case SEQUENTIALLY -- confirmed live (2026-08-29) as the actual
    # cause of a single investigation taking upwards of 10 minutes while
    # providers were degraded, not the core decision logic being slow at all.
    # gather() runs them concurrently instead, so total wall time is bounded by
    # the SLOWEST single resource, not the sum of all of them -- exactly the same
    # fix already applied to the retriever calls above.
    draft_results = await asyncio.gather(
        *(synthesize_claim(question, resource) for resource in resources),
        return_exceptions=True,
    )

    claims: list[Claim] = []
    for resource, result in zip(resources, draft_results):
        if isinstance(result, EvidenceRetrievalError):
            continue
        if isinstance(result, BaseException):
            raise result
        claims.append(
            Claim(
                question_id=question.id,
                evidence=result.evidence,
                reasoning=result.reasoning,
                confidence=result.confidence,
                source=resource,
            )
        )
    return claims
