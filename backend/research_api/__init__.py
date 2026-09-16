"""The stable Discovery.AI Research API contract (R5, docs/Phases.md's
Reasoning Engine Evolution track, docs/Architecture.md §0.57/§0.73).

R5.1, first slice: pure domain types only (`ResearchRequest`/
`ResearchResponse`) -- a projection over the real, already-built R1-R4/
Phase 8 models, never a second, competing epistemic model. No API route,
no orchestration, no `compile_research_response` (R5.2), no Neo4j change,
no LLM/retriever call. See `models.py`'s own module docstring for the full
field-by-field source mapping and every honestly-empty field's real reason.
"""

from .models import ResearchRequest, ResearchResponse, ResearchResponseStatus

__all__ = [
    "ResearchRequest",
    "ResearchResponse",
    "ResearchResponseStatus",
]
