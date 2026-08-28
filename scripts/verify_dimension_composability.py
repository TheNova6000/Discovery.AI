"""Ad-hoc verification — dimension-composability pass (docs/Memory.md). Not a
numbered Phases.md deliverable. Extends verify_dimension_steering.py (single
dimension, already verified) to two SIMULTANEOUS dimensions.

Acceptance criterion (agreed before running): the same entity and question, run
three times —

    1. baseline (no dimension)
    2. Historical only
    3. Historical + Incentives

— should show a progression, not just an accumulation of labels. Historical alone
should reason about emergence/evolution/transition. Historical + Incentives should
NOT be "a historical fact, and separately, an incentives fact" stapled together —
it should read as ONE fused angle: how participant incentives evolved over time and
shaped the system, the way a person holding both lenses at once would actually
frame the question. That fusion (not mere co-occurrence of both words) is what's
being graded, by reading the actual reasoning text — exactly as
verify_dimension_steering.py insisted on for the single-dimension case, and for the
same reason ("contains both dimension names" would be decomposition-theater's
metadata-composition cousin, not evidence of composition).

Same contamination trap as before applies here too: `rationale` is deliberately
neutral (no "historical", "incentive", "dimension", or "verification" words) so it
can't leak lens-flavored language into the baseline case.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import decide_next_step  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import DimensionContext, Question, QuestionLevel  # noqa: E402

QUESTION_TEXT = "How does Mastercard operate as a global payment network?"
# Deliberately NOT "How did Mastercard become..." — a first version of this script
# used that phrasing and it pre-loads a historical framing into the BASELINE
# (no-dimension) case regardless of which dimension is set, the same category of
# methodological trap verify_dimension_steering.py hit with a leaky `rationale`
# field. Caught by reading the baseline output (it front-ran straight to "ICA
# origins" reasoning with no dimension at all) rather than assuming a neutral
# question is automatically a clean control. "How does X operate" has no built-in
# lean toward history, incentives, or mechanics.
ENTITY_NAME = "Mastercard"
ABSTRACTION_NAME = "Payment Networks"
RATIONALE = "Understanding how a widely-used card network actually functions at scale."

HISTORICAL = DimensionContext(
    name="Historical",
    description="Examine how this emerged and changed over time — origins, key transitions, what came before and after.",
)
INCENTIVES = DimensionContext(
    name="Incentives",
    description=(
        "Examine what each participant (banks, merchants, consumers, the network "
        "itself) wants, gains, or risks, and how those incentives shape behavior."
    ),
)


def _make_question(*, dimensions: list[DimensionContext]) -> Question:
    return Question(
        text=QUESTION_TEXT,
        rationale=RATIONALE,
        dimension_id="composed" if dimensions else "none",
        dimensions=dimensions,
        level=QuestionLevel.MASTER,
        entity_name=ENTITY_NAME,
        abstraction_name=ABSTRACTION_NAME,
    )


def _print_result(label: str, decision) -> None:
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    print(f"action: {decision.action}")
    print(f"reasoning: {decision.reasoning}")
    print(f"sub_question_texts: {decision.sub_question_texts}")
    print(f"discovered_entity_name: {decision.discovered_entity_name!r}")


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    baseline = await decide_next_step(_make_question(dimensions=[]))
    _print_result("BASELINE (no dimension)", baseline)

    historical = await decide_next_step(_make_question(dimensions=[HISTORICAL]))
    _print_result("DIMENSION = Historical", historical)

    composed = await decide_next_step(_make_question(dimensions=[HISTORICAL, INCENTIVES]))
    _print_result("DIMENSIONS = Historical + Incentives", composed)

    print("\n" + "=" * 70)
    print("Same entity, same question, same level — only the dimension set differs.")
    print("Read all three reasoning traces above. Progression to look for:")
    print("  baseline   -> structural/functional (how the network mechanically works)")
    print("  historical -> emergence/evolution/transition over time")
    print("  composed   -> ONE fused angle: how incentives evolved and drove that")
    print("                history — not a historical clause plus a separate")
    print("                incentives clause stapled together.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
