"""Phase 1 verification script — see docs/Phases.md "Phase 1".

Creates a small abstraction, reads it back via get_subgraph, and confirms an entity can
belong to two abstractions at once (non-strict hierarchy — docs/Rules.md rule 13).

Requires a running Neo4j instance: `docker compose up -d` from the project root first,
and a `.env` file (copy .env.example) matching its credentials.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.graph import (  # noqa: E402
    attach_entity,
    close_driver,
    create_abstraction,
    create_node,
    create_relationship,
    ensure_constraints,
    get_abstractions_for_node,
    get_subgraph,
)


async def run() -> None:
    try:
        await ensure_constraints()

        abstraction = await create_abstraction(
            "Payment Platforms", "Entities that move money between parties online"
        )
        paypal = await create_node("PayPal", "entity", "Online payments company")
        stripe = await create_node("Stripe", "entity", "Payments infrastructure for the internet")
        mastercard = await create_node("Mastercard", "entity", "Card payment network")

        await create_relationship(paypal.id, stripe.id, "competes_with")
        await create_relationship(paypal.id, mastercard.id, "uses_network")

        for node in (paypal, stripe, mastercard):
            await attach_entity(node.id, abstraction.id)

        subgraph = await get_subgraph(abstraction.id)
        assert subgraph.abstraction.id == abstraction.id
        got_ids = {n.id for n in subgraph.nodes}
        want_ids = {paypal.id, stripe.id, mastercard.id}
        assert got_ids == want_ids, f"get_subgraph node mismatch: got {got_ids}, want {want_ids}"
        assert len(subgraph.relationships) == 2, (
            f"expected 2 relationships in subgraph, got {len(subgraph.relationships)}"
        )
        print(
            f"[ok] get_subgraph('{abstraction.name}') returned "
            f"{len(subgraph.nodes)} nodes and {len(subgraph.relationships)} relationships"
        )

        # Non-strict hierarchy check (docs/Rules.md rule 13): PayPal belongs to a second,
        # unrelated abstraction at the same time.
        case_studies = await create_abstraction(
            "Fintech Case Studies", "Companies studied for a business-history deep dive"
        )
        await attach_entity(paypal.id, case_studies.id)

        paypal_abstractions = await get_abstractions_for_node(paypal.id)
        abstraction_ids = {a.id for a in paypal_abstractions}
        assert abstraction.id in abstraction_ids and case_studies.id in abstraction_ids, (
            "PayPal should belong to both abstractions at once (non-strict hierarchy)"
        )
        names = [a.name for a in paypal_abstractions]
        print(f"[ok] PayPal belongs to {len(paypal_abstractions)} abstractions simultaneously: {names}")

        print("\nPhase 1 verification PASSED.")
    finally:
        await close_driver()


if __name__ == "__main__":
    asyncio.run(run())
