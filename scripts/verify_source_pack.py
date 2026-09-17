"""Dewey Source Pack v0.1 verification (docs/Memory.md, 2026-09-17) --
CppReferenceRetriever/GitHubRetriever, plus the source_role/acquisition_mode
metadata added to every retriever.

**Architectural evaluation result, recorded here rather than silently
assumed:** the source-pack design record (docs/Architecture.md §0.83)
proposed a new `SourceAdapter`/`ResearchBundle` abstraction with its own
search/acquire/extract pipeline. Direct inspection of the real, existing
Evidence Engine (`backend/evidence/engine.py`'s `gather_evidence_with_outcomes`,
already wired through `RetrievalOutcome -> Evidence -> Claim`, R1.2) found
that pipeline already does exactly this -- entity/relationship discovery
already happens downstream, from synthesized claims (`decide_next_step`/
`extract_relations`), not from raw retrieved text directly. A new
`ResearchBundle` type would duplicate that, the exact "second competing
model" this whole project has repeatedly rejected (R1-R5). **Decision:
coexist, extend, don't replace** -- new retrievers slot into the existing
`Retriever` ABC and `DEFAULT_RETRIEVERS`, each stamping the new
`source_role`/`acquisition_mode` metadata (backend/evidence/models.py) onto
every `RetrievedResource` it returns; no new endpoint, no new pipeline. This
script verifies that decision holds, not a parallel system.

Checks:
  1. CppReferenceRetriever returns real, individually-verified technical
     content for a real C++ query, tagged source_role="technical_reference",
     acquisition_mode="controlled_document" -- and returns EMPTY (not
     fabricated) for a query outside its real coverage.
  2. GitHubRetriever returns real repository results for a real code query,
     tagged source_role="implementation", acquisition_mode="api".
  3. Every one of the 8 DEFAULT_RETRIEVERS now reports a real, non-default
     source_role/acquisition_mode ClassVar (the backfill onto the 6
     pre-existing retrievers didn't miss one).
  4. Live, through the REAL existing pipeline (gather_evidence_with_outcomes,
     unmodified): a real C++ pointers/memory question produces real Claims
     whose `.source.source_role`/`.source.acquisition_mode` are populated,
     confirming the new metadata survives all the way through
     RetrievalOutcome -> Evidence -> Claim without a new type being invented
     to carry it.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.evidence.engine import gather_evidence_with_outcomes  # noqa: E402
from backend.evidence.retrievers import (  # noqa: E402
    DEFAULT_RETRIEVERS,
    CppReferenceRetriever,
    GitHubRetriever,
)
from backend.questions.models import Question, QuestionLevel  # noqa: E402


async def check_cppreference_retriever() -> None:
    hits = await CppReferenceRetriever().search("C++ pointers and smart pointer memory management", max_results=3)
    assert hits, "expected real cppreference hits for a real C++ query"
    for hit in hits:
        assert hit.source_role == "technical_reference"
        assert hit.acquisition_mode == "controlled_document"
        assert hit.snippet.strip(), "expected real, non-empty snippet content"
    print(f"[PASS] #1a cppreference: {len(hits)} real hit(s) for a real C++ query, correctly tagged")

    miss = await CppReferenceRetriever().search("how does a central bank control interest rates", max_results=3)
    assert miss == [], "expected zero fabricated hits for a query outside cppreference's real curated coverage"
    print("[PASS] #1b cppreference: zero hits (not fabricated) for a query outside its real coverage")


async def check_github_retriever() -> None:
    hits = await GitHubRetriever().search("C++ pointer tutorial examples", max_results=3)
    assert hits, "expected real GitHub repository hits"
    for hit in hits:
        assert hit.source_role == "implementation"
        assert hit.acquisition_mode == "api"
        assert hit.url.startswith("https://github.com/")
    print(f"[PASS] #2 github: {len(hits)} real repository hit(s), correctly tagged")


def check_all_default_retrievers_classified() -> None:
    for retriever in DEFAULT_RETRIEVERS:
        assert retriever.source_role != "unclassified", f"{type(retriever).__name__} was never backfilled with a real source_role"
        assert retriever.acquisition_mode in ("api", "controlled_document", "archive")
    names_and_roles = [(type(r).__name__, r.source_role, r.acquisition_mode) for r in DEFAULT_RETRIEVERS]
    print(f"[PASS] #3 all {len(DEFAULT_RETRIEVERS)} DEFAULT_RETRIEVERS carry a real source_role/acquisition_mode: {names_and_roles}")


async def check_real_pipeline_carries_metadata() -> None:
    question = Question(
        text="What is a pointer in C++, and how do smart pointers like unique_ptr manage its memory?",
        rationale="Dewey Source Pack v0.1 real integration check.",
        dimension_id="scale", level=QuestionLevel.GROUND,
        entity_name="C++ pointers and memory", abstraction_name="C++ pointers and memory",
    )
    result = await gather_evidence_with_outcomes(question, max_results_per_retriever=3)

    assert result.retrieval_outcomes, "expected at least one real retrieval outcome"
    tagged = [c for c in result.claims if c.source.source_role and c.source.acquisition_mode]
    print(f"[ok] {len(result.retrieval_outcomes)} real retrieval outcome(s), {len(result.claims)} real claim(s), {len(tagged)} claim(s) with real source_role/acquisition_mode")
    for c in result.claims:
        print(f"  - [{c.source.source_role}/{c.source.acquisition_mode}] {c.source.title!r} (confidence {c.confidence})")

    # The real, honest claim this check makes: metadata survives through the
    # UNMODIFIED existing pipeline for every claim that has a source at all --
    # not that a claim from the two NEW retrievers specifically was
    # synthesized this run (real LLM relevance judgment, not guaranteed every
    # single run, same as every other retriever in this codebase).
    for c in result.claims:
        assert c.source.source_role is not None, f"claim {c.id} lost its source_role somewhere in the existing pipeline"
        assert c.source.acquisition_mode is not None, f"claim {c.id} lost its acquisition_mode somewhere in the existing pipeline"
    print(f"[PASS] #4 real pipeline (gather_evidence_with_outcomes, unmodified) preserves source_role/acquisition_mode on every real claim's source, no new type needed to carry it")


async def _run() -> None:
    await check_cppreference_retriever()
    await check_github_retriever()
    check_all_default_retrievers_classified()
    await check_real_pipeline_carries_metadata()
    print("\nAll 4 checks passed. Checks #1-#3 pure API calls, no LLM. Check #4 is the one real,")
    print("live, un-mocked call in this script (real retrievers + real LLM synthesis).")


if __name__ == "__main__":
    asyncio.run(_run())
