"""docs/Architecture.md §0.27 live verification -- Semantic Graph Projections.

Runs against the REAL SessionState/handle_set_projection code, not a mock,
following this project's established "no LLM in the loop for logic that
doesn't need one" verification pattern (see verify_relation_claims.py). This
sidesteps external provider quota exhaustion (Groq TPD cap hit, Gemini's
instructor json_schema_mode incompatibility) entirely -- the code under test
here (handle_set_projection, PROJECTION_FAMILIES, to_payload's family field)
makes zero LLM calls by architectural design, so verifying it needs none
either. Provider-dependent behavior (parse_intent turning "show it as a flow"
into a set_projection Intent) is a separate, already-covered concern -- this
script proves the handler's OWN logic once an Intent has been produced.

Run on the VM (needs the real asyncpg/db-backed import chain):
    ssh ... "cd ~/app && .venv/bin/python scripts/verify_projections.py"
"""
import asyncio
import sys

sys.path.insert(0, ".")

from backend.api.app import handle_set_projection
from backend.api.session import SessionState
from backend.questions.intent import Intent


def make_intent(projection):
    return Intent(action="set_projection", projection=projection)


async def main():
    session = SessionState()
    # A small graph spanning multiple families -- composition (structure),
    # causal, and interaction (network) -- deliberately with ZERO temporal
    # edges, so "flow" is the case that must produce an honest gap.
    session.add_edge("Payment System", "PayPal", "decomposes_into")
    session.add_edge("Payment System", "Mastercard", "decomposes_into")
    session.add_edge("PayPal", "Mastercard", "uses")
    session.add_edge("Fraud Detected", "Payment Blocked", "causes")
    session.current_entity = "Payment System"

    nodes_before = sorted(n.id for n in session._nodes.values())
    edges_before = sorted(session._edges)

    def assert_world_unchanged(label):
        nodes_after = sorted(n.id for n in session._nodes.values())
        edges_after = sorted(session._edges)
        assert nodes_after == nodes_before, f"[{label}] FAIL: nodes changed! {nodes_before} -> {nodes_after}"
        assert edges_after == edges_before, f"[{label}] FAIL: edges changed! {edges_before} -> {edges_after}"
        print(f"[{label}] world model unchanged (G_after == G_before): OK")

    # 1. structure -> should surface the two decomposes_into edges
    reply = await handle_set_projection(session, make_intent("structure"))
    print("structure:", reply)
    assert session.current_projection == "structure"
    assert "2 relationship" in reply, f"expected 2 structural relations, got: {reply}"
    assert_world_unchanged("structure")

    # 2. causal -> should surface the one causal edge
    reply = await handle_set_projection(session, make_intent("causal"))
    print("causal:", reply)
    assert "Fraud Detected" in reply and "Payment Blocked" in reply
    assert_world_unchanged("causal")

    # 3. network -> should surface the uses edge
    reply = await handle_set_projection(session, make_intent("network"))
    print("network:", reply)
    assert "PayPal" in reply and "Mastercard" in reply
    assert_world_unchanged("network")

    # 4. flow -> HONEST GAP: zero temporal edges exist, must say so, not investigate
    reply = await handle_set_projection(session, make_intent("flow"))
    print("flow (expect honest gap):", reply)
    assert "gap" not in reply.lower() or "doesn't currently contain" in reply, reply
    assert "doesn't currently contain" in reply, f"expected an honest-gap message, got: {reply}"
    assert "investigat" not in reply.lower() or "try investigating further" in reply
    assert_world_unchanged("flow (gap)")

    # 5. dependency -> also a gap (no dependency-family edges either)
    reply = await handle_set_projection(session, make_intent("dependency"))
    print("dependency (expect honest gap):", reply)
    assert "doesn't currently contain" in reply
    assert_world_unchanged("dependency (gap)")

    # 6. all -> resets the filter, current_projection back to None
    reply = await handle_set_projection(session, make_intent("all"))
    print("all:", reply)
    assert session.current_projection is None
    assert_world_unchanged("all (reset)")

    # 7. to_payload's edges each carry the right family (what chat.html filters on)
    payload_families = {(e["source"], e["target"], e["label"]): e["family"] for e in session.to_payload()["edges"]}
    assert payload_families[("Payment System", "PayPal", "decomposes_into")] == "composition"
    assert payload_families[("PayPal", "Mastercard", "uses")] == "interaction"
    assert payload_families[("Fraud Detected", "Payment Blocked", "causes")] == "causal"
    print("to_payload family tagging: OK")

    # 8. Space-scoping: an interaction edge OUTSIDE the entered space must not
    # count as a match -- the honest-gap check has to agree with what
    # computeSpaceViewport in chat.html will actually render, not the whole
    # accumulated graph, once the user has entered a specific space.
    session2 = SessionState()
    session2.add_edge("Payment System", "PayPal", "decomposes_into")
    session2.add_edge("Payment System", "Mastercard", "decomposes_into")
    session2.add_edge("Mastercard", "Visa Network", "uses")  # outside PayPal's space
    session2.current_space = "PayPal"  # entered PayPal's own (empty) subspace
    reply = await handle_set_projection(session2, make_intent("network"))
    print("space-scoped network (expect gap, Mastercard->Visa is outside PayPal's space):", reply)
    assert "doesn't currently contain" in reply, f"expected a gap scoped to PayPal's space, got: {reply}"

    session2.current_space = "Payment System"  # entered the space that DOES reach it
    reply = await handle_set_projection(session2, make_intent("network"))
    print("space-scoped network (expect match, now inside Payment System's space):", reply)
    assert "Mastercard" in reply and "Visa Network" in reply, f"expected the match once in-scope, got: {reply}"
    print("space-scoping: OK")

    print("\nALL §0.27 CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
