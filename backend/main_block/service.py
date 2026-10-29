"""The Main Block service: the one door into Discovery.AI (reasoning) + Dewey
(research). Clients (chat model, Tuni'n portal) use ONLY these functions or the
matching HTTP routes (`backend/main_block/api.py`); nothing outside this package
imports agents, evidence, Dewey, graph or retrievers
(`scripts/verify_mainblock_boundary.py` enforces it).

Operations
- `start_research(request, owner_id)` -> ResearchJob   (idempotent per owner+request)
- `get_job(job_id, owner_id)`         -> ResearchJob    (status, stage, events, result)
- `ask(request)`                      -> AskResult      (grounded answer, archive first)

Research jobs run in the background, one (MAINBLOCK_MAX_CONCURRENT_JOBS) at a
time by default to protect free-tier quota, and are persisted so a restart
marks them INTERRUPTED rather than losing or faking them.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

from .reasoning_engine.interface import (
    EXPLORATORY_POLICY,
    Claim,
    GroundAgent,
    Grounding,
    GroundResult,
    Question,
    QuestionLevel,
    fetch_and_compile_research_response,
    find_or_create_entity,
    gather_evidence_with_outcomes,
    ground_answer,
    materialize_abstraction,
)

from .models import (
    AskRequest,
    AskResult,
    Citation,
    GroundedAnswer,
    JobEvent,
    JobStatus,
    ResearchJob,
    ResearchJobRequest,
    ResearchResult,
)
from .store import JobStore


class JobNotFound(Exception):
    pass


def _max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get("MAINBLOCK_MAX_CONCURRENT_JOBS", "1")))
    except ValueError:
        return 1


_slots: dict[int, asyncio.Semaphore] = {}
_tasks: set[asyncio.Task] = set()


def _slot() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _slots:
        _slots[loop_id] = asyncio.Semaphore(_max_concurrent())
    return _slots[loop_id]


def _citations(grounding: Optional[Grounding], claims: list[Claim]) -> list[Citation]:
    if grounding is None:
        return []
    by_id = {c.id: c for c in claims}
    out = []
    for claim_id in grounding.answer.claim_ids:
        claim = by_id.get(claim_id)
        if claim is None:
            continue
        out.append(Citation(
            claim_id=claim.id, evidence=claim.evidence, source_title=claim.source.title,
            source_url=claim.source.url, source_type=claim.source.source_type,
            content_kind=claim.source.content_kind, retrieved_at=claim.source.retrieved_at,
            confidence=claim.confidence,
        ))
    return out


def _all_claims(result: GroundResult) -> list[Claim]:
    claims = list(result.claims)
    for child in result.child_results:
        claims.extend(_all_claims(child))
    return claims


def _grounded_answer(question: str, answer: Optional[str], grounding: Optional[Grounding], claims: list[Claim]) -> GroundedAnswer:
    if grounding is None:
        return GroundedAnswer(question=question, answer=answer, grounded=False,
                              note="evidence gathering was off; answer is model memory only")
    return GroundedAnswer(
        question=question,
        answer=answer,
        grounded=grounding.answer.grounded,
        support_ratio=grounding.support_ratio,
        citations=_citations(grounding, claims),
        unsupported_statements=grounding.unsupported_statements,
        evidence_gaps=grounding.evidence_gaps,
        note=grounding.note,
    )


async def _record(store: JobStore, job: ResearchJob, stage: str, message: str, status: Optional[JobStatus] = None) -> None:
    job.stage = stage
    if status is not None:
        job.status = status
    job.events.append(JobEvent(stage=stage, message=message))
    await store.save(job)


async def _run_job(store: JobStore, job: ResearchJob) -> None:
    request = job.request
    async with _slot():
        try:
            await _record(store, job, "investigating", "Discovery.AI is decomposing and researching the question",
                          JobStatus.RUNNING)
            await find_or_create_entity(request.topic, scope_hint=request.scope_hint)
            question = Question(
                text=request.effective_question(),
                rationale=f"Main Block research job {job.job_id}" + (f"; objective: {request.objective}" if request.objective else ""),
                dimension_id="none",
                level=QuestionLevel.MASTER,
                entity_name=request.topic,
                entity_scope_hint=request.scope_hint,
                abstraction_name=request.topic,
            )
            agent = GroundAgent(question, gather_evidence=True, persist_to_graph=True, policy=EXPLORATORY_POLICY)
            result = await agent.run()

            await _record(store, job, "compiling", "Compiling the research response from the knowledge graph")
            claims = _all_claims(result)
            findings = [
                _grounded_answer(child.question or "", child.answer, child.grounding, claims)
                for child in result.child_results
            ]
            limitations: list[str] = []
            research_response = None
            entity = await find_or_create_entity(request.topic, scope_hint=request.scope_hint)
            abstraction = await materialize_abstraction(entity.id)
            if abstraction is None:
                limitations.append("the topic has no persisted decomposition yet, so no ResearchResponse was compiled")
            else:
                response = await fetch_and_compile_research_response(abstraction.id, EXPLORATORY_POLICY)
                research_response = response.model_dump(mode="json")
            job.result = ResearchResult(
                answer=_grounded_answer(question.text, result.answer, result.grounding, claims),
                findings=findings,
                research_response=research_response,
                limitations=limitations,
            )
            await _record(store, job, "completed",
                          "grounded" if job.result.answer.grounded else "completed, but the answer is NOT grounded",
                          JobStatus.COMPLETED)
        except Exception as exc:  # noqa: BLE001 - a job failure is recorded on the job, never raised into the event loop
            job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            await _record(store, job, "failed", job.error, JobStatus.FAILED)


async def start_research(request: ResearchJobRequest, owner_id: str, *, store: Optional[JobStore] = None,
                         run_inline: bool = False) -> ResearchJob:
    """Idempotent: the same owner + request returns its existing queued, running
    or completed job. A failed/interrupted one is retried as a new job."""
    store = store or JobStore()
    fingerprint = request.fingerprint()
    existing = await store.latest_for(owner_id, fingerprint)
    if existing is not None and existing.status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.COMPLETED):
        return existing
    job = ResearchJob(job_id=f"rj_{uuid.uuid4().hex[:16]}", owner_id=owner_id, fingerprint=fingerprint, request=request)
    job.events.append(JobEvent(stage="queued", message="research job accepted"))
    await store.save(job)
    if run_inline:
        await _run_job(store, job)
    else:
        task = asyncio.create_task(_run_job(store, job))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return job


async def get_job(job_id: str, owner_id: str, *, store: Optional[JobStore] = None) -> ResearchJob:
    job = await (store or JobStore()).get(job_id)
    if job is None or job.owner_id != owner_id:
        # Another owner's job is reported exactly like a missing one.
        raise JobNotFound(job_id)
    return job


async def ask(request: AskRequest) -> AskResult:
    """A grounded answer to one question, for the chat's "tell me more" turns:
    Dewey's archive first, research on a miss, listed gaps re-searched once.
    No memory draft is ever returned as the answer."""
    topic = request.topic or "general"

    def as_question(text: str) -> Question:
        return Question(text=text, rationale="Main Block ask", dimension_id="none", level=QuestionLevel.GROUND,
                        entity_name=topic, abstraction_name=topic)

    question = as_question(request.question if not request.topic else f"{request.question} ({request.topic})")
    gathered = await gather_evidence_with_outcomes(question)

    async def requery(gap: str) -> list[Claim]:
        # The question itself is re-searched as a gap when nothing usable came
        # back; it already names the topic ("... (photosynthesis) (photosynthesis)").
        text = gap if topic.lower() in gap.lower() else f"{gap} ({topic})"
        return (await gather_evidence_with_outcomes(as_question(text))).claims

    grounding = await ground_answer(question, None, gathered.claims, requery=requery)
    claims = gathered.claims + grounding.gap_claims
    text = grounding.answer.text if grounding.answer.grounded else None
    return AskResult(
        answer=_grounded_answer(request.question, text, grounding, claims),
        evidence_source=gathered.evidence_source,
    )


async def recover_interrupted(store: Optional[JobStore] = None) -> int:
    return await (store or JobStore()).mark_interrupted()
