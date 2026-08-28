from __future__ import annotations

import httpx

from ..config import YOUTUBE_API_KEY
from ..models import RetrievedResource
from .base import Retriever

_YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


class YouTubeRetriever(Retriever):
    """Needs YOUTUBE_API_KEY (free: a Google Cloud API key with the YouTube Data
    API v3 enabled — 10,000 quota units/day, and search.list costs 100 units, so
    ~100 searches/day; cache aggressively if this gets wired into anything
    high-volume). Returns zero results (not an error) when the key is missing."""

    source_type = "video"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        if not YOUTUBE_API_KEY:
            print("[evidence] YouTube retriever skipped: no YOUTUBE_API_KEY set")
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    _YOUTUBE_SEARCH_URL,
                    params={
                        "part": "snippet",
                        "q": query,
                        "key": YOUTUBE_API_KEY,
                        "maxResults": max_results,
                        "type": "video",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] YouTube retriever failed, degrading to zero results: {reason}")
            return []

        resources: list[RetrievedResource] = []
        for item in data.get("items") or []:
            snippet = item.get("snippet") or {}
            video_id = (item.get("id") or {}).get("videoId")
            title = snippet.get("title")
            if not title or not video_id:
                continue
            resources.append(
                RetrievedResource(
                    title=title,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    snippet=snippet.get("description") or "",
                    source_type=self.source_type,
                    published=snippet.get("publishedAt"),
                )
            )
        return resources
