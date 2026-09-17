"""Phase 10 verification -- compile_lesson, Lesson Authoring's real I/O shell
(docs/Phases.md, docs/Architecture.md, docs/Rules.md rules 2/16/19,
backend/lessons/).

Two parts, same structure as scripts/verify_phase9_2.py:

Part 1 (pure, no LLM call): a module with zero real claims must never reach
compose_lesson_explanation at all -- confirmed by construction (the function
returns before any I/O), not by mocking.

Part 2 (real, live): compile_lesson against a real Module from the actual
"online payment" Course (Phase 9.1/9.2's own real live data) -- a real LLM
composition call, then a real, independent audit_synthesis call, both
against real providers now that Phase S0.1's has_any_provider_key() fix
makes this environment's real keys usable.

Checks:
  1. A module with zero claims never calls the LLM and returns
     status="insufficient_claims", fully_traceable=None, no fabricated text.
  2. A real module's lesson is composed only from its own claims (identity
     of source_claim_ids), with a real, non-empty explanation.
  3. Every sentence audited by audit_synthesis is either "investigated" or
     "uninvestigated" -- never a third, invented value -- and
     fully_traceable is computed correctly from those real sentence origins.
  4. The lesson never contains a source_claim_id that wasn't in the input
     module (no fabricated provenance).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.agents.policy import EXPLORATORY_POLICY  # noqa: E402
from backend.curriculum import Module, compile_course  # noqa: E402
from backend.graph import close_driver, find_or_create_entity, materialize_abstraction  # noqa: E402
from backend.lessons import Lesson, compile_lesson  # noqa: E402
from backend.research_api import fetch_and_compile_research_response  # noqa: E402


async def check_zero_claims_module_never_calls_llm() -> None:
    empty_module = Module(entity_id="e-empty", entity_name="Empty Concept", claims=[])
    lesson = await compile_lesson(empty_module)
    assert lesson.status == "insufficient_claims"
    assert lesson.explanation == ""
    assert lesson.sentences == []
    assert lesson.fully_traceable is None, "must be None (never attempted), not False (attempted and failed)"
    assert lesson.source_claim_ids == []
    print("[PASS] #1 a module with zero claims never calls the LLM, returns status='insufficient_claims' with fully_traceable=None")


async def _real_online_payment_module() -> Module:
    entity = await find_or_create_entity("online payment")
    abstraction = await materialize_abstraction(entity.id)
    if abstraction is None:
        raise RuntimeError("online payment has no discovered decomposition in this Neo4j instance -- expected real, already-investigated data")
    response = await fetch_and_compile_research_response(abstraction.id, EXPLORATORY_POLICY)
    course = compile_course(response)
    for module in course.modules:
        if module.claims:
            return module
    raise RuntimeError("no module in the real 'online payment' course has any claims -- cannot exercise compile_lesson's real path")


async def check_real_lesson_composition() -> Lesson:
    module = await _real_online_payment_module()
    lesson = await compile_lesson(module)

    assert lesson.status == "composed"
    assert lesson.entity_id == module.entity_id
    assert lesson.explanation.strip(), "expected a real, non-empty composed explanation"
    print(f"[PASS] #2 real module {module.entity_name!r} ({len(module.claims)} claim(s)) -> a real, non-empty composed explanation ({len(lesson.explanation)} chars)")

    real_origins = {s.origin for s in lesson.sentences}
    assert real_origins <= {"investigated", "uninvestigated"}, f"unexpected origin value(s): {real_origins - {'investigated', 'uninvestigated'}}"
    expected_fully_traceable = all(s.origin == "investigated" for s in lesson.sentences) if lesson.sentences else False
    assert lesson.fully_traceable == expected_fully_traceable
    print(f"[PASS] #3 {len(lesson.sentences)} sentence(s) audited, each 'investigated' or 'uninvestigated' -- fully_traceable={lesson.fully_traceable!r} computed correctly")

    real_claim_ids = {c.claim_id for c in module.claims}
    assert set(lesson.source_claim_ids) == real_claim_ids, "source_claim_ids must exactly match the real input module's claims -- no fabricated or dropped provenance"
    print(f"[PASS] #4 source_claim_ids ({len(lesson.source_claim_ids)}) exactly matches the real input module's claim ids -- no fabricated provenance")

    return lesson


async def _run() -> None:
    await check_zero_claims_module_never_calls_llm()
    try:
        await check_real_lesson_composition()
    finally:
        await close_driver()

    print("\nAll 4 checks passed. Part 1 pure (no LLM call). Part 2 against real Neo4j data")
    print("('online payment') and real LLM providers (compose_lesson_explanation + audit_synthesis).")


if __name__ == "__main__":
    asyncio.run(_run())
