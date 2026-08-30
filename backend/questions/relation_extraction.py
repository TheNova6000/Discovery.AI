from __future__ import annotations

import re

import instructor
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import GROUND_MODEL_CHAIN
from .relation_types import is_compositional

# docs/Architecture.md §0.18: a candidate relation named by this call is NOT
# necessarily written to the graph — `is_relation_worthy` still has to pass it
# first. This schema stays deliberately separate from GroundDecision (not a
# field on it): §0.18's controlled experiment showed that asking about
# relationships as a rider on an action literally named "decompose" biases the
# model toward composition even when the content describes something else
# (the IDS/Privilege-Escalation miss). The fix was never better wording on that
# field — it was asking the question outside that framing entirely.
#
# Compositional types are banned here for a DIFFERENT reason than the generic/
# symmetric ones below (they belong to the decompose branch in
# ground_agent.py, not here) — that check is now `is_compositional()`
# (docs/Architecture.md §0.25), the single registry replacing what used to be
# three separately-hardcoded compositional-type lists across this codebase.
_UNINFORMATIVE_RELATIONSHIP_TYPES = {
    # Generic/symmetric — discards exactly the acting-direction information that
    # makes a relation worth having (§0.18's relation-worthiness test, point 4).
    "relates_to",
    "related_to",
    "connected_to",
    "associated_with",
    "linked_to",
}


class CandidateRelation(BaseModel):
    # docs/Memory.md's relation-extraction schema-flakiness chase: aliased to
    # the subject/predicate/object names the model already reaches for
    # naturally (observed live, repeatedly -- Groq's smaller model kept
    # emitting exactly these field names instead of the ones below, even
    # under Instructor's JSON_SCHEMA mode, which didn't stop the drift).
    # `populate_by_name=True` means Python code everywhere else keeps using
    # `.source_entity`/`.target_entity`/`.relationship_type` completely
    # unchanged -- only the JSON SCHEMA SENT TO THE MODEL uses the aliases
    # (Pydantic's `model_json_schema(by_alias=True)` default, confirmed
    # empirically), so this is a schema-level fix with zero call-site churn.
    model_config = ConfigDict(populate_by_name=True)

    source_entity: str = Field(
        alias="subject", description="The entity that acts, causes, or is the subject of the relation."
    )
    target_entity: str = Field(alias="object", description="The entity being acted on, caused, or affected.")
    relationship_type: str = Field(
        # AliasChoices, not a single alias: the model's natural word choice for
        # the middle slot of a subject/?/object triple split between
        # "predicate" and "relation" across observed live failures -- accept
        # either rather than betting on one.
        validation_alias=AliasChoices("predicate", "relation"),
        serialization_alias="predicate",
        description=(
            "Short verb-phrase naming the actual relation (e.g. 'spots', 'exploits', "
            "'routes_to', 'depends_on', 'regulates'). Never a compositional relation "
            "('decomposes_into', 'is_part_of', ...) and never a generic symmetric one "
            "('relates_to', 'connected_to', ...) — name the specific acting direction."
        ),
    )
    # Optional with a default (docs/Memory.md's schema-flakiness chase): observed
    # live, the model sometimes omits this field entirely from an otherwise
    # perfectly usable triple. Nothing downstream requires a non-empty
    # justification for a relation to be persisted (is_relation_worthy doesn't
    # check it) -- it exists for human interpretability, same rationale as
    # GroundDecision.reasoning being optional for the identical reason.
    justification: str = Field(
        default="", description="One short sentence: where in the text this relation is stated."
    )


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
handles that. Your only job here: name any actor, causal, functional, or temporal/\
sequential relationships between two entities that are each independently a "thing" \
(not adjectives or sub-facts describing one entity).

