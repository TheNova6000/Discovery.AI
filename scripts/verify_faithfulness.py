"""Verifies claim <-> source faithfulness (backend/main_block/reasoning_engine/evidence/faithfulness.py and
its use in gather_evidence_with_outcomes), loop iteration 04, E13 — offline,
fake LLM.

  1. "distorted" and "unsupported" claims are dropped and kept visible as
     RetrievalOutcomes (relevant=False, verdict in raw_content)
  2. "supported" claims stay; faithfulness_checked=True when all were judged
  3. checker failure -> all claims kept, faithfulness_checked=False (unverified, not dropped)
  4. EVIDENCE_FAITHFULNESS=off -> no check call at all
  5. the prompt carries each claim next to ITS OWN passage; verdict item
     numbers outside the batch are ignored
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import backend.main_block.reasoning_engine.evidence.engine as engine_mod  # noqa: E402
import backend.main_block.reasoning_engine.evidence.faithfulness as faith_mod  # noqa: E402
from backend.main_block.reasoning_engine.evidence.faithfulness import ClaimVerdict, FaithfulnessReport  # noqa: E402
from backend.main_block.reasoning_engine.evidence.models import ClaimDraft, RetrievedResource  # noqa: E402
from backend.main_block.reasoning_engine.llm_steps import Question, QuestionLevel  # noqa: E402

Q = Question(text="What is the time complexity of traversal in a BST?", rationale="t", dimension_id="none",
             level=QuestionLevel.GROUND, entity_name="Binary search tree", abstraction_name="Binary search tree")

PASSAGES = [
    ("search-cost", "Searching a binary search tree takes O(h) time, where h is the height."),
    ("traversal", "An in-order traversal visits every node once, so it takes O(n) time."),
    ("history", "Binary search trees were developed in the 1960s."),
]
EVIDENCE = {"search-cost": "Traversal takes O(h) time.", "traversal": "Traversal takes O(n) time.",
            "history": "AVL trees rebalance with rotations."}


class Retriever:
    content_kind = "excerpt"

    async def search(self, query, max_results=3):
        return [RetrievedResource(title=t, url=f"https://ex.org/{t}", source_type="web", snippet=p) for t, p in PASSAGES]


async def synth(question, resource):
    return ClaimDraft(evidence=EVIDENCE[resource.title], reasoning="r", confidence=0.9)


async def main() -> int:
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    engine_mod.synthesize_claim = synth
    os.environ.pop("EVIDENCE_FAITHFULNESS", None)
    prompts: list[str] = []

    async def fake_call(**kw):
        prompts.append(kw["user_prompt"])
        verdicts = []
        for i, title in enumerate([t for t, _ in PASSAGES], start=1):
            item = next(n for n in range(1, 4) if f"[{n}] SOURCE PASSAGE ({title})" in kw["user_prompt"])
            verdicts.append(ClaimVerdict(item=item, verdict={"search-cost": "distorted", "traversal": "supported",
                                                              "history": "unsupported"}[title], note="n"))
        verdicts.append(ClaimVerdict(item=9, verdict="supported"))
        return FaithfulnessReport(verdicts=verdicts)

    faith_mod.structured_call = fake_call
    r = await engine_mod.gather_evidence_with_outcomes(Q, retrievers=[Retriever()])
    kept = [c.source.title for c in r.claims]
    dropped = [o.raw_content for o in r.retrieval_outcomes if (o.raw_content or "").startswith("[faithfulness")]
    check(kept == ["traversal"] and len(dropped) == 2 and any("distorted" in d for d in dropped)
          and any("unsupported" in d for d in dropped), f"#1 distorted + unsupported dropped, visible as outcomes: kept={kept}")
    check(r.faithfulness_checked, "#2 all claims judged -> faithfulness_checked=True")
    p = prompts[0]
    check("Searching a binary search tree takes O(h)" in p.split("CLAIM: Traversal takes O(h)")[0].split("[")[-2]
          or "SOURCE PASSAGE (search-cost): Searching a binary search tree takes O(h)" in p,
          "#5 each claim sits next to its own passage; out-of-range item 9 ignored")

    async def broken(**kw):
        raise RuntimeError("all providers down")

    faith_mod.structured_call = broken
    r = await engine_mod.gather_evidence_with_outcomes(Q, retrievers=[Retriever()])
    check(len(r.claims) == 3 and not r.faithfulness_checked, "#3 checker down -> claims kept, unverified")

    # 6-8 (iteration 05): Groq validates tool calls server-side; tolerant schemas
    from backend.main_block.reasoning_engine.llm_steps.audit import AtomicClaim
    from backend.main_block.reasoning_engine.llm_steps.relation_extraction import RelationExtraction
    a = AtomicClaim.model_validate({"text": "x", "status": "investigated", "supported_by": [1]})
    b = AtomicClaim.model_validate({"proposition": "y"})
    check(a.origin == "investigated" and b.text == "y" and b.origin == "uninvestigated",
          "#6 audit accepts 'status'/'proposition'; an unlabelled statement defaults to uninvestigated")
    r = RelationExtraction.model_validate({"relations": [{"subject": "A", "relation": "uses", "object": "B"},
                                                         {"subject": "A", "object": "C"}]})
    check([(x.relationship_type, x.target_entity) for x in r.relations] == [("uses", "B")],
          "#7 relation 'relation' key accepted; untyped triple dropped")
    fr = FaithfulnessReport.model_validate({"verdicts": [{"verdict": "supported"}, {"verdict": "distorted"}]})
    check([v.item for v in fr.verdicts] == [None, None], "#8 verdicts without item numbers are accepted (list position used)")

    calls = len(prompts)
    faith_mod.structured_call = fake_call
    os.environ["EVIDENCE_FAITHFULNESS"] = "off"
    r = await engine_mod.gather_evidence_with_outcomes(Q, retrievers=[Retriever()])
    os.environ.pop("EVIDENCE_FAITHFULNESS", None)
    check(len(prompts) == calls and len(r.claims) == 3 and not r.faithfulness_checked, "#4 switched off -> no check call")

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
