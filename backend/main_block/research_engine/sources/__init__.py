from .arxiv_retriever import ArxivRetriever
from .base import Retriever
from .cppreference_retriever import CppReferenceRetriever
from .github_retriever import GitHubRetriever
from .open_library import OpenLibraryRetriever
from .semantic_scholar import SemanticScholarRetriever
from .tavily_retriever import TavilyRetriever
from .wikipedia_retriever import WikipediaRetriever
from .youtube_retriever import YouTubeRetriever

# Keyless retrievers first (arXiv/Semantic Scholar/Open Library/Wikipedia work with
# zero setup); Tavily/YouTube are included too but self-skip to zero results
# without a key (docs/Rules.md §3) rather than needing a separate "enabled
# retrievers" list. Wikipedia added after a real evaluation run
# (scripts/evaluate_known_answers.py) showed the other four contribute almost
# nothing for everyday "how does X work" / "history of X" questions.
#
# CppReferenceRetriever/GitHubRetriever added 2026-09-17 (docs/Memory.md's Dewey
# Source Pack research) -- both keyless, both degrade to zero results for any
# question outside their real coverage (CppReferenceRetriever's curated page list
# only matches C++-shaped keywords; GitHub's repository search just returns
# low/no relevant results for a non-code query), the same way arXiv/Semantic
# Scholar already return nothing useful for a non-academic question. No new
# topic-routing logic was added to gate them -- `synthesize_claim`'s existing
# confidence scoring is what already separates a genuinely relevant result from
# an irrelevant one for every retriever in this list; these two follow the same
# established mechanism rather than inventing a second one.
DEFAULT_RETRIEVERS: list[Retriever] = [
    WikipediaRetriever(),
    ArxivRetriever(),
    SemanticScholarRetriever(),
    OpenLibraryRetriever(),
    CppReferenceRetriever(),
    GitHubRetriever(),
    TavilyRetriever(),
    YouTubeRetriever(),
]

__all__ = [
    "Retriever",
    "ArxivRetriever",
    "SemanticScholarRetriever",
    "OpenLibraryRetriever",
    "TavilyRetriever",
    "WikipediaRetriever",
    "YouTubeRetriever",
    "CppReferenceRetriever",
    "GitHubRetriever",
    "DEFAULT_RETRIEVERS",
]
