"""Ad-hoc quality evaluation — NOT a Phases.md deliverable.

Five targeted questions with PRE-REGISTERED expected-answer checklists (written
before running this script, to avoid grading with hindsight bias). Each question is
run through the real `GroundAgent(gather_evidence=True)` — real LLM calls, real
external retrievers, no mocking — and the raw output is printed for manual grading
against the checklist below. This exists to answer a concrete question: does the
system actually produce good information, not just "run without crashing."

--- PRE-REGISTERED EXPECTATIONS (written before seeing any output) ---

Q1 (factual/historical, PayPal): "In what year and under what original name did
PayPal launch, and who were its co-founders?"
  Expect: 1998, originally "Confinity" (or FieldLink), founded by Max Levchin and
  Peter Thiel (Luke Nosek too). Merged with Elon Musk's X.com in 2000; renamed
  PayPal in 2001. A good answer mentions 1998/Confinity, the X.com merger, and at
  least one founder. A bad answer invents an unrelated founding story or claims the
  name "PayPal" from day one.

Q2 (mechanism, PayPal): "What are the main steps PayPal follows to authorize a
credit card payment?"
  Expect: distinct authorization vs. capture/settlement steps, the request routing
  through a card network (Visa/Mastercard) to the issuing bank, and some mention of
  fraud/risk screening. A bad answer treats it as one atomic step with no
  network/issuer involved.

Q3 (economic/business model, PayPal): "How does PayPal make money?"
  Expect: merchant transaction fees as the primary answer, plus ideally one
  secondary stream (currency conversion markup, PayPal Credit interest, or a
  subsidiary like Braintree/Venmo). A bad answer claims user account fees or
  advertising as the main revenue source (both false).

Q4 (broad/decomposable): "How does the global card payment processing ecosystem
work?"
  Expect: recognition of the four/five-party model — cardholder, merchant,
  acquiring bank/processor, card network, issuing bank. GOOD outcomes: either (a)
  the agent decomposes into 2+ sub-questions reflecting distinct parties, or (b) if
  answered directly, the answer names and distinguishes at least 3 of the 5 roles.
  BAD outcome: a vague answer that doesn't distinguish these roles, or a boundary
  hit with no real content attempted.

Q5 (different domain entirely — CRISPR, tests generality beyond the PayPal/payments
context this project was developed against all day): "How does CRISPR-Cas9 edit a
gene?"
  Expect: guide RNA directing Cas9 to a target DNA sequence, Cas9 cutting a
  double-strand break, and at least one repair pathway (NHEJ or HDR) completing the
  edit. A bad answer confuses CRISPR with an unrelated mechanism (e.g. RNA
  interference) or omits Cas9/the guide RNA entirely.

--- END PRE-REGISTERED EXPECTATIONS ---
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents import GroundAgent, GroundResult  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.models import Question, QuestionLevel  # noqa: E402

QUESTIONS = [
    ("Q1-factual", Question(
        text="In what year and under what original name did PayPal launch, and who were its co-founders?",
        rationale="Known-answer eval: factual/historical.",
        dimension_id="time", level=QuestionLevel.GROUND,
        entity_name="PayPal", abstraction_name="Payment Platforms",
    )),
    ("Q2-mechanism", Question(
        text="What are the main steps PayPal follows to authorize a credit card payment?",
        rationale="Known-answer eval: mechanism.",
        dimension_id="scale", level=QuestionLevel.GROUND,
        entity_name="PayPal", abstraction_name="Payment Platforms",
    )),
    ("Q3-economic", Question(
        text="How does PayPal make money?",
        rationale="Known-answer eval: economic/business model.",
        dimension_id="perspective", level=QuestionLevel.GROUND,
        entity_name="PayPal", abstraction_name="Payment Platforms",
    )),
    ("Q4-broad", Question(
        text="How does the global card payment processing ecosystem work?",
        rationale="Known-answer eval: broad/decomposable.",
        dimension_id="scale", level=QuestionLevel.MASTER,
        entity_name="Card payment ecosystem", abstraction_name="Payment Platforms",
    )),
    ("Q5-other-domain", Question(
        text="How does CRISPR-Cas9 edit a gene?",
        rationale="Known-answer eval: generality outside the payments domain.",
        dimension_id="scale", level=QuestionLevel.GROUND,
        entity_name="CRISPR-Cas9", abstraction_name="Gene Editing",
    )),
]


def _print_result(label: str, result: GroundResult, depth: int = 0) -> None:
    indent = "  " * depth
    print(f"{indent}[{label}] status={result.status.value}")
    if result.answer:
        print(f"{indent}  answer: {result.answer}")
        print(f"{indent}  self-confidence: {result.confidence}")
    if result.boundary_reason:
        print(f"{indent}  boundary_reason: {result.boundary_reason}")
    for claim in result.claims:
        print(f"{indent}  claim [{claim.source.source_type}] {claim.source.title!r} (confidence={claim.confidence})")
        print(f"{indent}    evidence: {claim.evidence}")
    for i, child in enumerate(result.child_results):
        _print_result(f"{label}.child{i}", child, depth + 1)


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    for label, question in QUESTIONS:
        print(f"\n{'=' * 70}\n{label}: {question.text}\n{'=' * 70}")
        agent = GroundAgent(question, max_depth=1, gather_evidence=True)
        result = await agent.run()
        _print_result(label, result)


if __name__ == "__main__":
    asyncio.run(run())
