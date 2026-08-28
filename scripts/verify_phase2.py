"""Phase 2 verification script — see docs/Phases.md "Phase 2".

Calls the Question Engine directly (no agent loop) with the same dimension at two
different levels for the same entity, and confirms the generated questions are
meaningfully different (level-awareness — docs/PRD.md §4.3).

Requires at least one LLM provider key in .env (GEMINI_API_KEY, GROQ_API_KEY, or
CEREBRAS_API_KEY) — see Implimentation-Research/Free-LLM-APIs.md.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import SCALE, QuestionLevel, generate_question  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402


async def run() -> None:
    if not has_any_provider_key():
        print(
            "[fail] No LLM provider key found in .env "
            "(GEMINI_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY / COHERE_API_KEY)."
        )
        raise SystemExit(1)

    ground_question = await generate_question(
        abstraction_name="Payment Platforms",
        entity_name="PayPal",
        dimension=SCALE,
        level=QuestionLevel.GROUND,
        objective="Understand how PayPal actually processes a single transaction.",
    )
    print(f"[ground] {ground_question.text}")
    print(f"         rationale: {ground_question.rationale}")

    master_question = await generate_question(
        abstraction_name="Payment Platforms",
        entity_name="PayPal",
        dimension=SCALE,
        level=QuestionLevel.MASTER,
        objective="Understand PayPal's role in the global payments ecosystem.",
    )
    print(f"[master] {master_question.text}")
    print(f"         rationale: {master_question.rationale}")

    assert ground_question.text.strip().lower() != master_question.text.strip().lower(), (
        "ground and master questions must not be identical"
    )
    # A rough but real signal of level-awareness rather than a reworded duplicate:
    # the two questions should share few enough words that they aren't just paraphrases.
    ground_words = set(ground_question.text.lower().split())
    master_words = set(master_question.text.lower().split())
    overlap = len(ground_words & master_words) / max(len(ground_words | master_words), 1)
    assert overlap < 0.6, (
        f"ground/master questions are too similar (word overlap {overlap:.0%}) — "
        "level-awareness requirement not met"
    )
    print(f"[ok] word overlap between levels: {overlap:.0%} (< 60% threshold)")

    print("\nPhase 2 verification PASSED.")


if __name__ == "__main__":
    asyncio.run(run())
