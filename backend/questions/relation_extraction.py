from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import GROUND_MODEL_CHAIN

# docs/Architecture.md §0.18: a candidate relation named by this call is NOT
# necessarily written to the graph — `is_relation_worthy` still has to pass it
# first. This schema stays deliberately separate from GroundDecision (not a
# field on it): §0.18's controlled experiment showed that asking about
# relationships as a rider on an action literally named "decompose" biases the
# model toward composition even when the content describes something else
# (the IDS/Privilege-Escalation miss). The fix was never better wording on that
# field — it was asking the question outside that framing entirely.
_BANNED_RELATIONSHIP_TYPES = {
    # Compositional — belongs to the decompose branch (ground_agent.py), not here.
    "decomposes_into",
    "is_part_of",
    "part_of",
    "component_of",
    "consists_of",
    "contains",
    # Generic/symmetric — discards exactly the acting-direction information that
    # makes a relation worth having (§0.18's relation-worthiness test, point 4).
    "relates_to",
    "related_to",
    "connected_to",
    "associated_with",
    "linked_to",
}


class CandidateRelation(BaseModel):
    source_entity: str = Field(description="The entity that acts, causes, or is the subject of the relation.")
    target_entity: str = Field(description="The entity being acted on, caused, or affected.")
    relationship_type: str = Field(
        description=(
            "Short verb-phrase naming the actual relation (e.g. 'spots', 'exploits', "
            "'routes_to', 'depends_on', 'regulates'). Never a compositional relation "
            "('decomposes_into', 'is_part_of', ...) and never a generic symmetric one "
            "('relates_to', 'connected_to', ...) — name the specific acting direction."
        )
    )
    justification: str = Field(description="One short sentence: where in the text this relation is stated.")


class RelationExtraction(BaseModel):
    relations: list[CandidateRelation] = Field(
        description=(
            "Real-world relationships between DISTINCT entities mentioned in the text, "
            "where each entity could stand as its own node under some question — not "
            "adjectives or sub-facts about a single entity. Skip purely compositional "
            "relationships (X is a part/phase/component of Y); those are handled "
            "elsewhere. Empty list if the text names no such relationship."
        )
    )


_SYSTEM_PROMPT = """\
You extract real-world relationships between distinct entities mentioned in a passage, \
for a knowledge graph. You are NOT deciding what to investigate next, and you are NOT \
deciding how to decompose a topic into parts — a separate part of the system already \
handles that. Your only job here: given text about one entity, name any actor, causal, \
or functional relationships between two entities that are each independently a "thing" \
(not adjectives or sub-facts describing one entity).

Skip purely compositional relationships (X is a component, phase, or part of Y) — those \
are out of scope for this call. Focus on: who acts on what, what detects/causes/enables/ \
depends on/routes to/regulates what. Only include a relation if BOTH ends could \
reasonably be their own entity elsewhere in a graph about this domain, and the relation \
would still hold regardless of how this particular question happened to be phrased — not \
an incidental detail true only of this one sentence.

Return an empty list rather than forcing a relation that doesn't clearly fit.
"""


def is_relation_worthy(candidate: CandidateRelation) -> bool:
    """Mechanically enforceable half of docs/Architecture.md §0.18's four-question
    worthiness test. Points 2 and 3 (stable across phrasings; useful for a
    different question than the one that surfaced it) are judgment calls the
    extraction prompt above is asked to apply itself — not something a function
    can verify from the candidate alone. This only catches what code safely can:
    a relation whose ends are the same entity, empty, or whose type is
    compositional/generic rather than a real acting direction.
    """
    source = candidate.source_entity.strip()
    target = candidate.target_entity.strip()
    relationship_type = candidate.relationship_type.strip().lower()
    if not source or not target or not relationship_type:
        return False
    if source.casefold() == target.casefold():
        return False
    if relationship_type in _BANNED_RELATIONSHIP_TYPES:
        return False
    return True