Skip purely compositional relationships (X is a component, phase, or part of Y) — those \
are out of scope for this call. Focus on: who acts on what, what detects/causes/enables/ \
depends on/routes to/regulates what, and what comes before/after what. Only include a \
relation if BOTH ends could reasonably be their own entity elsewhere in a graph about \
this domain, and the relation would still hold regardless of how this particular question \
happened to be phrased — not an incidental detail true only of this one sentence.

Temporal / sequential / process relationships are just as much in scope as actor and \
causal ones — do not skip a step just because it's ordering rather than acting. When the \
text describes a process, workflow, or lifecycle, extract the ordering between its \
named stages, not only what each stage does: precedes/follows, happens_before/ \
happens_after, occurs_before/occurs_after, and branch/convergence points (multiple \
paths rejoining at a later stage). Examples:
- "Risk checks precede authorization." -> Risk checks -[PRECEDES]-> Authorization
- "Authorization is followed by capture." -> Authorization -[PRECEDES]-> Capture
- "Multiple capture streams converge during clearing." -> Capture -[CONVERGES_AT]-> Clearing
A described sequence of N stages should usually yield N-1 (or more, if it branches or \
converges) ordering relations between consecutive stages — not just relations about what \
each stage individually does.

When a list of "Entities discovered together" is given below, treat it as the full \
candidate set to check — actively look for relationships directly BETWEEN those entities, \
not only relationships anchored on whichever one is named "entity under discussion." A \
real-world process usually involves several of them acting on each other in sequence or in \
parallel (e.g. a client pays its own bank, which forwards the payment to a second bank, \
which credits the recipient) — extract those direct links between the co-discovered \
entities too. Do not default to routing every relation through a single hub entity just \
because it was named first or most often; check every pair in the list against the text, \
not just pairs that include the first-named entity.

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
    if is_compositional(relationship_type) or relationship_type in _UNINFORMATIVE_RELATIONSHIP_TYPES:
        return False
    return True


async def extract_relations(
    entity_name: str,
    known_text: str,
    *,
    sibling_entity_names: list[str] | None = None,
    model_chain: list[str] | None = None,
) -> list[CandidateRelation]:
    """The standalone relation-discovery call (docs/Architecture.md §0.18) — a
    genuinely separate decision from `decide_next_step`, not a field on
    `GroundDecision`. Returns raw candidates; callers still need
    `is_relation_worthy` before persisting any of them.

    `sibling_entity_names` (docs/Architecture.md §0.22): entities discovered
    under the SAME parent as `entity_name` during decomposition (e.g. "Client
    Bank", "Merchant Bank" discovered while investigating a payment). Passing
    them explicitly and asking for all-pairs relations among the set — not just
    pairs involving `entity_name` — is the documented fix (GraphRAG's and
    LightRAG's own production prompts both do this) for LLM extraction's
    well-documented bias toward relations anchored on the one named "topic"
    entity, which is exactly why this call previously only ever produced edges
    radiating from the current entity and never sibling-to-sibling edges.
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    entities_line = ""
    if sibling_entity_names:
        seen = {entity_name.casefold()}
        all_names = [entity_name]
        for name in sibling_entity_names:
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                all_names.append(name)
        if len(all_names) > 1:
            entities_line = (
                "\nEntities discovered together (check every pair, not just ones "
                f"involving the entity under discussion): {', '.join(all_names)}"
            )
    user_prompt = (
        f"Entity under discussion: {entity_name}{entities_line}\n\n"
        f"Known text:\n{known_text}\n\nExtract relations."
    )
    try:
        result = await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=RelationExtraction,
            model_chain=chain,
            # docs/Memory.md's relation-extraction schema-flakiness chase:
            # observed live, repeatedly, on this specific call -- the default
            # Mode.TOOLS lets a smaller model drift onto its own field names
            # (subject/predicate/object) instead of RelationExtraction's real
            # schema. JSON_SCHEMA maps to actual constrained decoding where a
            # provider supports it (Groq, Cerebras); falls back silently to
            # default mode for providers that don't (Google).
            mode=instructor.Mode.JSON_SCHEMA,
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
