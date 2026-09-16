"""Phase 8.5 verification -- Evidence and contradiction validation, the
deterministic layer only (docs/Phases.md Phase 8.5, docs/PRD.md §9.3a,
docs/Architecture.md §0.45, backend/research/validation.py).

Same split as every prior phase in this track: `assess_claim_validity` is a
pure function over already-fetched ClaimNodes (pydantic-only, no neo4j
package required), so it's testable here with hand-built fixtures and zero
LLM/retriever/Neo4j calls. `detect_contradictions` (the one real LLM call in
this module, reusing backend.questions.analyze_claim_relationships) is NOT
exercised by this script -- it needs a live LLM key, not guaranteed in every
environment this runs in. This file's __main__ block prints instructions for
the separate live smoke test that actually exercises it, same pattern every
phase in this track has used for its one real-LLM-call module.

Six checks:
  1. Two claims citing the identical source_url are flagged as duplicates,
     reason "identical source_url".
  2. Two claims with identical evidence text but different source_urls are
     flagged as duplicates, reason "identical evidence text" -- the second,
     independent duplicate-detection path.
  3. A superseded claim is excluded from active_claim_count/weak_claim_ids
     but still surfaced in superseded_claim_ids -- visible, not silently
     dropped the way Phase 8.3's coverage model drops it.
  4. A claim below the weak-confidence threshold is flagged in
     weak_claim_ids; one at or above it is not.
  5. distinct_source_count and has_independent_support correctly reflect
     DISTINCT non-superseded sources, not raw active claim count -- three
     claims all citing the same URL must NOT count as independent support.
  6. A concept with zero claims produces a valid, non-crashing report (zero
     everything, has_independent_support=False) -- bounded-view honesty,
     same principle every prior phase's empty-input check already followed.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph.models import ClaimNode  # noqa: E402
from backend.research import assess_claim_validity  # noqa: E402

_NOW = "2026-01-01T00:00:00+00:00"


def _claim(claim_id: str, confidence: float, source_url: str, evidence: str, superseded_by: str | None = None) -> ClaimNode:
    return ClaimNode(
        id=claim_id,
        evidence=evidence,
        reasoning="fixture reasoning",
        confidence=confidence,
        source_title="fixture source",
        source_url=source_url,
        source_type="web",
        valid_from=_NOW,
        superseded_by=superseded_by,
    )


def check_identical_source_url_flagged_as_duplicate() -> None:
    claims = [_claim("c1", 0.8, "http://a.example", "Evidence A"), _claim("c2", 0.8, "http://a.example", "Different wording")]
    report = assess_claim_validity("e1", "Fixture Entity", claims)
    assert len(report.duplicate_pairs) == 1
    assert report.duplicate_pairs[0].reason == "identical source_url"
    print("[PASS] check_identical_source_url_flagged_as_duplicate: same source_url -> flagged")


def check_identical_evidence_text_flagged_as_duplicate() -> None:
    claims = [_claim("c1", 0.8, "http://a.example", "Same evidence text"), _claim("c2", 0.8, "http://b.example", "Same evidence text")]
    report = assess_claim_validity("e1", "Fixture Entity", claims)
    assert len(report.duplicate_pairs) == 1
    assert report.duplicate_pairs[0].reason == "identical evidence text"
    print("[PASS] check_identical_evidence_text_flagged_as_duplicate: same evidence, different source -> flagged")


def check_superseded_excluded_but_still_surfaced() -> None:
    claims = [
        _claim("c1", 0.9, "http://a.example", "Live evidence"),
        _claim("c2", 0.95, "http://b.example", "Stale evidence", superseded_by="c1"),
    ]
    report = assess_claim_validity("e1", "Fixture Entity", claims)
    assert report.active_claim_count == 1
    assert report.weak_claim_ids == []
    assert report.superseded_claim_ids == ["c2"]
    print("[PASS] check_superseded_excluded_but_still_surfaced: superseded claim excluded from active count, still visible in report")


def check_weak_confidence_flagged_correctly() -> None:
    claims = [_claim("c1", 0.1, "http://a.example", "Weak"), _claim("c2", 0.9, "http://b.example", "Strong")]
    report = assess_claim_validity("e1", "Fixture Entity", claims, weak_confidence_threshold=0.3)
    assert report.weak_claim_ids == ["c1"]
    print("[PASS] check_weak_confidence_flagged_correctly: below-threshold claim flagged, above-threshold claim not")


def check_independent_support_requires_distinct_sources() -> None:
    same_source = [_claim(f"c{i}", 0.8, "http://a.example", f"Evidence {i}") for i in range(3)]
    report_same = assess_claim_validity("e1", "Fixture Entity", same_source)
    assert report_same.distinct_source_count == 1
    assert report_same.has_independent_support is False

    two_sources = [_claim("c1", 0.8, "http://a.example", "A"), _claim("c2", 0.8, "http://b.example", "B")]
    report_two = assess_claim_validity("e1", "Fixture Entity", two_sources)
    assert report_two.distinct_source_count == 2
    assert report_two.has_independent_support is True
    print("[PASS] check_independent_support_requires_distinct_sources: 3 claims/1 source -> not independent; 2 claims/2 sources -> independent")


def check_empty_claims_yields_valid_empty_report() -> None:
    report = assess_claim_validity("e1", "Fixture Entity", [])
    assert report.active_claim_count == 0
    assert report.duplicate_pairs == []
    assert report.distinct_source_count == 0
    assert report.has_independent_support is False
    print("[PASS] check_empty_claims_yields_valid_empty_report: zero claims -> zero everything, no crash")


if __name__ == "__main__":
    check_identical_source_url_flagged_as_duplicate()
    check_identical_evidence_text_flagged_as_duplicate()
    check_superseded_excluded_but_still_surfaced()
    check_weak_confidence_flagged_correctly()
    check_independent_support_requires_distinct_sources()
    check_empty_claims_yields_valid_empty_report()
    print("\nAll 6 checks passed. This covers assess_claim_validity's pure logic only --")
    print("no LLM, retriever, or Neo4j call was made. Separately confirm detect_contradictions")
    print("(this phase's one real LLM call, live smoke test): run it against a real concept's")
    print("claims (e.g. the real 'online payment' abstraction's entities) and confirm it either")
    print("returns checked=True with a real, reasoned finding list, or checked=False with an")
    print("honest skipped_reason -- never a silent crash or a fabricated finding.")
