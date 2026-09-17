from __future__ import annotations

from backend.curriculum import Module
from backend.lessons.models import Lesson, LessonSentence
from backend.questions import audit_synthesis, compose_lesson_explanation

# Phase 10 (docs/Phases.md, docs/Rules.md rules 2/16/19): the one real I/O
# shell that turns a real, already-compiled Module (Phase 9.1 -- one already-
# complete concept and its real Claim objects) into a Lesson. This is the
# ONLY function in this whole slice that calls an LLM, and it does so
# entirely through backend.questions (rule 2's own boundary) -- never a raw
# SDK/requests call embedded here.
#
# Two calls, never one, mirroring audit_synthesis's own original design
# principle (docs/Memory.md's content-provenance pass): the thing that
# COMPOSES a lesson and the thing that AUDITS it for traceability are
# deliberately separate calls, not one call self-certifying its own output --
# a generator declaring its own text "fully sourced" is exactly the weaker,
# already-rejected self-report pattern this project chose not to repeat.


async def compile_lesson(module: Module) -> Lesson:
    if not module.claims:
        return Lesson(
            entity_id=module.entity_id,
            entity_name=module.entity_name,
            status="insufficient_claims",
        )

    claim_texts = [c.normalized_form for c in module.claims]
    draft = await compose_lesson_explanation(module.entity_name, claim_texts)
    audit = await audit_synthesis(draft.explanation, known=claim_texts)

    sentences = [LessonSentence(text=c.text, origin=c.origin) for c in audit.claims]
    fully_traceable = all(s.origin == "investigated" for s in sentences) if sentences else False

    return Lesson(
        entity_id=module.entity_id,
        entity_name=module.entity_name,
        status="composed",
        explanation=draft.explanation,
        examples=draft.examples,
        sentences=sentences,
        fully_traceable=fully_traceable,
        source_claim_ids=[c.claim_id for c in module.claims],
    )
