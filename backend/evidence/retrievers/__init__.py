from .arxiv_retriever import ArxivRetriever
from .base import Retriever
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
DEFAULT_RETRIEVERS: list[Retriever] = [
    WikipediaRetriever(),
    ArxivRetriever(),
    SemanticScholarRetriever(),
    OpenLibraryRetriever(),
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
    "DEFAULT_RETRIEVERS",
]
