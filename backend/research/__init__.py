"""Learning Research Planner + Coverage/Completeness model + targeted
investigation orchestration + evidence validation (Phases 8.2-8.5,
docs/PRD.md §9.3a, docs/Phases.md).

Phase 8.2 (planner.py): turns an already-investigated abstraction's subgraph
plus an active ResearchPolicy (Phase 8.1, backend.agents.policy) into a
ResearchPlan -- one ConceptResearchTarget per already-discovered entity, each
carrying which research fields that policy requires ("what SHOULD this
concept contain"). Deterministic, no LLM/retriever call (Rules.md rule 14) --
never decides what concepts SHOULD exist, only what's required of the ones
that already do.

Phase 8.3 (coverage.py): given a plan, reads each target's REAL, already-
recorded evidence and decides which required fields are actually satisfied
("what DOES this concept contain, and is that enough"). Also deterministic,
no LLM call -- honestly reports the three content-classification fields
(prerequisites/examples/misconceptions) as missing unless a real, tagged
targeted question already covers them (models.py's UNCLASSIFIED_FIELDS note).

Phase 8.4 (investigate.py): the first module in this track that makes real
LLM/retriever calls. plan_targeted_investigations (pure, bounded) decides
which (entity, field) gaps to close; run_targeted_investigation (I/O) runs
one bounded, non-recursive GroundAgent investigation per gap and tags its
Question with research_field; close_coverage_gaps orchestrates both and
returns a fresh coverage report.

Phase 8.5 (validation.py): evidence quality, distinct from field coverage.
assess_claim_validity (pure, deterministic) flags duplicate/superseded/weak
claims and independent-source count. detect_contradictions (I/O, the one
real LLM call, bounded and opt-in) reuses the existing epistemic layer's
analyze_claim_relationships (Post-Phase-5) rather than inventing new
contradiction logic.

Phase 8.6 (artifact.py): packages Phase 8.1-8.5's already-computed research
state into one stable ResearchArtifact -- the contract Phase 9's Curriculum
Compiler is meant to consume. Performs NO new research and calls NO LLM of
its own (not even optionally); a caller who wants Phase 8.5's contradiction
findings included runs detect_contradictions separately and passes the
results in.

Curriculum compilation and lesson/exercise generation are explicitly later
phases, not this module's job.

R4.1 (claim_mapping.py, docs/Architecture.md §0.66/§0.67): the pure bridge
from a persisted `ClaimNode` (this package's existing representation) to
`backend.reasoning.domain.Claim` (R1's lifecycle-bearing canonical model)
that R4.0's audit found was missing. Representation conversion only -- no
validation logic, no lifecycle promotion, no Evidence fabrication; every
mapped claim lands at `"requires_reclassification"`, the same sanctioned
status R1.1's `reclassify_legacy_claim` already uses for real, persisted
data that has never been run through this model's own checks.
"""

from .artifact import assemble_research_artifact, compile_research_artifact
from .claim_mapping import ClaimMappingRejected, claim_node_to_domain_claim
from .coverage import assess_plan_readiness, assess_target_completeness, build_readiness_report
from .investigate import close_coverage_gaps, plan_targeted_investigations, run_targeted_investigation
from .models import (
    BASE_REQUIRED_FIELDS,
    CONFIDENCE_GATED_FIELDS,
    REQUIRED_FIELD_POLICY_GATES,
    UNCLASSIFIED_FIELDS,
    ClaimValidationReport,
    ConceptCompleteness,
    ConceptResearchArtifact,
    ConceptResearchTarget,
    ContradictionFinding,
    ContradictionReport,
    DuplicateClaimPair,
    EvidenceReference,
    FieldCoverage,
    ResearchArtifact,
    ResearchPlan,
    ResearchReadinessReport,
    TargetedInvestigationRequest,
)
from .planner import build_research_plan, plan_targets
from .validation import assess_claim_validity, detect_contradictions

__all__ = [
    "build_research_plan",
    "plan_targets",
    "ResearchPlan",
    "ConceptResearchTarget",
    "BASE_REQUIRED_FIELDS",
    "REQUIRED_FIELD_POLICY_GATES",
    "assess_plan_readiness",
    "assess_target_completeness",
    "build_readiness_report",
    "CONFIDENCE_GATED_FIELDS",
    "UNCLASSIFIED_FIELDS",
    "ConceptCompleteness",
    "FieldCoverage",
    "ResearchReadinessReport",
    "plan_targeted_investigations",
    "run_targeted_investigation",
    "close_coverage_gaps",
    "TargetedInvestigationRequest",
    "assess_claim_validity",
    "detect_contradictions",
    "ClaimValidationReport",
    "DuplicateClaimPair",
    "ContradictionFinding",
    "ContradictionReport",
    "assemble_research_artifact",
    "compile_research_artifact",
    "ResearchArtifact",
    "ConceptResearchArtifact",
    "EvidenceReference",
    "claim_node_to_domain_claim",
    "ClaimMappingRejected",
]
