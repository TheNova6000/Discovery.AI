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

    claims: list[Claim] = []
    for resource in resources:
        try:
            draft = await synthesize_claim(question, resource)
        except EvidenceRetrievalError:
            continue
        claims.append(
            Claim(
                question_id=question.id,
                evidence=draft.evidence,
                reasoning=draft.reasoning,
                confidence=draft.confidence,
                source=resource,
            )
        )
    return claims
