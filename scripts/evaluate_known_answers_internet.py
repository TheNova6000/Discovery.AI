"""Ad-hoc quality evaluation #2 — NOT a Phases.md deliverable.

Second known-answer set (2026-08-27), this time on "Modern Internet Infrastructure"
rather than payments/biology, to check the first eval's findings weren't specific
to the PayPal/CRISPR domain. The 10 questions and their expected answers/citations
were supplied by the user (originally drafted with ChatGPT's help) — used here
verbatim as the pre-registered grading rubric, not written by this script.

Two things are checked:
1. Answer quality against the user's own provided answers/citations for all 10
   questions, run independently through `GroundAgent(gather_evidence=True)`.
2. Whether the system's OWN recursive decomposition of Q1 (the broadest question,
   "how does a website request travel through the Internet?") resembles the
   DNS/TCP/HTTP/routing structure the user's design sketch proposed — run with a
   real depth budget and no forced structure, to see what actually emerges rather
   than what was hand-designed.

--- PRE-REGISTERED EXPECTATIONS (the user's own table, used as the rubric) ---

Q1  How does a website request travel through the Internet?
    Expect: DNS resolution, TCP connection, TLS encryption, HTTP request, packets
    through networks, server returns content. (Cloudflare)
Q2  How does DNS turn example.com into an IP address?
    Expect: resolver queries DNS hierarchy (root -> TLD -> authoritative
    nameserver), caching can shortcut this. (Cloudflare)
Q3  What physically carries Internet traffic?
    Expect: cables, routers, switches, radio links — real physical/wireless
    infrastructure, not an abstract "cloud". (Cloudflare)
Q4  What does a company like Cloudflare actually do inside this network?
    Expect: operates DNS/CDN/reverse-proxy services, sits between users and origin
    servers, improves security/performance/reliability. (Cloudflare Docs)
Q5  How can open-source projects become infrastructure used by huge numbers of
    systems?
    Expect: scales through communities/governance/contributors/standards; Linux
    Foundation as a neutral hub example. (Linux Foundation)
Q6  Why would a company provide infrastructure instead of only selling an
    end-user product?
    Expect: infrastructure becomes a platform others build on, creating recurring
    demand/network effects — the real question is what dependency it creates.
Q7  How does a payment actually move through a payment-processing system?
    Expect: multiple actors/stages — merchants, processors, financial
    institutions, authorization, clearing, settlement. (Stripe)
Q8  Why do payment systems need multiple layers and organizations?
    Expect: different entities specialize (initiation, processing, banking, risk,
    network, settlement); separation lets the ecosystem coordinate at scale.
    (Mastercard)
Q9  How can a relatively small open-source component become foundational to
    enormous systems?
    Expect: importance comes from dependency/network position, not organization
    size — many systems depending on an interface/standard/implementation.
    (Linux Foundation)
Q10 What actually constitutes "the Internet": companies, protocols, physical
    infrastructure, or people?
    Expect: none alone — an interconnected system of physical infrastructure,
    protocols, software, organizations, standards, users, economic/institutional
    relationships. (Cloudflare)

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

ABSTRACTION = "Modern Internet Infrastructure"

QUESTIONS = [
    ("Q1", "systemic_global", QuestionLevel.MASTER,
     "How does a website request travel through the Internet?"),
    ("Q2", "computational_network", QuestionLevel.GROUND,
     "How does DNS turn example.com into an IP address?"),
    ("Q3", "physical_infrastructure", QuestionLevel.GROUND,
     "What physically carries Internet traffic?"),
    ("Q4", "systemic_organization", QuestionLevel.GROUND,
     "What does a company like Cloudflare actually do inside the Internet's network?"),
    ("Q5", "organizational_ecosystem", QuestionLevel.MASTER,
     "How can open-source projects become infrastructure used by huge numbers of systems?"),
    ("Q6", "economic_organization", QuestionLevel.MASTER,
     "Why would a company provide infrastructure instead of only selling an end-user product?"),
    ("Q7", "financial_system", QuestionLevel.GROUND,
     "How does a payment actually move through a payment-processing system?"),
    ("Q8", "network_global", QuestionLevel.MASTER,
     "Why do payment systems need multiple layers and organizations?"),
    ("Q9", "institutional_ecosystem", QuestionLevel.MASTER,
     "How can a relatively small open-source component become foundational to enormous systems?"),
    ("Q10", "philosophical_system", QuestionLevel.MASTER,
     "What actually constitutes \"the Internet\": companies, protocols, physical infrastructure, or people?"),
]


def _make_question(dimension_id: str, level: QuestionLevel, text: str) -> Question:
    return Question(
        text=text,
        rationale="Known-answer eval #2 (internet infrastructure).",
        dimension_id=dimension_id,
        level=level,
        entity_name="Internet Infrastructure",
        abstraction_name=ABSTRACTION,
    )


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
        print(f"{indent}    url: {claim.source.url}")
    for i, child in enumerate(result.child_results):
        _print_result(f"{label}.child{i}", child, depth + 1)


async def run_flat_eval() -> None:
    for label, dim, level, text in QUESTIONS:
        print(f"\n{'=' * 70}\n{label}: {text}\n{'=' * 70}")
        agent = GroundAgent(_make_question(dim, level, text), max_depth=0, gather_evidence=True)
        result = await agent.run()
        _print_result(label, result)


async def run_q1_decomposition_test() -> None:
    print(f"\n{'=' * 70}\nQ1-DEEP: real decomposition test (max_depth=2, gather_evidence=True)\n{'=' * 70}")
    q1 = _make_question("systemic_global", QuestionLevel.MASTER,
                         "How does a website request travel through the Internet?")
    agent = GroundAgent(q1, max_depth=2, gather_evidence=True)
    result = await agent.run()
    _print_result("Q1-DEEP", result)


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    await run_flat_eval()
    await run_q1_decomposition_test()


if __name__ == "__main__":
    asyncio.run(run())
