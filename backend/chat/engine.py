"""The chat model's turn logic. It talks; the main block researches.

    discovery  --(brief complete)-->  confirming  --(learner says go)-->  researching  --(job done)-->  ready

- In any phase, a learner QUESTION ("how does X work?") is answered through
  `mainblock.ask` -- grounded in sources or honestly reported as not grounded.
  The chat model never answers subject matter from its own memory.
- Everything else in `discovery` updates the course-design brief
  (`backend.tunin.discovery`, which uses the chat model's own LLM chain).
- `confirming` shows the brief and starts a main-block research job only on
  an explicit go-ahead (the learner stays in control; nothing is researched
  or generated silently).
- `researching` reports the job's real stage; `ready` presents the grounded
  findings and their gaps. Turning findings into a course is the next part
  of the pipeline (owner to specify), so it is not done here.

The main block is reached only through `MainBlockPort` (default: the
in-process door), so tests and a remote deployment can swap it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from backend.main_block import interface as mainblock
from backend.main_block.interface import AskRequest, AskResult, GroundedAnswer, JobStatus, ResearchJob, ResearchJobRequest
from backend.tunin import discovery

from .models import ChatMessage, ChatReply, ChatSession


@dataclass
class MainBlockPort:
    ask: Callable[[AskRequest], Awaitable[AskResult]]
    start_research: Callable[[ResearchJobRequest, str], Awaitable[ResearchJob]]
    get_job: Callable[[str, str], Awaitable[ResearchJob]]


DEFAULT_PORT = MainBlockPort(ask=mainblock.ask, start_research=mainblock.start_research, get_job=mainblock.get_job)

_QUESTION_START = re.compile(
    r"^\s*(what|how|why|when|where|which|who|whom|whose|is|are|does|do|can|could|would|should|explain|tell me|describe)\b",
    re.I,
)
_CONFIRM = re.compile(r"^\s*(yes|yeah|yep|sure|ok|okay|go( ahead)?|start|approve[d]?|looks good|sounds good|do it|let'?s go)\b", re.I)
_ANSWERS_OUR_QUESTION = re.compile(r"^\s*(i|my|we|about|around|maybe|probably|\d)", re.I)


def is_question(text: str, session: ChatSession) -> bool:
    """A learner question to research, as opposed to an answer to OUR question.
    Before a topic exists everything is discovery ("what should I learn?" is
    about the course, not subject matter)."""
    if not session.brief.topic:
        return False
    stripped = text.strip()
    if _ANSWERS_OUR_QUESTION.match(stripped):
        return False
    return stripped.endswith("?") or bool(_QUESTION_START.match(stripped))


def _cite(answer: GroundedAnswer) -> str:
    lines = []
    seen: set[str] = set()
    for c in answer.citations:
        if c.source_url in seen:
            continue
        seen.add(c.source_url)
        lines.append(f"[{len(seen)}] {c.source_title} — {c.source_url}")
    return "\n".join(lines)


def render_answer(answer: GroundedAnswer) -> str:
    if answer.grounded and answer.answer:
        text = answer.answer
        sources = _cite(answer)
        if sources:
            text += f"\n\nSources:\n{sources}"
        if answer.unsupported_statements:
            text += "\n\nNot confirmed by these sources: " + "; ".join(answer.unsupported_statements)
        if answer.evidence_gaps:
            text += "\n\nThe sources didn't cover: " + "; ".join(answer.evidence_gaps)
        return text
    text = "I couldn't find sources that answer that, so I won't guess."
    if answer.evidence_gaps:
        text += " Not covered yet: " + "; ".join(answer.evidence_gaps) + "."
    return text


def _brief_summary(session: ChatSession) -> str:
    b = session.brief
    topics = ", ".join(t.title for t in b.syllabus_topics) or "(none yet)"
    lines = [
        f"Topic: {b.topic}",
        f"Goal: {b.goal or '(not stated)'}",
        f"Depth: {b.depth}",
        f"Syllabus topics: {topics}",
    ]
    if b.weekly_hours is not None:
        lines.append(f"Time: {b.weekly_hours:g} h/week" + (f" for {b.target_weeks} weeks" if b.target_weeks else ""))
    if b.assumptions:
        lines.append("Assumptions I made: " + "; ".join(b.assumptions))
    return "\n".join(lines)


def research_request(session: ChatSession) -> ResearchJobRequest:
    b = session.brief
    # Only topics the learner actually gave steer the research. Placeholders
    # discovery inferred ("Foundations of X", "Methods and tools used in X") are
    # assumptions, not syllabus -- in the live chat they made the research spend a
    # sub-question on "a 6-week lesson plan" (loop E24).
    topics = [t.title for t in b.syllabus_topics if t.source == "learner"]
    question = f"What is {b.topic}, how does it work, and what are its main parts"
    if topics:
        question += " — in particular " + ", ".join(topics[:6])
    question += "?"
    return ResearchJobRequest(topic=b.topic, question=question[:1000], objective=b.goal or None, learner_level=b.depth)


def _findings_summary(job: ResearchJob) -> str:
    result = job.result
    if result is None:
        return "Research finished but produced no result."
    parts = ["Here is what the research found (grounded in sources unless marked otherwise):\n", render_answer(result.answer)]
    for finding in result.findings:
        marker = "" if finding.grounded else " (not grounded)"
        parts.append(f"\n• {finding.question}{marker}")
    if result.limitations:
        parts.append("\nLimitations: " + "; ".join(result.limitations))
    parts.append("\nNext: turning this into your course plan (syllabus, mini-projects, capstone) for your approval.")
    return "\n".join(parts)


async def start_session(owner_id: str) -> ChatSession:
    session = ChatSession(owner_id=owner_id)
    session.messages.append(ChatMessage(role="tunin", text=discovery.greeting(), kind="discovery"))
    return session


async def chat_turn(session: ChatSession, text: str, *, port: MainBlockPort = DEFAULT_PORT,
                    use_llm: bool | None = None) -> ChatReply:
    session = session.model_copy(deep=True)
    session.messages.append(ChatMessage(role="learner", text=text))

    if session.phase in ("discovery", "ready", "researching", "confirming") and is_question(text, session) \
            and not (session.phase == "confirming" and _CONFIRM.match(text)):
        result = await port.ask(AskRequest(question=text, topic=session.brief.topic or None))
        reply_text = render_answer(result.answer)
        if session.phase == "discovery":
            pending = next((m.text for m in reversed(session.messages) if m.role == "tunin" and m.kind == "discovery"), "")
            if pending:
                reply_text += f"\n\nBack to your course: {pending.splitlines()[-1]}"
        reply = ChatMessage(role="tunin", text=reply_text, kind="answer", grounded=result.answer.grounded)
    elif session.phase == "discovery":
        turn = await discovery.respond(session.brief, text, use_llm=use_llm)
        session.brief = turn.brief
        if turn.done:
            session.phase = "confirming"
            reply = ChatMessage(role="tunin", kind="summary", text=(
                "Here is the course brief I put together:\n\n" + _brief_summary(session)
                + "\n\nShall I start researching it? Say yes to begin, or tell me what to change."
            ))
        else:
            reply = ChatMessage(role="tunin", text=turn.text, kind="discovery")
    elif session.phase == "confirming":
        if _CONFIRM.match(text):
            job = await port.start_research(research_request(session), session.owner_id)
            session.research_job_id = job.job_id
            session.phase = "researching"
            reply = ChatMessage(role="tunin", kind="status", text=(
                "Research started. I'll investigate the topic, read sources, and check every claim against them. "
                "This can take several minutes; ask me anything meanwhile, or say 'status'."
            ))
        else:
            turn = await discovery.respond(session.brief, text, use_llm=use_llm)
            session.brief = turn.brief
            reply = ChatMessage(role="tunin", kind="summary", text=(
                "Updated:\n\n" + _brief_summary(session) + "\n\nStart researching now? (yes / tell me what to change)"
            ))
    elif session.phase == "researching":
        job = await port.get_job(session.research_job_id or "", session.owner_id)
        if job.status == JobStatus.COMPLETED:
            session.phase = "ready"
            reply = ChatMessage(role="tunin", kind="summary", text=_findings_summary(job),
                                grounded=job.result.answer.grounded if job.result else None)
        elif job.status in (JobStatus.FAILED, JobStatus.INTERRUPTED):
            session.phase = "confirming"
            reply = ChatMessage(role="tunin", kind="status", text=(
                f"The research job stopped ({job.status.value}: {job.error or 'no detail'}). Say yes to try again."
            ))
        else:
            reply = ChatMessage(role="tunin", kind="status", text=f"Still researching — current stage: {job.stage}.")
    else:  # ready
        reply = ChatMessage(role="tunin", kind="info", text=(
            "The research is done. Building the course from it is the next step; ask me anything about the topic meanwhile."
        ))

    session.messages.append(reply)
    return ChatReply(session=session, reply=reply)
