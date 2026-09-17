"""Dewey's curriculum-concept coverage checking (Dewey Source Pack
Experiment C, docs/Architecture.md §0.86-§0.87).

**A genuinely different axis from `backend.research.models.FieldCoverage` /
`ConceptCompleteness` (Phase 8.3) -- evaluated explicitly before this package
was built, not assumed.** Phase 8.3's `FieldCoverage` answers "is one
required FIELD satisfied for one concept, inside one Learning Research Mode
investigation, via tagged Questions?" -- a per-entity, internal, structured
completeness check. This package answers a different question: "does a body
of free-text evidence/claims mention or explain a named CURRICULUM concept
at all?" -- a cross-topic, external, free-text presence check, aimed at
Dewey's own "did the Source Pack actually teach C++ pointers" use case, not
at grading one entity's own internal field set. Neither replaces the other.

Versioned progression (per the 2026-09-17 design conversation):
  v0 -- lexical candidates (`lexical_candidate_checker_v0.py`, this slice).
        Can only claim `CoverageStatus.ABSENT` or `.MENTIONED`.
  v1 -- semantic status classification (`semantic_coverage_checker_v1.py`,
        not yet built -- needs real LLM-based judgment, deliberately
        deferred until v0's own honest limits were written down first).
  v2 -- evidence-grounded coverage (not yet designed).
  v3 -- learner-specific mastery / course completeness (not yet designed).
"""
