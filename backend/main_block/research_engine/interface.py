"""Public interface of the research engine (Dewey).

Everything outside `research_engine/` — including the reasoning engine —
imports from HERE only. To upgrade or replace the research engine, keep these
names and contracts; `scripts/verify_dewey_*.py` and `verify_grounding.py` are
the acceptance tests for a replacement.

Contract: `InformationNeed` in → `EvidenceBatch` out (passages with provenance +
one `ProviderReport` per source). The research engine finds, fetches, extracts
and keeps sources; it never judges truth and never creates claims.
"""

from __future__ import annotations

from .archive import ArchiveStore, Document, IngestResult, LedgerEntry, PassageHit, canonical_url, chunk_text
from .contracts import EvidenceBatch, InformationNeed, NeedKind, ProviderReport
from .engine import DeweyEngine
from .providers import ProviderRegistry
from .resource import RetrievedResource
from .sources import DEFAULT_RETRIEVERS, Retriever
from .sources.base import CONTACT_USER_AGENT


async def find(need: InformationNeed, *, archive_path: str | None = None) -> EvidenceBatch:
    """Archive first, research on a miss (the engine's one main operation)."""
    async with ArchiveStore(archive_path) as archive:
        return await DeweyEngine(archive).find(need)


__all__ = [
    "ArchiveStore",
    "CONTACT_USER_AGENT",
    "DEFAULT_RETRIEVERS",
    "DeweyEngine",
    "Document",
    "EvidenceBatch",
    "IngestResult",
    "InformationNeed",
    "LedgerEntry",
    "NeedKind",
    "PassageHit",
    "ProviderRegistry",
    "ProviderReport",
    "Retriever",
    "RetrievedResource",
    "canonical_url",
    "chunk_text",
    "find",
]
