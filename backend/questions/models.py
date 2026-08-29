from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class QuestionLevel(str, Enum):
    """How broad/concrete the question should be. Maps to the two-tier agent model
    in docs/Architecture.md §0 (Master + dynamically-recursive Ground) — not a fixed
    class hierarchy, just a granularity signal the Question Engine uses to shape the
    prompt. Intermediate granularities can be added later without breaking callers.
    """

    GROUND = "ground"
    """Concrete, specific, mechanism-level — about the entity itself."""

    MASTER = "master"
    """Broad, strategic, systemic — about how the entity fits into the larger abstraction."""


class Dimension(BaseModel):
    """A lens applied to an abstraction/entity to generate questions.
    See docs/PRD.md §3 and the System Design spec §9-11.
    """

    id: str
    name: str
    description: str


class DimensionContext(BaseModel):
    """One lens in a possibly-multi-lens investigation frame (docs/Memory.md's
    dimension-composability pass). Deliberately just {name, description} — no `id`
    — because this is carried on `Question.dimensions` purely to shape LLM
    reasoning in `decide_next_step`; it is not a graph-attachment key (that's still
    `Question.dimension_id`, untouched by this change).
    """

    name: str
    description: Optional[str] = None


class QuestionDraft(BaseModel):
    """The only shape the LLM is asked to produce (via Instructor). Deliberately
    narrow — the model never sees/sets provenance fields like entity_name or
    dimension_id, so those can't be hallucinated or overridden; the engine fills
    them in from the caller's actual arguments after generation.
    """

    text: str = Field(description="The generated question itself, in natural language.")
    rationale: str = Field(
        description="One sentence on why this question matters at this level/dimension."
    )


