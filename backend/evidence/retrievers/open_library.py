from __future__ import annotations

import httpx

from ..models import RetrievedResource
from .base import Retriever

_OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"


class OpenLibraryRetriever(Retriever):
    """Keyless — https://openlibrary.org/search.json. No setup needed. Open
    Library's search results don't include an abstract/summary field, so the
    snippet here is bibliographic (author + year), not a content excerpt."""

    source_type = "book"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(_OPEN_LIBRARY_URL, params={"q": query, "limit": max_results})
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] Open Library retriever failed, degrading to zero results: {reason}")
            return []

        resources: list[RetrievedResource] = []
        for doc in data.get("docs") or []:
            title = doc.get("title")
            key = doc.get("key")
            if not title or not key:
                continue
            authors = ", ".join(doc.get("author_name") or []) or "unknown author"
            year = doc.get("first_publish_year")
            snippet = f"By {authors}" + (f", first published {year}" if year else "")
            resources.append(
                RetrievedResource(
                    title=title,
                    url=f"https://openlibrary.org{key}",
                    snippet=snippet,
                    source_type=self.source_type,
                    published=str(year) if year else None,
                )
            )
        return resources
