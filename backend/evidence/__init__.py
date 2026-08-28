"""Evidence Engine (Phase 5): real external retrievers (Tavily/Semantic Scholar/
arXiv/Open Library/YouTube) behind a common interface, synthesized into typed
`Claim`s (evidence/reasoning/confidence/provenance — docs/Rules.md rule 4). Per
Rules.md rule 2, this module (and `backend/questions`) are the only ones allowed to
call external LLM/search APIs.
"""

from .engine import gather_evidence
from .exceptions import EvidenceRetrievalError
from .models import Claim, ClaimDraft, RetrievedResource
from .retrievers import (
    DEFAULT_RETRIEVERS,
    ArxivRetriever,
    OpenLibraryRetriever,
    Retriever,
    SemanticScholarRetriever,
    TavilyRetriever,
    WikipediaRetriever,
    YouTubeRetriever,
)
from .synthesis import synthesize_claim

__all__ = [
    "gather_evidence",
    "synthesize_claim",
    "EvidenceRetrievalError",
    "Claim",
    "ClaimDraft",
    "RetrievedResource",
    "Retriever",
    "DEFAULT_RETRIEVERS",
    "ArxivRetriever",
    "SemanticScholarRetriever",
    "OpenLibraryRetriever",
    "TavilyRetriever",
    "WikipediaRetriever",
    "YouTubeRetriever",
]
