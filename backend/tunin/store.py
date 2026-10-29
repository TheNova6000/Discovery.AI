"""SQLite persistence for Tuni'n.

Why SQLite: the repository already uses SQLite for agent checkpoints and
telemetry (`aiosqlite` is a pinned dependency, docs/Rules.md), and the learner
records here are small, relational and transactional.  Neo4j stays the canonical
research graph; nothing in this module writes research claims to a second graph.

Design choices that matter:

* JSON payload columns hold pydantic models (`model_dump`), so schema changes
  stay inside `models.py`.
* Every mutating call takes a course id that the caller has already
  authorization-checked.  Ownership checks live in `orchestrator.py` so a
  missing filter cannot silently widen a query here.
* Research jobs and module generation are idempotent at this layer through
  explicit natural keys (course + version, course + sequence).
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

from .models import (
    AdaptationDecision,
    ArtifactRecord,
    Attempt,
    Course,
    CourseEvent,
    CourseProposal,
    DiscoveryMessage,
    MasteryRecord,
    ModuleFeedback,
    ModulePlan,
    ModuleStatus,
    ResearchJob,
    utcnow,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "tunin.sqlite3"


def db_path() -> Path:
    """Read the path at call time so tests can point at a temp file."""
    configured = os.environ.get("TUNIN_DB_PATH")
    return Path(configured) if configured else DEFAULT_DB_PATH


_SCHEMA = """
create table if not exists courses (
    id text primary key,
    learner_id text not null,
    title text not null,
    state text not null,
    version integer not null default 1,
    brief text not null default '{}',
    research text,
    proposal text,
    active_module_ids text not null default '[]',
    completed_module_ids text not null default '[]',
    approved_proposal_version integer,
    error text,
    last_decision text,
    created_at text not null,
    updated_at text not null
);
create index if not exists idx_courses_learner on courses(learner_id, updated_at);

create table if not exists messages (
    id text primary key,
    course_id text not null,
    role text not null,
    content text not null,
    created_at text not null,
    meta text not null default '{}'
);
create index if not exists idx_messages_course on messages(course_id, created_at);

create table if not exists research_jobs (
    id text primary key,
    course_id text not null,
    status text not null,
    stage text not null,
    progress real not null default 0,
    message text not null default '',
    result text,
    error text,
    attempts integer not null default 0,
    created_at text not null,
    updated_at text not null
);
create index if not exists idx_jobs_course on research_jobs(course_id, created_at);

create table if not exists proposals (
    id text primary key,
    course_id text not null,
    version integer not null,
    status text not null,
    data text not null,
    created_at text not null,
    approved_at text,
    unique(course_id, version)
);
create index if not exists idx_proposals_course on proposals(course_id, version);

create table if not exists modules (
    id text primary key,
    course_id text not null,
    proposal_id text not null,
    sequence integer not null,
    status text not null,
    version integer not null default 1,
    data text not null,
    updated_at text not null,
    unique(course_id, sequence, version)
);
create index if not exists idx_modules_course on modules(course_id, sequence);

create table if not exists attempts (
    id text primary key,
    course_id text not null,
    module_id text not null,
    exercise_id text not null,
    learner_id text not null,
    answer text not null,
    confidence real,
    result text not null,
    created_at text not null
);
create index if not exists idx_attempts_course on attempts(course_id, module_id);

create table if not exists feedback (
    id text primary key,
    course_id text not null,
    module_id text not null,
    learner_id text not null,
    data text not null,
    created_at text not null
);
create index if not exists idx_feedback_course on feedback(course_id, module_id);

create table if not exists mastery (
    learner_id text not null,
    course_id text not null,
    concept_id text not null,
    data text not null,
    updated_at text not null,
    primary key (learner_id, course_id, concept_id)
);

create table if not exists decisions (
    id text primary key,
    course_id text not null,
    module_id text not null,
    action text not null,
    data text not null,
    created_at text not null
);
create index if not exists idx_decisions_course on decisions(course_id, created_at);

create table if not exists events (
    id text primary key,
    course_id text not null,
    type text not null,
    payload text not null default '{}',
    created_at text not null
);
create index if not exists idx_events_course on events(course_id, created_at);