class Question(BaseModel):
    """A single generated question with full provenance. Assembled by the Question
    Engine from a QuestionDraft plus the caller's context — never constructed
    directly from raw LLM output.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    rationale: str
    dimension_id: str
    dimension_name: Optional[str] = None
    dimension_description: Optional[str] = None
    """Both optional and additive (docs/Memory.md's dimension-steering pass) so
    every existing caller that only ever set `dimension_id` (a bare label) keeps
    working unchanged. When present, `decide_next_step` uses these to make the
    dimension an actual investigation lens instead of inert metadata — `Dimension`
    was already a free-form `{id, name, description}` model with no restriction to
    the 3 universal ones (SCALE/PERSPECTIVE/TIME); this is what makes a
    user-defined dimension ("Power Dynamics", "Incentives", ...) actually steer
    reasoning rather than just being carried along as a label.
    """
    dimensions: list[DimensionContext] = Field(default_factory=list)
    """Zero or more lenses that JOINTLY frame this investigation (docs/Memory.md's
    dimension-composability pass, extending the single-dimension steering above).
    Additive and independent of dimension_name/dimension_description — a caller can
    set either, both, or neither. `decide_next_step` treats a non-empty `dimensions`
    list as the combined frame to synthesize (not concatenate) the question through;
    when empty, it falls back to dimension_name/dimension_description exactly as
    before. Intentionally has no built-in conflict-resolution policy for lenses
    that pull in different directions (e.g. Technical + Psychological) — left to the
    LLM to compose naturally for now, per the deliberate "observe failures before
    adding a policy" call made when this was designed.
    """
    level: QuestionLevel
    entity_name: str
    entity_scope_hint: Optional[str] = None
    """Pass 3 (docs/Architecture.md §0.10/§0.14) — disambiguating context for
    `entity_name` when the SAME name refers to different real-world things
    depending on domain (e.g. "Transmission" in an electric grid vs. in
    telecommunications). Optional and additive: unset means `find_or_create_entity`
    falls back to its original global-name-only lookup, unchanged for every
    existing caller. Populated from `Intent.scope_hint` when the user's own
    phrasing names a disambiguating context ("...in electric grids").
    """
    abstraction_name: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GroundDecision(BaseModel):
    """The only shape the LLM is asked to produce for a Ground Agent's step
    (docs/Phases.md Phase 3, refined post-Phase-5 into the iterative one-unknown-
    at-a-time loop AgenticArchitecture.md §23 actually describes — GENERATE ->
    INVESTIGATE -> INTEGRATE -> CHECK COMPLETENESS -> REFINE/EXPAND). This is
    called REPEATEDLY for the same question as investigation proceeds, each time
    given everything resolved so far (`known`, in `decide_next_step`) — it is not a
    one-shot plan for the whole sub-question tree. The agent, not the model,
    decides afterward whether a "decompose" verdict is actually honored (depth/step
    budget) or downgraded to a boundary hit (Rules.md rule 10's spirit, applied
    locally since no Master exists yet to own the spawn budget in this phase).
    """

    action: Literal["answer", "decompose", "boundary_hit"]
    reasoning: Optional[str] = Field(
        default=None,
        description=(
            "One or two sentences on why THIS action, not another, is the right "
            "call here — for 'decompose' vs 'answer' at master level, name the "
            "structural judgment made (e.g. 'this splits into independently "
            "investigable components' vs 'these are interacting explanations of "
            "one phenomenon, splitting would create artificial boundaries')."
        ),
    )
    # Optional, not required (hackathon-reliability fix, docs/Memory.md): observed
    # live on Groq's gpt-oss-20b returning a complete, correct `answer` but
    # omitting `reasoning` from its structured tool-call output — a required
    # field failing schema validation discarded an otherwise-perfectly-usable
    # answer and cascaded the whole call through two more providers (one of which
    # was down for an unrelated billing reason) before failing outright. Nothing
    # in the agent loop branches on `reasoning`'s content — it exists purely for
    # human interpretability (why this action, not another) — so it should never
    # be the reason a substantively good decision gets thrown away.
    answer: Optional[str] = Field(
        default=None, description="Required when action == 'answer'."
    )
    confidence: Optional[float] = Field(
        default=None, description="0-1 confidence in the answer, when action == 'answer'."
    )
    sub_question_texts: Optional[list[str]] = Field(
        default=None,
        description=(
            "Exactly ONE short, narrower sub-question text (as the only list item), "
            "required when action == 'decompose' — the single specific unknown "
            "still blocking a real answer, not a batch covering several unknowns "
            "at once. Must be genuinely more specific than the parent, not a "
            "rewording of it."
        ),
    )
    discovered_entity_name: Optional[str] = Field(
        default=None,
        description=(
            "Only set when action == 'decompose' AND the sub-question reveals a "
            "genuinely identifiable, reusable real-world entity distinct from the "
            "current one — a thing with its own substantial internal structure "
            "worth its own node in the graph (e.g. 'DNS' discovered while "
            "investigating 'Internet Infrastructure'). Leave unset when the "
            "sub-question is just a narrower question about the SAME entity (e.g. "
            "'How does PayPal verify identity at signup?' is NOT a new entity, "
            "it's still just PayPal). A sub-question alone never automatically "
            "implies a new entity — most decompositions should leave this unset."
        ),
    )
    relationship_type: Optional[str] = Field(
        default=None,
        description=(
            "Only meaningful when action == 'decompose' AND discovered_entity_name "
            "is set — names HOW the discovered entity relates to the current one, "
            "as a short verb-phrase (e.g. 'routes_to', 'authorizes', 'delegates_to', "
            "'regulates', 'precedes', 'depends_on', 'produces'). This list is "
            "illustrative, not exhaustive — use whatever verb-phrase actually "
            "describes the relationship, or invent one if none of these fit. Leave "
            "unset when the relationship really is compositional ('the entity is "
            "made up of / decomposes into this part') — unset defaults to "
            "'decomposes_into', so most ordinary structural decompositions should "
            "leave this unset. Only set it when the relationship is something OTHER "
            "than plain composition — e.g. one entity acting on, routing to, "
            "delegating to, or preceding another, as opposed to one entity being a "
            "structural part of another."
        ),
    )
    boundary_reason: Optional[str] = Field(
        default=None,
        description=(
            "Required when action == 'boundary_hit': what information/context "
            "outside the current scope this question actually needs."
        ),
    )
    working_framing: Optional[str] = Field(
        default=None,
        description=(
            "Only set when action == 'decompose' AT MASTER LEVEL AND no explicit "
            "Dimension/Dimensions were given for this question. A few words naming "
            "the lens you are IMPLICITLY using to decide this split — the framing "
            "that made THIS decomposition look natural rather than some other "
            "equally valid one (e.g. 'Technical/system architecture', 'Business "
            "model', 'Regulatory structure'). Leave unset when an explicit "
            "Dimension was given (the dimension already IS the framing — don't "
            "restate it here) or when action != 'decompose' at master level."
        ),
    )
    boundary_kind: Optional[Literal["subject", "entity"]] = Field(
        default=None,
        description=(
            "Only set AT MASTER LEVEL, regardless of whether action is 'answer' or "
            "'decompose': does the entity/subject you are CURRENTLY investigating "
            "deserve to be understood as a named boundary in its own right? "
            "'subject' = a boundary drawn around a set of domains, with no single "
            "specific problem it individually solves (e.g. 'Quantum Computing' "
            "spanning Physics, Computer Science, Information Theory — a region, "
            "not a solution). 'entity' = a boundary that ALSO exists specifically "
            "to solve one nameable question/problem (e.g. PayPal exists to solve "
            "'how can people transact online without physical exchange'; a company, "
            "project, or organization is almost always this kind, not 'subject'). "
            "Leave BOTH this and boundary_solves_question unset when the current "
            "entity doesn't yet warrant being understood as a named boundary at "
            "all — most ground-level narrow questions never earn one."
        ),
    )
    boundary_solves_question: Optional[str] = Field(
        default=None,
        description=(
            "Required when boundary_kind == 'entity': the one specific question or "
            "problem this entity exists to solve, in one sentence, in your own "
            "words — not a restatement of the investigation's own question. Leave "
            "unset for 'subject' or whenever boundary_kind is unset."
        ),
    )


class SynthesisDraft(BaseModel):
    """The only shape the LLM is asked to produce when synthesizing a parent
    question's answer from its already-resolved sub-questions (docs/Phases.md
    Phase 3/4's decomposition, refined after a real evaluation run found decomposed
    questions had no top-level answer at all — just a bag of disconnected child
    results). Uses `MASTER_MODEL_CHAIN` by default: "synthesis across many
    children" is Rules.md rule 3's named example of when escalating tiers is
    justified.
    """

    answer: str = Field(
        description="A coherent, organized answer to the ORIGINAL (parent) question, drawn only from the given sub-answers."
    )
    confidence: float = Field(
        description=(
            "0-1: how completely the sub-answers actually cover the original "
            "question. Lower this when one or more sub-questions were unresolved."
        )
    )
