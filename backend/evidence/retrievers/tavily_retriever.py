from __future__ import annotations

from ..config import TAVILY_API_KEY
from ..models import RetrievedResource
from .base import Retriever


class TavilyRetriever(Retriever):
    """Needs TAVILY_API_KEY (free: 1,000 credits/mo — https://tavily.com). Returns
    zero results (not an error) when the key is missing, same as any other
    retriever failure (docs/Rules.md §3)."""

    source_type = "web"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        if not TAVILY_API_KEY:
            print("[evidence] Tavily retriever skipped: no TAVILY_API_KEY set")
            return []

        try:
            from tavily import AsyncTavilyClient  # imported lazily: optional dependency

            client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
            response = await client.search(query, max_results=max_results)
        except Exception as exc:  # noqa: BLE001 - collapse any SDK/HTTP error into a graceful skip
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] Tavily retriever failed, degrading to zero results: {reason}")
            return []

        resources: list[RetrievedResource] = []
        for item in response.get("results") or []:
            title = item.get("title")
            url = item.get("url")
            if not title or not url:
                continue
            resources.append(
                RetrievedResource(
                    title=title,
                    url=url,
                    snippet=item.get("content") or "",
                    source_type=self.source_type,
                )
            )
        return resources
