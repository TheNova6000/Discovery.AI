"""Ad-hoc quality evaluation #3 — NOT a Phases.md deliverable.

Tests whether MASTER-level decisions make a DEFENSIBLE STRUCTURAL JUDGMENT, not
whether they decompose. "Good Master Decision = Correct structural representation",
not "= Decompose" — a MASTER question that is genuinely one tightly-coupled
phenomenon should be answered directly, not force-split into arbitrary pieces
("decomposition theater"). Only Q1-Q3 are pre-registered as "should discover real
separable structure"; Q4 is explicitly pre-registered as legitimately either
outcome — the grading question for it is "did the agent make a defensible call,"
not "did it decompose."

Run through the real fallback chain, no artificial cost-reduction — free-tier
rate-limit behavior under real use is itself useful operational information at this
stage, not noise to eliminate.

--- PRE-REGISTERED EXPECTATIONS (written before running) ---

Q1 "How does a website request travel through the Internet?"
   Tests: can it discover a mechanism/system decomposition?
   GOOD: represents the real separable structure — DNS resolution, the
   TCP/TLS connection, and network transport/routing as distinct components —
   whether via decompose (preferred) or, at minimum, an answer that clearly
   distinguishes them as separate phases rather than one flat narrative.
   BAD: a decomposition into arbitrary/meaningless pieces, or an answer that
   flattens the real structure into an undifferentiated paragraph.

Q2 "How does PayPal make money?"
   Tests: can it discover economically meaningful components?
   GOOD: identifies genuine distinct revenue streams — merchant transaction fees
   (primary), plus at least one of currency conversion, lending/credit interest,
   or subsidiary revenue — as separable economic mechanisms.
   BAD: a vague or factually wrong revenue model, or decomposition into pieces
   that aren't real distinct economic mechanisms.

Q3 "How does a pharmaceutical company take a new drug from research to market?"
   Tests: can it discover organizational/process structure?
   GOOD: identifies the genuine sequential stages — discovery/preclinical
   research, clinical trials (phases I-III), regulatory approval, manufacturing
   and distribution — as real, ordered, separable process stages.
   BAD: vague or missing the real regulatory/process structure.

Q4 "Why does money have value?"
   Tests: can it recognize a LEGITIMATE multi-perspective phenomenon without
   manufacturing a decomposition it doesn't need? EITHER outcome can be correct:
   GOOD (decompose): genuinely separate investigable angles (e.g. economic backing
   /trust mechanisms, psychological/social convention, historical evolution from
   commodity to fiat money) treated as distinct.
   GOOD (answer): one synthesized explanation that itself names and connects the
   economic/psychological/historical/institutional facets, rather than picking one
   narrow angle and ignoring the rest.
   BAD: an arbitrary/meaningless split, OR a shallow single-facet answer (e.g.
   "because the government says so") that ignores the phenomenon's other real
   dimensions.

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
    ("Q1", "How does a website request travel through the Internet?", "Internet Infrastructure"),
    ("Q2", "How does PayPal make money?", "PayPal"),
    ("Q3", "How does a pharmaceutical company take a new drug from research to market?", "Drug Development"),
    ("Q4", "Why does money have value?", "Money"),
]


def _make_question(text: str, entity: str) -> Question:
    return Question(
        text=text,
        rationale="Structural-judgment eval — see pre-registered expectations in this script's docstring.",
        dimension_id="systemic_global",
        level=QuestionLevel.MASTER,
        entity_name=entity,
        abstraction_name="Structural Judgment Eval",
    )


def _print_result(label: str, result: GroundResult, depth: int = 0) -> None:
    indent = "  " * depth
    print(f"{indent}[{label}] status={result.status.value}")
    if result.answer:
        print(f"{indent}  answer: {result.answer}")
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

    print("\nDone — grade each question's [ground:...] reasoning lines and final structure above")
    print("against the pre-registered expectations in this script's docstring.")


if __name__ == "__main__":
    asyncio.run(run())
