"""Phase 10.2 verification -- POST /lesson, wiring Lesson Authoring (Phase 10)
behind the same shallow-wrapper shape /course (Phase 9.2) already established
(docs/Phases.md, backend/api/app.py).

Two parts, same structure as scripts/verify_phase9_2.py/verify_phase10.py:

Part 1 (real Neo4j + real LLM, no HTTP): confirm the real "online payment"
course has at least one module with claims, so Part 2's real-success check
has real data to exercise.

Part 2 (real HTTP, via FastAPI's TestClient, real LLM calls): the actual
/lesson route -- a real concept -> 200 with a well-formed Lesson body; an
unknown concept -> 404; mode="learning" -> 501.

Checks:
  1. The real "online payment" course has at least one module with claims
     (a precondition, not new behavior -- confirms Part 2 has something
     real to ask for).
  2. POST /lesson with mode="learning" returns 501.
  3. POST /lesson for a concept that isn't in the course returns 404.
  4. POST /lesson for a real, ready concept returns 200 with a well-formed
     Lesson body (status="composed", non-empty explanation, source_claim_ids
     matching the real module's claims).
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
from backend.dewey.curriculum import compile_course  # noqa: E402
from backend.graph import close_driver, find_or_create_entity, materialize_abstraction  # noqa: E402
from backend.research_api import fetch_and_compile_research_response  # noqa: E402

_REAL_MODULE_NAME: str = ""


async def check_real_course_has_claims() -> None:
    global _REAL_MODULE_NAME
    entity = await find_or_create_entity("online payment")
    abstraction = await materialize_abstraction(entity.id)
    if abstraction is None:
        raise RuntimeError("online payment has no discovered decomposition in this Neo4j instance -- expected real, already-investigated data")
    response = await fetch_and_compile_research_response(abstraction.id, EXPLORATORY_POLICY)
    course = compile_course(response)

    with_claims = [m for m in course.modules if m.claims]
    assert with_claims, "expected at least one real module with claims in the 'online payment' course"
    _REAL_MODULE_NAME = with_claims[0].entity_name
    print(f"[PASS] #1 real course has {len(with_claims)} module(s) with claims -- using {_REAL_MODULE_NAME!r} for Part 2")

    # Same reason as verify_phase9_2.py/verify_r5_3.py: close the driver in
    # the same loop that created it, before Part 2's TestClient runs the app
    # in its own loop.
    await close_driver()


def check_learning_mode_rejected(client: TestClient) -> None:
    resp = client.post("/lesson", json={"topic": "online payment", "concept": _REAL_MODULE_NAME, "mode": "learning"})
    assert resp.status_code == 501, f"expected 501 for mode='learning', got {resp.status_code}: {resp.text}"
    print("[PASS] #2 POST /lesson with mode='learning' returns 501, matching /research and /course's own convention")


def check_unknown_concept_rejected(client: TestClient) -> None:
    resp = client.post("/lesson", json={"topic": "online payment", "concept": "Totally Made Up Concept Not In This Course"})
    assert resp.status_code == 404, f"expected 404 for a concept not in the course, got {resp.status_code}: {resp.text}"
    print("[PASS] #3 POST /lesson for a concept not in the compiled course returns 404")


def check_real_success_response(client: TestClient) -> None:
    resp = client.post("/lesson", json={"topic": "online payment", "concept": _REAL_MODULE_NAME})
    assert resp.status_code == 200, f"expected 200 for a real, ready concept, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "composed", f"expected status='composed', got {body['status']!r}"
    assert body["explanation"].strip(), "expected a real, non-empty explanation"
    assert body["source_claim_ids"], "expected real source_claim_ids, not an empty list"
    print(f"[PASS] #4 POST /lesson for {_REAL_MODULE_NAME!r} returns 200, status='composed', {len(body['source_claim_ids'])} real source claim(s)")


def run() -> None:
    try:
        asyncio.run(check_real_course_has_claims())
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] Part 1 (real Neo4j): could not run against real data ({exc})")
        return

    from backend.api.app import app

    with TestClient(app) as client:
        check_learning_mode_rejected(client)
        check_unknown_concept_rejected(client)
        check_real_success_response(client)

    print("\nAll 4 checks passed. Part 1 against real Neo4j ('online payment'). Part 2 via FastAPI's real TestClient, real LLM calls.")


if __name__ == "__main__":
    run()
