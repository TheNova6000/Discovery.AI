from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j.exceptions import Neo4jError

from .driver import get_driver
from .exceptions import GraphInterfaceError
from .models import (
    Abstraction,
    CandidateEvidence,
    ClaimNode,
    EntityExplanation,
    GraphNode,
    IdentityResolution,
    QuestionNode,
    QuestionProvenance,
    Relationship,
    Subgraph,
)
from .schema import (
    ABSTRACTION_LABEL,
    ANSWERED_BY,
    CLAIM_LABEL,
    HAS_QUESTION,
    HAS_RELATION_CLAIM,
    MEMBER_OF,
    NODE_LABEL,
    QUESTION_LABEL,
    RELATES_TO,
    SUPERSEDES,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_to_node(node) -> GraphNode:
    return GraphNode(
        id=node["id"],
        name=node["name"],
        type=node["type"],
        description=node.get("description"),
        scope=node.get("scope"),
        merged_from=list(node.get("merged_from") or []),
        created_at=node["created_at"],
        updated_at=node["updated_at"],
        # .get(), not [] -- both are absent on every node created before §0.21,
        # and that's a real, distinct "no judgment made yet" state, not missing data.
        boundary_kind=node.get("boundary_kind"),
        solves_question=node.get("solves_question"),
    )


def _record_to_abstraction(node) -> Abstraction:
    return Abstraction(
        id=node["id"],
        name=node["name"],
        description=node.get("description"),
        created_at=node["created_at"],
        updated_at=node["updated_at"],
    )


def _record_to_question(node) -> QuestionNode:
    return QuestionNode(
        id=node["id"],
        text=node["text"],
        dimension_id=node["dimension_id"],
        level=node["level"],
        rationale=node["rationale"],
        created_at=node["created_at"],
    )


def _record_to_claim(node) -> ClaimNode:
    return ClaimNode(
        id=node["id"],
        evidence=node["evidence"],
        reasoning=node["reasoning"],
        confidence=node["confidence"],
        source_title=node["source_title"],
        source_url=node["source_url"],
        source_type=node["source_type"],
        valid_from=node["valid_from"],
        superseded_by=node.get("superseded_by"),
    )


async def create_node(
    name: str, type_: str = "entity", description: Optional[str] = None, *, scope: Optional[str] = None
) -> GraphNode:
    """Create a canonical GraphNode (a domain or entity). See docs/Rules.md rule 12 —
    entities are canonical and deduplicated (via merge_entity), not created per-abstraction.

    `scope` (docs/Architecture.md §0.16): part of canonical IDENTITY, not
    descriptive metadata — a separate property from `description` on purpose,
    so identity is never encoded inside prose. See `find_or_create_entity`,
    the only caller that actually sets this today.
    """
    if type_ not in ("entity", "domain"):
        raise GraphInterfaceError(f"invalid node type: {type_!r} (expected 'entity' or 'domain')")
    node_id = str(uuid.uuid4())
    now = _now()
    query = (
        f"CREATE (n:{NODE_LABEL} {{id: $id, name: $name, type: $type, description: $description, "
        f"scope: $scope, merged_from: [], created_at: $created_at, updated_at: $updated_at}}) "
        "RETURN n"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query,
                id=node_id,
                name=name,
                type=type_,
                description=description,
                scope=scope,
                created_at=now,
                updated_at=now,
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError("create_node: insert did not return a node")
            return _record_to_node(record["n"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"create_node failed: {exc}") from exc


async def set_boundary_kind(
    entity_id: str, *, boundary_kind: str, solves_question: Optional[str] = None
) -> GraphNode:
    """docs/Architecture.md §0.21 -- records the agent's own explicit judgment
    that this node deserves to be understood as a named boundary (a "subject"
    or "entity", SystemDesign.md §4-6), separate from and in addition to
    whatever `decompose`/`answer` decision produced it. A plain `SET`, not a
    `MERGE` — the node must already exist (created via `find_or_create_entity`
    elsewhere in the same turn); this only ever updates an existing record.
    Idempotent: calling it again with the same values is a no-op in effect,
    matching every other write in this module.
    """
    if boundary_kind not in ("subject", "entity"):
        raise GraphInterfaceError(f"invalid boundary_kind: {boundary_kind!r} (expected 'subject' or 'entity')")
    query = (
        f"MATCH (n:{NODE_LABEL} {{id: $entity_id}}) "
        "SET n.boundary_kind = $boundary_kind, n.solves_question = $solves_question, n.updated_at = $now "
        "RETURN n"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query,
                entity_id=entity_id,
                boundary_kind=boundary_kind,
                solves_question=solves_question,
                now=_now(),
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(f"set_boundary_kind: no node with id {entity_id!r}")
            return _record_to_node(record["n"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"set_boundary_kind failed: {exc}") from exc


async def find_or_create_entity(
    name: str,
    type_: str = "entity",
    description: Optional[str] = None,
    *,
    scope_hint: Optional[str] = None,
) -> GraphNode:
    """Resolve `name` against existing canonical entities (case/whitespace-
    insensitive exact match) before creating a new one — the minimal form of
    docs/Rules.md rule 12's "entities are canonical, not duplicated" for entities
    an agent's own investigation discovers, as opposed to ones a human explicitly
    creates via `create_node`.

    This is deliberately NOT `merge_entity`: it only prevents creating an
    exact-name duplicate at the moment of discovery. It does not attempt fuzzy or
    semantic resolution (e.g. realizing "Google" and "Alphabet" are the same real
    entity) — that harder case is still `merge_entity`'s job, called explicitly
    once such a duplication is actually detected.

    `scope_hint` (docs/Architecture.md §0.9/§0.10/§0.16): disambiguating context
    for names that collide across domains ("Transmission" in an electric grid
    vs. in telecommunications). Matched against the dedicated `scope` property
    — identity is `(name, scope)`, not `name` alone, and `scope` is deliberately
    NOT the same property as `description` (§0.16: encoding identity inside
    prose makes canonical resolution fragile). Earlier revisions of this
    function reused `description` as a minimal Pass-3 testing mechanism
    (§0.14); any node created under that scheme has its scope sitting in
    `description` instead of `scope` and won't be found by this version —
    acceptable and not migrated, since every such node was disposable
    mechanism-verification test data, not real investigated content. When
    `scope_hint` is omitted, behavior is byte-for-byte the original
    global-name-only lookup, so no existing caller regresses.
    """
    if scope_hint:
        query = (
            f"MATCH (n:{NODE_LABEL}) WHERE toLower(trim(n.name)) = toLower(trim($name)) "
            "AND toLower(trim(coalesce(n.scope, ''))) = toLower(trim($scope_hint)) "
            "RETURN n LIMIT 1"
        )
        params = {"name": name, "scope_hint": scope_hint}
    else:
        query = (
            f"MATCH (n:{NODE_LABEL}) WHERE toLower(trim(n.name)) = toLower(trim($name)) "
            "RETURN n LIMIT 1"
        )
        params = {"name": name}
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, **params)
            record = await result.single()
            if record is not None:
                return _record_to_node(record["n"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"find_or_create_entity lookup failed: {exc}") from exc

    return await create_node(name, type_, description, scope=scope_hint)


# docs/Architecture.md §0.18: minimal, uncontroversial stopword filter -- not a
# scoring formula, just hygiene. Validated live: without it, a relationship-type
# string like "CONNECTS_TO" contributes the meaningless fragment "to" to a
# candidate's vocabulary, which can spuriously match unrelated context text and
# manufacture a false CONFLICT/tie. Not exhaustive by design -- extend only when
# a real observed case demands it, same discipline as `normalize_relationship_type`.
_RESOLVE_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "to", "of", "in", "on", "and",
    "or", "with", "this", "that", "it", "its", "by", "for", "as", "also", "while",
}


def _tokenize_for_resolution(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", text.lower()) if t and t not in _RESOLVE_STOPWORDS}


async def _find_all_candidates(name: str) -> list[GraphNode]:
    """Every existing node matching `name` (case/whitespace-insensitive), across
    ALL scopes -- the candidate search `find_or_create_entity` never does (it
    stops at the first match, or requires an exact scope match). This is the
    search step `resolve_entity` needs and the older function was never meant
    to provide.
    """
    query = f"MATCH (n:{NODE_LABEL}) WHERE toLower(trim(n.name)) = toLower(trim($name)) RETURN n"
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, name=name)
            return [_record_to_node(record["n"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"_find_all_candidates failed: {exc}") from exc


async def _candidate_vocab(node: GraphNode) -> set[str]:
    """A candidate's evidence vocabulary: its real graph neighborhood (outgoing
    relations' verb + target-entity words) plus its own `scope` string --
    validated live as necessary, not decorative (docs/Architecture.md §0.18's
    six-case matrix, case B: a bare domain-name reference resolved correctly
    ONLY because of the scope-string fold-in, with zero neighborhood overlap).
    """
    query = (
        f"MATCH (n:{NODE_LABEL} {{id: $id}})-[r:{RELATES_TO}]->(b:{NODE_LABEL}) "
        "RETURN r.relationship_type AS rel, b.name AS target"
    )
    words: set[str] = set()
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, id=node.id)
            async for record in result:
                words |= _tokenize_for_resolution(f"{record['rel']} {record['target']}")
    except Neo4jError as exc:
        raise GraphInterfaceError(f"_candidate_vocab failed: {exc}") from exc
    if node.scope:
        words |= _tokenize_for_resolution(node.scope)
    return words


async def resolve_entity(
    mention: str,
    context: str,
    *,
    scope_hint: Optional[str] = None,
) -> IdentityResolution:
    """docs/Architecture.md §0.18 — the frozen identity-resolution contract,
    validated against a 6-case evidence-type matrix (all 6 correct) before being
    built for real. Deterministic, zero LLM calls: candidate search over the
    existing Node model, then evidence scoring over each candidate's real graph
    neighborhood plus its own scope string. Four decisions:

    - 0 existing candidates -> `CREATE` (mints via `find_or_create_entity`,
      tagged with `scope_hint` if given — the same default `find_or_create_entity`
      already used, just reached through a decision that records *why*).
    - 1 existing candidate, no competitor -> `REUSE` it. Matches this project's
      standing preference for reuse over duplication when there's no competing
      alternative to weigh it against.
    - 2+ candidates, scored by token overlap between `context` (+ `scope_hint`,
      folded in as ordinary evidence, never as an override — docs/Architecture.md
      §0.18: "scope is evidence that may help resolve identity," not identity
      itself) and each candidate's vocabulary:
        - top score is 0 for everyone -> `AMBIGUOUS` (no evidence at all)
        - top score ties with the runner-up -> `CONFLICT` (real, competing evidence)
        - otherwise -> `REUSE` the clear winner

    `selected_node` is populated only for `REUSE`/`CREATE` — never for
    `AMBIGUOUS`/`CONFLICT`. Callers must not persist anything using an
    unresolved endpoint; a relation with an ambiguous/conflicting endpoint
    should be skipped, not forced.
    """
    candidates = await _find_all_candidates(mention)

    if not candidates:
        node = await find_or_create_entity(mention, scope_hint=scope_hint)
        return IdentityResolution(
            decision="CREATE",
            selected_node=node,
            candidates=[],
            reason="No existing candidate found.",
        )

    if len(candidates) == 1:
        node = candidates[0]
        return IdentityResolution(
            decision="REUSE",
            selected_node=node,
            candidates=[CandidateEvidence(node=node, matched_tokens=[], score=0)],
            reason="Single existing candidate, no competing alternative to weigh it against.",
        )

    context_tokens = _tokenize_for_resolution(f"{context} {scope_hint or ''}")
    evidence: list[CandidateEvidence] = []
    for node in candidates:
        vocab = await _candidate_vocab(node)
        matched = sorted(context_tokens & vocab)
        evidence.append(CandidateEvidence(node=node, matched_tokens=matched, score=len(matched)))
    evidence.sort(key=lambda e: e.score, reverse=True)
    top, runner_up = evidence[0], evidence[1]

    if top.score == 0:
        return IdentityResolution(
            decision="AMBIGUOUS",
            selected_node=None,
            candidates=evidence,
            reason="No candidate has any matching evidence.",
        )
    if top.score == runner_up.score:
        return IdentityResolution(
            decision="CONFLICT",
            selected_node=None,
            candidates=evidence,
            reason=f"Multiple candidates have comparable evidence ({top.score} matched tokens each).",
        )
    return IdentityResolution(
        decision="REUSE",
        selected_node=top.node,
        candidates=evidence,
        reason=f"Matched: {', '.join(top.matched_tokens)}",
    )


async def get_node(node_id: str) -> GraphNode:
    query = f"MATCH (n:{NODE_LABEL} {{id: $id}}) RETURN n"
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, id=node_id)
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(f"get_node: no node with id {node_id!r}")
            return _record_to_node(record["n"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_node failed: {exc}") from exc


async def create_relationship(
    source_id: str,
    target_id: str,
    relationship_type: str,
    properties: Optional[dict] = None,
) -> Relationship:
    properties = properties or {}
    query = (
        f"MATCH (a:{NODE_LABEL} {{id: $source_id}}), (b:{NODE_LABEL} {{id: $target_id}}) "
        f"MERGE (a)-[r:{RELATES_TO} {{relationship_type: $relationship_type}}]->(b) "
        "SET r += $properties "
        "RETURN a.id AS source_id, b.id AS target_id, "
        "r.relationship_type AS relationship_type, properties(r) AS properties"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query,
                source_id=source_id,
                target_id=target_id,
                relationship_type=relationship_type,
                properties=properties,
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(
                    f"create_relationship: source {source_id!r} or target {target_id!r} not found"
                )
            props = dict(record["properties"])
            props.pop("relationship_type", None)
            return Relationship(
                source_id=record["source_id"],
                target_id=record["target_id"],
                relationship_type=record["relationship_type"],
                properties=props,
            )
    except Neo4jError as exc:
        raise GraphInterfaceError(f"create_relationship failed: {exc}") from exc


async def attach_relation_claim(
    source_id: str,
    target_id: str,
    relationship_type: str,
    *,
    claim_id: str,
    evidence: str,
    reasoning: str,
    confidence: float,
    source_title: str,
    source_url: str,
    source_type: str,
    valid_from: str,
    stance: str = "supports",
) -> ClaimNode:
    """docs/Architecture.md §0.26: evidence for a RELATION identity --
    (source_id, relationship_type, target_id), not confidence/wording/evidence
    itself, which are properties OF that identity, not part of it (already
    true today: `create_relationship`'s own MERGE key is exactly this triple,
    confirmed by reading it rather than assumed — re-discovering the same
    relation already reuses the same edge, it just previously discarded
    whatever evidence justified it).

    Deliberately additive: the native RELATES_TO edge this is evidence FOR is
    never touched here, so every existing traversal (get_decomposition,
    get_neighbors, zoom_in, §0.22/§0.24's box/space rendering) keeps working
    unchanged. Reuses the exact Claim node shape already used for Questions
    (`attach_claim`) rather than inventing a parallel evidence structure --
    only the connecting edge differs. `stance` ("supports" or "contradicts")
    lets a later, disconfirming discovery attach as competing evidence under
    the SAME relation identity instead of fragmenting into a new edge --
    §0.26's "contradictions become evidence, not new topology" test.
    """
    query = (
        f"MATCH (a:{NODE_LABEL} {{id: $source_id}}), (b:{NODE_LABEL} {{id: $target_id}}) "
        f"MERGE (c:{CLAIM_LABEL} {{id: $claim_id}}) "
        "ON CREATE SET c.evidence=$evidence, c.reasoning=$reasoning, c.confidence=$confidence, "
        "c.source_title=$source_title, c.source_url=$source_url, c.source_type=$source_type, "
        "c.valid_from=$valid_from "
        f"MERGE (a)-[r:{HAS_RELATION_CLAIM} "
        "{relationship_type: $relationship_type, target_id: $target_id, stance: $stance}]->(c) "
        "RETURN c"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query,
                source_id=source_id,
                target_id=target_id,
                relationship_type=relationship_type,
                claim_id=claim_id,
                evidence=evidence,
                reasoning=reasoning,
                confidence=confidence,
                source_title=source_title,
                source_url=source_url,
                source_type=source_type,
                valid_from=valid_from,
                stance=stance,
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(
                    f"attach_relation_claim: source {source_id!r} or target {target_id!r} not found"
                )
            return _record_to_claim(record["c"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"attach_relation_claim failed: {exc}") from exc


async def get_relation_claims(source_id: str, target_id: str, relationship_type: str) -> list[tuple[str, ClaimNode]]:
    """All evidence attached to one relation identity, each paired with its
    stance -- the accumulation §0.26 exists for: five independent discoveries
    of the same (source, type, target) return five entries here, not five
    edges in the graph.
    """
    query = (
        f"MATCH (a:{NODE_LABEL} {{id: $source_id}})"
        f"-[r:{HAS_RELATION_CLAIM} {{relationship_type: $relationship_type, target_id: $target_id}}]->"
        f"(c:{CLAIM_LABEL}) "
        "RETURN c, r.stance AS stance"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query, source_id=source_id, target_id=target_id, relationship_type=relationship_type
            )
            return [(record["stance"], _record_to_claim(record["c"])) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_relation_claims failed: {exc}") from exc


async def get_relation_confidence(source_id: str, target_id: str, relationship_type: str) -> dict:
    """A simple, honest heuristic, not a rigorous Bayesian update (§0.26 names
    this explicitly as a deliberate simplification): confidence rises with
    each supporting claim and falls with each contradicting one, clamped to
    [0.05, 0.95] so accumulated evidence is never treated as absolute
    certainty OR absolute impossibility. Returns zero-claim defaults rather
    than raising when nothing has been attached yet -- "no evidence" is a
    normal, common state for most relations today, not an error.
    """
    claims = await get_relation_claims(source_id, target_id, relationship_type)
    supports = sum(1 for stance, _ in claims if stance == "supports")
    contradicts = sum(1 for stance, _ in claims if stance == "contradicts")
    confidence = 0.5 + 0.15 * supports - 0.25 * contradicts
    confidence = max(0.05, min(0.95, confidence))
    return {
        "claim_count": len(claims),
        "supports": supports,
        "contradicts": contradicts,
        "confidence": confidence if claims else None,
    }


async def get_neighbors(node_id: str, relationship_type: Optional[str] = None) -> list[GraphNode]:
    if relationship_type:
        query = (
            f"MATCH (a:{NODE_LABEL} {{id: $node_id}})"
            f"-[:{RELATES_TO} {{relationship_type: $relationship_type}}]-(b:{NODE_LABEL}) "
            "RETURN DISTINCT b"
        )
        params = {"node_id": node_id, "relationship_type": relationship_type}
    else:
        query = f"MATCH (a:{NODE_LABEL} {{id: $node_id}})-[:{RELATES_TO}]-(b:{NODE_LABEL}) RETURN DISTINCT b"
        params = {"node_id": node_id}
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, **params)
            return [_record_to_node(record["b"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_neighbors failed: {exc}") from exc


async def create_abstraction(name: str, description: Optional[str] = None) -> Abstraction:
    """Create a named boundary/view over the graph. Cheap and revisable, not a permanent
    structural commitment — see docs/Architecture.md §0."""
    abstraction_id = str(uuid.uuid4())
    now = _now()
    query = (
        f"CREATE (a:{ABSTRACTION_LABEL} {{id: $id, name: $name, description: $description, "
        f"created_at: $created_at, updated_at: $updated_at}}) "
        "RETURN a"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query, id=abstraction_id, name=name, description=description, created_at=now, updated_at=now
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError("create_abstraction: insert did not return a node")
            return _record_to_abstraction(record["a"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"create_abstraction failed: {exc}") from exc


async def attach_entity(node_id: str, abstraction_id: str) -> None:
    """Attach a canonical node to an abstraction's boundary.

    Many-to-many by construction (MERGE on the MEMBER_OF edge) — a node may belong to
    multiple abstractions simultaneously. This is the non-strict-hierarchy guarantee
    required by docs/Rules.md rule 13; do not replace this with a single `parent_id`
    property on GraphNode.
    """
    query = (
        f"MATCH (n:{NODE_LABEL} {{id: $node_id}}), (a:{ABSTRACTION_LABEL} {{id: $abstraction_id}}) "
        f"MERGE (n)-[:{MEMBER_OF}]->(a) "
        "RETURN n.id AS node_id, a.id AS abstraction_id"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, node_id=node_id, abstraction_id=abstraction_id)
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(
                    f"attach_entity: node {node_id!r} or abstraction {abstraction_id!r} not found"
                )
    except Neo4jError as exc:
        raise GraphInterfaceError(f"attach_entity failed: {exc}") from exc


async def expand_abstraction(abstraction_id: str, node_ids: list[str]) -> None:
    """Widen an abstraction's boundary to include more existing canonical nodes.
    Never creates nodes — only membership edges. See docs/Architecture.md §2 (Abstraction Manager)."""
    for node_id in node_ids:
        await attach_entity(node_id, abstraction_id)


async def contract_abstraction(abstraction_id: str, node_ids: list[str]) -> None:
    """Narrow an abstraction's boundary by dropping membership edges. Never deletes the
    underlying canonical node — it may still belong to other abstractions."""
    query = (
        f"MATCH (n:{NODE_LABEL})-[r:{MEMBER_OF}]->(a:{ABSTRACTION_LABEL} {{id: $abstraction_id}}) "
        "WHERE n.id IN $node_ids "
        "DELETE r"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            await session.run(query, abstraction_id=abstraction_id, node_ids=node_ids)
    except Neo4jError as exc:
        raise GraphInterfaceError(f"contract_abstraction failed: {exc}") from exc


async def get_subgraph(abstraction_id: str) -> Subgraph:
    """Return every node MEMBER_OF this abstraction, plus RELATES_TO edges between them."""
    abstraction_query = f"MATCH (a:{ABSTRACTION_LABEL} {{id: $abstraction_id}}) RETURN a"
    node_query = f"MATCH (n:{NODE_LABEL})-[:{MEMBER_OF}]->(a:{ABSTRACTION_LABEL} {{id: $abstraction_id}}) RETURN n"
    rel_query = (
        f"MATCH (n1:{NODE_LABEL})-[:{MEMBER_OF}]->(a:{ABSTRACTION_LABEL} {{id: $abstraction_id}}) "
        f"MATCH (n2:{NODE_LABEL})-[:{MEMBER_OF}]->(a) "
        f"MATCH (n1)-[r:{RELATES_TO}]->(n2) "
        "RETURN n1.id AS source_id, n2.id AS target_id, "
        "r.relationship_type AS relationship_type, properties(r) AS properties"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            abs_result = await session.run(abstraction_query, abstraction_id=abstraction_id)
            abs_record = await abs_result.single()
            if abs_record is None:
                raise GraphInterfaceError(f"get_subgraph: no abstraction with id {abstraction_id!r}")
            abstraction = _record_to_abstraction(abs_record["a"])

            node_result = await session.run(node_query, abstraction_id=abstraction_id)
            nodes = [_record_to_node(record["n"]) async for record in node_result]

            rel_result = await session.run(rel_query, abstraction_id=abstraction_id)
            relationships: list[Relationship] = []
            async for record in rel_result:
                props = dict(record["properties"])
                props.pop("relationship_type", None)
                relationships.append(
                    Relationship(
                        source_id=record["source_id"],
                        target_id=record["target_id"],
                        relationship_type=record["relationship_type"],
                        properties=props,
                    )
                )
            return Subgraph(abstraction=abstraction, nodes=nodes, relationships=relationships)
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_subgraph failed: {exc}") from exc


async def get_abstractions_for_node(node_id: str) -> list[Abstraction]:
    """Read-only helper: every abstraction a node currently belongs to. Supports the
    non-strict-hierarchy verification in docs/Phases.md Phase 1."""
    query = f"MATCH (n:{NODE_LABEL} {{id: $node_id}})-[:{MEMBER_OF}]->(a:{ABSTRACTION_LABEL}) RETURN a"
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, node_id=node_id)
            return [_record_to_abstraction(record["a"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_abstractions_for_node failed: {exc}") from exc


async def merge_entity(keep_id: str, merge_id: str) -> GraphNode:
    """Merge `merge_id` into `keep_id`: rewrite its relationships, abstraction
    memberships, and attached questions onto `keep_id`, record provenance in
    `keep_id.merged_from`, delete `merge_id`. Implements the canonical-entity rule
    (docs/Rules.md rule 12) — call this instead of creating a duplicate node for a
    re-discovered real-world entity.
    """
    if keep_id == merge_id:
        raise GraphInterfaceError("merge_entity: keep_id and merge_id must differ")

    async def _tx(tx):
        check = await tx.run(
            f"MATCH (keep:{NODE_LABEL} {{id: $keep_id}}), (merge:{NODE_LABEL} {{id: $merge_id}}) "
            "RETURN keep.id AS keep_id",
            keep_id=keep_id,
            merge_id=merge_id,
        )
        if await check.single() is None:
            raise GraphInterfaceError(f"merge_entity: node {keep_id!r} or {merge_id!r} not found")

        await tx.run(
            f"MATCH (merge:{NODE_LABEL} {{id: $merge_id}})-[r:{RELATES_TO}]->(other) "
            f"MATCH (keep:{NODE_LABEL} {{id: $keep_id}}) "
            f"MERGE (keep)-[r2:{RELATES_TO} {{relationship_type: r.relationship_type}}]->(other) "
            "SET r2 += properties(r)",
            keep_id=keep_id,
            merge_id=merge_id,
        )
        await tx.run(
            f"MATCH (other)-[r:{RELATES_TO}]->(merge:{NODE_LABEL} {{id: $merge_id}}) "
            f"MATCH (keep:{NODE_LABEL} {{id: $keep_id}}) "
            f"MERGE (other)-[r2:{RELATES_TO} {{relationship_type: r.relationship_type}}]->(keep) "
            "SET r2 += properties(r)",
            keep_id=keep_id,
            merge_id=merge_id,
        )
        await tx.run(
            f"MATCH (merge:{NODE_LABEL} {{id: $merge_id}})-[:{MEMBER_OF}]->(a:{ABSTRACTION_LABEL}) "
            f"MATCH (keep:{NODE_LABEL} {{id: $keep_id}}) "
            f"MERGE (keep)-[:{MEMBER_OF}]->(a)",
            keep_id=keep_id,
            merge_id=merge_id,
        )
        # Added post-Phase-5: HAS_QUESTION didn't exist when merge_entity was
        # first written (Phase 1). Without this, DETACH DELETE below would
        # silently sever the merged node's attached questions instead of
        # transferring them — the Question nodes would survive but become
        # unreachable from any entity. Found by actually exercising merge_entity
        # against real duplicate entities with attached questions for the first
        # time (see Memory.md).
        await tx.run(
            f"MATCH (merge:{NODE_LABEL} {{id: $merge_id}})-[:{HAS_QUESTION}]->(q:{QUESTION_LABEL}) "
            f"MATCH (keep:{NODE_LABEL} {{id: $keep_id}}) "
            f"MERGE (keep)-[:{HAS_QUESTION}]->(q)",
            keep_id=keep_id,
            merge_id=merge_id,
        )
        result = await tx.run(
            f"MATCH (keep:{NODE_LABEL} {{id: $keep_id}}), (merge:{NODE_LABEL} {{id: $merge_id}}) "
            "SET keep.merged_from = keep.merged_from + [merge.id] + merge.merged_from, "
            "keep.updated_at = $now "
            "WITH keep, merge "
            "DETACH DELETE merge "
            "RETURN keep",
            keep_id=keep_id,
            merge_id=merge_id,
            now=_now(),
        )
        record = await result.single()
        return record["keep"]

    try:
        driver = get_driver()
        async with driver.session() as session:
            keep_node = await session.execute_write(_tx)
            return _record_to_node(keep_node)
    except Neo4jError as exc:
        raise GraphInterfaceError(f"merge_entity failed: {exc}") from exc


async def attach_question(
    entity_id: str,
    *,
    question_id: str,
    text: str,
    dimension_id: str,
    level: str,
    rationale: str,
) -> QuestionNode:
    """Create (or reuse) a Question node and attach it to an existing canonical
    entity/domain via HAS_QUESTION (docs/Phases.md Phase 5). MERGEs on
    `question_id` (the same id backend.questions.Question already generates) so
    re-attaching the same Question — e.g. a Ground Agent resuming, docs/Rules.md
    rule 7 — never creates a duplicate node.
    """
    now = _now()
    query = (
        f"MATCH (n:{NODE_LABEL} {{id: $entity_id}}) "
        f"MERGE (q:{QUESTION_LABEL} {{id: $question_id}}) "
        "ON CREATE SET q.text=$text, q.dimension_id=$dimension_id, q.level=$level, "
        "q.rationale=$rationale, q.created_at=$now "
        f"MERGE (n)-[:{HAS_QUESTION}]->(q) "
        "RETURN q"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query,
                entity_id=entity_id,
                question_id=question_id,
                text=text,
                dimension_id=dimension_id,
                level=level,
                rationale=rationale,
                now=now,
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(f"attach_question: entity {entity_id!r} not found")
            return _record_to_question(record["q"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"attach_question failed: {exc}") from exc


async def attach_claim(
    question_id: str,
    *,
    claim_id: str,
    evidence: str,
    reasoning: str,
    confidence: float,
    source_title: str,
    source_url: str,
    source_type: str,
    valid_from: str,
) -> ClaimNode:
    """Create a Claim node answering an existing Question, via ANSWERED_BY
    (docs/Phases.md Phase 5). Multiple claims may answer the same Question —
    different sources, or re-investigation over time — this function doesn't
    dedupe or pick a winner between them; surfacing contradictions rather than
    silently overwriting is Phase 7's job (Rules.md's conflict-resolution rule).
    """
    query = (
        f"MATCH (q:{QUESTION_LABEL} {{id: $question_id}}) "
        f"MERGE (c:{CLAIM_LABEL} {{id: $claim_id}}) "
        "ON CREATE SET c.evidence=$evidence, c.reasoning=$reasoning, c.confidence=$confidence, "
        "c.source_title=$source_title, c.source_url=$source_url, c.source_type=$source_type, "
        "c.valid_from=$valid_from "
        f"MERGE (q)-[:{ANSWERED_BY}]->(c) "
        "RETURN c"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(
                query,
                question_id=question_id,
                claim_id=claim_id,
                evidence=evidence,
                reasoning=reasoning,
                confidence=confidence,
                source_title=source_title,
                source_url=source_url,
                source_type=source_type,
                valid_from=valid_from,
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(f"attach_claim: question {question_id!r} not found")
            return _record_to_claim(record["c"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"attach_claim failed: {exc}") from exc


async def get_claims_for_question(question_id: str) -> list[ClaimNode]:
    """Read-only helper: every Claim currently answering a Question, including
    superseded ones (their `superseded_by` property marks them non-current without
    deleting them — the temporal history stays queryable)."""
    query = f"MATCH (q:{QUESTION_LABEL} {{id: $question_id}})-[:{ANSWERED_BY}]->(c:{CLAIM_LABEL}) RETURN c"
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, question_id=question_id)
            return [_record_to_claim(record["c"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_claims_for_question failed: {exc}") from exc


async def supersede_claim(new_claim_id: str, old_claim_id: str) -> None:
    """Temporal edge (Graphiti-inspired valid-time/superseded pattern,
    docs/Phases.md Phase 5): record that `new_claim_id` supersedes `old_claim_id`
    rather than deleting the old one — the old claim stays in the graph as history,
    just marked non-current via `superseded_by`.
    """
    query = (
        f"MATCH (new:{CLAIM_LABEL} {{id: $new_claim_id}}), (old:{CLAIM_LABEL} {{id: $old_claim_id}}) "
        f"MERGE (new)-[:{SUPERSEDES}]->(old) "
        "SET old.superseded_by = $new_claim_id "
        "RETURN old, new"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, new_claim_id=new_claim_id, old_claim_id=old_claim_id)
            record = await result.single()
            if record is None:
                raise GraphInterfaceError(
                    f"supersede_claim: claim {new_claim_id!r} or {old_claim_id!r} not found"
                )
    except Neo4jError as exc:
        raise GraphInterfaceError(f"supersede_claim failed: {exc}") from exc


_SUB_QUESTION_PREFIX = "Sub-question of: "


def _parse_parent_question_text(rationale: str) -> Optional[str]:
    """Best-effort text parse, not a graph traversal — see QuestionProvenance's
    docstring for why there's no queryable parent-question edge yet."""
    if rationale.startswith(_SUB_QUESTION_PREFIX):
        return rationale[len(_SUB_QUESTION_PREFIX) :]
    return None


async def get_questions_for_entity(entity_id: str) -> list[QuestionNode]:
    """Read-only: every Question currently attached to this entity via
    HAS_QUESTION. The read-side analog of `get_claims_for_question`, needed by
    `explain_entity` below.
    """
    query = f"MATCH (n:{NODE_LABEL} {{id: $entity_id}})-[:{HAS_QUESTION}]->(q:{QUESTION_LABEL}) RETURN q"
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, entity_id=entity_id)
            return [_record_to_question(record["q"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_questions_for_entity failed: {exc}") from exc


async def explain_entity(entity_id: str) -> EntityExplanation:
    """Read-only provenance trace (docs/Phases.md Phase 6's deferred "why am I
    seeing this" concept — first concrete step, built directly on data already
    persisted, no new graph property added). Raises `GraphInterfaceError` if
    `entity_id` doesn't exist (via `get_node`'s own check — consistent with every
    other Graph Interface function's behavior for a missing id, e.g.
    `attach_question`/`attach_entity`). An entity that exists but has no attached
    questions returns an `EntityExplanation` with an empty `discovered_by` — a
    real, distinct state from "entity not found."
    """
    entity = await get_node(entity_id)
    questions = await get_questions_for_entity(entity_id)
    discovered_by = [
        QuestionProvenance(
            question_id=q.id,
            question_text=q.text,
            rationale=q.rationale,
            parent_question_text=_parse_parent_question_text(q.rationale),
        )
        for q in questions
    ]
    return EntityExplanation(entity=entity, discovered_by=discovered_by)


async def get_decomposition(entity_id: str) -> list[GraphNode]:
    """The existing CHILDREN of an entity — the already-discovered substructure
    a "zoom in" would reveal. Pure read; exposes only what's already in the
    graph, never infers or invents structure. Raises `GraphInterfaceError` if
    `entity_id` doesn't exist (via `get_node`'s check).

    Deliberately does NOT delegate to `get_neighbors` (found live, hackathon-day —
    docs/Memory.md): `get_neighbors`'s `RELATES_TO` match is directionless, which
    is correct for symmetric relationship types but wrong for parent->child
    discovery edges. Calling `zoom_in` on a CHILD entity that itself has a parent
    previously returned that parent as if it were one of the child's own children
    (a confusing, circular edge in the UI). This query follows OUTWARD edges only,
    in the direction they were actually written by `_investigate_loop`.

    Matches ANY relationship_type, not just "decomposes_into" (docs/Architecture.md
    §0.17): a child discovered via a "routes_to"/"delegates_to"/etc. relationship
    is still a real, navigable child — filtering to one literal type here would
    make every non-default relationship_type silently invisible to zoom_in and
    the live graph sync, reproducing the "no further sub-components yet" bug for
    a new reason instead of fixing it.
    """
    await get_node(entity_id)
    query = (
        f"MATCH (a:{NODE_LABEL} {{id: $entity_id}})"
        f"-[:{RELATES_TO}]->(b:{NODE_LABEL}) "
        "RETURN DISTINCT b"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, entity_id=entity_id)
            return [_record_to_node(record["b"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_decomposition failed: {exc}") from exc


async def get_decomposition_typed(entity_id: str) -> list[tuple[str, GraphNode]]:
    """Same outward-edge query as `get_decomposition`, but also returns each
    edge's real `relationship_type` property instead of dropping it. Added for
    `_sync_decomposition` (backend/api/app.py) -- the session's in-memory graph
    mirror was hardcoding every edge label to "decomposes_into" regardless of
    what was actually stored, which silently hid every §0.17/§0.18/§0.22 typed
    relationship (routes_to, forwards_funds_to, ...) from the live chat UI even
    though Neo4j had them correct all along. `get_decomposition` itself is left
    unchanged since its other callers (zoom_in, explain_entity, /node_detail)
    only need the node, not the edge label.
    """
    await get_node(entity_id)
    query = (
        f"MATCH (a:{NODE_LABEL} {{id: $entity_id}})"
        f"-[r:{RELATES_TO}]->(b:{NODE_LABEL}) "
        "RETURN DISTINCT b, r.relationship_type AS relationship_type"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, entity_id=entity_id)
            return [
                (record["relationship_type"] or "decomposes_into", _record_to_node(record["b"]))
                async for record in result
            ]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_decomposition_typed failed: {exc}") from exc


async def _find_abstraction_by_name(name: str) -> Optional[Abstraction]:
    query = (
        f"MATCH (a:{ABSTRACTION_LABEL}) WHERE toLower(trim(a.name)) = toLower(trim($name)) "
        "RETURN a LIMIT 1"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, name=name)
            record = await result.single()
            return _record_to_abstraction(record["a"]) if record is not None else None
    except Neo4jError as exc:
        raise GraphInterfaceError(f"_find_abstraction_by_name lookup failed: {exc}") from exc


async def zoom_in(entity_id: str) -> Optional[Abstraction]:
    """Materialize an Abstraction view over an entity's already-discovered
    decomposition (docs/Phases.md Phase 6's deferred "active abstraction" concept
    — first concrete step). Deliberately exposes only what `get_decomposition`
    already contains — never invents structure that isn't already in the graph.

    An entity with no discovered decomposition returns `None`, not a manufactured
    empty Abstraction — callers can tell "nothing discovered here yet" apart from
    "zoomed in, but genuinely empty."

    Idempotent by entity name (docs/Rules.md rule 12's canonical-not-duplicated
    spirit, applied to Abstractions the same way `find_or_create_entity` applies
    it to entities): zooming into the same entity twice reuses the same
    Abstraction rather than creating a duplicate on every call. Exact-name match
    only, same limitation as `find_or_create_entity`.
    """
    entity = await get_node(entity_id)
    children = await get_decomposition(entity_id)
    if not children:
        return None

    abstraction = await _find_abstraction_by_name(entity.name)
    if abstraction is None:
        abstraction = await create_abstraction(
            entity.name,
            description=f"Zoomed-in view of {entity.name!r}'s discovered decomposition",
        )
    for child in children:
        await attach_entity(child.id, abstraction.id)
    return abstraction
