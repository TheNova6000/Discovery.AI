from __future__ import annotations

import os

import httpx

from ..models import RetrievedResource
from .base import Retriever

_SEARCH_URL = "https://api.github.com/search/repositories"

# GitHub's own robots.txt (checked directly, 2026-09-17 -- docs/Memory.md's Dewey
# Source Pack research) explicitly lists ClaudeBot/anthropic-ai as recognized
# crawlers with a 1s crawl-delay -- but that's the marketing site. Real content
# access is the documented REST API used here, not page scraping, which is the
# right path regardless of that listing.


class GitHubRetriever(Retriever):
    """Keyless -- GitHub's repository search API works unauthenticated (confirmed
    live, 2026-09-17), just at a lower rate limit (10 unauthenticated search
    requests/min vs. 30/min with a token -- https://docs.github.com/en/rest/search).
    An optional `GITHUB_TOKEN` env var raises the limit; its absence degrades to
    the lower unauthenticated limit, never a hard failure (docs/Rules.md §3).

    Real implementations/examples source -- the "implementation" role the Dewey
    Source Pack research identified (docs/Memory.md, 2026-09-17), distinct from
    Wikipedia's entity-discovery role or cppreference's technical-reference role.
    Searches repositories (not individual files/code search, which GitHub's API
    rate-limits far more aggressively and which returns noisier, less
    representative results for "does a real implementation of this concept
    exist") -- a repository's own name/description is usually enough signal for
    `synthesize_claim` to judge relevance; the repository's README/source itself
    is not fetched by this retriever (a real, stated scope limit, not an
    oversight -- fetching and summarizing repo contents is separate, heavier work
    this slice doesn't attempt).
    """

    source_type = "code"
    source_role = "implementation"
    acquisition_mode = "api"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "RecursiveKnowledgeGraph-EvidenceEngine/0.1 (student research project, non-commercial)",
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_API_KEY")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={"q": query, "sort": "stars", "order": "desc", "per_page": max_results},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] GitHub retriever failed, degrading to zero results: {reason}")
            return []

        resources: list[RetrievedResource] = []
        for repo in data.get("items") or []:
            full_name = repo.get("full_name")
            url = repo.get("html_url")
            if not full_name or not url:
                continue
            description = repo.get("description") or ""
            stars = repo.get("stargazers_count")
            snippet = f"{description} ({stars} stars)" if stars is not None else description
            resources.append(
                RetrievedResource(
                    title=full_name,
                    url=url,
                    snippet=snippet,
                    source_type=self.source_type,
                    published=repo.get("created_at"),
                    source_role=self.source_role,
                    acquisition_mode=self.acquisition_mode,
                )
            )
        return resources
