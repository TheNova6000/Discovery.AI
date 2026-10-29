"""Verifies Dewey's safe fetcher + full-page reading (backend/main_block/research_engine/fetch.py,
engine._read_full_pages, archive richer-version rule) — offline: httpx
MockTransport + fake DNS, temp archive. Nothing on the real network.

SSRF / scheme
  1. loopback, private, link-local (cloud metadata), IPv6 loopback, IPv4-mapped
     IPv6, and a hostname resolving to 127.0.0.1 are all refused
  2. file:// and ftp:// refused
  3. a public URL redirecting to a private address is refused at the redirect hop
robots.txt (RFC 9309)
  4. Disallow honoured; 404 robots -> allowed; 503 robots -> assume disallowed
Limits / types / extraction
  5. image/png refused; an over-size body refused
  6. HTML extraction keeps the article and drops nav/footer
  7. Wikipedia goes via the MediaWiki API; section headings kept, formula
     spill collapsed to inline LaTeX, reference sections dropped
  8. politeness: two requests to one host are spaced by the minimum interval
Archive / engine
  9. a later summary of a page never supersedes its stored full text
 10. the engine reads the best result in full, ingests it as full_text, and
     reports fetch failures per page without failing the batch
 11. plurals match singulars in term coverage (iteration 05, E16)
 12. a short summary below the passage gate is still read in full (E15)
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import backend.main_block.research_engine.fetch as fetch_mod  # noqa: E402
from backend.main_block.research_engine.archive import ArchiveStore, Document  # noqa: E402
from backend.main_block.research_engine.contracts import InformationNeed  # noqa: E402
from backend.main_block.research_engine.engine import DeweyEngine  # noqa: E402
from backend.main_block.research_engine.fetch import FetchError, SafeFetcher  # noqa: E402
from backend.main_block.research_engine.providers import ProviderRegistry  # noqa: E402
from backend.main_block.reasoning_engine.evidence.models import RetrievedResource  # noqa: E402

DNS = {"public.example": ["93.184.216.34"], "evil.example": ["127.0.0.1"], "wiki.example": ["93.184.216.35"],
       "en.wikipedia.org": ["185.15.59.224"], "redir.example": ["93.184.216.36"]}

ARTICLE = """<html><head><title>BST insertion</title></head><body>
<nav>Home | About | Login</nav>
<article><h1>Insertion in a binary search tree</h1>
<p>Insertion starts at the root and compares the new key with each node, moving left when the key is smaller and right when it is larger.</p>
<p>When an empty child position is reached, the new node is attached there, which preserves the binary search tree ordering property.</p>
<p>The cost is proportional to the height of the tree.</p></article>
<footer>Copyright 2026 Example Corp. All rights reserved.</footer></body></html>"""

WIKI_EXTRACT = ("A binary search tree is a rooted binary tree.\n\n== Operations ==\n\n=== Insertion ===\n"
                "New nodes are inserted as leaf nodes. The cost is \n    O\n    (\n    h\n    )\n"
                "    {\\displaystyle O(h)}\n where h is the height.\n\n== References ==\nKnuth 1973.")

hits: list[tuple[str, float]] = []


def handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    hits.append((host, time.monotonic()))
    if path == "/robots.txt":
        if host == "public.example":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        if host == "wiki.example":
            return httpx.Response(503, text="down")
        return httpx.Response(404, text="none")
    if host == "redir.example":
        return httpx.Response(302, headers={"location": "http://evil.example/secret"})
    if host == "en.wikipedia.org":
        return httpx.Response(200, json={"query": {"pages": [{"title": "Binary search tree", "extract": WIKI_EXTRACT}]}})
    if path == "/image.png":
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")
    if path == "/huge":
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 5000)
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=ARTICLE)


def make_fetcher(interval: float = 0.0) -> SafeFetcher:
    return SafeFetcher(transport=httpx.MockTransport(handler), resolver=lambda h: DNS.get(h, ["93.184.216.99"]),
                       min_host_interval=interval)


async def kind_of(fetcher: SafeFetcher, url: str) -> str:
    try:
        await fetcher.fetch(url)
        return "ok"
    except FetchError as exc:
        return exc.kind


async def main() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    f = make_fetcher()
    blocked = ["http://127.0.0.1/", "http://10.0.0.5/x", "http://169.254.169.254/latest/meta-data/",
               "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://evil.example/page"]
    kinds = [await kind_of(f, u) for u in blocked]
    check(kinds == ["ssrf_blocked"] * len(blocked), f"#1 private/loopback/link-local/mapped targets refused: {kinds}")
    kinds = [await kind_of(f, u) for u in ["file:///etc/passwd", "ftp://public.example/x"]]
    check(kinds == ["bad_scheme", "bad_scheme"], f"#2 non-http schemes refused: {kinds}")
    check(await kind_of(f, "http://redir.example/start") == "ssrf_blocked", "#3 redirect to a private address refused at the hop")

    r = [await kind_of(f, "http://public.example/private/doc"), await kind_of(f, "http://public.example/article"),
         await kind_of(f, "http://other.example/article"), await kind_of(f, "http://wiki.example/article")]
    check(r == ["robots_denied", "ok", "ok", "robots_denied"], f"#4 robots: disallow / allowed / 404-allowed / 503-denied: {r}")

    old_max = fetch_mod.MAX_BYTES
    fetch_mod.MAX_BYTES = 1000
    r = [await kind_of(f, "http://other.example/image.png"), await kind_of(f, "http://other.example/huge")]
    fetch_mod.MAX_BYTES = old_max
    check(r == ["bad_type", "too_large"], f"#5 type allowlist and size cap: {r}")

    page = await f.fetch("http://other.example/article")
    check("moving left when the key is smaller" in page.text and "Login" not in page.text and "Copyright" not in page.text,
          f"#6 extraction keeps article, drops nav/footer (method={page.method})")

    wiki = await f.fetch("https://en.wikipedia.org/wiki/Binary_search_tree")
    check(wiki.method == "wikipedia_api" and "\nInsertion\n" in wiki.text and "$O(h)$" in wiki.text
          and "displaystyle" not in wiki.text and "Knuth" not in wiki.text,
          f"#7 Wikipedia API: sections kept, math inline, references dropped: {wiki.text!r}"[:300])

    hits.clear()
    slow = make_fetcher(interval=0.3)
    await slow.fetch("http://other.example/article")
    await slow.fetch("http://other.example/article2")
    page_hits = [t for h, t in hits if h == "other.example"]
    gaps = [b - a for a, b in zip(page_hits, page_hits[1:])]
    check(gaps and min(gaps) >= 0.28, f"#8 per-host spacing >= 0.3s: {[round(g, 2) for g in gaps]}")

    with tempfile.TemporaryDirectory() as tmp:
        async with ArchiveStore(pathlib.Path(tmp) / "a.sqlite3") as archive:
            url = "https://ex.org/bst"
            await archive.ingest(Document(url=url, title="BST", provider="p", source_type="web", content_kind="full_text"),
                                 "Full article: insertion walks from the root to an empty child position and attaches the node there.")
            res = await archive.ingest(Document(url=url, title="BST", provider="p", source_type="web", content_kind="summary"),
                                       "A BST is a tree.")
            hits_q = await archive.query("insertion empty child position")
            check(res.status == "kept_richer" and hits_q and "Full article" in hits_q[0].text,
                  f"#9 summary after full text -> {res.status}; full text still served")

            class OneProvider:
                name, need_kinds, key_env_vars, query_style = "web", frozenset({"explanation"}), (), "keywords"

                async def search(self, query, max_results):
                    return [RetrievedResource(title="BST insertion", url="http://other.example/article", source_type="web",
                                              snippet="Insertion in a binary search tree.", content_kind="summary"),
                            RetrievedResource(title="BST insertion mirror", url="http://evil.example/article", source_type="web",
                                              snippet="Insertion in a binary search tree mirror.", content_kind="summary")]

            os.environ.pop("DEWEY_FETCH", None)
            engine = DeweyEngine(archive, ProviderRegistry(providers=[OneProvider()]), fetcher=make_fetcher())
            batch = await engine.find(InformationNeed(text="How does insertion work in a binary search tree?"))
            fetch_reports = {r.provider + ":" + r.status: r.detail for r in batch.reports if r.provider.startswith("fetch:")}
            full = [p for p in batch.passages if p.content_kind == "full_text"]
            check(full and "attached there" in full[0].text and any(k.endswith(":ok") for k in fetch_reports)
                  and any(k.endswith(":failed") and "ssrf_blocked" in (v or "") for k, v in fetch_reports.items()),
                  f"#10 full page read + ingested; blocked mirror reported, batch fine: {list(fetch_reports)}")

    # 11-12 (iteration 05): plural-insensitive coverage; a weak summary still gets its page read
    from backend.main_block.research_engine.engine import FETCH_GATE, RELEVANCE_GATE, term_coverage
    cov = term_coverage("inputs and outputs of the light reactions", "input output light reaction")
    check(cov == 1.0, f"#11 plurals match their singulars (coverage {cov})")
    with tempfile.TemporaryDirectory() as tmp2:
        async with ArchiveStore(pathlib.Path(tmp2) / "b.sqlite3") as archive2:
            class SummaryOnly:
                name, need_kinds, key_env_vars, query_style = "wiki", frozenset({"explanation"}), (), "keywords"

                async def search(self, query, max_results):
                    return [RetrievedResource(title="Photosynthesis", url="http://other.example/article", source_type="web",
                                              snippet="Photosynthesis converts light energy.", content_kind="summary")]

            need = InformationNeed(text="What are the light-dependent reactions of photosynthesis, and what are their inputs and outputs?")
            low = term_coverage(need.text, "Photosynthesis Photosynthesis converts light energy.")
            engine2 = DeweyEngine(archive2, ProviderRegistry(providers=[SummaryOnly()]), fetcher=make_fetcher())
            batch = await engine2.find(need)
            fetched = [r for r in batch.reports if r.provider.startswith("fetch:") and r.status == "ok"]
            check(FETCH_GATE <= low < RELEVANCE_GATE and fetched,
                  f"#12 summary coverage {low:.2f} (< gate {RELEVANCE_GATE}) still read in full: {len(fetched)} fetch")


    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
