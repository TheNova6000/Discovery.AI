"""Discovery.AI core reasoning domain model (R1.1, docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md §0.47-§0.57).

Pure domain types with validation invariants only -- no Neo4j, no LLM, no
event bus, no orchestration. See domain.py's own module docstring for the
full scope statement and the dependency-direction principle this package
exists to establish at the bottom of the stack.

The core invariant: RetrievalOutcome != Evidence != Claim != Answer. A
retrieval failure cannot become Evidence or a Claim just because it has
text and a confidence-shaped number -- classify_retrieval_outcome and
reclassify_legacy_claim are the only two functions that construct Evidence
or a migration-sourced Claim, and both enforce this structurally.
"""

from .domain import (
    Answer,
    Claim,
    ClaimStatus,
    Evidence,
    RetrievalOutcome,
    classify_retrieval_outcome,
    reclassify_legacy_claim,
)

__all__ = [
    "RetrievalOutcome",
    "Evidence",
    "Claim",
    "ClaimStatus",
    "Answer",
    "classify_retrieval_outcome",
    "reclassify_legacy_claim",
]
