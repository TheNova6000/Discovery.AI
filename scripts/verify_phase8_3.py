"""Phase 8.3 verification -- Coverage/Completeness model, pure logic only
(docs/Phases.md Phase 8.3, docs/PRD.md §9.3a, docs/Architecture.md §0.43,
backend/research/coverage.py).

Same split as Phase 6/8.1/8.2's own verify scripts: `assess_target_completeness`
and `assess_plan_readiness` are pure functions over already-fetched data
(ConceptResearchTarget from Phase 8.2, ClaimNode -- pydantic-only, no neo4j
package required), so they're testable here with hand-built fixtures and zero
LLM/retriever/Neo4j calls. `coverage.build_readiness_report`'s own I/O shell
(the get_questions_for_entity/get_claims_for_question calls) is NOT exercised
by this script, same scoping note every prior phase's verify script made.

Six checks:
  1. A target whose only required fields are confidence-gated (definition,
     mechanism) is complete once a claim meets the confidence threshold.
  2. The same target is NOT complete when its only claim falls below the
     threshold -- confidence actually gates completeness, not just presence.
  3. A target with zero claims at all is NOT complete, and every required
     field is reported missing (the "no evidence" case, unambiguous).
  4. A superseded claim does not count as current evidence -- completeness
     must be assessed against the LIVE claim set, not a stale one still
     sitting in the list.
  5. A target requiring the three unclassified fields (prerequisites/
     examples/misconceptions) is honestly NEVER complete today, even with
     strong qualifying evidence -- proves this phase doesn't fabricate
     field-level precision it doesn't have.
  6. assess_plan_readiness correctly rolls up ready/incomplete counts and
     is_ready across a mixed plan (one complete target, one incomplete one).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph.models import ClaimNode  # noqa: E402
from backend.research import (  # noqa: E402
    ConceptResearchTarget,
    ResearchPlan,
    assess_plan_readiness,
    assess_target_completeness,
)
from backend.agents.policy import EXPLORATORY_POLICY, ResearchPolicy  # noqa: E402

_NOW = "2026-01-01T00:00:00+00:00"


def _claim(claim_id: str, confidence: float, superseded_by: str | None = None) -> ClaimNode:
    return ClaimNode(
        id=claim_id,
        evidence="fixture evidence",
        reasoning="fixture reasoning",
        confidence=confidence,
        source_title="fixture source",
        source_url="http://example.invalid",
        source_type="web",
        valid_from=_NOW,
        superseded_by=superseded_by,
    )


_BASE_TARGET = ConceptResearchTarget(
    entity_id="e1", entity_name="Pointers", required_fields=frozenset({"definition", "mechanism"})
)
_LEARNING_TARGET = ConceptResearchTarget(
    entity_id="e2",
    entity_name="References",
    required_fields=frozenset({"definition", "mechanism", "prerequisites", "examples", "misconceptions", "evidence"}),
)


def check_qualifying_evidence_completes_base_fields() -> None:
    result = assess_target_completeness(_BASE_TARGET, [_claim("c1", 0.8)], confidence_threshold=0.5)
    assert result.is_complete is True
    assert result.missing_fields == frozenset()
    print("[PASS] check_qualifying_evidence_completes_base_fields: confidence 0.8 >= 0.5 -> complete")


def check_below_threshold_evidence_is_incomplete() -> None:
    result = assess_target_completeness(_BASE_TARGET, [_claim("c1", 0.1)], confidence_threshold=0.5)
    assert result.is_complete is False
    assert result.missing_fields == frozenset({"definition", "mechanism"})
    print("[PASS] check_below_threshold_evidence_is_incomplete: confidence 0.1 < 0.5 -> incomplete, both base fields missing")


def check_no_claims_is_incomplete_with_all_fields_missing() -> None:
    result = assess_target_completeness(_BASE_TARGET, [], confidence_threshold=0.0)
    assert result.is_complete is False
    assert result.missing_fields == frozenset({"definition", "mechanism"})
    print("[PASS] check_no_claims_is_incomplete_with_all_fields_missing: zero claims -> incomplete even at threshold 0.0")


def check_superseded_claims_do_not_count() -> None:
    # Only claim is superseded -- must be treated as zero live evidence, not
    # one qualifying claim, even though its own confidence is high.
    result = assess_target_completeness(_BASE_TARGET, [_claim("c1", 0.95, superseded_by="c2")], confidence_threshold=0.5)
    assert result.is_complete is False
    print("[PASS] check_superseded_claims_do_not_count: a superseded high-confidence claim is correctly excluded")


def check_unclassified_fields_never_complete_today() -> None:
    result = assess_target_completeness(_LEARNING_TARGET, [_claim("c1", 0.95)], confidence_threshold=0.5)
    assert result.is_complete is False
    assert result.missing_fields == frozenset({"prerequisites", "examples", "misconceptions"})
    # The confidence-gated third of the six fields DID get satisfied by the
    # strong claim -- only the three unclassified ones are missing, proving
    # this isn't just "always fails," it's specifically the unclassified gap.
    present = {fc.field for fc in result.field_coverage if fc.status == "present"}
    assert present == frozenset({"definition", "mechanism", "evidence"})
    print("[PASS] check_unclassified_fields_never_complete_today: strong evidence still leaves prerequisites/examples/misconceptions honestly missing")


def check_plan_readiness_rollup() -> None:
    learning_policy = ResearchPolicy(
        mode="learning",
        max_depth=2,
        max_sequential_steps=3,
        gather_evidence=True,
        max_results_per_retriever=2,
        require_prerequisites=False,
        require_examples=False,
        require_misconceptions=False,
        require_evidence_validation=False,
        confidence_threshold=0.5,
    )
    plan = ResearchPlan(
        abstraction_id="a1",
        abstraction_name="fixture abstraction",
        policy=learning_policy,
        targets=[_BASE_TARGET, ConceptResearchTarget(entity_id="e3", entity_name="Dangling Pointers", required_fields=frozenset({"definition", "mechanism"}))],
    )
    claims_by_entity = {"e1": [_claim("c1", 0.9)], "e3": []}
    report = assess_plan_readiness(plan, claims_by_entity)
    assert report.ready_count == 1
    assert report.incomplete_count == 1
    assert report.is_ready is False
    print("[PASS] check_plan_readiness_rollup: 1 complete + 1 incomplete -> ready_count=1, incomplete_count=1, is_ready=False")


if __name__ == "__main__":
    check_qualifying_evidence_completes_base_fields()
    check_below_threshold_evidence_is_incomplete()
    check_no_claims_is_incomplete_with_all_fields_missing()
    check_superseded_claims_do_not_count()
    check_unclassified_fields_never_complete_today()
    check_plan_readiness_rollup()
    print("\nAll 6 checks passed. This covers coverage/completeness pure logic only --")
    print("no LLM, retriever, or Neo4j call was made. build_readiness_report's own I/O")
    print("shell is not exercised here, same scoping as every prior phase's verify script.")
