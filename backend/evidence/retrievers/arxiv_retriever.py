from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from ..models import RetrievedResource
from .base import Retriever

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivRetriever(Retriever):
    """Keyless — https://export.arxiv.org/api/query, Atom XML feed. No setup needed."""

    source_type = "paper"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    _ARXIV_API_URL,
                    params={"search_query": f"all:{query}", "start": 0, "max_results": max_results},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] arXiv retriever failed, degrading to zero results: {reason}")
            return []

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            print(f"[evidence] arXiv response was not valid XML, degrading to zero results: {exc}")
            return []

        resources: list[RetrievedResource] = []
        for entry in root.findall(f"{_ATOM_NS}entry"):
            title = (entry.findtext(f"{_ATOM_NS}title") or "").strip()
            summary = (entry.findtext(f"{_ATOM_NS}summary") or "").strip()
            url = entry.findtext(f"{_ATOM_NS}id")
            published = entry.findtext(f"{_ATOM_NS}published")
            if not title or not url:
                continue
            resources.append(
                RetrievedResource(
                    title=title,
                    url=url,
                    snippet=summary,
                    source_type=self.source_type,
                    published=published,
                )
            )
        return resources
