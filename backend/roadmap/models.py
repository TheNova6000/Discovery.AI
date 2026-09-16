from __future__ import annotations

from pydantic import BaseModel, Field

from backend.graph.models import ClaimNode


class RoadmapStep(BaseModel):
    """One (Question -> Resource -> summary) entry in an ordered Roadmap
    (PRD.md §4a). Carries the entity it belongs to and that entity's zoom-chain
    depth so a frontend can render steps grouped/indented without a second
    graph query. `level` mirrors `backend.questions.QuestionLevel`'s string
    values ("master"/"ground") without importing that module -- Graph Interface
    (backend.graph) and this package must not depend on backend.questions
    (Rules.md rule 1's layering; QuestionNode itself already keeps `level` as a
    plain string for the same reason).
    """

    entity_id: str
    entity_name: str
    question_id: str
    question_text: str
    question_rationale: str
    level: str
    zoom_depth: int
    claims: list[ClaimNode] = Field(default_factory=list)


class Roadmap(BaseModel):
    """The full ordered sequence for one abstraction -- what
    `generate_roadmap(abstraction) -> list[Question]` (PRD.md §4a) actually
    returns, widened to carry entity/claim context a frontend needs to render
    each step without re-querying the graph per step.
    """

    abstraction_id: str
    abstraction_name: str
    steps: list[RoadmapStep] = Field(default_factory=list)
