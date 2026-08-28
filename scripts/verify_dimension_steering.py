"""Ad-hoc verification — dimension-steering pass (docs/Memory.md). Not a numbered
Phases.md deliverable.

Acceptance criterion (agreed before running): given the SAME entity and question,
changing ONLY the Dimension should legitimately change the investigation strategy
— not because of hardcoded expected children, but because the model's own
reasoning demonstrably reflects the lens. Deliberately uses a dimension that is
NOT one of the 3 universal ones (SCALE/PERSPECTIVE/TIME) and not something the
model would default to on its own: "Power Dynamics" (who has decision-making
power, who depends on whom, what leverage each participant holds).

This is graded by reading the actual reasoning text, not by asserting specific
sub-question content — asserting "contains the word leverage" would just be a
weaker version of the same "decomposition theater" trap flagged earlier in this
project's own evaluation history.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import decide_next_step  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question, QuestionLevel  # noqa: E402

QUESTION_TEXT = "How does a global payment network work?"
ENTITY_NAME = "Global Payment Network"
# Deliberately a neutral label. An earlier version of this script used "Dimension
# Steering Verification" here, which leaked semantically loaded words ("Dimension")
# into the prompt regardless of which dimension was actually set, contaminating
# the baseline (no-dimension) case with power/governance-flavored reasoning it had
# no business producing. Caught by actually reading the baseline output rather
# than assuming a null dimension_name/description meant a clean control.
ABSTRACTION_NAME = "Payment Systems"

POWER_DYNAMICS_NAME = "Power Dynamics"
POWER_DYNAMICS_DESCRIPTION = (
    "Analyze who has decision-making power, who depends on whom, what leverage "
    "each participant possesses, and how that leverage shapes the system."
)


def _make_question(*, dimension_name: str | None, dimension_description: str | None) -> Question:
    return Question(
        text=QUESTION_TEXT,
        # Neutral, realistic rationale — no mention of "dimension"/"verification"/
        # "steering" anywhere. This field IS included in decide_next_step's prompt
        # ("Rationale it was asked: ..."); the first version of this script left it
        # as "Dimension-steering verification.", which leaked straight into the
        # baseline (no-dimension) case's reasoning and invalidated the comparison —
        # caught by reading the baseline output, not assumed clean.
        rationale="Understanding how money actually moves between countries and institutions.",
        dimension_id="power_dynamics" if dimension_name else "none",
        dimension_name=dimension_name,
        dimension_description=dimension_description,
        level=QuestionLevel.MASTER,
        entity_name=ENTITY_NAME,
        abstraction_name=ABSTRACTION_NAME,
    )


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    baseline_question = _make_question(dimension_name=None, dimension_description=None)
    baseline = await decide_next_step(baseline_question)
    print("=" * 70)
    print("BASELINE (no dimension)")
    print("=" * 70)
    print(f"action: {baseline.action}")
    print(f"reasoning: {baseline.reasoning}")
    print(f"sub_question_texts: {baseline.sub_question_texts}")
    print(f"discovered_entity_name: {baseline.discovered_entity_name!r}")

    lens_question = _make_question(
        dimension_name=POWER_DYNAMICS_NAME, dimension_description=POWER_DYNAMICS_DESCRIPTION
    )
    lens = await decide_next_step(lens_question)
    print("\n" + "=" * 70)
    print(f"DIMENSION = {POWER_DYNAMICS_NAME!r}")
    print("=" * 70)
    print(f"action: {lens.action}")
    print(f"reasoning: {lens.reasoning}")
    print(f"sub_question_texts: {lens.sub_question_texts}")
    print(f"discovered_entity_name: {lens.discovered_entity_name!r}")

    print("\n" + "=" * 70)
    print("Same entity, same question, same level — only the Dimension differs.")
    print("Read both reasoning traces above: does the Power Dynamics run genuinely")
    print("reason in terms of power/leverage/dependency, or does it produce the")
    print("same generic technical framing as the baseline with a label stapled on?")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
