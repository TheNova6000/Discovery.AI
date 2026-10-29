from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Both optional — the keyless retrievers (arXiv, Semantic Scholar, Open Library)
# work with no setup at all. Tavily (1,000 free credits/mo, https://tavily.com) and
# YouTube Data API v3 (100 free searches/day via a Google Cloud API key) are richer
# sources but need the user to obtain a free key first; until then their retrievers
# just return zero results (docs/Rules.md §3's graceful degradation), same as any
# other retriever failure.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