create table if not exists artifacts (
    id text primary key,
    course_id text not null,
    module_id text not null,
    kind text not null,
    path text not null,
    version integer not null default 1,
    content_hash text not null default '',
    created_at text not null
);
create index if not exists idx_artifacts_course on artifacts(course_id, module_id);

create table if not exists idempotency (
    key text primary key,
    course_id text not null,
    response text not null,
    created_at text not null
);
"""


def _dump(value: Any) -> str:
    if value is None:
        return "null"
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False)


def _load(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


@asynccontextmanager
async def connect() -> AsyncIterator[aiosqlite.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        await conn.close()


async def init_db() -> None:
    async with connect() as conn:
        await conn.executescript(_SCHEMA)
        await conn.execute("PRAGMA user_version=1")
        await conn.commit()


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


def _course_from_row(row: aiosqlite.Row) -> Course:
    return Course(
        id=row["id"],
        learner_id=row["learner_id"],
        title=row["title"],
        state=row["state"],
        version=row["version"],
        brief=_load(row["brief"], {}) or {},
        research=_load(row["research"]),
        proposal=_load(row["proposal"]),
        active_module_ids=_load(row["active_module_ids"], []) or [],
        completed_module_ids=_load(row["completed_module_ids"], []) or [],
        approved_proposal_version=row["approved_proposal_version"],
        error=row["error"],
        last_decision=_load(row["last_decision"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def save_course(course: Course) -> Course:
    course.updated_at = utcnow()
    async with connect() as conn:
        await conn.execute(
            """
            insert into courses (id, learner_id, title, state, version, brief, research,
                                 proposal, active_module_ids, completed_module_ids,
                                 approved_proposal_version, error, last_decision,
                                 created_at, updated_at)
            values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
                learner_id=excluded.learner_id,
                title=excluded.title,
                state=excluded.state,
                version=excluded.version,
                brief=excluded.brief,
                research=excluded.research,
                proposal=excluded.proposal,
                active_module_ids=excluded.active_module_ids,
                completed_module_ids=excluded.completed_module_ids,
                approved_proposal_version=excluded.approved_proposal_version,
                error=excluded.error,
                last_decision=excluded.last_decision,
                updated_at=excluded.updated_at
            """,
            (
                course.id,
                course.learner_id,
                course.title,
                course.state.value,
                course.version,
                _dump(course.brief),
                _dump(course.research) if course.research else None,
                _dump(course.proposal) if course.proposal else None,
                _dump(course.active_module_ids),
                _dump(course.completed_module_ids),
                course.approved_proposal_version,
                course.error,
                _dump(course.last_decision) if course.last_decision else None,
                course.created_at,
                course.updated_at,
            ),
        )
        await conn.commit()
    return course


async def get_course(course_id: str) -> Optional[Course]:
    async with connect() as conn:
        cursor = await conn.execute("select * from courses where id = ?", (course_id,))
        row = await cursor.fetchone()
    return _course_from_row(row) if row else None


async def list_courses(learner_id: str) -> list[Course]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from courses where learner_id = ? order by updated_at desc", (learner_id,)
        )
        rows = await cursor.fetchall()
    return [_course_from_row(r) for r in rows]


async def delete_course(course_id: str) -> None:
    async with connect() as conn:
        for table in (
            "artifacts",
            "decisions",
            "events",
            "feedback",
            "attempts",
            "mastery",
            "modules",
            "proposals",
            "research_jobs",
            "messages",
            "idempotency",
            "courses",
        ):
            column = "id" if table == "courses" else "course_id"
            await conn.execute(f"delete from {table} where {column} = ?", (course_id,))
        await conn.commit()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


async def add_message(message: DiscoveryMessage) -> DiscoveryMessage:
    async with connect() as conn:
        await conn.execute(
            "insert or replace into messages (id, course_id, role, content, created_at, meta) values (?,?,?,?,?,?)",
            (
                message.id,
                message.course_id,
                message.role,
                message.content,
                message.created_at,
                _dump(message.meta),
            ),
        )
        await conn.commit()
    return message


async def list_messages(course_id: str, limit: int = 500) -> list[DiscoveryMessage]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from messages where course_id = ? order by created_at asc, rowid asc limit ?",
            (course_id, limit),
        )
        rows = await cursor.fetchall()
    return [
        DiscoveryMessage(
            id=r["id"],
            course_id=r["course_id"],
            role=r["role"],
            content=r["content"],
            created_at=r["created_at"],
            meta=_load(r["meta"], {}) or {},
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Research jobs
# ---------------------------------------------------------------------------


def _job_from_row(row: aiosqlite.Row) -> ResearchJob:
    return ResearchJob(
        id=row["id"],
        course_id=row["course_id"],
        status=row["status"],
        stage=row["stage"],
        progress=row["progress"],
        message=row["message"],
        result=_load(row["result"]),
        error=row["error"],
        attempts=row["attempts"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def save_job(job: ResearchJob) -> ResearchJob:
    job.updated_at = utcnow()
    async with connect() as conn:
        await conn.execute(
            """
            insert into research_jobs (id, course_id, status, stage, progress, message,
                                       result, error, attempts, created_at, updated_at)
            values (?,?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
                status=excluded.status, stage=excluded.stage, progress=excluded.progress,
                message=excluded.message, result=excluded.result, error=excluded.error,
                attempts=excluded.attempts, updated_at=excluded.updated_at
            """,
            (
                job.id,
                job.course_id,
                job.status.value,
                job.stage,
                job.progress,
                job.message,
                _dump(job.result) if job.result else None,
                job.error,
                job.attempts,
                job.created_at,
                job.updated_at,
            ),
        )
        await conn.commit()
    return job


async def get_job(job_id: str) -> Optional[ResearchJob]:
    async with connect() as conn:
        cursor = await conn.execute("select * from research_jobs where id = ?", (job_id,))
        row = await cursor.fetchone()
    return _job_from_row(row) if row else None


async def get_latest_job(course_id: str) -> Optional[ResearchJob]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from research_jobs where course_id = ? order by created_at desc, rowid desc limit 1",
            (course_id,),
        )
        row = await cursor.fetchone()
    return _job_from_row(row) if row else None


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------


def _proposal_from_row(row: aiosqlite.Row) -> CourseProposal:
    return CourseProposal(**_load(row["data"], {}))


async def save_proposal(proposal: CourseProposal) -> CourseProposal:
    async with connect() as conn:
        await conn.execute(
            """
            insert into proposals (id, course_id, version, status, data, created_at, approved_at)
            values (?,?,?,?,?,?,?)
            on conflict(course_id, version) do update set
                status=excluded.status, data=excluded.data, approved_at=excluded.approved_at
            """,
            (
                proposal.id,
                proposal.course_id,
                proposal.version,
                proposal.status.value,
                _dump(proposal),
                proposal.created_at,
                proposal.approved_at,
            ),
        )
        await conn.commit()
    return proposal


async def get_proposal(course_id: str, version: int) -> Optional[CourseProposal]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from proposals where course_id = ? and version = ?", (course_id, version)
        )
        row = await cursor.fetchone()
    return _proposal_from_row(row) if row else None


async def list_proposals(course_id: str) -> list[CourseProposal]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from proposals where course_id = ? order by version asc", (course_id,)
        )
        rows = await cursor.fetchall()
    return [_proposal_from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------


def _module_from_row(row: aiosqlite.Row) -> ModulePlan:
    return ModulePlan(**_load(row["data"], {}))


async def save_module(module: ModulePlan) -> ModulePlan:
    module.updated_at = utcnow()
    async with connect() as conn:
        await conn.execute(
            """
            insert into modules (id, course_id, proposal_id, sequence, status, version, data, updated_at)
            values (?,?,?,?,?,?,?,?)
            on conflict(id) do update set
                status=excluded.status, version=excluded.version, data=excluded.data,
                updated_at=excluded.updated_at
            """,
            (
                module.id,
                module.course_id,
                module.proposal_id,
                module.sequence,
                module.status.value,
                module.version,
                _dump(module),
                module.updated_at,
            ),
        )
        await conn.commit()
    return module


async def get_module(module_id: str) -> Optional[ModulePlan]:
    async with connect() as conn:
        cursor = await conn.execute("select * from modules where id = ?", (module_id,))
        row = await cursor.fetchone()
    return _module_from_row(row) if row else None


async def find_module_for_exercise(course_id: str, exercise_id: str) -> Optional[ModulePlan]:
    for module in await list_modules(course_id):
        if any(e.id == exercise_id for e in module.exercises):
            return module
    return None


async def list_modules(course_id: str) -> list[ModulePlan]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from modules where course_id = ? order by sequence asc, version asc",
            (course_id,),
        )
        rows = await cursor.fetchall()
    modules = [_module_from_row(r) for r in rows]
    # Only the newest version of a sequence is live.
    newest: dict[int, ModulePlan] = {}
    for module in modules:
        current = newest.get(module.sequence)
        if current is None or module.version > current.version:
            newest[module.sequence] = module
    return [newest[seq] for seq in sorted(newest)]


async def next_sequence(course_id: str) -> int:
    modules = await list_modules(course_id)
    return (max((m.sequence for m in modules), default=0)) + 1


# ---------------------------------------------------------------------------
# Attempts, feedback, mastery
# ---------------------------------------------------------------------------


async def add_attempt(attempt: Attempt) -> Attempt:
    async with connect() as conn:
        await conn.execute(
            """
            insert into attempts (id, course_id, module_id, exercise_id, learner_id,
                                  answer, confidence, result, created_at)
            values (?,?,?,?,?,?,?,?,?)
            """,
            (
                attempt.id,
                attempt.course_id,
                attempt.module_id,
                attempt.exercise_id,
                attempt.learner_id,
                _dump(attempt.answer),
                attempt.confidence,
                _dump(attempt.result),
                attempt.created_at,
            ),
        )
        await conn.commit()
    return attempt


def _attempt_from_row(row: aiosqlite.Row) -> Attempt:
    return Attempt(
        id=row["id"],
        course_id=row["course_id"],
        module_id=row["module_id"],
        exercise_id=row["exercise_id"],
        learner_id=row["learner_id"],
        answer=_load(row["answer"]),
        confidence=row["confidence"],
        result=_load(row["result"], {}),
        created_at=row["created_at"],
    )


async def list_attempts(course_id: str, module_id: Optional[str] = None) -> list[Attempt]:
    query = "select * from attempts where course_id = ?"
    params: list[Any] = [course_id]
    if module_id:
        query += " and module_id = ?"
        params.append(module_id)
    query += " order by created_at asc, rowid asc"
    async with connect() as conn:
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
    return [_attempt_from_row(r) for r in rows]


async def add_feedback(feedback: ModuleFeedback) -> ModuleFeedback:
    async with connect() as conn:
        await conn.execute(
            "insert into feedback (id, course_id, module_id, learner_id, data, created_at) values (?,?,?,?,?,?)",
            (
                feedback.id,
                feedback.course_id,
                feedback.module_id,
                feedback.learner_id,
                _dump(feedback),
                feedback.created_at,
            ),
        )
        await conn.commit()
    return feedback


def _feedback_from_row(row: aiosqlite.Row) -> ModuleFeedback:
    return ModuleFeedback(**_load(row["data"], {}))


async def list_feedback(course_id: str, module_id: Optional[str] = None) -> list[ModuleFeedback]:
    query = "select * from feedback where course_id = ?"
    params: list[Any] = [course_id]
    if module_id:
        query += " and module_id = ?"
        params.append(module_id)
    query += " order by created_at asc, rowid asc"
    async with connect() as conn:
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
    return [_feedback_from_row(r) for r in rows]


async def upsert_mastery(record: MasteryRecord) -> MasteryRecord:
    record.updated_at = utcnow()
    async with connect() as conn:
        await conn.execute(
            """
            insert into mastery (learner_id, course_id, concept_id, data, updated_at)
            values (?,?,?,?,?)
            on conflict(learner_id, course_id, concept_id) do update set
                data=excluded.data, updated_at=excluded.updated_at
            """,
            (record.learner_id, record.course_id, record.concept_id, _dump(record), record.updated_at),
        )
        await conn.commit()
    return record


async def get_mastery(course_id: str, learner_id: str, concept_id: str) -> Optional[MasteryRecord]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from mastery where learner_id = ? and course_id = ? and concept_id = ?",
            (learner_id, course_id, concept_id),
        )
        row = await cursor.fetchone()
    return MasteryRecord(**_load(row["data"], {})) if row else None


async def list_mastery(course_id: str, learner_id: str) -> list[MasteryRecord]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from mastery where learner_id = ? and course_id = ? order by updated_at asc",
            (learner_id, course_id),
        )
        rows = await cursor.fetchall()
    return [MasteryRecord(**_load(r["data"], {})) for r in rows]


async def add_decision(decision: AdaptationDecision) -> AdaptationDecision:
    async with connect() as conn:
        await conn.execute(
            "insert or replace into decisions (id, course_id, module_id, action, data, created_at) values (?,?,?,?,?,?)",
            (
                decision.id,
                decision.course_id,
                decision.module_id,
                decision.action.value,
                _dump(decision),
                decision.created_at,
            ),
        )
        await conn.commit()
    return decision


async def list_decisions(course_id: str) -> list[AdaptationDecision]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from decisions where course_id = ? order by created_at asc, rowid asc",
            (course_id,),
        )
        rows = await cursor.fetchall()
    return [AdaptationDecision(**_load(r["data"], {})) for r in rows]


# ---------------------------------------------------------------------------
# Events and artifacts
# ---------------------------------------------------------------------------


async def add_event(event: CourseEvent) -> CourseEvent:
    async with connect() as conn:
        await conn.execute(
            "insert into events (id, course_id, type, payload, created_at) values (?,?,?,?,?)",
            (event.id, event.course_id, event.type, _dump(event.payload), event.created_at),
        )
        await conn.commit()
    return event


async def list_events(course_id: str, limit: int = 200) -> list[CourseEvent]:
    async with connect() as conn:
        cursor = await conn.execute(
            "select * from events where course_id = ? order by created_at asc, rowid asc limit ?",
            (course_id, limit),
        )
        rows = await cursor.fetchall()
    return [
        CourseEvent(
            id=r["id"],
            course_id=r["course_id"],
            type=r["type"],
            payload=_load(r["payload"], {}) or {},
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def add_artifact(artifact: ArtifactRecord) -> ArtifactRecord:
    async with connect() as conn:
        await conn.execute(
            """
            insert or replace into artifacts (id, course_id, module_id, kind, path, version,
                                               content_hash, created_at)
            values (?,?,?,?,?,?,?,?)
            """,
            (
                artifact.id,
                artifact.course_id,
                artifact.module_id,
                artifact.kind,
                artifact.path,
                artifact.version,
                artifact.content_hash,
                artifact.created_at,
            ),
        )
        await conn.commit()
    return artifact


async def list_artifacts(course_id: str, module_id: Optional[str] = None) -> list[ArtifactRecord]:
    query = "select * from artifacts where course_id = ?"
    params: list[Any] = [course_id]
    if module_id:
        query += " and module_id = ?"
        params.append(module_id)
    query += " order by created_at asc, rowid asc"
    async with connect() as conn:
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
    return [
        ArtifactRecord(
            id=r["id"],
            course_id=r["course_id"],
            module_id=r["module_id"],
            kind=r["kind"],
            path=r["path"],
            version=r["version"],
            content_hash=r["content_hash"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def get_idempotent(key: str) -> Optional[dict]:
    async with connect() as conn:
        cursor = await conn.execute("select response from idempotency where key = ?", (key,))
        row = await cursor.fetchone()
    return _load(row["response"]) if row else None


async def put_idempotent(key: str, course_id: str, response: dict) -> None:
    async with connect() as conn:
        await conn.execute(
            "insert or replace into idempotency (key, course_id, response, created_at) values (?,?,?,?)",
            (key, course_id, _dump(response), utcnow()),
        )
        await conn.commit()


def new_idempotency_key(course_id: str, action: str, version: Any = "") -> str:
    return f"{course_id}:{action}:{version}:{uuid.uuid4().hex[:8]}"


async def module_status_counts(course_id: str) -> dict[str, int]:
    modules = await list_modules(course_id)
    counts: dict[str, int] = {}
    for module in modules:
        key = module.status.value if isinstance(module.status, ModuleStatus) else str(module.status)
        counts[key] = counts.get(key, 0) + 1
    return counts
