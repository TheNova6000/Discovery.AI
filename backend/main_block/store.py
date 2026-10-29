"""Persistent research-job store (SQLite). Jobs outlive the request that
started them and the process that ran them: a restart marks running jobs
INTERRUPTED instead of pretending they finished."""

from __future__ import annotations

from backend.paths import REPO_ROOT

import os
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import JobStatus, ResearchJob, utcnow

DEFAULT_PATH = REPO_ROOT / "mainblock.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_jobs (
    job_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_jobs_owner_fp ON research_jobs (owner_id, fingerprint, created_at);
"""


class JobStore:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = str(path or os.environ.get("MAINBLOCK_DB_PATH") or DEFAULT_PATH)

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self.path)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(_SCHEMA)
        return db

    async def save(self, job: ResearchJob) -> None:
        job.updated_at = utcnow()
        db = await self._connect()
        try:
            await db.execute(
                "INSERT INTO research_jobs (job_id, owner_id, fingerprint, status, payload, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (job.job_id, job.owner_id, job.fingerprint, job.status.value, job.model_dump_json(),
                 job.created_at, job.updated_at),
            )
            await db.commit()
        finally:
            await db.close()

    async def get(self, job_id: str) -> Optional[ResearchJob]:
        db = await self._connect()
        try:
            row = await (await db.execute("SELECT payload FROM research_jobs WHERE job_id=?", (job_id,))).fetchone()
        finally:
            await db.close()
        return ResearchJob.model_validate_json(row[0]) if row else None

    async def latest_for(self, owner_id: str, fingerprint: str) -> Optional[ResearchJob]:
        db = await self._connect()
        try:
            row = await (
                await db.execute(
                    "SELECT payload FROM research_jobs WHERE owner_id=? AND fingerprint=? ORDER BY created_at DESC LIMIT 1",
                    (owner_id, fingerprint),
                )
            ).fetchone()
        finally:
            await db.close()
        return ResearchJob.model_validate_json(row[0]) if row else None

    async def mark_interrupted(self) -> int:
        """Call once at process start: anything still QUEUED/RUNNING was cut off."""
        db = await self._connect()
        try:
            rows = await (
                await db.execute("SELECT payload FROM research_jobs WHERE status IN (?, ?)",
                                 (JobStatus.QUEUED.value, JobStatus.RUNNING.value))
            ).fetchall()
        finally:
            await db.close()
        for (payload,) in rows:
            job = ResearchJob.model_validate_json(payload)
            job.status = JobStatus.INTERRUPTED
            job.error = "the process stopped while this job was running; start it again to retry"
            await self.save(job)
        return len(rows)
