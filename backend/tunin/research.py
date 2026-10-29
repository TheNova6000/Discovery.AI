"""Tuni'n's research gateway: a thin client of the Main Block door.

Tuni'n does not own a research engine. Until 2026-10-28 this module called the
evidence retrievers itself (a "direct retrieval" fallback) -- a second research
path that bypassed Discovery.AI's grounding, faithfulness checks, gap search
and the Dewey Archive. It now only talks to `backend.main_block`, in-process by
default or over HTTP when `MAINBLOCK_URL` is set (the same contract either way).

Per syllabus topic it asks the main block one grounded question (archive first,
research on a miss) and turns the verified citations into learner-facing
source references. Nothing here upgrades text into evidence: an ungrounded
answer contributes no sources, only its listed gaps as notes.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable, Optional

import httpx

from backend.main_block.interface import AskRequest, AskResult
from backend.main_block.interface import ask as mainblock_ask

from .models import (
    CourseDesignBrief,
    ResearchBundle,
    ResearchMode,
    SourceReference,
    SyllabusTopic,
    TopicResearch,
    utcnow,
)

ProgressCallback = Callable[[str, float, str], Awaitable[None]]
Asker = Callable[[AskRequest], Awaitable[AskResult]]


async def _noop(stage: str, progress: float, message: str) -> None:
    return None


def _remote_asker(base_url: str) -> Asker:
    async def remote(request: AskRequest) -> AskResult:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(f"{base_url.rstrip('/')}/mainblock/ask", json=request.model_dump())
            response.raise_for_status()
            return AskResult.model_validate(response.json())

    return remote


def _topic_question(brief: CourseDesignBrief, topic: SyllabusTopic) -> str:
    focus = f" for someone who wants to {brief.goal}" if brief.goal else ""
    return f"What is {topic.title} in {brief.topic}, how does it work, and what are its key ideas{focus}?"


class ResearchGateway:
    def __init__(self, *, asker: Optional[Asker] = None, max_topics: int = 8) -> None:
        base_url = os.environ.get("MAINBLOCK_URL")
        self._ask = asker or (_remote_asker(base_url) if base_url else mainblock_ask)
        self._max_topics = max_topics

    async def run(self, brief: CourseDesignBrief, progress: ProgressCallback = _noop) -> ResearchBundle:
        bundle = ResearchBundle(mode=ResearchMode.DISCOVERY_AI, status="failed", started_at=utcnow(),
                                discovery_ai_available=True)
        topics = brief.syllabus_topics[: self._max_topics]
        if len(brief.syllabus_topics) > len(topics):
            bundle.limitations.append(
                f"{len(brief.syllabus_topics) - len(topics)} syllabus topic(s) beyond the first {self._max_topics} were not researched"
            )
        if not topics:
            bundle.error = "the brief has no syllabus topics to research"
            bundle.completed_at = utcnow()
            return bundle

        for index, topic in enumerate(topics):
            await progress("main_block", index / len(topics), f"Researching {topic.title!r} through the main block")
            bundle.topics.append(await self._research_topic(brief, topic))
        await progress("main_block", 1.0, "Main block research finished")

        bundle.sources = [s for t in bundle.topics for s in t.sources]
        grounded = [t for t in bundle.topics if t.status == "complete"]
        failed = [t for t in bundle.topics if t.status == "error"]
        if len(grounded) == len(bundle.topics):
            bundle.status = "complete"
        elif grounded or any(t.status == "partial" for t in bundle.topics):
            bundle.status = "partial"
            bundle.limitations.append(
                f"{len(bundle.topics) - len(grounded)} of {len(bundle.topics)} topic(s) are not fully grounded in sources"
            )
        if failed:
            bundle.limitations.append(f"{len(failed)} topic(s) could not be researched (main block error)")
        bundle.completed_at = utcnow()
        return bundle

    async def _research_topic(self, brief: CourseDesignBrief, topic: SyllabusTopic) -> TopicResearch:
        question = _topic_question(brief, topic)
        try:
            result = await self._ask(AskRequest(question=question, topic=brief.topic))
        except Exception as exc:  # noqa: BLE001 - one topic failing must not fail the whole bundle
            return TopicResearch(topic_id=topic.id, topic_title=topic.title, queries=[question], status="error",
                                 notes=[f"main block error: {str(exc)[:200]}"])
        answer = result.answer
        sources = [
            SourceReference(
                title=c.source_title, url=c.source_url, snippet=c.evidence, source_type=c.source_type,
                provider="main_block", retrieved_at=c.retrieved_at or utcnow(), relevance=c.confidence,
            )
            for c in answer.citations
        ]
        notes = []
        if answer.note:
            notes.append(answer.note)
        notes += [f"not covered by the evidence: {gap}" for gap in answer.evidence_gaps]
        notes += [f"not traced to a source: {s}" for s in answer.unsupported_statements]
        if answer.grounded and sources:
            status = "complete" if not answer.unsupported_statements else "partial"
        else:
            status = "partial" if sources else "empty"
        return TopicResearch(topic_id=topic.id, topic_title=topic.title, sources=sources, queries=[question],
                             status=status, notes=notes)
