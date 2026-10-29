from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..resource import RetrievedResource

CONTACT_USER_AGENT = (
    "TuninDewey/0.1 (https://github.com/TheNova6000/Discovery.AI; "
    "research engine for a student learning project)"
)
"""Identifying User-Agent with contact info, per Wikimedia's User-Agent policy
(a generic or contact-less agent is throttled harder). Verified 2026-10-28:
the old contact-less agent combined with curl_cffi's Chrome TLS impersonation
got HTTP 429 from Wikipedia; this agent, with or without impersonation, got 200."""


class Retriever(ABC):
    """Common retriever interface (docs/Phases.md Phase 5), pattern borrowed from
    `gpt-researcher`'s retriever plugins (docs/Architecture.md §1). Every concrete
    retriever must degrade gracefully on failure (docs/Rules.md §3): `search()`
    returns an empty list on any error (missing key, timeout, rate limit, malformed
    response) rather than raising — a failed source contributes nothing, it never
    sinks the whole `gather_evidence` call.
    """

    source_type: ClassVar[str]  # "web" | "paper" | "book" | "video" | "code"

    source_role: ClassVar[str] = "unclassified"
    """Dewey Source Pack research (docs/Memory.md, 2026-09-17): a fixed, honest
    property of THIS retriever's own nature -- what kind of evidence it
    structurally produces, never computed per result. See
    `backend.main_block.reasoning_engine.evidence.models.RetrievedResource.source_role`'s own docstring for
    the real vocabulary. Every concrete retriever's `search()` should stamp this
    onto each `RetrievedResource` it returns."""

    acquisition_mode: ClassVar[str] = "api"
    """"api" / "controlled_document" / "archive" -- see
    `RetrievedResource.acquisition_mode`'s own docstring. Defaults to "api"
    since that's what every retriever in this codebase used until the Dewey
    Source Pack research added the first non-API one (controlled_document)."""

    content_kind: ClassVar[str | None] = None
    """What this retriever's `snippet` text structurally is -- see
    `RetrievedResource.content_kind`. Stamped onto results centrally by the
    evidence engine and Dewey's providers."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]: ...
