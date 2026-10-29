"""Chat sessions persist (SQLite) so a conversation survives a restart."""

from __future__ import annotations

from backend.paths import REPO_ROOT

import os
from pathlib import Path
from typing import Optional

import aiosqlite

from backend.main_block.interface import utcnow

from .models import ChatSession

DEFAULT_PATH = REPO_ROOT / "tunin_chat.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SessionStore:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = str(path or os.environ.get("TUNIN_CHAT_DB_PATH") or DEFAULT_PATH)

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self.path)
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(_SCHEMA)
        return db

    async def save(self, session: ChatSession) -> None:
        session.updated_at = utcnow()
        db = await self._connect()
        try:
            await db.execute(
                "INSERT INTO chat_sessions (session_id, owner_id, payload, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (session.session_id, session.owner_id, session.model_dump_json(), session.updated_at),
            )
            await db.commit()
        finally:
            await db.close()

    async def get(self, session_id: str, owner_id: str) -> Optional[ChatSession]:
        db = await self._connect()
        try:
            row = await (await db.execute(
                "SELECT payload FROM chat_sessions WHERE session_id=? AND owner_id=?", (session_id, owner_id)
            )).fetchone()
        finally:
            await db.close()
        return ChatSession.model_validate_json(row[0]) if row else None
