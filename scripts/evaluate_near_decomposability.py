"""Ad-hoc research probe — NOT a Phases.md deliverable, not a permanent eval.

Follow-up to scripts/evaluate_structural_judgment.py's Q2 finding (PayPal revenue
streams answered directly, reasoning "facets of a single enterprise" — possibly a
business-domain bias rather than genuine structural judgment). Grounded in Herbert
Simon's near-decomposability (1962): a system is decomposable when interactions
WITHIN a proposed part are much stronger than interactions BETWEEN parts. This
script deliberately does NOT change decision.py's prompt — it's designed to isolate
whether the earlier inconsistency was really domain-genre bias (business vs.
technical) or a legitimate case-by-case distinction, before touching anything.

Three questions, each chosen to break the tech-vs-business confound found in the
first eval:

A. "How does Alphabet (Google) make money?" — BUSINESS domain, but with revenue
   segments (Search ads, YouTube ads, Google Cloud, Other Bets like Waymo) that are
   about as independent as real businesses get — different customers, competitors,
   unit economics, often literally separate SEC filing segments. If business
   questions never decompose regardless of actual independence, this should still
   answer directly. If independence genuinely drives the decision, this should
   decompose more readily than PayPal did.

B. "How does a mechanical doorbell work?" — TECHNICAL domain, but genuinely a
   single, tightly-integrated circuit (button -> circuit -> chime) with no deep
   independent sub-mechanisms. If technical questions decompose reflexively
   regardless of actual structure, this would get split into arbitrary pieces
   (decomposition theater). If independence genuinely drives the decision, this
   should be answered directly, or decomposed only minimally/sensibly.

C. "How does the United Nations function?" — INSTITUTIONAL domain (neither tech
   nor business), with genuinely independent bodies (Security Council, General
   Assembly, Secretariat, ICJ) with different powers, procedures, and histories.
   Tests whether the criterion generalizes past the tech/business binary.
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
    ("A-alphabet", "How does Alphabet (Google) make money?", "Alphabet"),
    ("B-doorbell", "How does a mechanical doorbell work?", "Mechanical Doorbell"),
    ("C-un", "How does the United Nations function?", "United Nations"),
]


def _make_question(text: str, entity: str) -> Question:
    return Question(
        text=text,
        rationale="Near-decomposability research probe — see this script's docstring.",
        dimension_id="systemic_global",
        level=QuestionLevel.MASTER,
        entity_name=entity,
        abstraction_name="Near-Decomposability Probe",
    )


def _print_result(label: str, result: GroundResult, depth: int = 0) -> None:
    indent = "  " * depth
    print(f"{indent}[{label}] status={result.status.value}")
    if result.answer:
        print(f"{indent}  answer: {result.answer[:500]}")
    for i, child in enumerate(result.child_results):
        _print_result(f"{label}.child{i}", child, depth + 1)


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    for label, text, entity in QUESTIONS:
        print(f"\n{'=' * 70}\n{label}: {text}\n{'=' * 70}")
        agent = GroundAgent(_make_question(text, entity), max_depth=2, max_sequential_steps=4)
        result = await agent.run()
        _print_result(label, result)


if __name__ == "__main__":
    asyncio.run(run())
