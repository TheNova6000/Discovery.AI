"""Verifies the Tuni'n chat model (backend/chat) and its communication with the
main block — offline: fake MainBlockPort, deterministic discovery (no LLM),
temp session DB.

  1. a session starts with the greeting, in the discovery phase
  2. answering our questions updates the brief (no main-block call)
  3. a learner QUESTION mid-discovery goes to mainblock.ask; a grounded answer
     is shown with its sources, and the pending discovery question is repeated
  4. an ungrounded answer is reported as such -- never a guessed answer
  5. before any topic exists, nothing is treated as a research question;
     replies like "I know Python" are answers, not questions
  6. discovery completes -> confirming shows the brief and waits
  7. a non-confirming reply edits the brief and stays in confirming; "yes"
     starts ONE research job built from the brief, phase -> researching
  8. researching reports the job's real stage; completed -> ready with the
     grounded findings; a failed job returns to confirming
  9. HTTP: create session 201; unknown session 404
 10. inferred placeholder topics never steer the research question (E24)
 11. background / time replies during the syllabus question are not syllabus topics (E21)
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.chat.engine import MainBlockPort, chat_turn, is_question, start_session  # noqa: E402
from backend.main_block.interface import AskResult, GroundedAnswer, JobStatus, ResearchJob, ResearchResult  # noqa: E402
from backend.main_block.models import Citation, JobEvent  # noqa: E402

asked: list[str] = []
started: list = []
JOB_STATE = {"status": JobStatus.RUNNING, "stage": "investigating"}


async def fake_ask(request):
    asked.append(request.question)
    if "deletion" in request.question.lower():
        return AskResult(answer=GroundedAnswer(question=request.question, answer=None, grounded=False,
                                               evidence_gaps=["deletion cases"]), evidence_source="research")
    return AskResult(answer=GroundedAnswer(
        question=request.question, answer="Insertion walks from the root to an empty child and attaches the node.",
        grounded=True, support_ratio=1.0,
        citations=[Citation(claim_id="c1", evidence="e", source_title="Binary search tree",
                            source_url="https://en.wikipedia.org/wiki/Binary_search_tree", source_type="web", confidence=0.9)]),
        evidence_source="archive")


def _job(request, owner):
    job = ResearchJob(job_id="rj_test", owner_id=owner, fingerprint="f", request=request,
                      status=JOB_STATE["status"], stage=JOB_STATE["stage"])
    if job.status == JobStatus.COMPLETED:
        job.result = ResearchResult(answer=GroundedAnswer(question="q", answer="A BST orders keys.", grounded=True,
                                                          citations=[Citation(claim_id="c", evidence="e", source_title="Wiki",
                                                                              source_url="https://ex.org/w", source_type="web", confidence=0.9)]),
                                    findings=[GroundedAnswer(question="What is a BST?", answer="x", grounded=True)])
    if job.status == JobStatus.FAILED:
        job.error = "all providers down"
    job.events.append(JobEvent(stage=job.stage, message="m"))
    return job


async def fake_start(request, owner):
    started.append(request)
    return _job(request, owner)


async def fake_get(job_id, owner):
    return _job(started[-1], owner)


PORT = MainBlockPort(ask=fake_ask, start_research=fake_start, get_job=fake_get)


async def say(session, text):
    reply = await chat_turn(session, text, port=PORT, use_llm=False)
    return reply.session, reply.reply


async def main() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    s = await start_session("alice")
    check(s.phase == "discovery" and s.messages and s.messages[0].role == "tunin", "#1 greeting, discovery phase")

    check(not is_question("What should I learn?", s), "#5 before a topic exists, nothing is a research question")
    s, r = await say(s, "I want to learn binary search trees so I can pass my data structures exam")
    check(s.brief.topic.lower() == "binary search trees" and "exam" in (s.brief.goal or "") and not asked
          and r.kind == "discovery", f"#2 brief: topic={s.brief.topic!r} goal={s.brief.goal!r}; no main-block call")
    check(not is_question("I know Python and basic arrays", s) and is_question("How does insertion work?", s),
          "#5 'I know Python...' is an answer; 'How does insertion work?' is a question")

    s, r = await say(s, "How does insertion work in a BST?")
    check(asked and r.kind == "answer" and r.grounded and "Sources:" in r.text and "wikipedia.org" in r.text
          and "Back to your course" in r.text, "#3 question -> mainblock.ask; grounded answer with sources; discovery resumes")

    s, r = await say(s, "How does deletion work?")
    check(r.grounded is False and "won't guess" in r.text and "deletion cases" in r.text and "Insertion" not in r.text,
          "#4 ungrounded -> honest 'won't guess' + gaps, no invented answer")

    for _ in range(14):
        if s.phase != "discovery":
            break
        s, r = await say(s, "not sure, you decide")
    check(s.phase == "confirming" and "Shall I start researching" in r.text and not started,
          f"#6 discovery complete -> confirming, waiting (phase={s.phase})")

    s, r = await say(s, "make it 5 hours a week")
    check(s.phase == "confirming" and not started, "#7 a non-confirming reply edits the brief, stays confirming")
    s, r = await say(s, "yes, go ahead")
    check(s.phase == "researching" and len(started) == 1 and started[0].topic == s.brief.topic
          and s.research_job_id == "rj_test", "#7 'yes' starts one research job from the brief")
    inferred = [t.title for t in s.brief.syllabus_topics if t.source != "learner"]
    check(not any(t in (started[0].question or "") for t in inferred),
          f"#10 inferred placeholder topics never steer the research question ({len(inferred)} placeholder(s))")
    from backend.tunin import discovery as disc
    from backend.tunin.models import CourseDesignBrief
    b = CourseDesignBrief(topic="photosynthesis", asked=["syllabus"])
    t = await disc.respond(b, "I know basic biology and chemistry", use_llm=False)
    t2 = await disc.respond(t.brief.model_copy(update={"asked": ["syllabus", "syllabus"]}), "about 4 hours a week for 6 weeks", use_llm=False)
    learner_topics = [x.title for x in t2.brief.syllabus_topics if x.source == "learner"]
    check(t.brief.prior_knowledge == ["basic biology and chemistry"] and not learner_topics and t2.brief.weekly_hours == 4.0,
          f"#11 background / time replies are not read as syllabus (learner topics={learner_topics})")

    s, r = await say(s, "status")
    check(s.phase == "researching" and "investigating" in r.text, "#8 researching reports the real stage")
    JOB_STATE.update(status=JobStatus.COMPLETED, stage="completed")
    s, r = await say(s, "status")
    check(s.phase == "ready" and "A BST orders keys." in r.text and "Sources:" in r.text and "What is a BST?" in r.text,
          "#8 completed -> ready with grounded findings + sources")
    JOB_STATE.update(status=JobStatus.FAILED, stage="failed")
    s2 = s.model_copy(update={"phase": "researching"})
    s2, r = await say(s2, "status")
    check(s2.phase == "confirming" and "all providers down" in r.text, "#8 failed job -> back to confirming with the reason")

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TUNIN_CHAT_DB_PATH"] = str(pathlib.Path(tmp) / "chat.sqlite3")
        os.environ["MAINBLOCK_DB_PATH"] = str(pathlib.Path(tmp) / "mb.sqlite3")
        from fastapi.testclient import TestClient

        from backend.api.app import app

        with TestClient(app) as client:
            created = client.post("/tunin/chat/sessions")
            missing = client.get("/tunin/chat/sessions/cs_nope")
            check(created.status_code == 201 and created.json()["phase"] == "discovery" and missing.status_code == 404,
                  f"#9 HTTP create -> {created.status_code}; unknown -> {missing.status_code}")
        os.environ.pop("TUNIN_CHAT_DB_PATH", None)
        os.environ.pop("MAINBLOCK_DB_PATH", None)

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
