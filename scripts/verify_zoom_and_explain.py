"""Ad-hoc verification — the two semantic operations agreed as the first concrete
Phase 6 step (docs/Memory.md): `materialize_abstraction` (materializes an
Abstraction over an entity's already-discovered `decomposes_into` structure) and
`explain_entity` (read-only provenance trace). Not a numbered Phases.md deliverable.

Originally written to run against data already in Neo4j from that same session's
earlier verification runs ("Internet Infrastructure Probe", "PayPal"). That
coupling has since broken on its own: this project has moved between Neo4j
instances since 2026-08-28 (the same drift `scripts/verify_r5_3.py` already
named explicitly for "PayPal" losing its decomposition), so those fixtures no
longer reliably exist. Fixed properly (2026-09-17 verification-hygiene pass),
not worked around: every check below now builds its own fresh, disposable,
uniquely-named fixture via the Graph Interface directly, the same convention
`scripts/verify_r4_4.py`/`verify_r4_5.py` already established ("R4.4 Verify Test
Entity") — durable regardless of which Neo4j instance this runs against, no
dependency on any other script having run first.

Requires a running Neo4j instance.

**Verification-hygiene note (2026-09-17):** this script originally imported and
called `zoom_in`, which Phase 6.1 renamed to `materialize_abstraction`
(docs/Architecture.md §0.39.2 — the old name collided with `app.py`'s unrelated
`handle_zoom_in`, and that collision is exactly what let Phase 6's own missing-
caller gap hide through its build-and-verify pass). This script was never updated
at the time, so it had been failing on import (`ImportError: cannot import name
'zoom_in'`) ever since — a stale verification script, not a product regression.
Fixed to the real name. Fixing the import alone was not sufficient, though:
re-running it against the current Neo4j instance surfaced the second, separate
issue above (fixture data drift) on the very first check, confirmed directly
(`get_decomposition` on "Internet Infrastructure Probe" returned zero children
in this instance) rather than assumed — both issues are fixed here, not just
the one originally reported.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import time

from backend.graph import (  # noqa: E402
    GraphInterfaceError,
    attach_question,
    close_driver,
    create_relationship,
    explain_entity,
    find_or_create_entity,
    materialize_abstraction,
)

_RUN_TAG = str(int(time.time()))
"""Appended to every fixture entity name so repeated runs never collide with
(or silently reuse) a previous run's disposable fixtures -- each run gets its
own genuinely fresh nodes, same discipline as R4.4/R4.5's real-Neo4j checks."""


async def check_multiple_children() -> None:
    """Entity with multiple decomposes_into children -- a fresh, disposable
    3-child fixture built directly via the Graph Interface, not depending on
    any other script (or an earlier run of this one) having populated Neo4j
    first."""
    parent = await find_or_create_entity(f"Zoom Test Multi-Child Parent {_RUN_TAG}")
    for child_name in ("DNS resolution", "TCP/TLS handshake", "IP routing"):
        child = await find_or_create_entity(f"Zoom Test Multi-Child Child: {child_name} {_RUN_TAG}")
        await create_relationship(parent.id, child.id, "decomposes_into")

    abstraction = await materialize_abstraction(parent.id)
    assert abstraction is not None, "expected a materialized abstraction for a multi-child entity"
    print(f"[ok] materialize_abstraction(multi-child fixture) -> abstraction {abstraction.name!r} ({abstraction.id})")

    # Idempotency: zooming in again must reuse the same Abstraction, not duplicate it.
    abstraction2 = await materialize_abstraction(parent.id)
    assert abstraction2 is not None
    assert abstraction2.id == abstraction.id, "materialize_abstraction must be idempotent by entity name, not create a duplicate"
    print("[ok] materialize_abstraction is idempotent — second call reused the same Abstraction")


async def check_single_child() -> None:
    """Entity with exactly one decomposes_into child — a fresh, disposable
    fixture, built directly via the Graph Interface, not a new agent run."""
    parent = await find_or_create_entity(f"Zoom Test Single-Child Parent {_RUN_TAG}")
    child = await find_or_create_entity(f"Zoom Test Single-Child Only Child {_RUN_TAG}")
    await create_relationship(parent.id, child.id, "decomposes_into")

    abstraction = await materialize_abstraction(parent.id)
    assert abstraction is not None
    print(f"[ok] materialize_abstraction on a single-child entity -> abstraction {abstraction.name!r}")


