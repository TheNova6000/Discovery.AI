"""Verifies P1 retrieve-then-write (backend/main_block/reasoning_engine/agents/grounding.py,
backend/main_block/reasoning_engine/llm_steps/grounded_answer.py, the Dewey path in
backend/main_block/reasoning_engine/evidence/engine.py) — offline: fake LLM calls, fake providers, temp
archive. No network, no quota.

Grounding:
  1. no claims -> answer is the memory draft, explicitly grounded=False
  2. evidence answers -> grounded=True, cites only real claim ids, audit gives
     support ratio + the unsupported statements
  3. evidence doesn't answer (empty answer / no citations) -> grounded=False, gaps kept
  4. composer fails on every provider -> grounded=False with a note, never a crash
  5. audit fails -> still grounded, but support_ratio None (unknown, not 0)
  6. out-of-range citation numbers from the LLM are dropped, not trusted
 10. citations come from the AUDIT (VeriCite-style): the writer cites [1, 2] but
     the audit finds only claim 1 supporting -> claim_ids = [claim 1]
 11. the audit traces nothing -> grounded=False even though the writer cited
 12. the audit names no supporting items -> writer citations kept, flagged unverified
Evidence quality (iteration 01):
 13. a metadata-sourced claim is capped below "supported" (E1)
 14. same URL + near-identical evidence -> one claim (E3)
 15. Dewey's relevance gate drops off-topic passages; metadata ranks last (E8)
 16. claims below 0.5 alone never ground an answer (iteration 02, E10)
 17. a synthesizing node grounds on its descendants' claims too (iteration 02, E11)
 18-20. listed gaps are re-searched (bounded), recomposed, new claims returned (iteration 03, E12)
Dewey evidence path:
  7. gather_evidence goes through Dewey: providers get KEYWORD queries,
     passages are synthesised into claims, provider reports are surfaced
  8. the same question again -> evidence_source=archive, zero provider calls
  9. EVIDENCE_SOURCE=retrievers restores the direct legacy path
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
from dataclasses import dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.main_block.reasoning_engine.agents.grounding as grounding_mod  # noqa: E402
import backend.main_block.research_engine.providers as providers_mod  # noqa: E402
import backend.main_block.reasoning_engine.evidence.engine as engine_mod  # noqa: E402
import backend.main_block.reasoning_engine.llm_steps.grounded_answer as ga_mod  # noqa: E402
from backend.main_block.reasoning_engine.evidence.models import Claim, ClaimDraft, RetrievedResource  # noqa: E402
from backend.main_block.reasoning_engine.llm_steps import AtomicClaim, GroundedDraft, Question, QuestionLevel, SynthesisAudit  # noqa: E402

Q = Question(text="How does search work in a binary search tree?", rationale="t", dimension_id="none",
             level=QuestionLevel.GROUND, entity_name="Binary search tree", abstraction_name="Binary search tree")


def _claim(evidence: str, title: str) -> Claim:
    return Claim(question_id=Q.id, evidence=evidence, reasoning="r", confidence=0.8,
                 source=RetrievedResource(title=title, url=f"https://ex.org/{title}", source_type="web"))


@dataclass
class FakeProvider:
    name: str
    results: list[RetrievedResource]
    need_kinds: frozenset[str] = frozenset({"explanation"})
    key_env_vars: tuple[str, ...] = ()
    query_style: str = "keywords"
    queries: list[str] = field(default_factory=list)

    async def search(self, query: str, max_results: int) -> list[RetrievedResource]:
        self.queries.append(query)
        return self.results[:max_results]


async def main() -> int:
    failures = 0
    os.environ["EVIDENCE_FAITHFULNESS"] = "off"  # covered by verify_faithfulness.py

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    claims = [_claim("Search compares the key with each node and goes left if smaller, right if larger.", "bst"),
              _claim("Search takes O(h) time, O(log n) when the tree is balanced.", "bst-cost")]

    # 1
    g = await grounding_mod.ground_answer(Q, "memory answer", [])
    check(not g.answer.grounded and g.answer.text == "memory answer" and g.answer.claim_ids == [] and g.note,
          "#1 no claims -> draft kept, grounded=False, note says why")

    # 2
    async def compose_ok(q, ev, **_):
        return GroundedDraft(answer="Compare and go left or right [1]; costs O(h) [2]. It was invented in 1960.", cited=[1, 2])

    async def audit_ok(ans, known, **_):
        return SynthesisAudit(claims=[AtomicClaim(text="compare left/right", origin="investigated", supported_by=[1]),
                                      AtomicClaim(text="O(h)", origin="investigated", supported_by=[2]),
                                      AtomicClaim(text="invented in 1960", origin="uninvestigated")])

    grounding_mod.compose_grounded_answer, grounding_mod.audit_synthesis = compose_ok, audit_ok
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(g.answer.grounded and g.answer.claim_ids == [c.id for c in claims] and g.draft_answer == "memory answer"
          and g.support_ratio == 0.667 and g.unsupported_statements == ["invented in 1960"] and g.citations_verified,
          f"#2 grounded, cites real ids, support={g.support_ratio}, unsupported={g.unsupported_statements}")

    # 3
    async def compose_nothing(q, ev, **_):
        return GroundedDraft(answer="", cited=[], gaps=["how search works"])

    grounding_mod.compose_grounded_answer = compose_nothing
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(not g.answer.grounded and g.evidence_gaps == ["how search works"], f"#3 evidence irrelevant -> ungrounded, gaps={g.evidence_gaps}")

    # 4
    async def compose_fail(q, ev, **_):
        raise RuntimeError("all providers down")

    grounding_mod.compose_grounded_answer = compose_fail
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(not g.answer.grounded and "failed" in (g.note or ""), f"#4 composer failure -> ungrounded, note={g.note!r}")

    # 5
    async def audit_fail(ans, known, **_):
        raise RuntimeError("audit down")

    grounding_mod.compose_grounded_answer, grounding_mod.audit_synthesis = compose_ok, audit_fail
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(g.answer.grounded and g.support_ratio is None and "audit failed" in (g.note or ""),
          "#5 audit failure -> grounded but support unknown (None), not 0")

    # 10-12
    async def audit_only_first(ans, known, **_):
        return SynthesisAudit(claims=[AtomicClaim(text="compare left/right", origin="investigated", supported_by=[1, 9]),
                                      AtomicClaim(text="O(n) worst case", origin="uninvestigated")])

    grounding_mod.audit_synthesis = audit_only_first
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(g.answer.grounded and g.answer.claim_ids == [claims[0].id] and g.citations_verified
          and [st.supported for st in g.statements] == [True, False],
          f"#10 writer cited [1,2], audit verified only claim 1 -> claim_ids={len(g.answer.claim_ids)} verified")

    async def audit_nothing(ans, known, **_):
        return SynthesisAudit(claims=[AtomicClaim(text="a", origin="uninvestigated"), AtomicClaim(text="b", origin="uninvestigated")])

    grounding_mod.audit_synthesis = audit_nothing
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(not g.answer.grounded and g.support_ratio == 0.0 and "traced none" in (g.note or ""),
          f"#11 audit traces nothing -> grounded=False (note={g.note!r})")

    async def audit_no_numbers(ans, known, **_):
        return SynthesisAudit(claims=[AtomicClaim(text="a", origin="investigated")])

    grounding_mod.audit_synthesis = audit_no_numbers
    g = await grounding_mod.ground_answer(Q, "memory answer", claims)
    check(g.answer.grounded and not g.citations_verified and len(g.answer.claim_ids) == 2,
          "#12 audit gives no item numbers -> writer citations kept, citations_verified=False")
    grounding_mod.audit_synthesis = audit_ok

    # 6
    async def fake_structured_call(**_):
        return GroundedDraft(answer="x", cited=[0, 1, 2, 7, 2])

    ga_mod.structured_call = fake_structured_call
    d = await ga_mod.compose_grounded_answer("q", ["a", "b"])
    check(d.cited == [1, 2], f"#6 out-of-range / duplicate citations dropped: {d.cited}")

    # 7-9: Dewey evidence path
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DEWEY_ARCHIVE_PATH"] = str(pathlib.Path(tmp) / "a.sqlite3")
        os.environ.pop("EVIDENCE_SOURCE", None)
        os.environ["DEWEY_FETCH"] = "off"
        fake = FakeProvider("fakeweb", [
            RetrievedResource(title="Binary search tree", url="https://ex.org/bst", source_type="web",
                              snippet="Binary search tree search compares the key at each node, going left or right; work is O(h).", content_kind="excerpt"),
            RetrievedResource(title="BST search", url="https://ex.org/bst-search", source_type="web",
                              snippet="Search in a binary search tree follows one path from the root, so it works in O(h).", content_kind="excerpt"),
        ])
        providers_mod.default_providers = lambda: [fake]

        synth_calls: list[str] = []

        async def fake_synthesize(question, resource):
            synth_calls.append(resource.url)
            return ClaimDraft(evidence=resource.snippet[:80], reasoning="supports", confidence=0.7)

        engine_mod.synthesize_claim = fake_synthesize
        r1 = await engine_mod.gather_evidence_with_outcomes(Q, max_results_per_retriever=2)
        keyword_ok = fake.queries and "?" not in fake.queries[0] and " how " not in f" {fake.queries[0]} "
        check(r1.evidence_source == "research" and len(r1.claims) == 2 and keyword_ok
              and [rep.provider for rep in r1.provider_reports] == ["fakeweb"],
              f"#7 Dewey path: source={r1.evidence_source}, claims={len(r1.claims)}, query sent={fake.queries[0]!r}")

        calls_before = len(fake.queries)
        r2 = await engine_mod.gather_evidence_with_outcomes(Q, max_results_per_retriever=2)
        check(r2.evidence_source == "archive" and len(fake.queries) == calls_before and len(r2.claims) == 2,
              f"#8 repeat question -> source={r2.evidence_source}, provider calls added={len(fake.queries) - calls_before}")

        class LegacyRetriever:
            async def search(self, query, max_results=2):
                return [RetrievedResource(title="legacy", url="https://ex.org/legacy", source_type="web", snippet="legacy")]

        os.environ["EVIDENCE_SOURCE"] = "retrievers"
        engine_mod.DEFAULT_RETRIEVERS[:] = [LegacyRetriever()]
        r3 = await engine_mod.gather_evidence_with_outcomes(Q)
        check(r3.evidence_source == "retrievers" and [c.source.title for c in r3.claims] == ["legacy"],
              "#9 EVIDENCE_SOURCE=retrievers -> direct legacy path")
        os.environ.pop("EVIDENCE_SOURCE", None)
        os.environ.pop("DEWEY_ARCHIVE_PATH", None)

    # 16: weak-only evidence (e.g. a capped metadata claim) can't ground an answer
    weak_claim = _claim("The repository implements a BST with all operations.", "some-repo")
    weak_claim.confidence = 0.35
    g = await grounding_mod.ground_answer(Q, "memory answer", [weak_claim])
    check(not g.answer.grounded and "weak evidence" in (g.note or ""), f"#16 weak-only evidence -> ungrounded ({g.note!r})")

    # 17: a master node grounds on its own + all descendants' claims, deduped
    from backend.main_block.reasoning_engine.agents.grounding import claims_with_descendants
    from backend.main_block.reasoning_engine.agents.models import AgentStatus, GroundResult
    c_a, c_b, c_c = _claim("a", "s1"), _claim("b", "s2"), _claim("c", "s3")
    grandchild = GroundResult(status=AgentStatus.COMPLETE, claims=[c_c])
    child = GroundResult(status=AgentStatus.COMPLETE, claims=[c_b, c_a], child_results=[grandchild])
    merged = claims_with_descendants([c_a], [child])
    check([c.id for c in merged] == [c_a.id, c_b.id, c_c.id], f"#17 own + descendants' claims, deduped: {len(merged)}")

    # 18-20: gap-driven re-query (iteration 03, E12)
    composes: list[int] = []

    async def compose_with_gaps(q, ev, **_):
        composes.append(len(ev))
        if len(ev) == 1:
            return GroundedDraft(answer="Ops run in O(h) [1].", cited=[1], gaps=["definition of a BST", "how it works", "history"])
        return GroundedDraft(answer="A BST orders keys [2]; ops run in O(h) [1].", cited=[1, 2])

    async def audit_two(ans, known, **_):
        return SynthesisAudit(claims=[AtomicClaim(text="orders keys", origin="investigated", supported_by=[2]),
                                      AtomicClaim(text="O(h)", origin="investigated", supported_by=[1])])

    gap_asked: list[str] = []
    new_claim = _claim("A BST keeps left keys smaller and right keys larger.", "bst-def")

    async def requery(gap):
        gap_asked.append(gap)
        if gap == "how it works":
            raise RuntimeError("provider down")
        return [new_claim] if gap == "definition of a BST" else []

    grounding_mod.compose_grounded_answer, grounding_mod.audit_synthesis = compose_with_gaps, audit_two
    g = await grounding_mod.ground_answer(Q, "memory answer", [claims[1]], requery=requery)
    check(composes == [1, 2] and gap_asked == ["definition of a BST", "how it works"]
          and new_claim.id in g.answer.claim_ids and [c.id for c in g.gap_claims] == [new_claim.id],
          f"#18 gaps re-searched (max {grounding_mod.MAX_GAP_QUERIES}), recomposed, new claim cited + returned: asked={gap_asked}")

    composes.clear(); gap_asked.clear()
    g = await grounding_mod.ground_answer(Q, "memory answer", [], requery=requery)
    check(gap_asked == [Q.text] and not g.answer.grounded, "#19 no evidence -> the question itself is searched once as a gap")

    composes.clear(); gap_asked.clear()
    grounding_mod.compose_grounded_answer = compose_ok
    g = await grounding_mod.ground_answer(Q, "memory answer", claims, requery=requery)
    check(gap_asked == [] and composes == [], "#20 no gaps listed -> no extra searches")
    grounding_mod.audit_synthesis = audit_ok

    # 21-22 (iteration 05): inline markers stripped; clean outgoing search queries
    async def marked_call(**_):
        return GroundedDraft(answer="Search is O(h) [1]. Insert is too [1, 2].【1】 Done.", cited=[1])
    ga_mod.structured_call = marked_call
    d = await ga_mod.compose_grounded_answer("q", ["a", "b"])
    check(d.answer == "Search is O(h). Insert is too. Done.", f"#21 inline citation markers stripped: {d.answer!r}")
    from backend.main_block.research_engine.providers import keyword_query
    check(keyword_query("What is mitosis, what happens in each of its phases, and why is it important?") == "mitosis phases",
          "#22 outgoing search query: original words, no question filler")

    # 13-14: evidence engine quality rules (legacy path, fake synthesis)
    class MetaRetriever:
        content_kind = "metadata"

        async def search(self, query, max_results=2):
            return [RetrievedResource(title="some/repo", url="https://github.com/some/repo", source_type="code",
                                      snippet="BST implementation with time complexities"),
                    RetrievedResource(title="some/repo", url="https://github.com/some/repo", source_type="code",
                                      snippet="BST implementation with time complexities.")]

    async def confident_synth(question, resource):
        return ClaimDraft(evidence="The repository implements a BST with all operations and time complexities.",
                          reasoning="r", confidence=0.7)

    engine_mod.synthesize_claim = confident_synth
    r = await engine_mod.gather_evidence_with_outcomes(Q, retrievers=[MetaRetriever()])
    check(len(r.claims) == 1, f"#14 same URL + same evidence -> {len(r.claims)} claim")
    check(bool(r.claims) and r.claims[0].confidence <= engine_mod.METADATA_CONFIDENCE_CAP < 0.5
          and r.claims[0].source.content_kind == "metadata",
          f"#13 metadata claim capped at {r.claims[0].confidence if r.claims else None} (< 0.5 supported)")

    # 15: relevance gate + metadata ordering
    from backend.main_block.research_engine.archive import PassageHit
    from backend.main_block.research_engine.contracts import InformationNeed
    from backend.main_block.research_engine.engine import _deliverable

    def hit(pid, title, text, kind, score):
        return PassageHit(passage_id=pid, text=text, score=score, document_id=pid, url=f"https://ex.org/{pid}",
                          title=title, provider="p", source_type="web", source_role=None, retrieved_at="t",
                          entity_ids=[], content_kind=kind)

    need = InformationNeed(text="How does insertion work in a binary search tree?")
    got = _deliverable(need, [
        hit("meta", "BST repo", "binary search tree insertion code", "metadata", 9.0),
        hit("phys", "Exciton-polaritons in cuprous oxide", "excitons couple to light", "abstract", 8.0),
        hit("wiki", "Binary search tree", "insertion in a binary search tree walks to a null child", "summary", 5.0),
    ])
    check([h.passage_id for h in got] == ["wiki", "meta"], f"#15 gate drops off-topic, metadata last: {[h.passage_id for h in got]}")

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
