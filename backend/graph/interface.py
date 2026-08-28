from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j.exceptions import Neo4jError

from .driver import get_driver
from .exceptions import GraphInterfaceError
from .models import (
    Abstraction,
    ClaimNode,
    EntityExplanation,
    GraphNode,
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
        merged_from=list(node.get("merged_from") or []),
        created_at=node["created_at"],
        updated_at=node["updated_at"],
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


async def create_node(name: str, type_: str = "entity", description: Optional[str] = None) -> GraphNode:
    """Create a canonical GraphNode (a domain or entity). See docs/Rules.md rule 12 —
    entities are canonical and deduplicated (via merge_entity), not created per-abstraction."""
    if type_ not in ("entity", "domain"):
        raise GraphInterfaceError(f"invalid node type: {type_!r} (expected 'entity' or 'domain')")
    node_id = str(uuid.uuid4())
    now = _now()
    query = (
        f"CREATE (n:{NODE_LABEL} {{id: $id, name: $name, type: $type, description: $description, "
        f"merged_from: [], created_at: $created_at, updated_at: $updated_at}}) "
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
                created_at=now,
                updated_at=now,
            )
            record = await result.single()
            if record is None:
                raise GraphInterfaceError("create_node: insert did not return a node")
            return _record_to_node(record["n"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"create_node failed: {exc}") from exc


async def find_or_create_entity(name: str, type_: str = "entity", description: Optional[str] = None) -> GraphNode:
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
    """
    query = (
        f"MATCH (n:{NODE_LABEL}) WHERE toLower(trim(n.name)) = toLower(trim($name)) "
        "RETURN n LIMIT 1"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, name=name)
            record = await result.single()
            if record is not None:
                return _record_to_node(record["n"])
    except Neo4jError as exc:
        raise GraphInterfaceError(f"find_or_create_entity lookup failed: {exc}") from exc

    return await create_node(name, type_, description)


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
    """The existing `decomposes_into` CHILDREN of an entity — the already-
    discovered substructure a "zoom in" would reveal. Pure read; exposes only
    what's already in the graph, never infers or invents structure. Raises
    `GraphInterfaceError` if `entity_id` doesn't exist (via `get_node`'s check).

    Deliberately does NOT delegate to `get_neighbors` (found live, hackathon-day —
    docs/Memory.md): `get_neighbors`'s `RELATES_TO` match is directionless, which
    is correct for symmetric relationship types but wrong for "decomposes_into"
    specifically, which is inherently parent->child. Calling `zoom_in` on a CHILD
    entity that itself has a parent previously returned that parent as if it were
    one of the child's own children (a confusing, circular edge in the UI). This
    query follows the `decomposes_into` edge outward only, in the direction it was
    actually written by `_investigate_loop`.
    """
    await get_node(entity_id)
    query = (
        f"MATCH (a:{NODE_LABEL} {{id: $entity_id}})"
        f"-[:{RELATES_TO} {{relationship_type: 'decomposes_into'}}]->(b:{NODE_LABEL}) "
        "RETURN DISTINCT b"
    )
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, entity_id=entity_id)
            return [_record_to_node(record["b"]) async for record in result]
    except Neo4jError as exc:
        raise GraphInterfaceError(f"get_decomposition failed: {exc}") from exc


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
