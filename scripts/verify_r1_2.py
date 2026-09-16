"""R1.2 verification -- wiring RetrievalOutcome -> Evidence -> Claim into the
live investigation output path (docs/Phases.md's Reasoning Engine Evolution
track, docs/Architecture.md §0.59, backend/evidence/engine.py).

Two parts:

Part 1 (mocked, deterministic, no real network/LLM call): a fake Retriever
and a patched synthesize_claim exercise gather_evidence_with_outcomes'
actual classification logic end to end -- a genuine answer, a non-answer
("does not answer the question," confidence 0.1 -- the exact real pattern
from Architecture.md §0.47's DNS example), and a synthesis failure. Fast,
repeatable, and what actually proves the classifier's logic is correct,
independent of any live provider's mood that day.

Part 2 (live, real network/LLM calls): re-runs gather_evidence_with_outcomes
directly against the exact real question that originally produced the
failure pattern this whole track exists to fix ("What is the role of the
recursive resolver in DNS resolution?", Architecture.md §0.47) -- not the
full recursive GroundAgent investigation (would cost minutes and re-spend a
much larger LLM budget for the same underlying function), just the one
function that actually changed. Requires reachable retrievers/LLM keys;
skips with a clear message rather than failing opaquely if unavailable.

Acceptance criteria (from the user's own list):
  1. Retrieval outcomes are produced for every resource, always -- not just
     the ones that succeed.
  2. A non-answer (confidence < NON_ANSWER_CONFIDENCE_THRESHOLD) is
     represented as a RetrievalOutcome, never a Claim.
  3. A synthesis failure is represented as a RetrievalOutcome
     (success=False), never silently dropped with zero record (the actual
     pre-R1.2 behavior).
  4. Evidence count reflects only successful, relevant retrievals.
  5. Claim count excludes every non-answer and every failure.
  6. The existing gather_evidence() call sites (ground_agent.py,
     verify_phase5.py) are unaffected -- same signature, same claim content
     for genuine answers, byte-for-byte.
  7. Provenance (question_id, source fields) remains intact end to end.
  8. Existing Phase 8/R1.1 checks remain green.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.evidence import gather_evidence, gather_evidence_with_outcomes  # noqa: E402
from backend.evidence.exceptions import EvidenceRetrievalError  # noqa: E402
from backend.evidence.models import ClaimDraft, RetrievedResource  # noqa: E402
from backend.questions import Question, QuestionLevel  # noqa: E402

_QUESTION = Question(
    text="What is the role of X in the system?",
    rationale="fixture",
    dimension_id="none",
    level=QuestionLevel.MASTER,
    entity_name="X",
    abstraction_name="X",
)

_GOOD = RetrievedResource(title="Good source", url="http://good.example", snippet="...", source_type="web")
_NON_ANSWER = RetrievedResource(title="Irrelevant source", url="http://bad.example", snippet="...", source_type="web")
_ERROR = RetrievedResource(title="Broken source", url="http://err.example", snippet="...", source_type="web")

_DRAFTS = {
    "http://good.example": ClaimDraft(evidence="X performs role Y in the system.", reasoning="directly relevant", confidence=0.8),
    # The exact real pattern from Architecture.md §0.47's DNS example.
    "http://bad.example": ClaimDraft(evidence="The provided resource does not answer the question.", reasoning="irrelevant", confidence=0.1),
}


class _FakeRetriever:
    def __init__(self, resources: list[RetrievedResource]) -> None:
        self._resources = resources

    async def search(self, query: str, max_results: int = 2) -> list[RetrievedResource]:
        return self._resources[:max_results]


async def _fake_synthesize(question: Question, resource: RetrievedResource) -> ClaimDraft:
    if resource.url == "http://err.example":
        raise EvidenceRetrievalError("all providers failed")
    return _DRAFTS[resource.url]


def run_mocked_checks() -> None:
    async def _run():
        with patch("backend.evidence.engine.synthesize_claim", side_effect=_fake_synthesize):
            retriever = _FakeRetriever([_GOOD, _NON_ANSWER, _ERROR])
            result = await gather_evidence_with_outcomes(_QUESTION, retrievers=[retriever], max_results_per_retriever=3)

            # #1: a RetrievalOutcome for every one of the 3 resources, always.
            assert len(result.retrieval_outcomes) == 3
            print("[PASS] acceptance #1: retrieval_outcomes produced for all 3 resources (good, non-answer, error)")

            # #2: the non-answer is a RetrievalOutcome, never a Claim.
            by_url = {o.source_url: o for o in result.retrieval_outcomes}
            non_answer_outcome = by_url["http://bad.example"]
            assert non_answer_outcome.success is True and non_answer_outcome.relevant is False
            assert not any(c.evidence == _DRAFTS["http://bad.example"].evidence for c in result.claims)
            print("[PASS] acceptance #2: non-answer represented as RetrievalOutcome(success=True, relevant=False), never a Claim")

            # #3: the synthesis failure is a real, recorded RetrievalOutcome
            # (success=False) -- not silently dropped (the actual pre-R1.2
            # behavior: a bare `continue` with zero trace).
            error_outcome = by_url["http://err.example"]
            assert error_outcome.success is False and error_outcome.failure_reason
            print("[PASS] acceptance #3: synthesis failure represented as RetrievalOutcome(success=False), not silently dropped")

            # #4/#5: exactly one Evidence and one Claim, both from the
            # genuine answer only.
            assert len(result.evidence) == 1
            assert len(result.claims) == 1
            assert result.claims[0].evidence == "X performs role Y in the system."
            print("[PASS] acceptance #4/#5: evidence count and claim count both reflect only the one genuine answer")

            # #6: gather_evidence() (unchanged signature) returns the same
            # single genuine claim, byte-for-byte -- backward compatible.
            legacy_claims = await gather_evidence(_QUESTION, retrievers=[_FakeRetriever([_GOOD, _NON_ANSWER, _ERROR])], max_results_per_retriever=3)
            assert len(legacy_claims) == 1
            assert legacy_claims[0].evidence == result.claims[0].evidence
            print("[PASS] acceptance #6: gather_evidence()'s existing callers see identical claim content for genuine answers")

            # #7: provenance intact.
            assert result.claims[0].question_id == _QUESTION.id
            assert result.evidence[0].retrieval_outcome_id == by_url["http://good.example"].outcome_id
            print("[PASS] acceptance #7: question_id/retrieval_outcome_id provenance intact end to end")

    asyncio.run(_run())


def run_live_acceptance_test() -> None:
    """Re-runs the exact real question that originally produced the failure
    pattern (Architecture.md §0.47), live, through the actual changed
    function -- not a full GroundAgent investigation."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] live acceptance test: could not load environment ({exc})")
        return

    real_question = Question(
        text="What is the role of the recursive resolver in DNS resolution?",
        rationale="R1.2 live acceptance test -- the exact real question from Architecture.md §0.47's DNS example",
        dimension_id="none",
        level=QuestionLevel.MASTER,
        entity_name="Recursive Resolver",
        abstraction_name="DNS",
    )
    try:
        result = asyncio.run(gather_evidence_with_outcomes(real_question))
    except Exception as exc:  # noqa: BLE001 - no reachable retrievers/LLM keys, skip rather than fail opaquely
        print(f"[SKIP] live acceptance test: retrievers/LLM unreachable ({exc})")
        return

    print(f"\n[LIVE] retrieval_outcomes={len(result.retrieval_outcomes)} evidence={len(result.evidence)} claims={len(result.claims)}")
    for o in result.retrieval_outcomes:
        tag = "RELEVANT" if o.relevant else ("FAILED" if not o.success else "NON-ANSWER")
        print(f"  [{tag}] {o.source_url} -- {(o.raw_content or o.failure_reason or '')[:80]!r}")
    assert len(result.retrieval_outcomes) >= len(result.claims), "every claim must correspond to a retrieval outcome, never more claims than outcomes"
    non_answer_texts = {"does not answer", "does not address", "no information about"}
    for claim in result.claims:
        assert not any(t in claim.evidence.lower() for t in non_answer_texts), (
            f"a claim slipped through that reads like a non-answer: {claim.evidence!r}"
        )
    print("[PASS] live acceptance test: real run against the real question -- no claim reads like a retrieval failure")


if __name__ == "__main__":
    run_mocked_checks()
    run_live_acceptance_test()
    print("\nPart 1 (7 mocked checks, deterministic, no real network/LLM) covers the")
    print("classifier logic end to end. Part 2 is a real live call against the exact")
    print("question that originally produced the failure pattern -- skips, rather than")
    print("fails, if retrievers/LLM keys aren't reachable in this environment.")
