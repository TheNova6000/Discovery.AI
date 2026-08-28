from __future__ import annotations

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import MASTER_MODEL_CHAIN
from .models import Question, SynthesisDraft

_SYSTEM_PROMPT = """\
You are synthesizing a final answer to a broader question from several
already-investigated sub-questions (each answered separately, some possibly left
unresolved).

Produce ONE coherent, well-organized answer to the ORIGINAL question, drawing only
on the sub-answers given — do not introduce new facts beyond what they contain, but
you should connect and organize them into a single readable narrative rather than
just listing them back.

If a sub-question was left unresolved (a boundary hit), briefly acknowledge the gap
but still synthesize the best answer possible from what IS available — do not
refuse to answer just because one piece is missing.

confidence: 0-1, reflecting how completely the sub-answers actually cover the
original question. Lower it when one or more sub-questions were unresolved or when
the sub-answers only partially address the original question.
"""


def _build_user_prompt(question: Question, child_summaries: list[str]) -> str:
    lines = [f"Original question: {question.text}", "", "Sub-question results:"]
    for i, summary in enumerate(child_summaries, start=1):
        lines.append(f"\n{i}. {summary}")
    return "\n".join(lines)


async def synthesize_answer(
    question: Question,
    child_summaries: list[str],
    *,
    model_chain: list[str] | None = None,
) -> SynthesisDraft:
    """Roll up a decomposed question's sub-answers into one coherent top-level
    answer (docs/Rules.md rule 2 — this LLM call lives in `backend/questions`, not
    `backend/agents`). `child_summaries` is plain pre-formatted text, not typed
    agent objects — this module must not depend on `backend/agents`, which is the
    layer above it.
    """
    chain = model_chain or MASTER_MODEL_CHAIN
    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(question, child_summaries),
            response_model=SynthesisDraft,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(
            f"synthesize_answer failed on every provider in {chain}: {exc}"
        ) from exc
