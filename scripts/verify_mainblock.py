"""Verifies the Main Block door (backend/main_block) and its first client
(backend/tunin/research.py) — offline: fake agent, fake graph, fake evidence,
temp job DB. No network, no quota.

  1. idempotency: same owner + request -> same job; different request -> new job
  2. a job runs queued -> investigating -> compiling -> completed; the result
     carries the grounded answer, verified citations and per-child findings
  3. a failing investigation -> FAILED with the error recorded; starting the
     same request again creates a fresh attempt
  4. ownership: another owner's job is reported as not found
  5. restart: RUNNING jobs become INTERRUPTED; the same request then re-runs
  6. ask: grounded -> answer + citations; ungrounded -> answer None, gaps kept
     (a memory draft is never returned as the answer)
  7. Tuni'n's gateway maps citations to sources, and an ungrounded topic
     contributes no sources, only notes
  8. HTTP: POST /mainblock/research -> 202 + job; GET unknown id -> 404
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.main_block.service as svc  # noqa: E402
from backend.main_block.reasoning_engine.agents.grounding import Grounding  # noqa: E402
from backend.main_block.reasoning_engine.agents.models import AgentStatus, GroundResult  # noqa: E402
from backend.main_block.reasoning_engine.evidence.models import Claim, RetrievedResource  # noqa: E402
from backend.main_block.interface import (  # noqa: E402
    AskRequest,
    AskResult,
    GroundedAnswer,
    JobNotFound,
    JobStatus,
    ResearchJobRequest,
)
from backend.main_block.models import Citation  # noqa: E402
from backend.main_block.store import JobStore  # noqa: E402
from backend.main_block.reasoning_engine.domain import Answer  # noqa: E402


def _claim(text: str) -> Claim:
    return Claim(question_id="q", evidence=text, reasoning="r", confidence=0.9,
                 source=RetrievedResource(title="Wiki", url="https://ex.org/w", source_type="web", content_kind="full_text"))


class FakeAgent:
    fail = False

    def __init__(self, question, **_kw):
        self.question = question

    async def run(self) -> GroundResult:
        if FakeAgent.fail:
            raise RuntimeError("all providers down")
        child_claim = _claim("A BST keeps smaller keys on the left.")
        child = GroundResult(status=AgentStatus.COMPLETE, question="What is a BST?", answer="A BST orders keys.",
                             claims=[child_claim],
                             grounding=Grounding(answer=Answer(text="A BST orders keys.", claim_ids=[child_claim.id], grounded=True),
                                                 support_ratio=1.0))
        return GroundResult(status=AgentStatus.COMPLETE, question=self.question.text, answer="BSTs order keys [1].",
                            child_results=[child],
                            grounding=Grounding(answer=Answer(text="BSTs order keys [1].", claim_ids=[child_claim.id], grounded=True),
                                                support_ratio=1.0))


async def fake_entity(name, **_kw):
    class E:
        id = "ent-1"
    return E()


async def fake_materialize(entity_id):
    return None


async def main() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    svc.GroundAgent = FakeAgent
    svc.find_or_create_entity = fake_entity
    svc.materialize_abstraction = fake_materialize

    with tempfile.TemporaryDirectory() as tmp:
        store = JobStore(pathlib.Path(tmp) / "jobs.sqlite3")
        req = ResearchJobRequest(topic="Binary search tree")

        j1 = await svc.start_research(req, "alice", store=store, run_inline=True)
        j1b = await svc.start_research(ResearchJobRequest(topic="  binary SEARCH tree "), "alice", store=store, run_inline=True)
        j2 = await svc.start_research(ResearchJobRequest(topic="Heap"), "alice", store=store, run_inline=True)
        check(j1.job_id == j1b.job_id and j2.job_id != j1.job_id, "#1 same request -> same job; different -> new job")

        done = await svc.get_job(j1.job_id, "alice", store=store)
        stages = [e.stage for e in done.events]
        r = done.result
        check(done.status == JobStatus.COMPLETED and stages == ["queued", "investigating", "compiling", "completed"]
              and r is not None and r.answer.grounded and len(r.answer.citations) == 1
              and r.answer.citations[0].source_url == "https://ex.org/w" and r.findings
              and r.findings[0].question == "What is a BST?" and r.findings[0].grounded
              and any("no persisted decomposition" in lim for lim in r.limitations),
              f"#2 lifecycle {stages}; grounded answer, citation, finding, honest limitation")

        FakeAgent.fail = True
        f1 = await svc.start_research(ResearchJobRequest(topic="Trie"), "alice", store=store, run_inline=True)
        f1 = await svc.get_job(f1.job_id, "alice", store=store)
        FakeAgent.fail = False
        f2 = await svc.start_research(ResearchJobRequest(topic="Trie"), "alice", store=store, run_inline=True)
        check(f1.status == JobStatus.FAILED and "all providers down" in (f1.error or "") and f2.job_id != f1.job_id
              and (await svc.get_job(f2.job_id, "alice", store=store)).status == JobStatus.COMPLETED,
              "#3 failure recorded; same request retried as a new job")

        try:
            await svc.get_job(j1.job_id, "mallory", store=store)
            check(False, "#4 another owner's job must not be readable")
        except JobNotFound:
            check(True, "#4 another owner's job reported as not found")

        stuck = await svc.start_research(ResearchJobRequest(topic="Skip list"), "alice", store=store, run_inline=True)
        stuck = await svc.get_job(stuck.job_id, "alice", store=store)
        stuck.status = JobStatus.RUNNING
        await store.save(stuck)
        n = await store.mark_interrupted()
        again = await svc.start_research(ResearchJobRequest(topic="Skip list"), "alice", store=store, run_inline=True)
        check(n == 1 and (await svc.get_job(stuck.job_id, "alice", store=store)).status == JobStatus.INTERRUPTED
              and again.job_id != stuck.job_id, "#5 running job -> INTERRUPTED on restart; same request re-runs")

    # 6: ask
    class Gathered:
        def __init__(self, claims):
            self.claims, self.evidence_source = claims, "archive"

    ask_claim = _claim("Search takes O(h).")

    async def fake_gather(question, **_kw):
        return Gathered([ask_claim])

    async def grounded_answer(question, draft, claims, requery=None):
        return Grounding(answer=Answer(text="Search takes O(h) [1].", claim_ids=[ask_claim.id], grounded=True), support_ratio=1.0)

    async def ungrounded_answer(question, draft, claims, requery=None):
        return Grounding(answer=Answer(text=draft or "No answer could be produced.", grounded=False),
                         evidence_gaps=["cost of deletion"], note="the gathered evidence did not answer the question")

    svc.gather_evidence_with_outcomes = fake_gather
    svc.ground_answer = grounded_answer
    a = await svc.ask(AskRequest(question="How fast is search?", topic="Binary search tree"))
    svc.ground_answer = ungrounded_answer
    b = await svc.ask(AskRequest(question="How fast is deletion?", topic="Binary search tree"))
    check(a.answer.grounded and a.answer.answer and a.answer.citations and a.evidence_source == "archive"
          and not b.answer.grounded and b.answer.answer is None and b.answer.evidence_gaps == ["cost of deletion"],
          "#6 ask: grounded -> answer + citations; ungrounded -> no answer text, gaps kept")

    # 7: Tuni'n gateway
    from backend.tunin.models import CourseDesignBrief, SyllabusTopic
    from backend.tunin.research import ResearchGateway

    async def fake_asker(request: AskRequest) -> AskResult:
        if "Deletion" in request.question:
            return AskResult(answer=GroundedAnswer(question=request.question, answer=None, grounded=False,
                                                   evidence_gaps=["deletion cases"]), evidence_source="research")
        return AskResult(answer=GroundedAnswer(question=request.question, answer="x", grounded=True, support_ratio=1.0,
                                               citations=[Citation(claim_id="c", evidence="e", source_title="Wiki",
                                                                   source_url="https://ex.org/w", source_type="web", confidence=0.9)]),
                         evidence_source="archive")

    brief = CourseDesignBrief(topic="Binary search tree", syllabus_topics=[SyllabusTopic(title="Search"), SyllabusTopic(title="Deletion")])
    bundle = await ResearchGateway(asker=fake_asker).run(brief)
    by_title = {t.topic_title: t for t in bundle.topics}
    check(by_title["Search"].status == "complete" and len(by_title["Search"].sources) == 1
          and by_title["Deletion"].status == "empty" and not by_title["Deletion"].sources
          and any("deletion cases" in n for n in by_title["Deletion"].notes) and bundle.status == "partial",
          f"#7 gateway: grounded topic -> sources; ungrounded -> notes only; bundle {bundle.status}")

    # 8: HTTP routes
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MAINBLOCK_DB_PATH"] = str(pathlib.Path(tmp) / "api.sqlite3")
        from fastapi.testclient import TestClient

        from backend.api.app import app

        with TestClient(app) as client:
            resp = client.post("/mainblock/research", json={"topic": "Graph coloring"})
            job = resp.json()
            missing = client.get("/mainblock/research/rj_doesnotexist")
            for _ in range(50):  # let the background job finish before the app shuts down
                if client.get(f"/mainblock/research/{job['job_id']}").json().get("status") in ("completed", "failed"):
                    break
                import time
                time.sleep(0.1)
            check(resp.status_code == 202 and job.get("job_id", "").startswith("rj_") and missing.status_code == 404,
                  f"#8 POST -> {resp.status_code} {job.get('status')}; unknown id -> {missing.status_code}")
        os.environ.pop("MAINBLOCK_DB_PATH", None)

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
