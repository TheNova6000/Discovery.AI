"""Maintenance: re-read archived FULL-TEXT pages that were split by an older
chunker, so they get section-aware passages (CHUNKER_VERSION). Network only
(Dewey's safe fetcher), no LLM. Summaries/abstracts are re-split from their
stored snippet text on their next ingest; this script handles full pages.

Usage: python scripts/dewey_refresh_outdated.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.main_block.research_engine.archive import ArchiveStore, Document  # noqa: E402
from backend.main_block.research_engine.fetch import FetchError, SafeFetcher  # noqa: E402


async def main() -> int:
    fetcher = SafeFetcher()
    async with ArchiveStore() as archive:
        before = await archive.stats()
        outdated = [d for d in await archive.outdated_documents() if d["content_kind"] == "full_text"]
        print(f"{len(outdated)} outdated full-text document(s); archive {before}")
        for doc in outdated:
            try:
                page = await fetcher.fetch(doc["url"])
            except FetchError as exc:
                print(f"  skip {doc['url']}: {exc.kind}")
                continue
            result = await archive.ingest(
                Document(url=doc["url"], title=page.title or doc["title"], provider=doc["provider"],
                         source_type=doc["source_type"], source_role=doc["source_role"], content_kind="full_text"),
                page.text,
            )
            print(f"  {result.status:12s} v{result.version} +{result.passages_added} passages  {doc['url']}")
        print(f"archive now {await archive.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
