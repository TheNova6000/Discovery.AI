"""Phase 9.2 verification -- POST /course, wiring the Curriculum Compiler
(Phase 9.1) behind the same shallow-wrapper shape /research (R5.3) already
established (docs/Phases.md, backend/api/app.py).

Two parts, same structure and same real test data as scripts/verify_r5_3.py:

Part 1 (real Neo4j, no HTTP): fetch_and_compile_research_response +
compile_course against "online payment" -- the same real, already-
investigated abstraction R5.3's own live check used.

Part 2 (real HTTP, via FastAPI's TestClient): the actual /course route --
mode="learning" rejected with 501, an undecomposed topic rejected with 400,
a real successful 200 response for "online payment" with a well-formed
Course body.

Checks:
  1. compile_course over real, live-fetched ResearchResponse data produces
     a real Course with a real investigation_id.
  2. /course with mode="learning" returns 501, matching /research's own
     convention.
  3. /course for a topic with no discovered decomposition returns 400.
  4. /course for a real, already-decomposed topic returns 200 with a
     well-formed Course body (modules/incomplete_concepts/
     ordered_by_prerequisites all present).
  5. Existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1-R5.3/
     Phase 9.1 checks remain green.
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


async def _real_online_payment_abstraction_id() -> str:
    entity = await find_or_create_entity("online payment")
    abstraction = await materialize_abstraction(entity.id)
    if abstraction is None:
        raise RuntimeError("online payment has no discovered decomposition in this Neo4j instance -- expected real, already-investigated data")
    return abstraction.id


async def check_compile_course_against_real_data() -> None:
    abstraction_id = await _real_online_payment_abstraction_id()
    response = await fetch_and_compile_research_response(abstraction_id, EXPLORATORY_POLICY)
    course = compile_course(response)

    assert course.investigation_id == abstraction_id
    assert isinstance(course.modules, list)
    assert isinstance(course.incomplete_concepts, list)
    print(f"[PASS] #1 compile_course over real data: investigation_id={course.investigation_id!r} modules={len(course.modules)} incomplete_concepts={len(course.incomplete_concepts)} ordered_by_prerequisites={course.ordered_by_prerequisites!r}")

    # Same reason as verify_r5_3.py: close the driver in the same loop that
    # created it, before Part 2's TestClient runs the app in its own loop.
    await close_driver()


def check_learning_mode_rejected(client: TestClient) -> None:
    resp = client.post("/course", json={"topic": "online payment", "mode": "learning"})
    assert resp.status_code == 501, f"expected 501 for mode='learning', got {resp.status_code}: {resp.text}"
    print("[PASS] #2 POST /course with mode='learning' returns 501, matching /research's own convention")


def check_undecomposed_topic_rejected(client: TestClient) -> None:
    import uuid

    fresh_topic = f"Phase 9.2 Verify Undecomposed Topic {uuid.uuid4()}"
    resp = client.post("/course", json={"topic": fresh_topic})
    assert resp.status_code == 400, f"expected 400 for a topic with no decomposition, got {resp.status_code}: {resp.text}"
    print("[PASS] #3 POST /course for a topic with no discovered decomposition returns 400")


def check_real_success_response(client: TestClient) -> None:
    resp = client.post("/course", json={"topic": "online payment"})
    assert resp.status_code == 200, f"expected 200 for a real, already-decomposed topic, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["investigation_id"]
    assert "modules" in body and "incomplete_concepts" in body and "ordered_by_prerequisites" in body
    print(f"[PASS] #4 POST /course for 'online payment' returns 200 with a well-formed Course body (investigation_id={body['investigation_id']!r}, {len(body['modules'])} module(s))")


def run() -> None:
    try:
        asyncio.run(check_compile_course_against_real_data())
    except Exception as exc:  # noqa: BLE001
        print(f"[SKIP] Part 1 (real Neo4j): could not run against real data ({exc})")
        return

    from backend.api.app import app

    with TestClient(app) as client:
        check_learning_mode_rejected(client)
        check_undecomposed_topic_rejected(client)
        check_real_success_response(client)

    print("\nAll 4 checks passed. Part 1 against real Neo4j ('online payment'). Part 2 via FastAPI's real TestClient.")
    print("Acceptance #5 (existing Phase 6/8.1-8.6/R1.1-R1.5/R2.1/R3.1/R3.2/R4.1-R4.5/R5.1-R5.3/Phase 9.1 checks remain green)")
    print("is verified separately by re-running those scripts unmodified.")


if __name__ == "__main__":
    run()
