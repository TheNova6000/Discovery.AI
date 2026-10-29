"""Verifies stage-1 entity canonicalisation (backend/main_block/reasoning_engine/graph/canonical.py +
find_or_create_entity), loop iteration 02, E4.

Pure (no database):
  1. canonical keys: case, articles, punctuation, camelCase and plurals collapse
  2. acronyms: initials of multi-word names; acronym tokens detected in names
  3. acronym expansion only uses the expansions given
Live Neo4j (unique made-up names, deleted afterwards):
  4. "Quokka heap forest" then "QHF" -> same node (acronym)
  5. "QHF Property" and "the QHF property" -> same node (key)
  6. "QuokkaHeapForestOperations" and "QHF operations" -> same node (camelCase + acronym)
  7. a genuinely different name still creates a new node
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.main_block.reasoning_engine.graph import close_driver, find_or_create_entity, get_driver  # noqa: E402
from backend.main_block.reasoning_engine.graph.canonical import acronym_of, acronym_tokens, canonical_key, expand_acronyms  # noqa: E402


async def main() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    keys = [canonical_key(n) for n in ["BST Property", "the BST property", "BST properties"]]
    check(len(set(keys)) == 1, f"#1 keys collapse: {keys}")
    check(canonical_key("BinarySearchTreeOperations") == canonical_key("binary search tree operations") == "binary search tree operation",
          f"#1 camelCase + plural: {canonical_key('BinarySearchTreeOperations')!r}")
    check(acronym_of("Binary search tree") == "bst" and acronym_of("Insertion") is None
          and acronym_tokens("BST operations") == ["bst"] and acronym_tokens("Binary search tree") == [],
          "#2 acronym_of / acronym_tokens")
    check(expand_acronyms("BST operations", {"bst": "binary search tree"}) == "binary search tree operation"
          and expand_acronyms("BST operations", {}) == "bst operation", "#3 expansion only with a known expansion")

    created: set[str] = set()
    try:
        forest = await find_or_create_entity("Quokka heap forest")
        created.add(forest.id)
        acr = await find_or_create_entity("QHF")
        created.add(acr.id)
        check(acr.id == forest.id, "#4 'QHF' resolves to 'Quokka heap forest'")

        p1 = await find_or_create_entity("QHF Property")
        p2 = await find_or_create_entity("the QHF property")
        created |= {p1.id, p2.id}
        check(p1.id == p2.id, "#5 'QHF Property' == 'the QHF property'")

        o1 = await find_or_create_entity("QuokkaHeapForestOperations")
        o2 = await find_or_create_entity("QHF operations")
        created |= {o1.id, o2.id}
        check(o1.id == o2.id, "#6 'QuokkaHeapForestOperations' == 'QHF operations'")

        other = await find_or_create_entity("Quokka heap meadow")
        created.add(other.id)
        check(other.id not in {forest.id, p1.id, o1.id}, "#7 a different name gets its own node")
    finally:
        async with get_driver().session() as session:
            await session.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=list(created))
        await close_driver()

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
