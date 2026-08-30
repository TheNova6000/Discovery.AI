from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .exceptions import TelemetryError

# Same override pattern as backend/runtime/state_store.py.
DEFAULT_DB_PATH = os.environ.get(
    "CURSOR_FLOW_DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "cursor_flow.sqlite3")
)

# Redesigned per docs/Memory.md's cursor-flow pass: real recorded (t, nx, ny)
# paths, looped on playback, replaced the earlier coarse-grid spatial-average
# approach entirely -- home page only, per the user's explicit scope. This is
# a materially different privacy posture than an aggregate grid (a stored path
# is a real, if anonymous, movement trace, closer to session-replay tooling
# than heatmap aggregation), so the bounds below are deliberately stricter
# than typical session-replay retention guidance (30-90 days): capped by
# COUNT, not time, no PII/DOM/keypress/identity data of any kind is ever
# captured, and the data is used purely for decorative playback, never
# surfaced or analyzed per-visitor.
MAX_STORED_PATHS = 60
MAX_SAMPLES_PER_PATH = 2400
MAX_PATH_DURATION_MS = 130_000
MIN_SAMPLES_PER_PATH = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cursor_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    samples_json TEXT NOT NULL
);
"""


async def init_path_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the path table if it doesn't exist yet, and drop the earlier
    grid-aggregate table this replaces -- a clean migration is cheap and
    appropriate here (personal project, no users depending on the old data),
    and leaving an unused table around is exactly the kind of half-finished
    leftover this project's own discipline says not to leave.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(_SCHEMA)
            await db.execute("DROP TABLE IF EXISTS cursor_flow")
            await db.commit()
    except aiosqlite.Error as exc:
        raise TelemetryError(f"init_path_db failed for {db_path}: {exc}") from exc


async def add_path(samples: list[tuple[float, float, float]], db_path: str = DEFAULT_DB_PATH) -> bool:
    """Store one recorded (t_ms, nx, ny) path. Callers (the /telemetry/path
    endpoint) are responsible for clamping every value into range before
    calling this -- this is internal storage, not the validation boundary.
    Returns False (and stores nothing) for a path too short to be worth
    replaying later -- a near-empty recording from someone who bounced
    immediately isn't a useful "collective memory" sample.
    """
    if len(samples) < MIN_SAMPLES_PER_PATH:
        return False
    ordered = sorted(samples, key=lambda s: s[0])
    payload = json.dumps(ordered)
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO cursor_paths (recorded_at, samples_json) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(), payload),
            )
            # Rolling cap on VOLUME, not a time-based retention window -- a
            # quiet site keeps a path far longer than a busy one would, by
            # design (see the privacy note above).
            await db.execute(
                """
                DELETE FROM cursor_paths WHERE id NOT IN (
                    SELECT id FROM cursor_paths ORDER BY id DESC LIMIT ?
                )
                """,
                (MAX_STORED_PATHS,),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        raise TelemetryError(f"add_path failed: {exc}") from exc
    return True


async def get_random_paths(limit: int, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """A random sample of currently-stored paths (not necessarily the most
    recent) so repeat visits see different "ghosts" rather than the same
    handful every time.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT samples_json FROM cursor_paths ORDER BY RANDOM() LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
    except aiosqlite.Error as exc:
        raise TelemetryError(f"get_random_paths failed: {exc}") from exc
    return [{"samples": json.loads(row[0])} for row in rows]
