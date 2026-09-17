"""Dewey Source Pack v0.1 -- Quality Pass (docs/Memory.md, 2026-09-17).

A diagnostic evaluation, not a pass/fail test -- matches this project's own
established `evaluate_*` convention (evaluate_known_answers.py,
evaluate_structural_judgment.py, evaluate_near_decomposability.py): run one
real, un-mocked investigation and report honestly what actually happened,
rather than assert a specific outcome. The Source Pack being "connected"
(scripts/verify_source_pack.py) and being "educationally complete" are
different properties -- this script measures the second, over one real,
controlled topic: "C++ pointers and memory" (the exact example topic named
throughout the Dewey Source Pack design conversation).

Real investigation, not a single flat gather_evidence call: a real
`GroundAgent(persist_to_graph=True, gather_evidence=True)` run, so real
decomposition (discovered concepts) and real per-concept evidence gathering
both happen, exactly the shape a real Learning Research Mode investigation
would take.

What this measures, matching the six real questions the design conversation
asked for:
  1. Coverage       -- which of a real, stated expected-concept list were
                       actually discovered (by entity name or claim text)?
  2. Source quality -- which source_roles/acquisition_modes contributed a
                       real, surviving claim?
  3. Evidence/synthesis quality -- confidence distribution, supported vs.
                       weak claims (an explicit, stated threshold, not a
                       vague "seems fine").
  4. Metadata integrity -- does every claim's source carry a real
                       source_role/acquisition_mode (a provenance check, not
                       assumed from the earlier backfill).
  5. Failure honesty -- which of the 8 retrievers contributed zero surviving
                       claims this run, reported as a real fact, not hidden.

Deliberately NOT built here: a course, a full knowledge graph, a learner
path -- per the design conversation's own explicit "keep these layers
separate" instruction. This script stops at evidence/claim quality.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import statistics
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.agents import GroundAgent, GroundResult  # noqa: E402
from backend.evidence import Claim  # noqa: E402
from backend.evidence.retrievers import DEFAULT_RETRIEVERS  # noqa: E402
from backend.graph import close_driver, find_or_create_entity, get_decomposition  # noqa: E402
from backend.questions.models import Question, QuestionLevel  # noqa: E402

TOPIC_ENTITY_NAME = "C++ pointers and memory"
SUPPORTED_CONFIDENCE_THRESHOLD = 0.5
"""A stated, explicit threshold, not a vague judgment call -- matches
synthesize_claim's own real semantics (below 0.2 is a non-answer, per R1.2;
0.5 is a real, separate, stricter bar for "supported enough to teach from,"
distinct from "survived the non-answer filter at all")."""

# A real, explicit expected-concept list, drawn directly from the Dewey
# Source Pack design conversation's own worked example -- not invented for
# this script. Each entry is a set of real keyword variants to search for in
# discovered entity names AND claim text, since an LLM-driven investigation
# will not necessarily use the exact same words as this list.
EXPECTED_CONCEPTS: dict[str, list[str]] = {
    "pointer": ["pointer"],
    "reference": ["reference"],
    "address": ["address"],
    "dereference": ["dereferenc"],
    "pointer arithmetic": ["pointer arithmetic", "arithmetic on pointer"],
    "array/pointer decay": ["array", "decay"],
    "dynamic allocation": ["dynamic", "allocat", "new/delete", " new ", " delete "],
    "stack and heap": ["stack", "heap"],
    "lifetime/ownership": ["lifetime", "ownership"],
    "smart pointer": ["smart pointer", "unique_ptr", "shared_ptr"],
    "dangling/invalid access": ["dangling", "invalid", "use-after-free", "undefined behavior"],
    "memory leak": ["memory leak", "leak"],
}


def _collect_claims(result: GroundResult) -> list[Claim]:
    claims = list(result.claims)
    for child in result.child_results:
        claims.extend(_collect_claims(child))
    return claims


def _text_mentions_any(text: str, variants: list[str]) -> bool:
    text_lower = text.lower()
    return any(v in text_lower for v in variants)


async def run() -> dict:
    entity = await find_or_create_entity(TOPIC_ENTITY_NAME)

    question = Question(
        text="What are pointers in C++, how is memory allocated and managed with them, and what are the common risks (dangling pointers, memory leaks)?",
        rationale="Dewey Source Pack v0.1 Quality Pass -- real, controlled evaluation topic.",
        dimension_id="scale", level=QuestionLevel.MASTER,
        entity_name=TOPIC_ENTITY_NAME, abstraction_name=TOPIC_ENTITY_NAME,
    )

    agent = GroundAgent(
        question,
        max_depth=2,
        max_sequential_steps=3,
        gather_evidence=True,
        persist_to_graph=True,
    )
    ground_result = await agent.run()

    all_claims = _collect_claims(ground_result)
    supported_claims_for_coverage = [c for c in all_claims if c.confidence >= SUPPORTED_CONFIDENCE_THRESHOLD]

    # Real discovered concepts, read back from the real graph -- the same
    # authoritative source scripts/verify_graph_persistence.py already
    # trusts, not reconstructed from in-memory decompose decisions.
    discovered_nodes = await get_decomposition(entity.id)
    discovered_names = [n.name for n in discovered_nodes]

    # Coverage: does a discovered entity name OR a SUPPORTED claim's text
    # mention each expected concept's real keyword variants? Deliberately
    # excludes weak (< threshold) claims from this check -- a real bug found
    # running this script the first time (2026-09-17, docs/Memory.md): a weak
    # claim reading "...does not cover delete, malloc, free, or smart
    # pointers" made "smart pointer" register as a false positive, since the
    # concept's own NAME appeared in the text even though the claim's actual
    # content says the opposite of "covered." Simple substring matching
    # cannot distinguish "explains X" from "explicitly says it does not cover
    # X" -- restricting the check to claims that already cleared the
    # supported-confidence bar is an honest, partial mitigation (not a full
    # fix; a genuinely thorough one would need real negation-aware judgment,
    # out of scope for this diagnostic script), stated here rather than left
    # to silently overclaim coverage.
    supported_claim_text = " ".join(c.evidence for c in supported_claims_for_coverage)
    discovered_concepts: list[str] = []
    missing_concepts: list[str] = []
    for concept, variants in EXPECTED_CONCEPTS.items():
        found_in_names = any(_text_mentions_any(name, variants) for name in discovered_names)
        found_in_claims = _text_mentions_any(supported_claim_text, variants)
        if found_in_names or found_in_claims:
            discovered_concepts.append(concept)
        else:
            missing_concepts.append(concept)

    supported_claims = [c for c in all_claims if c.confidence >= SUPPORTED_CONFIDENCE_THRESHOLD]
    weak_claims = [c for c in all_claims if c.confidence < SUPPORTED_CONFIDENCE_THRESHOLD]

    source_roles_used = sorted({c.source.source_role for c in all_claims if c.source.source_role})
    acquisition_modes_used = sorted({c.source.acquisition_mode for c in all_claims if c.source.acquisition_mode})

    # Provenance/metadata integrity -- a real check, not assumed from the
    # earlier backfill commit.
    provenance_errors = [
        c.id for c in all_claims
        if c.source.source_role is None or c.source.acquisition_mode is None
    ]

    contributing_retriever_roles = {r.source_role for r in DEFAULT_RETRIEVERS}
    roles_with_zero_claims = sorted(contributing_retriever_roles - set(source_roles_used))

    confidences = [c.confidence for c in all_claims]
    confidence_distribution = {
        "count": len(confidences),
        "min": round(min(confidences), 3) if confidences else None,
        "max": round(max(confidences), 3) if confidences else None,
        "mean": round(statistics.mean(confidences), 3) if confidences else None,
        "median": round(statistics.median(confidences), 3) if confidences else None,
    }

    report = {
        "topic": TOPIC_ENTITY_NAME,
        "investigation_status": ground_result.status.value,
        "discovered_entities": discovered_names,
        "expected_concepts_found": discovered_concepts,
        "expected_concepts_missing": missing_concepts,
        "total_claims": len(all_claims),
        "supported_claims": [
            {"text": c.evidence, "confidence": c.confidence, "source": c.source.title, "role": c.source.source_role}
            for c in supported_claims
        ],
        "weak_claims": [
            {"text": c.evidence, "confidence": c.confidence, "source": c.source.title, "role": c.source.source_role}
            for c in weak_claims
        ],
        "source_roles_used": source_roles_used,
        "acquisition_modes_used": acquisition_modes_used,
        "roles_contributing_zero_claims_this_run": roles_with_zero_claims,
        "provenance_errors": provenance_errors,
        "confidence_distribution": confidence_distribution,
    }
    return report


async def _run_and_close() -> dict:
    try:
        return await run()
    finally:
        await close_driver()


if __name__ == "__main__":
    report = asyncio.run(_run_and_close())
    print(json.dumps(report, indent=2))

    print("\n--- summary (docs/Memory.md's six real questions) ---", file=sys.stderr)
    print(f"1. Coverage: {len(report['expected_concepts_found'])}/{len(EXPECTED_CONCEPTS)} expected concepts found. Missing: {report['expected_concepts_missing']}", file=sys.stderr)
    print(f"2. Source quality: roles contributing a surviving claim: {report['source_roles_used']}. Zero-contribution roles this run: {report['roles_contributing_zero_claims_this_run']}", file=sys.stderr)
    print(f"3. Evidence/synthesis quality: {len(report['supported_claims'])} supported (>= {SUPPORTED_CONFIDENCE_THRESHOLD}), {len(report['weak_claims'])} weak, of {report['total_claims']} total. Distribution: {report['confidence_distribution']}", file=sys.stderr)
    print(f"4. Metadata integrity: {len(report['provenance_errors'])} claim(s) missing source_role/acquisition_mode (expect 0)", file=sys.stderr)
    print(f"5. Investigation status: {report['investigation_status']}", file=sys.stderr)
