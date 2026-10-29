"""Public interface of the reasoning engine (Discovery.AI).

Everything outside `reasoning_engine/` imports from HERE only (the main
block's door does; clients never do -- they use `backend.main_block.interface`).
To upgrade or replace the reasoning engine, keep these names and contracts;
`verify_grounding`, `verify_faithfulness`, `verify_mainblock` and the R1-R5 /
phase-8 suites are the acceptance tests for a replacement.

Contract: a question goes in; a grounded answer (claims with provenance, an
audited support ratio, gaps) and a persisted knowledge graph come out. The
reasoning engine reaches sources only through `research_engine.interface`.
"""

from __future__ import annotations

from .agents.ground_agent import GroundAgent
from .agents.grounding import Grounding, ground_answer
from .agents.models import GroundResult
from .agents.policy import EXPLORATORY_POLICY, ResearchPolicy
from .domain import Answer
from .domain import Claim as DomainClaim
from .evidence import Claim
from .evidence.engine import GatherEvidenceResult, gather_evidence, gather_evidence_with_outcomes
from .graph import GraphNode, Relationship, find_or_create_entity, materialize_abstraction
from .llm_steps import Question, QuestionLevel, audit_synthesis, compose_lesson_explanation
from .research_api import ResearchResponse
from .research_api.service import fetch_and_compile_research_response


async def investigate(question: Question, *, policy: ResearchPolicy = EXPLORATORY_POLICY) -> GroundResult:
    """Run one recursive, evidence-grounded investigation and persist it to the graph."""
    return await GroundAgent(question, gather_evidence=True, persist_to_graph=True, policy=policy).run()


__all__ = [
    "Answer",
    "Claim",
    "DomainClaim",
    "EXPLORATORY_POLICY",
    "GatherEvidenceResult",
    "GraphNode",
    "GroundAgent",
    "GroundResult",
    "Grounding",
    "Question",
    "QuestionLevel",
    "Relationship",
    "ResearchPolicy",
    "ResearchResponse",
    "audit_synthesis",
    "compose_lesson_explanation",
    "fetch_and_compile_research_response",
    "find_or_create_entity",
    "gather_evidence",
    "gather_evidence_with_outcomes",
    "ground_answer",
    "investigate",
    "materialize_abstraction",
]
