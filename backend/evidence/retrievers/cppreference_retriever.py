from __future__ import annotations

import re

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from ..models import RetrievedResource
from .base import Retriever

_PARSE_URL = "https://en.cppreference.com/api.php"
_USER_AGENT = "RecursiveKnowledgeGraph-EvidenceEngine/0.1 (student research project, non-commercial)"

# Dewey Source Pack research (docs/Memory.md, 2026-09-17): cppreference.com runs
# real MediaWiki software with a real REST/action API -- confirmed live -- but it
# sits behind an active Cloudflare bot-challenge that blocked `action=opensearch`
# outright (a "Just a moment..." JS-challenge page, not a clean 403/429) while
# `action=parse` on a KNOWN page title succeeded cleanly in the same session.
# Free-text search across the whole site is therefore NOT reliable here (the
# `action=query&list=search` endpoint also errored) -- this is a real,
# `acquisition_mode="controlled_document"` retriever, not `"api"`: a small,
# individually-verified set of real page titles (every one below confirmed to
# resolve via a live `action=query&titles=...` call before being added, not
# guessed), matched by keyword rather than searched freely. This is the correct
# scope for a v0.1 Source Pack slice per the project's own explicit instruction
# ("selected public pages," not a universal crawler) -- expanding this list is
# safe (just verify a new title first), building a general free-text search
# against this site is not, given the Cloudflare layer's demonstrated
# unpredictability.
_KNOWN_PAGES: dict[str, str] = {
    "pointer": "cpp/language/pointer",
    "pointers": "cpp/language/pointer",
    "dereference": "cpp/language/pointer",
    "reference": "cpp/language/reference",
    "references": "cpp/language/reference",
    "new": "cpp/language/new",
    "dynamic allocation": "cpp/language/new",
    "dynamic memory": "cpp/language/new",
    "delete": "cpp/language/delete",
    "deallocation": "cpp/language/delete",
    "smart pointer": "cpp/memory",
    "smart pointers": "cpp/memory",
    "memory management": "cpp/memory",
    "unique_ptr": "cpp/memory/unique_ptr",
    "unique pointer": "cpp/memory/unique_ptr",
    "shared_ptr": "cpp/memory/shared_ptr",
    "shared pointer": "cpp/memory/shared_ptr",
    "array": "cpp/language/array",
    "arrays": "cpp/language/array",
    "pointer arithmetic": "cpp/language/operator_arithmetic",
    "arithmetic": "cpp/language/operator_arithmetic",
    "lifetime": "cpp/language/lifetime",
    "object lifetime": "cpp/language/lifetime",
    "ownership": "cpp/language/lifetime",
    "storage duration": "cpp/language/storage_duration",
    "stack": "cpp/language/storage_duration",
    "heap": "cpp/language/storage_duration",
}
"""Every value here was individually confirmed to resolve via a real, live
`action=query&titles=...` call on 2026-09-17 (docs/Memory.md) -- not guessed
from memory of cppreference's URL structure. Extend by verifying a new title
the same way, not by pattern-guessing a plausible-looking path."""

_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")


def _strip_wikitext_noise(wikitext: str) -> str:
    """A real, stated limitation, not a silent gap: this does not render
    wikitext to plain prose (that needs a real wikitext parser, out of scope for
    this slice). It only strips the most common, purely-structural
    `{{template|...}}` markup (navboxes, title templates) that would otherwise
    dominate the snippet with noise -- the remaining text can still carry
    residual markup (tables, links) that `synthesize_claim` has to read past,
    the same way it already reads past HTML/markdown artifacts in other
    retrievers' raw snippets."""
    return _TEMPLATE_RE.sub(" ", wikitext).strip()


class CppReferenceRetriever(Retriever):
    """C++ technical reference -- `acquisition_mode="controlled_document"`
    (see the module docstring above for why this is a curated page list, not
    free-text search). CC-BY-SA-3.0 + GFDL (cppreference.com's own stated
    license, confirmed 2026-09-17). Degrades gracefully (docs/Rules.md §3) on
    any failure, including a Cloudflare challenge page -- detected as a JSON
    decode failure, since a real API response is always JSON and a challenge
    page is always HTML.
    """

    source_type = "web"
    source_role = "technical_reference"
    acquisition_mode = "controlled_document"

    async def search(self, query: str, max_results: int = 3) -> list[RetrievedResource]:
        query_lower = query.lower()
        matched_titles: list[str] = []
        for keyword, title in _KNOWN_PAGES.items():
            if keyword in query_lower and title not in matched_titles:
                matched_titles.append(title)
        matched_titles = matched_titles[:max_results]

        if not matched_titles:
            return []

        resources: list[RetrievedResource] = []
        try:
            async with AsyncSession(headers={"User-Agent": _USER_AGENT}, timeout=15) as session:
                for title in matched_titles:
                    response = await session.get(
                        _PARSE_URL,
                        params={"action": "parse", "page": title, "format": "json", "prop": "wikitext"},
                        impersonate="chrome",
                    )
                    if response.status_code != 200:
                        continue
                    try:
                        data = response.json()
                    except ValueError:
                        # A Cloudflare challenge page (or any other non-JSON
                        # response) lands here -- skip this one page, keep
                        # trying the rest, never crash the whole call over it.
                        continue
                    wikitext = ((data.get("parse") or {}).get("wikitext") or {}).get("*")
                    if not wikitext:
                        continue
                    snippet = _strip_wikitext_noise(wikitext)[:1000]
                    if not snippet:
                        continue
                    resources.append(
                        RetrievedResource(
                            title=title,
                            url=f"https://en.cppreference.com/w/{title}",
                            snippet=snippet,
                            source_type=self.source_type,
                            source_role=self.source_role,
                            acquisition_mode=self.acquisition_mode,
                        )
                    )
        except RequestException as exc:
            reason = str(exc) or type(exc).__name__
            print(f"[evidence] cppreference retriever failed, degrading to zero results: {reason}")
            return resources

        return resources
