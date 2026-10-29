"""Verifies the Dewey Archive (backend/main_block/research_engine/archive.py) — offline, temp DB,
no network, no LLM:

  1. ingest + query: the relevant passage ranks first, provenance intact
  2. dedupe: re-ingesting identical text is a no-op
  3. versioning: changed text -> version 2, old passages no longer returned
  4. FTS safety: query text full of FTS5 syntax ( " - AND ( * ) ) never errors
  5. entity filter: passages can be scoped to a graph entity id
  6. ledger: same need in different wording -> same entry; retry window honoured
  7. persistence: data survives close + reopen (restart)
  8. chunking: no passage exceeds MAX_PASSAGE_CHARS; canonical URLs collapse
     tracking params / fragments / trailing slashes
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.main_block.research_engine.archive import MAX_PASSAGE_CHARS, ArchiveStore, Document, canonical_url, chunk_text  # noqa: E402

BST_TEXT = """A binary search tree (BST) is a rooted binary tree in which every node's key
is greater than all keys in its left subtree and less than all keys in its right subtree.

Search, insertion and deletion take time proportional to the height of the tree:
O(log n) when balanced, O(n) in the worst case when the tree degenerates into a list."""

HEAP_TEXT = """A binary heap is a complete binary tree satisfying the heap property: each parent
is ordered with respect to its children. It is commonly used to implement priority queues."""


def _doc(url: str, title: str) -> Document:
    return Document(url=url, title=title, provider="wikipedia", source_type="web", source_role="explanation")


async def main() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "archive.sqlite3"

        async with ArchiveStore(path) as archive:
            r1 = await archive.ingest(_doc("https://en.wikipedia.org/wiki/Binary_search_tree", "Binary search tree"), BST_TEXT, entity_ids=["ent-bst"])
            await archive.ingest(_doc("https://en.wikipedia.org/wiki/Binary_heap", "Binary heap"), HEAP_TEXT, entity_ids=["ent-heap"])
            hits = await archive.query("How does deletion work in a binary search tree and what does it cost?")
            check(
                bool(hits) and hits[0].title == "Binary search tree" and hits[0].url.endswith("/Binary_search_tree")
                and hits[0].provider == "wikipedia" and hits[0].retrieved_at,
                f"#1 relevant passage ranks first with provenance (top={hits[0].title if hits else None!r}, n={len(hits)})",
            )

            again = await archive.ingest(_doc("https://en.wikipedia.org/wiki/Binary_search_tree#History", "Binary search tree"), BST_TEXT)
            check(again.status == "unchanged" and again.passages_added == 0 and again.document_id == r1.document_id,
                  f"#2 identical re-ingest (fragment URL) is a no-op: {again.status}")

            changed = BST_TEXT.replace("O(n) in the worst case", "O(n) in the worst case, e.g. inserting sorted keys")
            v2 = await archive.ingest(_doc("https://en.wikipedia.org/wiki/Binary_search_tree/", "Binary search tree"), changed)
            hits = await archive.query("worst case sorted keys")
            texts = [h.text for h in hits if h.title == "Binary search tree"]
            check(v2.version == 2 and v2.status == "new_version" and texts and all("inserting sorted keys" in t for t in texts),
                  f"#3 changed text -> v{v2.version}, only current version returned ({len(texts)} hit(s))")

            hostile = 'C++ "pointers" -delete AND (heap OR * ) NEAR( NOT'
            try:
                await archive.query(hostile)
                empty = await archive.query("??? the of a")
                check(empty == [], "#4 FTS syntax in query never errors; stopword-only query returns []")
            except Exception as exc:  # noqa: BLE001
                check(False, f"#4 FTS-syntax query raised {exc!r}")

            scoped = await archive.query("binary tree", entity_id="ent-heap")
            check(bool(scoped) and all(h.title == "Binary heap" for h in scoped), f"#5 entity filter -> {[h.title for h in scoped]}")

            await archive.record_research("What is a BST?", providers=["wikipedia", "arxiv"], outcome="nothing_found",
                                          passages_added=0, retry_after=timedelta(hours=24))
            entry = await archive.ledger_entry("bst: what is it")
            check(entry is not None and entry.outcome == "nothing_found" and not entry.retry_due,
                  "#6 reworded need hits same ledger entry; retry not yet due")
            await archive.record_research("What is a BST?", providers=["wikipedia"], outcome="found",
                                          passages_added=2, retry_after=timedelta(seconds=-1))
            entry = await archive.ledger_entry("what is a bst")
            check(entry is not None and entry.outcome == "found" and entry.retry_due, "#6 re-research upserts the entry; past window -> retry due")

        async with ArchiveStore(path) as reopened:
            stats = await reopened.stats()
            hits = await reopened.query("binary search tree height")
            check(stats["documents"] == 2 and stats["document_versions"] == 3 and stats["ledger_entries"] == 1 and hits,
                  f"#7 survives restart: {stats}")

    long_para = ("Sentence number one is here. " * 200).strip()
    chunks = chunk_text(long_para + "\n\n" + "x" * 4000)
    check(all(len(c) <= MAX_PASSAGE_CHARS for c in chunks) and len(chunks) >= 5, f"#8 chunking bounded: {len(chunks)} chunks, max {max(map(len, chunks))}")
    check(
        canonical_url("HTTPS://Example.COM/a/b/?utm_source=x&b=2&a=1#frag") == "https://example.com/a/b?a=1&b=2",
        "#8 canonical URL drops tracking params, fragment, trailing slash; sorts query",
    )

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
