from __future__ import annotations

import os
from pathlib import Path

import aiosqlite

from .exceptions import StateStoreError

# Overridable so scripts/verify_phase3.py can point at a throwaway DB per run, and
# the VM deployment can point at a persistent path outside the repo checkout.
DEFAULT_DB_PATH = os.environ.get(
    "AGENT_STATE_DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "agent_state.sqlite3")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


async def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the state table if it doesn't exist yet. Safe to call repeatedly —
    this is what makes the store usable both for a fresh run and for a "process
    restarted" resume (docs/Phases.md Phase 3 verification) without any special
    first-run setup step.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(_SCHEMA)
            await db.commit()
    except aiosqlite.Error as exc:
        raise StateStoreError(f"init_db failed for {db_path}: {exc}") from exc


async def save_state(agent_id: str, state_json: str, updated_at: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Upsert an agent's serialized state. Called at every state transition
    (docs/Rules.md rule 7 — persisted, not held only in memory) so a process kill at
    any point leaves the last-committed transition recoverable, never a half-written
    one (SQLite's own transaction commit is the atomicity boundary here).
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO agent_state (agent_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (agent_id, state_json, updated_at),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        raise StateStoreError(f"save_state failed for agent {agent_id}: {exc}") from exc


async def load_state(agent_id: str, db_path: str = DEFAULT_DB_PATH) -> str | None:
    """Return the raw serialized state for `agent_id`, or None if it has never been
    checkpointed. None is the signal callers use to distinguish "fresh agent" from
    "resuming agent" — it is not an error.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT state_json FROM agent_state WHERE agent_id = ?", (agent_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
    except aiosqlite.Error as exc:
        raise StateStoreError(f"load_state failed for agent {agent_id}: {exc}") from exc
