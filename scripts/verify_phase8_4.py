"""Phase 8.4 verification -- Deep investigation orchestration, the bounded
planning logic only (docs/Phases.md Phase 8.4, docs/PRD.md §9.3a,
docs/Architecture.md §0.44, backend/research/investigate.py).

Same split as every prior phase in this track: `plan_targeted_investigations`
is a pure function over an already-computed ResearchReadinessReport
(Phase 8.3, pydantic-only), so it's testable here with hand-built fixtures
and zero LLM/retriever/Neo4j calls. `run_targeted_investigation` (one real
GroundAgent investigation per call) and `close_coverage_gaps` (the full
orchestration loop) are NOT exercised by this script -- they need a live LLM
key and Neo4j, neither guaranteed in every environment this runs in. This
file's __main__ block prints instructions for the separate live smoke test
that actually exercises them, same pattern Phase 8.1's verify script used.

Six checks:
  1. A complete concept contributes zero requests.
  2. A concept whose only missing field is confidence-gated (not in
     UNCLASSIFIED_FIELDS) contributes zero requests -- this module never
     targets a gap it can't actually close.
  3. A concept with multiple missing unclassified fields produces one
     request per field, correctly identified.
  4. max_fields_per_target actually caps the field count per concept.
  5. max_targets actually caps how many DIFFERENT concepts get processed --
     confirmed a concept skipped for having no unclassified gap does not
     count against this budget.
  6. Every UNCLASSIFIED_FIELDS member has a real question template (the
     module-level assertion in investigate.py itself, re-checked here so a
     future field added to UNCLASSIFIED_FIELDS without a matching template
     fails a test, not silently at runtime).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.research import ConceptCompleteness, FieldCoverage, ResearchReadinessReport  # noqa: E402
from backend.research.investigate import _FIELD_QUESTION_TEMPLATES, plan_targeted_investigations  # noqa: E402
from backend.research.models import UNCLASSIFIED_FIELDS  # noqa: E402


def _concept(entity_id: str, name: str, missing: list[str]) -> ConceptCompleteness:
    fc = [FieldCoverage(field=f, status="missing", reason="fixture") for f in missing]
    return ConceptCompleteness(
        entity_id=entity_id, entity_name=name, field_coverage=fc, is_complete=not missing, missing_fields=frozenset(missing)
    )


def _report(concepts: list[ConceptCompleteness]) -> ResearchReadinessReport:
    ready = sum(1 for c in concepts if c.is_complete)
    return ResearchReadinessReport(
        abstraction_id="a1",
        abstraction_name="fixture abstraction",
        policy=EXPLORATORY_POLICY,
        concepts=concepts,
        ready_count=ready,
        incomplete_count=len(concepts) - ready,
        is_ready=ready == len(concepts),
    )


def check_complete_concept_yields_no_requests() -> None:
    report = _report([_concept("e1", "Complete", [])])
    requests = plan_targeted_investigations(report)
    assert requests == []
    print("[PASS] check_complete_concept_yields_no_requests: complete concept -> zero requests")


def check_confidence_gated_only_gap_yields_no_requests() -> None:
    report = _report([_concept("e1", "Needs definition only", ["definition"])])
    requests = plan_targeted_investigations(report)
    assert requests == [], "a confidence-gated-only gap must never be targeted by this module"
    print("[PASS] check_confidence_gated_only_gap_yields_no_requests: confidence-gated-only gap -> zero requests")


def check_multiple_unclassified_fields_each_get_a_request() -> None:
    report = _report([_concept("e1", "Needs two", ["examples", "misconceptions"])])
    requests = plan_targeted_investigations(report)
    assert {r.field for r in requests} == {"examples", "misconceptions"}
    assert all(r.entity_id == "e1" and r.entity_name == "Needs two" for r in requests)
    print("[PASS] check_multiple_unclassified_fields_each_get_a_request: 2 missing unclassified fields -> 2 requests")


def check_max_fields_per_target_caps_field_count() -> None:
    report = _report([_concept("e1", "Needs three", ["prerequisites", "examples", "misconceptions"])])
    requests = plan_targeted_investigations(report, max_fields_per_target=1)
    assert len(requests) == 1
    print("[PASS] check_max_fields_per_target_caps_field_count: 3 missing fields, cap=1 -> 1 request")


def check_max_targets_caps_concepts_not_skipped_ones() -> None:
    report = _report(
        [
            _concept("e1", "Actionable A", ["examples"]),
            _concept("e2", "Skipped, confidence-gated only", ["mechanism"]),
            _concept("e3", "Actionable B", ["misconceptions"]),
            _concept("e4", "Actionable C", ["prerequisites"]),
        ]
    )
    requests = plan_targeted_investigations(report, max_targets=2)
    entities = {r.entity_id for r in requests}
    assert entities == {"e1", "e3"}, "e2 (skipped, no unclassified gap) must not consume the max_targets budget"
    print("[PASS] check_max_targets_caps_concepts_not_skipped_ones: max_targets=2 correctly picks e1+e3, skips e2 for free")


def check_every_unclassified_field_has_a_template() -> None:
    assert set(_FIELD_QUESTION_TEMPLATES) == UNCLASSIFIED_FIELDS
    for field, template in _FIELD_QUESTION_TEMPLATES.items():
        assert "{entity_name}" in template, f"{field!r}'s template must be parameterized by entity_name"
    print("[PASS] check_every_unclassified_field_has_a_template: template coverage matches UNCLASSIFIED_FIELDS exactly")


if __name__ == "__main__":
    check_complete_concept_yields_no_requests()
    check_confidence_gated_only_gap_yields_no_requests()
    check_multiple_unclassified_fields_each_get_a_request()
    check_max_fields_per_target_caps_field_count()
    check_max_targets_caps_concepts_not_skipped_ones()
    check_every_unclassified_field_has_a_template()
    print("\nAll 6 checks passed. This covers plan_targeted_investigations' pure logic")
    print("only -- no LLM, retriever, or Neo4j call was made. Separately confirm the")
    print("live orchestration actually closes a real gap (this phase's own live smoke")
    print("test): run close_coverage_gaps against a real incomplete ResearchPlan/report")
    print("(e.g. a 'learning'-shaped policy over the real 'online payment' abstraction)")
    print("and confirm ready_count increases and the new evidence is real, tagged, and")
    print("visible on a re-run of build_readiness_report.")
