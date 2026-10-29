"""Verifies Dewey's read-through engine (backend/main_block/research_engine/engine.py) with fake
providers — offline, temp archive, no LLM:

  1. a miss researches, ingests, and answers from the Archive (source=research)
  2. the same need again is served from the Archive with ZERO provider calls
     (the "evolving archive" property)
  3. nothing found -> ledger records it; asking again inside the retry window
     does not re-search (source=known_gap)
  4. a failing / hanging provider is reported (failed / timed_out), the rest
     still contribute
  5. routing: an "evidence" need never calls an implementation-only provider
  6. a keyed provider with no key is skipped_no_key and never called
  7. every provider down -> source=unavailable, ledger retry in ~1h
  8. passages are tagged with the need's entity id
  9. results that don't cover the need are recorded "weak_results", not "found",
     and are re-searchable within hours
 10. metadata-only passages never count as covering a need
 11. the Archive is queried for a candidate pool wider than the output (retrieve-then-rerank)
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
from dataclasses import dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.main_block.research_engine.archive import ArchiveStore  # noqa: E402
from backend.main_block.research_engine.contracts import InformationNeed  # noqa: E402
from backend.main_block.research_engine.engine import DeweyEngine  # noqa: E402
from backend.main_block.research_engine.providers import ProviderRegistry  # noqa: E402
from backend.main_block.reasoning_engine.evidence.models import RetrievedResource  # noqa: E402

KEY_VAR = "DEWEY_TEST_FAKE_KEY"


@dataclass
class FakeProvider:
    name: str
    need_kinds: frozenset[str]
    results: list[RetrievedResource] = field(default_factory=list)
    key_env_vars: tuple[str, ...] = ()
    mode: str = "ok"  # ok | raise | hang
    calls: int = 0

    async def search(self, query: str, max_results: int) -> list[RetrievedResource]:
        self.calls += 1
        if self.mode == "raise":
            raise RuntimeError("boom")
        if self.mode == "hang":
            await asyncio.sleep(10)
        return self.results[:max_results]


def _res(title: str, url: str, snippet: str) -> RetrievedResource:
    return RetrievedResource(title=title, url=url, snippet=snippet, source_type="web", source_role="explanation",
                             content_kind="excerpt")


BST = [
    _res("Binary search tree", "https://ex.org/bst", "A binary search tree keeps keys ordered so search insertion and deletion follow one root-to-leaf path."),
    _res("BST operations", "https://ex.org/bst-ops", "Binary search tree search insertion deletion cost O(h): O(log n) balanced, O(n) degenerate."),
]


async def main() -> int:
    failures = 0
    os.environ.pop(KEY_VAR, None)
    os.environ["DEWEY_FETCH"] = "off"  # page fetching has its own offline suite (verify_dewey_fetch.py)

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    with tempfile.TemporaryDirectory() as tmp:
        async with ArchiveStore(pathlib.Path(tmp) / "a.sqlite3") as archive:
            web = FakeProvider("web", frozenset({"explanation", "definition"}), BST)
            broken = FakeProvider("broken", frozenset({"explanation"}), mode="raise")
            slow = FakeProvider("slow", frozenset({"explanation"}), mode="hang")
            code_only = FakeProvider("code_only", frozenset({"implementation"}), BST)
            paper = FakeProvider("paper", frozenset({"evidence"}), [])
            keyed = FakeProvider("keyed", frozenset({"explanation", "evidence"}), BST, key_env_vars=(KEY_VAR,))
            registry = ProviderRegistry(providers=[web, broken, slow, code_only, paper, keyed], timeout_seconds=0.5)
            engine = DeweyEngine(archive, registry)

            need = InformationNeed(text="How do binary search tree search insertion and deletion work?", entity_id="ent-bst")
            b1 = await engine.find(need)
            check(b1.source == "research" and b1.passages_ingested == 2 and len(b1.passages) >= 2 and web.calls == 1,
                  f"#1 miss -> research, ingested {b1.passages_ingested}, {len(b1.passages)} passage(s)")

            statuses = {r.provider: r.status for r in b1.reports}
            check(statuses.get("broken") == "failed" and statuses.get("slow") == "timed_out" and statuses.get("web") == "ok",
                  f"#4 failures reported per provider {statuses}")
            check(code_only.calls == 0 and "code_only" not in statuses, "#5 explanation need never routed to implementation-only provider")
            check(statuses.get("keyed") == "skipped_no_key" and keyed.calls == 0, "#6 keyed provider without key skipped, not called")
            check(all("ent-bst" in p.entity_ids for p in b1.passages), "#8 passages tagged with entity id")

            calls_before = web.calls + broken.calls + slow.calls
            b2 = await engine.find(InformationNeed(text="binary search tree deletion and insertion: how do they work"))
            check(b2.source == "archive" and web.calls + broken.calls + slow.calls == calls_before and b2.passages,
                  f"#2 repeat need (reworded) served from archive with zero provider calls (source={b2.source})")

            gap = InformationNeed(text="empirical studies on red-black versus AVL cache behaviour", need_kind="evidence")
            g1 = await engine.find(gap)
            g2 = await engine.find(gap)
            entry = await archive.ledger_entry(gap.text)
            check(g1.source == "research" and entry is not None and entry.outcome == "nothing_found"
                  and g2.source == "known_gap" and paper.calls == 1,
                  f"#3 nothing found -> ledger '{entry.outcome if entry else None}', second ask = {g2.source}, paper calls={paper.calls}")

            junk = FakeProvider("junk", frozenset({"history"}), [
                _res("Exciton-polaritons in cuprous oxide", "https://ex.org/phys", "Excitons couple to light in Cu2O crystals."),
            ])
            registry.providers.append(junk)
            weak = await engine.find(InformationNeed(text="history of red black tree invention", need_kind="history"))
            entry = await archive.ledger_entry("history of red black tree invention")
            check(weak.source == "research" and entry is not None and entry.outcome == "weak_results"
                  and not entry.retry_due, f"#9 irrelevant results -> ledger '{entry.outcome if entry else None}', not 'found'")

            meta = FakeProvider("meta", frozenset({"implementation"}), [
                _res("trie-lib", "https://ex.org/trie-lib", "Trie prefix autocomplete library with lookup and insertion costs."),
                _res("trie-lib2", "https://ex.org/trie-lib2", "Trie prefix autocomplete lookup insertion costs in Java."),
            ])
            registry.providers.append(meta)
            orig_search = meta.search

            async def stamped(query, max_results):
                out = await orig_search(query, max_results)
                for r in out:
                    r.content_kind = "metadata"
                return out

            meta.search = stamped
            m1 = await engine.find(InformationNeed(text="trie prefix autocomplete lookup insertion costs", need_kind="implementation"))
            entry = await archive.ledger_entry("trie prefix autocomplete lookup insertion costs")
            check(entry is not None and entry.outcome == "weak_results",
                  f"#10 metadata-only results never count as coverage -> {entry.outcome if entry else None}")

            # 11: the engine asks the Archive for a candidate pool wider than its output,
            # so the relevance gate/rerank has something to choose from
            asked: list[int] = []
            real_query = archive.query

            async def spy_query(text, *, limit=8, entity_id=None):
                asked.append(limit)
                return await real_query(text, limit=limit, entity_id=entity_id)

            archive.query = spy_query
            got = await engine.find(InformationNeed(text="binary search tree deletion and insertion: how do they work", max_passages=2))
            archive.query = real_query
            check(asked and asked[0] >= 2 * 4 and len(asked) > 1 and len(got.passages) <= 2,
                  f"#11 main pool {asked[:1]} + per-term pools {asked[1:]} > output {len(got.passages)} (max_passages=2)")

            web.mode = "raise"
            down = await engine.find(InformationNeed(text="splay tree amortized analysis zig zag"))
            entry = await archive.ledger_entry("splay tree amortized analysis zig zag")
            check(down.source == "unavailable" and entry is not None and entry.outcome == "providers_failed",
                  f"#7 all providers down -> {down.source}, ledger {entry.outcome if entry else None}")

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
