from __future__ import annotations

from backend.questions import Question
from backend.questions.llm_client import structured_call
from backend.questions.llm_config import GROUND_MODEL_CHAIN

from .exceptions import EvidenceRetrievalError
from .models import ClaimDraft, RetrievedResource

_SYSTEM_PROMPT = """\
You are the Evidence Engine's claim synthesizer inside a recursive knowledge graph \
system. You are given a Question and ONE retrieved resource (a paper, book, web \
page, or video) that might help answer it.

Read ONLY the given title/snippet — do not invent facts beyond what's there.

Produce:
- evidence: a concise, direct answer to the question, grounded only in this \
resource's title/snippet. If the resource doesn't actually answer the question, \
say so plainly in `evidence` rather than fabricating an answer.
- reasoning: one or two sentences on why (or why not) this resource supports that \
answer.
- confidence: 0-1, how WELL this resource answers the question — NOT how sure you \
are in your own judgment. If `evidence` says the resource does not answer the \
question (a title/abstract mismatch, wrong topic, wrong domain entirely), \
confidence MUST be low (below 0.2), even if you are completely certain that it \
does not answer it. High confidence (above 0.7) is reserved for resources that \
substantively answer the question.
"""


def _build_user_prompt(question: Question, resource: RetrievedResource) -> str:
    return (
        f"Question: {question.text}\n"
        f"Resource title: {resource.title}\n"
        f"Resource type: {resource.source_type}\n"
        f"Resource snippet: {resource.snippet or '(no snippet available)'}\n"
        f"Resource URL: {resource.url}"
    )


async def synthesize_claim(
    question: Question,
    resource: RetrievedResource,
    *,
    model_chain: list[str] | None = None,
) -> ClaimDraft:
    """The one LLM call behind the Evidence Engine (docs/Phases.md Phase 5) — turns
    one raw `RetrievedResource` plus the Question it's meant to help answer into a
    `ClaimDraft`. Lives in `backend/evidence`, not `backend/agents`, per
    docs/Rules.md rule 2.
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(question, resource),
            response_model=ClaimDraft,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise EvidenceRetrievalError(
            f"synthesize_claim failed on every provider in {chain}: {exc}"
        ) from exc
