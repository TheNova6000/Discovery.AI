"""Dewey's provider registry: every external source, what it needs (API key
env vars) and which kinds of information need it serves (routing).

Today every provider wraps one of the existing `backend.main_block.research_engine.sources`
(they move under Dewey in the Discovery.AI split, build step 4). Those
retrievers swallow their own errors and return [] (docs/Rules.md §3), so a
wrapped provider can only report ok / no_results / timed_out / failed /
skipped_no_key; providers written natively for Dewey (web search, fetch)
will raise typed errors so rate limits are reported as such.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Protocol

from .resource import RetrievedResource
from backend.main_block.research_engine.sources import (
    ArxivRetriever,
    CppReferenceRetriever,
    GitHubRetriever,
    OpenLibraryRetriever,
    Retriever,
    SemanticScholarRetriever,
    TavilyRetriever,
    WikipediaRetriever,
    YouTubeRetriever,
)

from .archive import query_words
from .contracts import NeedKind, ProviderReport

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 20.0


MAX_KEYWORDS = 6

QUERY_FILLER = frozenset(
    "happen happens happening each important importance main key basic work works working way ways "
    "explain describe overview introduction role function different kinds kind types type exactly "
    "really also mean means meaning need needed also".split()
)
"""Question words that carry no topic: as search terms they pull unrelated pages
("mitosis happen each phas important" -> Protist, Chemotherapy, Animal on
Wikipedia, loop iteration 05; "mitosis phases" -> Mitosis, Interphase, Cell cycle)."""


def keyword_query(text: str) -> str:
    """Search APIs (Wikipedia, arXiv, Semantic Scholar, GitHub...) match keywords;
    sending them a whole sentence was part of the live 429 / empty-result
    pattern (2026-10-28). ORIGINAL words (search engines stem themselves --
    pre-stemmed "phas" broke the query), stopwords and filler dropped, order kept."""
    words = [w for w in query_words(text) if w not in QUERY_FILLER]
    return " ".join(words[:MAX_KEYWORDS]) or text


class Provider(Protocol):
    name: str
    need_kinds: frozenset[str]
    query_style: str
    """"keywords" (default for search APIs) or "natural" (LLM-backed search like Tavily)."""
    key_env_vars: tuple[str, ...]
    """Empty = keyless. Otherwise at least one of these env vars must be set."""

    async def search(self, query: str, max_results: int) -> list[RetrievedResource]: ...


@dataclass
class RetrieverProvider:
    """Adapts an existing `Retriever` to the `Provider` interface."""

    name: str
    retriever: Retriever
    need_kinds: frozenset[str]
    key_env_vars: tuple[str, ...] = ()
    query_style: str = "keywords"

    async def search(self, query: str, max_results: int) -> list[RetrievedResource]:
        results = await self.retriever.search(query, max_results=max_results)
        for resource in results:
            if resource.content_kind is None:
                resource.content_kind = self.retriever.content_kind
        return results


_GENERAL: frozenset[str] = frozenset({"definition", "explanation", "example", "history", "comparison", "prerequisite", "misconception"})
_ALL: frozenset[str] = frozenset(NeedKind.__args__)  # type: ignore[attr-defined]


def default_providers() -> list[Provider]:
    return [
        RetrieverProvider("wikipedia", WikipediaRetriever(), _GENERAL),
        RetrieverProvider("arxiv", ArxivRetriever(), frozenset({"evidence", "history"})),
        RetrieverProvider("semantic_scholar", SemanticScholarRetriever(), frozenset({"evidence", "history"})),
        RetrieverProvider("open_library", OpenLibraryRetriever(), frozenset({"definition", "explanation", "prerequisite", "history"})),
        RetrieverProvider("cppreference", CppReferenceRetriever(), frozenset({"definition", "implementation", "example"})),
        RetrieverProvider("github", GitHubRetriever(), frozenset({"implementation", "example"})),
        RetrieverProvider("tavily", TavilyRetriever(), _ALL, key_env_vars=("TAVILY_API_KEY",), query_style="natural"),
        RetrieverProvider("youtube", YouTubeRetriever(), _GENERAL, key_env_vars=("YOUTUBE_API_KEY",)),
    ]


@dataclass
class ProviderRegistry:
    providers: list[Provider] = field(default_factory=lambda: default_providers())
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def has_key(self, provider: Provider) -> bool:
        return not provider.key_env_vars or any(os.environ.get(v) for v in provider.key_env_vars)

    def route(self, need_kind: str) -> list[Provider]:
        return [p for p in self.providers if need_kind == "general" or need_kind in p.need_kinds]

    def status(self) -> list[dict]:
        """For a provider/key status page: name, routing, and whether its key is configured."""
        return [
            {
                "provider": p.name,
                "need_kinds": sorted(p.need_kinds),
                "requires_key": list(p.key_env_vars),
                "key_configured": self.has_key(p),
            }
            for p in self.providers
        ]

    async def search(
        self, need_kind: str, query: str, max_results: int
    ) -> tuple[list[tuple[str, RetrievedResource]], list[ProviderReport]]:
        """Results as (provider name, resource) pairs, plus one report per routed provider."""
        routed = self.route(need_kind)
        reports: list[ProviderReport] = []
        runnable: list[Provider] = []
        for provider in routed:
            if self.has_key(provider):
                runnable.append(provider)
            else:
                reports.append(ProviderReport(provider=provider.name, status="skipped_no_key", detail=f"set {' or '.join(provider.key_env_vars)}"))

        async def one(provider: Provider) -> tuple[list[RetrievedResource], ProviderReport]:
            try:
                provider_query = query if getattr(provider, "query_style", "keywords") == "natural" else keyword_query(query)
                results = await asyncio.wait_for(provider.search(provider_query, max_results), timeout=self.timeout_seconds)
            except asyncio.TimeoutError:
                return [], ProviderReport(provider=provider.name, status="timed_out", detail=f">{self.timeout_seconds:.0f}s")
            except Exception as exc:  # noqa: BLE001 - one source failing must not sink the batch
                return [], ProviderReport(provider=provider.name, status="failed", detail=str(exc)[:200])
            return results, ProviderReport(provider=provider.name, status="ok" if results else "no_results", results=len(results))

        outcomes = await asyncio.gather(*(one(p) for p in runnable))
        resources: list[tuple[str, RetrievedResource]] = []
        for results, report in outcomes:
            resources.extend((report.provider, r) for r in results)
            reports.append(report)
        return resources, reports
