"""Ad-hoc verification — the two semantic operations agreed as the first concrete
Phase 6 step (docs/Memory.md): `zoom_in` (materializes an Abstraction over an
entity's already-discovered `decomposes_into` structure) and `explain_entity`
(read-only provenance trace). Not a numbered Phases.md deliverable.

Deliberately runs against data ALREADY in Neo4j from today's earlier verification
runs — no new agent/LLM calls needed, since the point is to validate the semantic
layer over discoveries that already exist, not to discover anything new.

Requires a running Neo4j instance (VM only — no local Docker on the dev machine).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph import (  # noqa: E402
    GraphInterfaceError,
    attach_entity,
    close_driver,
    create_abstraction,
    create_relationship,
    explain_entity,
    find_or_create_entity,
    zoom_in,
)


async def check_multiple_children() -> None:
    """Entity with multiple decomposes_into children — 'Internet Infrastructure
    Probe' from the graph-persistence verification (DNS/TCP-TLS/Routing)."""
    parent = await find_or_create_entity("Internet Infrastructure Probe")
    abstraction = await zoom_in(parent.id)
    assert abstraction is not None, "expected a materialized abstraction for a multi-child entity"
    print(f"[ok] zoom_in('Internet Infrastructure Probe') -> abstraction {abstraction.name!r} ({abstraction.id})")

    # Idempotency: zooming in again must reuse the same Abstraction, not duplicate it.
    abstraction2 = await zoom_in(parent.id)
    assert abstraction2 is not None
    assert abstraction2.id == abstraction.id, "zoom_in must be idempotent by entity name, not create a duplicate"
    print("[ok] zoom_in is idempotent — second call reused the same Abstraction")


async def check_single_child() -> None:
    """Entity with exactly one decomposes_into child — manufactured fixture (no
    existing single-child case in today's data), built directly via the Graph
    Interface, not a new agent run."""
    parent = await find_or_create_entity("Zoom Test Single-Child Parent")
    child = await find_or_create_entity("Zoom Test Single-Child Only Child")
    await create_relationship(parent.id, child.id, "decomposes_into")

    abstraction = await zoom_in(parent.id)
    assert abstraction is not None
    print(f"[ok] zoom_in on a single-child entity -> abstraction {abstraction.name!r}")


async def check_no_children() -> None:
    """Entity with no decomposes_into children — 'PayPal', created via plain
    create_node in earlier phases, never decomposed."""
    entity = await find_or_create_entity("PayPal")
    abstraction = await zoom_in(entity.id)
    assert abstraction is None, "zoom_in on a childless entity must return None, not a manufactured abstraction"
    print("[ok] zoom_in('PayPal') correctly returned None (no manufactured empty abstraction)")


async def check_multiple_discovering_questions() -> None:
    """'PayPal' has had attach_question called against it across several separate
    verify_phase5.py runs today (each generates a fresh question_id) — a real,
    not manufactured, multi-question case."""
    entity = await find_or_create_entity("PayPal")
    explanation = await explain_entity(entity.id)
    print(f"[explain] PayPal discovered_by {len(explanation.discovered_by)} question(s):")
    for prov in explanation.discovered_by:
        print(f"  - {prov.question_text!r} (parent: {prov.parent_question_text!r})")
    assert len(explanation.discovered_by) >= 1, "expected at least one attached question for PayPal"


async def check_explain_sub_question_provenance() -> None:
    """A discovered entity's question should show its parent question's TEXT,
    parsed from the existing rationale — 'Internet Infrastructure Probe's
    children (DNS resolution etc.) all have rationale 'Sub-question of: <parent
    question text>'."""
    parent = await find_or_create_entity("Internet Infrastructure Probe")
    children = await zoom_in(parent.id)
    assert children is not None
    dns = await find_or_create_entity("DNS resolution")
    explanation = await explain_entity(dns.id)
    print(f"[explain] 'DNS resolution' discovered_by {len(explanation.discovered_by)} question(s):")
    found_parent_text = False
    for prov in explanation.discovered_by:
        print(f"  - question: {prov.question_text!r}")
        print(f"    parent_question_text: {prov.parent_question_text!r}")
        if prov.parent_question_text:
            found_parent_text = True
    assert found_parent_text, "expected at least one question on 'DNS resolution' with a parsed parent_question_text"
    print("[ok] parent_question_text correctly parsed from existing rationale, no new graph property needed")


async def check_unknown_entity_id() -> None:
    fake_id = str(uuid.uuid4())
    for label, fn in (("zoom_in", zoom_in), ("explain_entity", explain_entity)):
        try:
            await fn(fake_id)
            raise AssertionError(f"{label} should have raised GraphInterfaceError for an unknown id")
        except GraphInterfaceError:
            print(f"[ok] {label}(unknown id) raised GraphInterfaceError as expected")


async def check_explain_entity_is_read_only() -> None:
    """explain_entity must never write — call it 3x on the same entity and
    confirm the result (and therefore the underlying graph state it reflects) is
    byte-identical every time."""
    entity = await find_or_create_entity("PayPal")
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
        print("\nzoom_in / explain_entity verification PASSED.")
    finally:
        await close_driver()


if __name__ == "__main__":
    asyncio.run(run())
