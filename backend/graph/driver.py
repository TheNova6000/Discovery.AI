from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from neo4j import AsyncDriver, AsyncGraphDatabase

from .schema import ABSTRACTION_LABEL, CLAIM_LABEL, NODE_LABEL, QUESTION_LABEL

load_dotenv()

_driver: Optional[AsyncDriver] = None


def get_driver() -> AsyncDriver:
    """Lazily create the process-wide async Neo4j driver from env vars (see .env.example)."""
    global _driver
    if _driver is None:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "changeme-local-dev")
        _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    return _driver


async def close_driver() -> None:
    """Close and clear the driver. Call once at process shutdown."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def ensure_constraints() -> None:
    """Create uniqueness constraints on node/abstraction ids. Idempotent — safe to call on every startup."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            f"CREATE CONSTRAINT graphnode_id_unique IF NOT EXISTS "
            f"FOR (n:{NODE_LABEL}) REQUIRE n.id IS UNIQUE"
        )
        await session.run(
            f"CREATE CONSTRAINT abstraction_id_unique IF NOT EXISTS "
            f"FOR (a:{ABSTRACTION_LABEL}) REQUIRE a.id IS UNIQUE"
        )
        await session.run(
            f"CREATE CONSTRAINT question_id_unique IF NOT EXISTS "
            f"FOR (q:{QUESTION_LABEL}) REQUIRE q.id IS UNIQUE"
        )
        await session.run(
            f"CREATE CONSTRAINT claim_id_unique IF NOT EXISTS "
            f"FOR (c:{CLAIM_LABEL}) REQUIRE c.id IS UNIQUE"
        )
