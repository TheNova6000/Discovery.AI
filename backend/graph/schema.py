"""Neo4j label/relationship-type constants.

Per docs/Architecture.md §0, the graph schema is deliberately simple (typed nodes/edges/
properties only) — no hierarchy or zoom logic lives here; that belongs in the agent and
Question Engine layers above.
"""

NODE_LABEL = "GraphNode"
"""Canonical domain/entity nodes (property `type` distinguishes "domain" vs "entity")."""

ABSTRACTION_LABEL = "Abstraction"
"""A named boundary/view over a set of GraphNodes. See docs/PRD.md §4.1."""

RELATES_TO = "RELATES_TO"
"""Generic network edge between two GraphNodes; the `relationship_type` property carries
the actual semantic label (e.g. "competes_with", "regulates")."""

MEMBER_OF = "MEMBER_OF"
"""GraphNode -> Abstraction membership edge. Many-to-many by construction: a node may be
MEMBER_OF more than one Abstraction at once (non-strict hierarchy — docs/Rules.md rule 13)."""

QUESTION_LABEL = "Question"
"""A Question node (backend.questions.Question, persisted), attached to the canonical
entity/domain it was asked about. See docs/Phases.md Phase 5."""

CLAIM_LABEL = "Claim"
"""A Claim node — one piece of evidence-backed answer to a Question, carrying
evidence/reasoning/confidence/provenance (docs/Rules.md rule 4)."""

HAS_QUESTION = "HAS_QUESTION"
"""GraphNode -> Question: this entity/domain has this question attached to it."""

ANSWERED_BY = "ANSWERED_BY"
"""Question -> Claim: this question is (partially) answered by this claim. Multiple
claims may answer the same question — conflicting ones are surfaced, not overwritten
(Phase 7's conflict-resolution rule)."""

SUPERSEDES = "SUPERSEDES"
"""Claim -> Claim: the source claim supersedes the target claim (Graphiti-inspired
valid-time/superseded temporal pattern) — the old claim is kept, not deleted, just
marked non-current via its `superseded_by` property."""

HAS_RELATION_CLAIM = "HAS_RELATION_CLAIM"
"""docs/Architecture.md §0.26: GraphNode -> Claim, evidence for a specific RELATION
identity (source_id, relationship_type, target_id) rather than for a Question.
Deliberately additive and separate from the native RELATES_TO edge it's evidence
FOR — Neo4j relationships can't be the source/target of another edge, so this
reuses the existing Claim node shape (ClaimNode/attach_claim) rather than
reifying every relationship as its own node, which would touch every existing
traversal function (get_decomposition, get_neighbors, zoom_in, box/space
rendering). The edge's own `relationship_type`/`target_id`/`stance` properties
say WHICH relation this claim is evidence for and whether it supports or
contradicts it -- multiple claims naturally accumulate under the same identity
via repeated MERGE, they never create a duplicate RELATES_TO edge."""
