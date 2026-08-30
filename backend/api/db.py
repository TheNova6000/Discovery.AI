from __future__ import annotations

import os
from typing import Optional

import asyncpg

# Postgres connection string (Supabase's own database — Project Settings ->
# Database -> Connection string). Unset means every session lives only in this
# process's memory, exactly as before (backend/api/session.py's original
# scope) — so local/VM dev needs nothing extra. Set on a real deployment so
# sessions survive Render's free-tier spin-down and ordinary redeploys, which
# otherwise wipe the in-memory store on every cold start.
DATABASE_URL = os.environ.get("DATABASE_URL")

_pool: Optional[asyncpg.Pool] = None

_SCHEMA = """
create table if not exists sessions (
    session_id text primary key,
    user_id text not null,
    title text not null default 'New session',
    created_at timestamptz not null default now(),
    current_entity text,
    current_abstraction text,
    current_dimension_name text,
    current_dimension_description text,
    known_entities jsonb not null default '[]'::jsonb,
    nodes jsonb not null default '[]'::jsonb,
    edges jsonb not null default '[]'::jsonb,
    messages jsonb not null default '[]'::jsonb,
    pending_action jsonb,
    current_space text,
    space_history jsonb not null default '[]'::jsonb,
    current_projection text
);
create index if not exists idx_sessions_user on sessions (user_id, created_at desc);
-- docs/Architecture.md §0.20: additive migration for databases that already had
-- this table before pending_action existed -- CREATE TABLE IF NOT EXISTS above
-- has no effect on an already-existing table, so an already-provisioned
-- deployment (e.g. Render) needs this to actually get the new column.
alter table sessions add column if not exists pending_action jsonb;
-- docs/Architecture.md §0.24: Focus vs. Enter Space -- same additive-migration
-- reasoning as pending_action above.
alter table sessions add column if not exists current_space text;
alter table sessions add column if not exists space_history jsonb not null default '[]'::jsonb;
-- docs/Architecture.md §0.27: same additive-migration reasoning.
alter table sessions add column if not exists current_projection text;

-- Per-user, bring-your-own LLM provider keys, so one user's investigations are
-- never blocked by another user (or the shared server pool) hitting a rate
-- limit or an invalid/rotated key -- exactly the failure just hit live on the
-- server's own shared keys. Never returned to the client in plaintext after
-- being saved (see GET /settings in app.py) -- only whether each is set.
create table if not exists user_api_keys (
    user_id text primary key,
    groq_api_key text,
    gemini_api_key text,
    cerebras_api_key text,
    cohere_api_key text,
    updated_at timestamptz not null default now()
);
"""


async def init_pool() -> None:
    """Called once on FastAPI startup. A no-op when DATABASE_URL isn't set."""
    global _pool
    if not DATABASE_URL or _pool is not None:
        return
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with _pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def enabled() -> bool:
    return _pool is not None


async def upsert_session(row: dict) -> None:
    """Row keys match the `sessions` table columns exactly — see
    SessionState.to_row() in session.py, the only caller that builds one.
    """
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            insert into sessions (
                session_id, user_id, title, current_entity, current_abstraction,
                current_dimension_name, current_dimension_description,
                known_entities, nodes, edges, messages, pending_action,
                current_space, space_history, current_projection
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            on conflict (session_id) do update set
                title = excluded.title,
                current_entity = excluded.current_entity,
                current_abstraction = excluded.current_abstraction,
                current_dimension_name = excluded.current_dimension_name,
                current_dimension_description = excluded.current_dimension_description,
                known_entities = excluded.known_entities,
                nodes = excluded.nodes,
                edges = excluded.edges,
                messages = excluded.messages,
                pending_action = excluded.pending_action,
                current_space = excluded.current_space,
                space_history = excluded.space_history,
                current_projection = excluded.current_projection
            """,
            row["session_id"],
            row["user_id"],
            row["title"],
            row["current_entity"],
            row["current_abstraction"],
            row["current_dimension_name"],
            row["current_dimension_description"],
            row["known_entities"],
            row["nodes"],
            row["edges"],
            row["messages"],
            row["pending_action"],
            row["current_space"],
            row["space_history"],
            row["current_projection"],
        )


async def fetch_sessions(user_id: str) -> list[dict]:
    """Most-recent-first, matching SessionStore.order's convention."""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "select * from sessions where user_id = $1 order by created_at desc", user_id
        )
    return [dict(r) for r in rows]


async def delete_session(user_id: str, session_id: str) -> None:
    """Scoped by user_id as well as session_id -- a session id alone is a UUID
    an attacker could guess/enumerate; this makes it impossible to delete a
    row that isn't the caller's own even if they somehow got another user's id.
    A no-op (not an error) when DATABASE_URL isn't set, matching every other
    function here -- the in-memory SessionStore.delete is what actually
    matters for that deployment shape.
    """
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            "delete from sessions where user_id = $1 and session_id = $2", user_id, session_id
        )


async def fetch_user_keys(user_id: str) -> Optional[dict]:
    """None when DB is disabled OR the user has never saved any keys -- callers
    must treat both the same way (fall back to the shared server pool)."""
    if _pool is None:
        return None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("select * from user_api_keys where user_id = $1", user_id)
    return dict(row) if row is not None else None


async def upsert_user_keys(user_id: str, keys: dict) -> None:
    """`keys` values: a non-empty string sets/replaces that key, an empty
    string clears it, a key genuinely absent from the dict leaves the
    currently-stored value untouched (see PATCH /settings in app.py) --
    achieved with `coalesce(excluded.x, user_api_keys.x)` only for the columns
    the caller didn't include, which the caller handles by passing the
    existing value through unchanged rather than this function guessing.
    """
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_api_keys (user_id, groq_api_key, gemini_api_key, cerebras_api_key, cohere_api_key, updated_at)
            values ($1, $2, $3, $4, $5, now())
            on conflict (user_id) do update set
                groq_api_key = excluded.groq_api_key,
                gemini_api_key = excluded.gemini_api_key,
                cerebras_api_key = excluded.cerebras_api_key,
                cohere_api_key = excluded.cohere_api_key,
                updated_at = excluded.updated_at
            """,
            user_id,
            keys.get("groq_api_key"),
            keys.get("gemini_api_key"),
            keys.get("cerebras_api_key"),
            keys.get("cohere_api_key"),
        )
