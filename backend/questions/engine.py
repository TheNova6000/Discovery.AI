from __future__ import annotations

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import GROUND_MODEL_CHAIN
from .models import Dimension, Question, QuestionDraft, QuestionLevel

_SYSTEM_PROMPT = """\
You are the Question Engine inside a recursive knowledge graph system.

The system represents knowledge as: Domains -> Networks -> Abstractions -> Entities \
-> Dimensions -> Questions -> Resources -> Knowledge -> New Questions.

An "Abstraction" is a named boundary drawn around part of a knowledge network (e.g. \
"Payment Platforms", "Quantum Computing"). An "Entity" is a concrete thing inside \
that abstraction (e.g. "PayPal"). A "Dimension" is a lens applied to interrogate the \
entity/abstraction and produce a question.

You must generate exactly ONE question, and it must be LEVEL-AWARE:
- level="ground": a concrete, specific, mechanism-level question about the entity \
itself — the kind a specialist investigating one narrow detail would ask.
- level="master": a broad, strategic, systemic question about how the entity fits \
into the larger abstraction/system — the kind someone surveying the whole space \
would ask.

The SAME dimension at different levels must produce STRUCTURALLY DIFFERENT \
questions, not just reworded versions of the same question. Also give a one-sentence \
rationale for why this specific question matters at this level.
"""


def _build_user_prompt(
    abstraction_name: str,
    entity_name: str,
    dimension: Dimension,
    level: QuestionLevel,
    objective: str | None,
    known: list[str] | None,
    unknowns: list[str] | None,
) -> str:
    lines = [
        f"Abstraction: {abstraction_name}",
        f"Entity: {entity_name}",
        f"Dimension: {dimension.name} — {dimension.description}",
        f"Level: {level.value}",
    ]
    if objective:
        lines.append(f"Objective: {objective}")
    if known:
        lines.append(f"Already known: {'; '.join(known)}")
    if unknowns:
        lines.append(f"Open unknowns: {'; '.join(unknowns)}")
    lines.append(
        "Generate one question that applies this dimension to this entity, at this "
        "level, in the context of this abstraction."
    )
    return "\n".join(lines)


async def generate_question(
    *,
    abstraction_name: str,
    entity_name: str,
    dimension: Dimension,
    level: QuestionLevel,
    objective: str | None = None,
    known: list[str] | None = None,
    unknowns: list[str] | None = None,
    model_chain: list[str] | None = None,
) -> Question:
    """Q = f(Abstraction, Entity, Dimension, Level, Objective, Known, Unknowns).

    Lazy by construction (docs/Rules.md rule 11) — this generates exactly one
    question per call; nothing here loops over entities/dimensions/levels. Callers
    (the future Ground/Master agents) decide when to call this, on demand.

    Tries each model in `model_chain` in order, falling back on rate limits / outages
    (every free tier here is capped low enough to hit limits during real use —
    see Implimentation-Research/Free-LLM-APIs.md).
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    user_prompt = _build_user_prompt(
        abstraction_name, entity_name, dimension, level, objective, known, unknowns
    )

    try:
        # instructor.from_provider() (inside structured_call) derives the real
        # provider from the "provider/model" string and talks to that provider's
        # native SDK directly (Gemini/Groq/Cerebras), each with its own pre-vetted
        # default structured-output mode. Deliberately NOT using
        # instructor.from_litellm() — it hardcodes provider=OPENAI internally
        # regardless of the model string and hits registry errors unpredictably
        # (confirmed via live testing against this exact instructor version).
        draft: QuestionDraft = await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=QuestionDraft,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(
            f"generate_question failed on every provider in {chain}: {exc}"
        ) from exc

    return Question(
        text=draft.text,
        rationale=draft.rationale,
        dimension_id=dimension.id,
        dimension_name=dimension.name,
        dimension_description=dimension.description,
        level=level,
        entity_name=entity_name,
        abstraction_name=abstraction_name,
    )