async def check_no_children() -> None:
    """A fresh entity with no decomposes_into children -- built disposably
    rather than assumed of a named real entity (e.g. "PayPal"), whose real
    decomposition state legitimately varies across Neo4j instances and over
    time as this project's own real investigation history grows."""
    entity = await find_or_create_entity(f"Zoom Test No-Children Entity {_RUN_TAG}")
    abstraction = await materialize_abstraction(entity.id)
    assert abstraction is None, "materialize_abstraction on a childless entity must return None, not a manufactured abstraction"
    print("[ok] materialize_abstraction on a childless entity correctly returned None (no manufactured empty abstraction)")


async def check_multiple_discovering_questions() -> None:
    """A fresh entity with two real, distinct attached questions -- built
    disposably via attach_question directly, rather than depending on a named
    real entity having accumulated multiple questions from other scripts'
    prior runs (fragile across Neo4j instances and over time)."""
    entity = await find_or_create_entity(f"Zoom Test Multi-Question Entity {_RUN_TAG}")
    await attach_question(
        entity.id, question_id=f"zoom-test-q1-{_RUN_TAG}", text="What is this entity?",
        dimension_id="scale", level="ground", rationale="Root question.",
    )
    await attach_question(
        entity.id, question_id=f"zoom-test-q2-{_RUN_TAG}", text="How does this entity work internally?",
        dimension_id="scale", level="ground", rationale="Sub-question of: What is this entity?",
    )
    explanation = await explain_entity(entity.id)
    print(f"[explain] fixture entity discovered_by {len(explanation.discovered_by)} question(s):")
    for prov in explanation.discovered_by:
        print(f"  - {prov.question_text!r} (parent: {prov.parent_question_text!r})")
    assert len(explanation.discovered_by) >= 2, "expected both attached questions on the fixture entity"


async def check_explain_sub_question_provenance() -> None:
    """A discovered entity's question should show its parent question's TEXT,
    parsed from the existing rationale ('Sub-question of: <parent question
    text>', already written by attach_question) -- verified here against a
    fresh, disposable fixture built with that exact rationale format, not
    assumed to still exist from an earlier real investigation."""
    parent_question_text = "What is this entity?"
    entity = await find_or_create_entity(f"Zoom Test Provenance Entity {_RUN_TAG}")
    await attach_question(
        entity.id, question_id=f"zoom-test-provenance-q-{_RUN_TAG}", text="How does this entity work internally?",
        dimension_id="scale", level="ground", rationale=f"Sub-question of: {parent_question_text}",
    )
    explanation = await explain_entity(entity.id)
    print(f"[explain] fixture entity discovered_by {len(explanation.discovered_by)} question(s):")
    found_parent_text = False
    for prov in explanation.discovered_by:
        print(f"  - question: {prov.question_text!r}")
        print(f"    parent_question_text: {prov.parent_question_text!r}")
        if prov.parent_question_text == parent_question_text:
            found_parent_text = True
    assert found_parent_text, "expected the fixture question's parent_question_text to be parsed correctly from its rationale"
    print("[ok] parent_question_text correctly parsed from existing rationale, no new graph property needed")


async def check_unknown_entity_id() -> None:
    fake_id = str(uuid.uuid4())
    for label, fn in (("materialize_abstraction", materialize_abstraction), ("explain_entity", explain_entity)):
        try:
            await fn(fake_id)
            raise AssertionError(f"{label} should have raised GraphInterfaceError for an unknown id")
        except GraphInterfaceError:
            print(f"[ok] {label}(unknown id) raised GraphInterfaceError as expected")


async def check_explain_entity_is_read_only() -> None:
    """explain_entity must never write — call it 3x on the same entity and
    confirm the result (and therefore the underlying graph state it reflects) is
    byte-identical every time."""
    entity = await find_or_create_entity(f"Zoom Test Read-Only Entity {_RUN_TAG}")
    results = [await explain_entity(entity.id) for _ in range(3)]
    assert results[0] == results[1] == results[2], "explain_entity must be read-only (identical repeated results)"
    print("[ok] explain_entity confirmed read-only (3 calls, identical results)")


async def run() -> None:
    try:
        await check_multiple_children()
        await check_single_child()
        await check_no_children()
        await check_multiple_discovering_questions()
        await check_explain_sub_question_provenance()
        await check_unknown_entity_id()
        await check_explain_entity_is_read_only()
        print("\nmaterialize_abstraction / explain_entity verification PASSED.")
    finally:
        await close_driver()


if __name__ == "__main__":
    asyncio.run(run())
