from __future__ import annotations

from pydantic import BaseModel, Field

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import MASTER_MODEL_CHAIN

# Phase 10 (docs/Phases.md, docs/PRD.md §9.6.3, docs/Rules.md rules 2/16/19):
# the one LLM call Lesson Authoring is allowed to make, confined to
# backend/questions per rule 2 -- backend/dewey/lessons (the pure Lesson model
# + orchestration) never calls an LLM itself, exactly the same split
# backend/dewey/curriculum already keeps from backend/research (rule 16).
#
# Rule 19's own requirement -- "a lesson's explanatory text is a claim like
# any other, it must trace to evidence already retrieved... not asserted
# directly by Lesson Authoring from the model's own unsourced knowledge" --
# is enforced by CONSTRUCTION here, not just by the later audit_synthesis
# check: the system prompt gives the model ONLY the concept's real claims and
# explicitly forbids adding outside facts. audit_synthesis (backend/questions/
# audit.py, already built, Post-Phase-5 epistemic layer) is what actually
# VERIFIES that constraint held -- this module produces a draft, it does not
# certify its own honesty.
#
# **The voice, added 2026-09-17 alongside the Dewey module rename** (docs/
# Architecture.md §0.83): this prompt now asks for Dewey's own tone -- warm,
# plain-spoken, honest about gaps -- purely as STYLE. It changes zero of the
# constraints above; a style instruction is not licensed to loosen "only the
# given claims, nothing invented." Verified this stays true by
# scripts/verify_phase10.py's own real-data check, unmodified.

_SYSTEM_PROMPT = """\
You are Dewey, a warm, curious, plain-spoken teaching guide. You are \
composing one lesson explanation for a course, from a fixed set of \
already-investigated claims about ONE concept. You are given nothing else -- \
no external knowledge, no assumed context beyond what is listed.

Your job: write a clear, well-organized EXPLANATION of the concept, in your \
own encouraging voice, built ONLY from the claims given. You may synthesize, \
reorder, and connect the claims into readable prose, and you may draw the \
most basic, unavoidable connective inferences a reader would need to follow \
the explanation sentence-to-sentence (e.g. "therefore", "as a result") -- \
but you must NOT introduce a new fact, example, mechanism, number, or named \
entity that is not present in the claims given, even if it is common \
knowledge to you and even if it would make the explanation better.

If the claims are too thin, contradictory, or fragmentary to produce a \
coherent explanation, say so plainly and honestly, the way a good teacher \
admits "I don't have enough to go on here yet" rather than bluffing -- an \
honest, incomplete-sounding explanation is correct behavior here, not a \
failure, and it is exactly what your character would actually say.

Then separately list 0-3 WORKED EXAMPLES, each one drawn directly from a \
concrete detail already present in the claims (never invented) -- if no \
claim contains anything example-shaped, return an empty list rather than \
fabricating one.
"""


class LessonDraft(BaseModel):
    explanation: str = Field(min_length=1, description="The composed explanation, built only from the given claims.")
    examples: list[str] = Field(default_factory=list, description="0-3 examples, each drawn directly from a detail already present in the given claims.")


def _build_user_prompt(concept_name: str, claim_texts: list[str]) -> str:
    lines = [f"CONCEPT: {concept_name}", "", "CLAIMS (the only real material available -- do not go beyond these):"]
    for i, text in enumerate(claim_texts, start=1):
        lines.append(f"{i}. {text}")
    return "\n".join(lines)


async def compose_lesson_explanation(
    concept_name: str,
    claim_texts: list[str],
    *,
    model_chain: list[str] | None = None,
) -> LessonDraft:
    """One isolated call, mirroring audit_synthesis's own shape (backend/
    questions/audit.py) -- a separate, narrow LLM call, not a general-purpose
    prompt. `claim_texts` must be real, non-empty `Claim.normalized_form`
    strings from an already-compiled `Module` (Phase 9.1) -- this function
    itself does not fetch, filter, or fabricate claims.

    Uses MASTER_MODEL_CHAIN (Rules.md rule 3: synthesis across multiple
    investigated pieces is a higher-stakes call, same tier `synthesize_answer`
    and `audit_synthesis` already use), not the cheaper ground-tier chain.
    """
    if not claim_texts:
        raise QuestionEngineError("compose_lesson_explanation called with zero claim_texts -- nothing to compose from")

    chain = model_chain or MASTER_MODEL_CHAIN
    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(concept_name, claim_texts),
            response_model=LessonDraft,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(
            f"compose_lesson_explanation failed on every provider in {chain}: {exc}"
        ) from exc
