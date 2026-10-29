"""Evidence Engine (Phase 5): real external retrievers (Tavily/Semantic Scholar/
arXiv/Open Library/YouTube) behind a common interface, synthesized into typed
`Claim`s (evidence/reasoning/confidence/provenance — docs/Rules.md rule 4). Per
Rules.md rule 2, this module (and `backend/main_block/reasoning_engine/llm_steps`) are the only ones allowed to
call external LLM/search APIs.
"""

from .engine import GatherEvidenceResult, gather_evidence, gather_evidence_with_outcomes
from .exceptions import EvidenceRetrievalError
from .models import Claim, ClaimDraft, RetrievedResource  # RetrievedResource: the research engine's type
from .synthesis import synthesize_claim

__all__ = [
    "gather_evidence",
    "gather_evidence_with_outcomes",
    "GatherEvidenceResult",
    "synthesize_claim",
    "EvidenceRetrievalError",
    "Claim",
    "ClaimDraft",
    "RetrievedResource",
]
