from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RelationFamily(str, Enum):
    """docs/Architecture.md §0.25. Not an invented list -- COMPOSITION is the
    single-bucket simplification of Winston/Chaffin/Herrmann's six-way
    part-whole taxonomy (Cognitive Science, 1987); the rest name the other
    established relation shapes this project's own extraction has actually
    produced (§0.17-§0.22's live runs): TEMPORAL/CAUSAL/DEPENDENCY/INTERACTION/
    CLASSIFICATION. One bucket per family for now -- finer subtypes (e.g.
    meronymy's six kinds) are real but not needed until something in this
    project actually reasons across chained relations, per §0.25's own
    "don't build the mechanism before something needs it" note.
    """

    COMPOSITION = "composition"
    CAUSAL = "causal"
    TEMPORAL = "temporal"
    DEPENDENCY = "dependency"
    INTERACTION = "interaction"
    CLASSIFICATION = "classification"


@dataclass(frozen=True)
class RelationTypeInfo:
    family: RelationFamily
    # OWL/RDF property-characteristic vocabulary (W3C OWL Reference), not
    # bespoke flags -- see §0.25 for why this grounding matters. Declared now,
    # consumed by nothing yet: no traversal/inference code reads these fields
    # this pass, on purpose (§0.25's explicit scope boundary).
    transitive: bool = False
    symmetric: bool = False
    inverse_of: Optional[str] = None


# Canonical relationship_type (already-normalized form, i.e. what
# normalize_relationship_type produces or what decompose writes directly) ->
# its semantics. This is the SINGLE source of truth §0.25 exists to create --
# before this, "is this compositional" was a hardcoded set duplicated across
# relation_extraction.py, app.py, and chat.html's JS, with a code comment
# admitting the JS copy had to be kept in sync by hand.
RELATION_TYPES: dict[str, RelationTypeInfo] = {
    # ---- composition (structural part-whole; drives box/space nesting) ----
    "decomposes_into": RelationTypeInfo(RelationFamily.COMPOSITION),
    "contains": RelationTypeInfo(RelationFamily.COMPOSITION, inverse_of="is_part_of"),
    "is_part_of": RelationTypeInfo(RelationFamily.COMPOSITION, inverse_of="contains"),
    "part_of": RelationTypeInfo(RelationFamily.COMPOSITION, inverse_of="contains"),
    "component_of": RelationTypeInfo(RelationFamily.COMPOSITION, inverse_of="contains"),
    "consists_of": RelationTypeInfo(RelationFamily.COMPOSITION, inverse_of="is_part_of"),
    # ---- temporal (ordering -- seeded now per §0.23's named flow-view gap) ----
    "precedes": RelationTypeInfo(RelationFamily.TEMPORAL, transitive=True, inverse_of="follows"),
    "follows": RelationTypeInfo(RelationFamily.TEMPORAL, transitive=True, inverse_of="precedes"),
    "occurs_during": RelationTypeInfo(RelationFamily.TEMPORAL),
    # ---- causal ----
    "causes": RelationTypeInfo(RelationFamily.CAUSAL, transitive=True),
    "enables": RelationTypeInfo(RelationFamily.CAUSAL),
    "prevents": RelationTypeInfo(RelationFamily.CAUSAL),
    # ---- dependency ----
    "requires": RelationTypeInfo(RelationFamily.DEPENDENCY, inverse_of="required_by"),
    "required_by": RelationTypeInfo(RelationFamily.DEPENDENCY, inverse_of="requires"),
    "depends_on": RelationTypeInfo(RelationFamily.DEPENDENCY, transitive=True),
    # ---- interaction (actor-to-actor; explicitly never compositional --
    # this is the exact family the PayPal/Mastercard bug turned out to be) ----
    "uses": RelationTypeInfo(RelationFamily.INTERACTION),
    "uses_network": RelationTypeInfo(RelationFamily.INTERACTION),
    "routes_to": RelationTypeInfo(RelationFamily.INTERACTION),
    "routes_data_between": RelationTypeInfo(RelationFamily.INTERACTION, symmetric=True),
    "connects_to": RelationTypeInfo(RelationFamily.INTERACTION, symmetric=True),
    "connects": RelationTypeInfo(RelationFamily.INTERACTION, symmetric=True),
    "serves": RelationTypeInfo(RelationFamily.INTERACTION),
    "provides": RelationTypeInfo(RelationFamily.INTERACTION),
    "delegates_to": RelationTypeInfo(RelationFamily.INTERACTION),
    "authorizes": RelationTypeInfo(RelationFamily.INTERACTION),
    "regulates": RelationTypeInfo(RelationFamily.INTERACTION),
    "transfers_funds_to": RelationTypeInfo(RelationFamily.INTERACTION),
    "queries": RelationTypeInfo(RelationFamily.INTERACTION),
    "evaluates": RelationTypeInfo(RelationFamily.INTERACTION),
    # ---- classification ----
    "instance_of": RelationTypeInfo(RelationFamily.CLASSIFICATION, transitive=True),
    "is_example_of": RelationTypeInfo(RelationFamily.CLASSIFICATION, transitive=True),
    "example_of": RelationTypeInfo(RelationFamily.CLASSIFICATION, transitive=True),
    "subtype_of": RelationTypeInfo(RelationFamily.CLASSIFICATION, transitive=True),
}


def get_relation_info(relationship_type: str) -> Optional[RelationTypeInfo]:
    """None for an unrecognized type -- unmapped != an error, same tolerance
    normalize_relationship_type already has for a verb it's never seen
    before. Callers that need a boolean should use is_compositional() below
    rather than testing this for None themselves.
    """
    return RELATION_TYPES.get(relationship_type.strip().lower())


def is_compositional(relationship_type: str) -> bool:
    """The single source of truth for "does this relation nest/box" --
    replaces the hardcoded compositional sets that used to live separately in
    relation_extraction.py's _BANNED_RELATIONSHIP_TYPES, app.py's
    _COMPOSITIONAL_TYPES, and chat.html's two JS copies.
    """
    info = get_relation_info(relationship_type)
    return info is not None and info.family == RelationFamily.COMPOSITION


# docs/Architecture.md §0.27: the deterministic mapping a View-switch intent
# resolves against -- "who decides which relations belong in a projection?"
# is answered by this table, never by an LLM re-reasoning about the subject.
# "network" reuses the INTERACTION family name at the user-facing layer
# because that's the vocabulary a person actually asks in ("show what X
# connects to"), even though the registry's own internal name is INTERACTION.
PROJECTION_FAMILIES: dict[str, RelationFamily] = {
    "structure": RelationFamily.COMPOSITION,
    "flow": RelationFamily.TEMPORAL,
    "causal": RelationFamily.CAUSAL,
    "dependency": RelationFamily.DEPENDENCY,
    "network": RelationFamily.INTERACTION,
}


def get_family(relationship_type: str) -> Optional[str]:
    """String, not the enum, since this is what gets serialized onto each
    edge in the /graph payload for chat.html to read (JS has no notion of a
    Python Enum) -- None for a relation type not yet in the registry, which
    chat.html treats as "not compositional" (§0.22's original default:
    unmapped types render as ordinary edges, never as containment).
    """
    info = get_relation_info(relationship_type)
    return info.family.value if info else None
