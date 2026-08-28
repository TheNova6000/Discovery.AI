from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..models import RetrievedResource


class Retriever(ABC):
    """Common retriever interface (docs/Phases.md Phase 5), pattern borrowed from
    `gpt-researcher`'s retriever plugins (docs/Architecture.md §1). Every concrete
    retriever must degrade gracefully on failure (docs/Rules.md §3): `search()`
    returns an empty list on any error (missing key, timeout, rate limit, malformed
    response) rather than raising — a failed source contributes nothing, it never
    sinks the whole `gather_evidence` call.
    """

    source_type: ClassVar[str]  # "web" | "paper" | "book" | "video"

    @abstractmethod
    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]: ...
