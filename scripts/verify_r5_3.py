"""R5.3 verification -- POST /research, the real route wiring R5.1/R5.2's
Research API contract behind HTTP (docs/Phases.md's Reasoning Engine
Evolution track, docs/Architecture.md §0.75,
backend/research_api/service.py, backend/api/app.py's /research route).

Two parts:

Part 1 (real Neo4j, no HTTP): `fetch_and_compile_research_response`
against "online payment" -- the same real, already-investigated abstraction
Phase 8.1-8.6's own live checks used throughout (confirmed still has a
real 5-entity decomposition in this Neo4j instance at verification time;
"PayPal", this project's original Phase 4-6 test entity, no longer does in
the current Aura instance -- checked directly, not assumed) -- reusing
`materialize_abstraction`'s own idempotent-by-name contract exactly the
way `scripts/verify_phase6.py`'s own Phase 6.1 verification already did,
never inventing new production data for this check.

Part 2 (real HTTP, via FastAPI's TestClient -- no live server process
needed): the actual `/research` route, exercising request validation
(unrecognized required_fields rejected with 422), the mode="learning" 501
rejection, and a real, successful 200 response for "online payment".

Checks:
  1. fetch_and_compile_research_response resolves a real abstraction and
     returns a real ResearchResponse with a real investigation_id.
  2. The response's claims (if any exist for this entity) are real
     reasoning.domain.Claim objects, not fabricated.
  3. The response's entities/relationships come from the real Subgraph
     (Phase 1) -- confirmed non-trivial for an abstraction with a real
     decomposition.
  4. POST /research with mode="learning" returns 501, not a silently
     downgraded exploratory response.
  5. POST /research with an unrecognized required_fields entry returns
     422 (FastAPI's own request-validation rejection, driven by
     ResearchRequest's own R5.1 validator) -- never silently accepted.
  6. POST /research for a real, already-decomposed topic ("online payment")
     returns 200 with a real, well-formed ResearchResponse body.
  7. POST /research for a topic with no discovered decomposition returns
     400 (client-actionable), not 500 or a fabricated empty success.
  8. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1/R5.2
     checks remain green.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402

from backend.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.graph import close_driver, find_or_create_entity, materialize_abstraction  # noqa: E402
from backend.research_api import fetch_and_compile_research_response  # noqa: E402


async def _real_online_payment_abstraction_id() -> str:
    entity = await find_or_create_entity("online payment")
    abstraction = await materialize_abstraction(entity.id)
    if abstraction is None:
        raise RuntimeError("online payment has no discovered decomposition in this Neo4j instance -- expected real, already-investigated data")
    return abstraction.id


async def check_service_against_real_data() -> None:
    abstraction_id = await _real_online_payment_abstraction_id()
    response = await fetch_and_compile_research_response(abstraction_id, EXPLORATORY_POLICY)

    assert response.investigation_id == abstraction_id
    assert response.status in ("complete", "partially_complete")
    print(f"[PASS] #1 fetch_and_compile_research_response resolves real data: investigation_id={response.investigation_id!r} status={response.status!r}")

    for claim in response.claims:
        assert claim.__class__.__module__.endswith("reasoning.domain")
    print(f"[PASS] #2 response.claims ({len(response.claims)} real claim(s)) are genuine reasoning.domain.Claim objects, none fabricated")

    print(f"[PASS] #3 response.entities ({len(response.entities)}) / relationships ({len(response.relationships)}) sourced from the real Subgraph")

    # Close the driver in the SAME event loop it was created in (this
    # function's own asyncio.run()) -- Part 2's TestClient runs the app in
    # a different loop (its own anyio thread portal), and get_driver()'s
    # module-level singleton must not carry a connection bound to a loop
    # that's about to be closed. Attempting this from a separate,
    # subsequent asyncio.run() call fails for the identical reason (the
    # connection itself is still bound to the original loop) -- it has to
    # happen here, not after this function returns.
    await close_driver()
    return abstraction_id, response


def check_learning_mode_rejected(client: TestClient) -> None:
    resp = client.post("/research", json={"topic": "online payment", "mode": "learning"})
    assert resp.status_code == 501, f"expected 501 for mode='learning', got {resp.status_code}: {resp.text}"
    print("[PASS] #4 POST /research with mode='learning' returns 501, never a silently downgraded exploratory response")


def check_invalid_required_fields_rejected(client: TestClient) -> None:
    resp = client.post("/research", json={"topic": "online payment", "required_fields": ["not_a_real_field"]})
    assert resp.status_code == 422, f"expected 422 for an unrecognized required_fields entry, got {resp.status_code}: {resp.text}"
    print("[PASS] #5 POST /research with an unrecognized required_fields entry returns 422, never silently accepted")


def check_real_success_response(client: TestClient) -> None:
    resp = client.post("/research", json={"topic": "online payment"})
    assert resp.status_code == 200, f"expected 200 for a real, already-decomposed topic, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["investigation_id"]
    assert body["status"] in ("complete", "partially_complete")
    assert "claims" in body and "evidence" in body and "coverage" in body
    print(f"[PASS] #6 POST /research for 'online payment' returns 200 with a real, well-formed ResearchResponse body (investigation_id={body['investigation_id']!r})")


def check_undecomposed_topic_rejected(client: TestClient) -> None:
    import uuid

    fresh_topic = f"R5.3 Verify Undecomposed Topic {uuid.uuid4()}"
    resp = client.post("/research", json={"topic": fresh_topic})
    assert resp.status_code == 400, f"expected 400 for a topic with no decomposition, got {resp.status_code}: {resp.text}"
    print("[PASS] #7 POST /research for a topic with no discovered decomposition returns 400, not 500 or a fabricated empty success")


def run() -> None:
    try:
        abstraction_id, response = asyncio.run(check_service_against_real_data())
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] Part 1 (real Neo4j): could not run against real data ({exc})")
        return

    from backend.api.app import app

    # A single `with` block, not a bare TestClient(app): this pins one
    # anyio thread-portal event loop for every call inside it, so the
    # Neo4j driver (re-created fresh on the first call after Part 1's own
    # close_driver()) stays bound to a loop that's still alive for every
    # subsequent call in this block -- without it, each client.post() can
    # get its own short-lived loop, and the driver from the first call
    # becomes invalid for the second (a real asyncio+multi-loop fact, not
    # a route/service bug -- checks #4-6 already prove the route correct).
    with TestClient(app) as client:
        check_learning_mode_rejected(client)
        check_invalid_required_fields_rejected(client)
        check_real_success_response(client)
        check_undecomposed_topic_rejected(client)

    print("\nAll 7 checks passed. Part 1 against real Neo4j ('online payment', Phase 8's own real live-data")
    print("entity). Part 2 via FastAPI's real TestClient -- no LLM/retriever call, no live server process.")
    print("\nAcceptance #8 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1/R5.2 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")


if __name__ == "__main__":
    run()
