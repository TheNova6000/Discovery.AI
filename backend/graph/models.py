from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    name: str
    type: str  # "domain" | "entity"
    description: Optional[str] = None
    scope: Optional[str] = None
    """Part of canonical identity, NOT descriptive metadata (docs/Architecture.md
    §0.16) — disambiguates same-named nodes across domains ("Transmission" in an
    electric grid vs. in telecommunications). Identity is (name, scope), not name
    alone. Previously reused `description` as the scope carrier as a minimal
    Pass-3 mechanism (§0.9/§0.14) — split into its own field now that scope has
    earned its way into the real field set, so identity is never encoded inside
    prose.
    """
    merged_from: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    boundary_kind: Optional[Literal["subject", "entity"]] = None
    """docs/Architecture.md §0.21 -- the agent's own judgment, made explicitly
    (not inferred from `type`, which §0.16 found dead/unused in practice), of
    whether this node is a Subject (a named boundary around domains only, no
    single question it individually solves -- SystemDesign.md §4) or an Entity
    (a boundary that also exists specifically to solve one nameable problem --
    SystemDesign.md §5-6, "Entities as Solutions"). None means no such
    judgment has been made yet, a real and distinct state from either value --
    most ground-level nodes never earn one.
    """
    solves_question: Optional[str] = None
    """Only meaningful when boundary_kind == "entity" -- the one specific
    question/problem this entity exists to solve, in the agent's own words
    (e.g. PayPal -> "how can people transact online without physical
    exchange"). None for "subject" nodes and for nodes with no boundary_kind.
    """


class Abstraction(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str
    updated_at: str


class Relationship(BaseModel):
    source_id: str
    target_id: str
    relationship_type: str
    properties: dict = Field(default_factory=dict)


class Subgraph(BaseModel):
    abstraction: Abstraction
    nodes: list[GraphNode]
    relationships: list[Relationship]


class QuestionNode(BaseModel):
    """The persisted graph-side view of a backend.questions.Question. Deliberately
    a separate, plain model (not a re-export of Question) — backend/graph must not
    import from backend/questions (docs/Rules.md rule 1's layering: Graph Interface
    is the lowest layer, nothing above it should be imported into it)."""

    id: str
    text: str
    dimension_id: str
    level: str
    rationale: str
    created_at: str


class ClaimNode(BaseModel):
    """The persisted graph-side view of a backend.evidence.Claim — same reasoning
    as QuestionNode above for why this isn't a re-export."""

    id: str
    evidence: str
    reasoning: str
    confidence: float
    source_title: str
    source_url: str
    source_type: str
    valid_from: str
    superseded_by: Optional[str] = None


class QuestionProvenance(BaseModel):
    """One question attached to an entity, plus its parent question's TEXT if it
    was itself a discovered sub-question — read off the existing `rationale`
    string (`"Sub-question of: <parent text>"`, written by `attach_question`),
    not a new graph property. There is no persisted Question->Question edge yet
    (docs/Phases.md Phase 6's deferred Question Graph mirror), so this is a
    best-effort text parse, not a graph traversal — `parent_question_text` is the
    parent's TEXT, not a queryable id/node."""

    question_id: str
    question_text: str
    rationale: str
    parent_question_text: Optional[str] = None


class CandidateEvidence(BaseModel):
    """One existing candidate considered during `resolve_entity`, with the actual
    matched tokens that produced its score — not just the number, so a decision
    stays inspectable (docs/Architecture.md §0.18: "Reused X because 'packets'
    and 'networking' strongly matched its existing context", not just "score=2")."""

    node: GraphNode
    matched_tokens: list[str] = Field(default_factory=list)
    score: int


class IdentityResolution(BaseModel):
    """docs/Architecture.md §0.18 — the frozen contract for `resolve_entity`,
    validated against a 6-case evidence-type matrix (lexical/domain/relational/
    opposing-lexical/no-evidence/conflicting-evidence, all 6 correct) before
    being built for real. Four decisions, not two: `REUSE`/`CREATE` are actions
    a caller can safely act on; `AMBIGUOUS` (no candidate has any evidence) and
    `CONFLICT` (multiple candidates have real, comparable evidence) are both
    "don't guess" outcomes, but for different reasons — kept distinct rather
    than collapsed into one shrug, since a real caller (and eventually a human
    debugging the graph) needs to know which one happened. `selected_node` is
    only ever populated for `REUSE`/`CREATE`; always `None` for the other two —
    the resolver's whole point is refusing to pick when it shouldn't.
    """

    decision: Literal["REUSE", "CREATE", "AMBIGUOUS", "CONFLICT"]
    selected_node: Optional[GraphNode] = None
    candidates: list[CandidateEvidence] = Field(default_factory=list)
    reason: str


class EntityExplanation(BaseModel):
    """The read-only answer to "why does this entity exist in the graph" — every
    question currently attached to it, each with what (if anything) it was a
    sub-question of. An entity with zero attached questions still returns an
    `EntityExplanation` with an empty list — that's a real, distinct state from
    the entity not existing at all (which raises `GraphInterfaceError` instead)."""

    entity: GraphNode
    discovered_by: list[QuestionProvenance] = Field(default_factory=list)
