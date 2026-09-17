"""The stable Discovery.AI Research API contract (R5, docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md §0.57/§0.73/§0.74).

R5.1: pure domain types only (`ResearchRequest`/`ResearchResponse`) -- a
projection over the real, already-built R1-R4/Phase 8 models, never a
second, competing epistemic model. See `models.py`'s own module docstring
for the full field-by-field source mapping and every honestly-empty
field's real reason.

R5.2: `compile_research_response`, the pure compiler from a real, already-
assembled `ResearchArtifact` (Phase 8.6) into a `ResearchResponse`. No new
epistemic objects, no lifecycle transitions, no confidence gating, no
persistence, no orchestration, no Neo4j/LLM/retriever call. See
`compiler.py`'s own module docstring for the real finding that shaped its
design: `ResearchArtifact` carries no real `Claim` objects, only
`EvidenceReference` citation pointers -- `claims`/`subgraph`/`provenance`
are accepted as optional, real, already-fetched parameters rather than
fabricated from what the artifact alone provides.

No API route yet (R5.3).
"""

from .compiler import compile_research_response
from .models import ResearchRequest, ResearchResponse, ResearchResponseStatus

__all__ = [
    "ResearchRequest",
    "ResearchResponse",
    "ResearchResponseStatus",
    "compile_research_response",
]
