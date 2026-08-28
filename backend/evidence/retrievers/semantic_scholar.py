from __future__ import annotations

import httpx

from ..models import RetrievedResource
from .base import Retriever

_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarRetriever(Retriever):
    """Keyless (rate-limited without a key; a free key raises the limit to 100
    req/s — https://www.semanticscholar.org/product/api#api-key-form). No setup
    needed to get started."""

    source_type = "paper"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    _SEMANTIC_SCHOLAR_URL,
                    params={"query": query, "limit": max_results, "fields": "title,abstract,url,year"},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] Semantic Scholar retriever failed, degrading to zero results: {reason}")
            return []

        resources: list[RetrievedResource] = []
        for paper in data.get("data") or []:
            title = paper.get("title")
            url = paper.get("url")
            if not title or not url:
                continue
            year = paper.get("year")
            resources.append(
                RetrievedResource(
                    title=title,
                    url=url,
                    snippet=paper.get("abstract") or "",
                    source_type=self.source_type,
                    published=str(year) if year else None,
                )
            )
        return resources