async def extract_relations(
    entity_name: str,
    known_text: str,
    *,
    model_chain: list[str] | None = None,
) -> list[CandidateRelation]:
    """The standalone relation-discovery call (docs/Architecture.md §0.18) — a
    genuinely separate decision from `decide_next_step`, not a field on
    `GroundDecision`. Returns raw candidates; callers still need
    `is_relation_worthy` before persisting any of them.
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    user_prompt = f"Entity under discussion: {entity_name}\n\nKnown text:\n{known_text}\n\nExtract relations."
    try:
        result = await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=RelationExtraction,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(f"extract_relations failed on every provider in {chain}: {exc}") from exc
    return result.relations


class CanonicalRelation(BaseModel):
    canonical_source: str = Field(
        description="The semantic actor -- who/what actually does the acting, causing, or "
        "depending, regardless of which entity was the grammatical subject of the original text."
    )
    canonical_relationship_type: str = Field(
        description="Active-voice verb phrase, no passive markers ('is X by', 'can be X by') -- the direct verb form."
    )
    canonical_target: str = Field(description="The entity acted upon.")


_CANONICALIZE_SYSTEM_PROMPT = """\
You are given a (source, relationship, target) triple extracted from text, which may be \
phrased in passive or modal-passive voice (e.g. "is detected by", "can be caused by", "is \
depended on by"). Your ONLY job: normalize it to the canonical active-voice form. Identify \
who/what is the real semantic actor and who/what is acted upon, regardless of which one was \
written as the grammatical subject -- then output the relationship as a direct active verb \
with the actor as canonical_source and the acted-upon entity as canonical_target. Do not \
change the meaning. Do not invent entities. If the triple is already active/canonical, \
return it unchanged.
"""


async def canonicalize_relation(
    candidate: CandidateRelation,
    *,
    model_chain: list[str] | None = None,
) -> CanonicalRelation:
    """docs/Architecture.md §0.18: a genuinely separate step from extraction, run
    AFTER `is_relation_worthy` -- verified empirically (8/8 on an adversarial
    active/passive/modal matrix) to correctly collapse passive and modal
    surface forms onto the same source/target/direction as their active-voice
    equivalent, without inventing content. On total provider failure, the
    caller should fall back to the raw candidate rather than drop the relation
    entirely -- canonicalization improves representation, it isn't required
    for the relation to be true.
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    user_prompt = (
        f"source={candidate.source_entity!r}, relationship={candidate.relationship_type!r}, "
        f"target={candidate.target_entity!r}"
    )
    try:
        return await structured_call(
            system_prompt=_CANONICALIZE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=CanonicalRelation,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(f"canonicalize_relation failed on every provider in {chain}: {exc}") from exc


# docs/Architecture.md §0.18: a small, deterministic string-normalization layer over
# relationship_type VALUES ALREADY IN ACTIVE VOICE (canonicalize_relation's job is
# direction/voice; this is purely spelling/format) -- built from variants actually
# observed across this project's own test runs, not a speculative ontology. New
# verbs not in this table pass through as a consistently-formatted (upper snake
# case) string rather than being merged with anything -- unmapped != unworthy.
_RELATIONSHIP_TYPE_SYNONYMS: dict[str, str] = {
    "detects": "DETECTS",
    "detect": "DETECTS",
    "spots": "DETECTS",
    "spot": "DETECTS",
    "monitors": "DETECTS",
    "monitor": "DETECTS",
    "causes": "CAUSES",
    "cause": "CAUSES",
    "depends_on": "DEPENDS_ON",
    "depend_on": "DEPENDS_ON",
    "depends": "DEPENDS_ON",
    "depend": "DEPENDS_ON",
    "routes_to": "ROUTES_TO",
    "route_to": "ROUTES_TO",
    "routes": "ROUTES_TO",
    "is_an_example_of": "IS_EXAMPLE_OF",
    "example_of": "IS_EXAMPLE_OF",
}


def normalize_relationship_type(relationship_type: str) -> str:
    key = re.sub(r"\s+", "_", relationship_type.strip().lower())
    if key in _RELATIONSHIP_TYPE_SYNONYMS:
        return _RELATIONSHIP_TYPE_SYNONYMS[key]
    return key.upper()
