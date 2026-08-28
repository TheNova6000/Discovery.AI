"""Ad-hoc verification — implicit-framing-exposure pass (docs/Memory.md). Not a
numbered Phases.md deliverable.

Prompted directly by scripts/investigate_revision_signal.py's finding: the PayPal
case decomposed into a coherent technical structure (ledger/risk/external
integration) without ever signaling that it had picked ONE of several equally
valid framings (technical vs. business vs. regulatory). Rather than build a
general dynamic-abstraction-revision mechanism for a failure mode that empirical
battery never actually observed, this exposes the choice that's already being
made silently — the smallest change backed by something actually watched
happening, per the explicit "don't invent the mechanism, expose the framing"
decision.

Acceptance test (agreed before running), same entity/question, three runs:

  1. No dimension given -> `working_framing` should be POPULATED, naming
     whatever lens the model implicitly used (expected: something
     technical/architectural, matching what investigate_revision_signal.py
     already observed it defaults to).
  2. Explicit "Economic" dimension -> `working_framing` should be UNSET (the
     dimension already names the lens) AND the resulting decomposition should
     read as economically framed, distinct from case 1.
  3. Explicit "Historical" dimension -> `working_framing` UNSET again, and the
     decomposition should read as historically framed, distinct from both
     case 1 and case 2.

Graded by reading the actual reasoning/sub-question text for genuine framing
differences, not by asserting specific expected content — same discipline as
verify_dimension_steering.py and verify_dimension_composability.py.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import decide_next_step  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question, QuestionLevel  # noqa: E402

QUESTION_TEXT = "How does PayPal work?"
ENTITY_NAME = "PayPal"
ABSTRACTION_NAME = "Payment Systems"
RATIONALE = "Understanding what PayPal actually is and how it functions."

ECONOMIC_NAME = "Economic"
ECONOMIC_DESCRIPTION = (
    "Examine revenue sources, fees, incentives, and the business model that "
    "sustains the organization."
)
HISTORICAL_NAME = "Historical"
HISTORICAL_DESCRIPTION = (
    "Examine how this emerged and changed over time — origins, key transitions, "
    "what came before and after."
)


def _make_question(
    *, dimension_name: str | None = None, dimension_description: str | None = None
) -> Question:
    return Question(
        text=QUESTION_TEXT,
        rationale=RATIONALE,
        dimension_id="explicit" if dimension_name else "none",
        dimension_name=dimension_name,
        dimension_description=dimension_description,
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
    print(f"working_framing: {decision.working_framing!r}")


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    no_dimension = await decide_next_step(_make_question())
    _print_result("NO DIMENSION (implicit framing should be exposed)", no_dimension)

    economic = await decide_next_step(
        _make_question(dimension_name=ECONOMIC_NAME, dimension_description=ECONOMIC_DESCRIPTION)
    )
    _print_result("DIMENSION = Economic (working_framing should be unset)", economic)

    historical = await decide_next_step(
        _make_question(dimension_name=HISTORICAL_NAME, dimension_description=HISTORICAL_DESCRIPTION)
    )
    _print_result("DIMENSION = Historical (working_framing should be unset)", historical)

    print("\n" + "=" * 70)
    print("Checks to make by reading the above:")
    print("  1. Case 1 has a non-null working_framing naming an implicit lens.")
    print("  2/3. Cases 2 and 3 have working_framing == None (explicit dimension")
    print("     supersedes — it already names the lens).")
    print("  4. All three decompositions/reasoning read as genuinely differently")
    print("     framed (technical/implicit vs. economic vs. historical), not the")
    print("     same structure with a label stapled on.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
