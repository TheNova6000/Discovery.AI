"""The Dewey Archive — a persistent, growing store of source passages.

Read-through design (docs/research/Reasoning-Research-Orchestration.md §2b):
Discovery.AI asks the Archive first; only when it can't cover a need does
Dewey research it, ingest what it finds here, and the Archive is asked again.
The research ledger remembers what was already searched (including "searched,
found nothing") so the same gap isn't re-searched until a cool-down passes.

What lives here is *what was read* (documents and passages with provenance),
never *what was concluded* — claims stay in the Neo4j graph and point back to
passage ids, so nothing is stored twice.

SQLite + FTS5 (porter stemming, BM25 ranking): no server, no new dependency.
Every passage keeps its document's canonical URL, provider and retrieval time,
so provenance survives reuse across investigations and learners.
"""

from __future__ import annotations

from backend.paths import REPO_ROOT

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosqlite
from pydantic import BaseModel, Field

DEFAULT_ARCHIVE_PATH = REPO_ROOT / "dewey_archive.sqlite3"
MAX_PASSAGE_CHARS = 1500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_role TEXT,
    acquisition_mode TEXT,
    licence_note TEXT,
    content_kind TEXT,
    chunker_version INTEGER,
    published TEXT,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0,
    UNIQUE (canonical_url, version)
);
CREATE TABLE IF NOT EXISTS passages (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(id),
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    entity_ids TEXT NOT NULL DEFAULT '[]',
    UNIQUE (document_id, text_hash)
);
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text, title, content='', tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS research_ledger (
    fingerprint TEXT PRIMARY KEY,
    need_text TEXT NOT NULL,
    researched_at TEXT NOT NULL,
    providers TEXT NOT NULL,
    outcome TEXT NOT NULL,
    passages_added INTEGER NOT NULL,
    next_retry_at TEXT NOT NULL
);
"""

_PROVIDER_CONTENT_KIND = {
    "wikipedia": "summary", "arxiv": "abstract", "semantic_scholar": "abstract", "open_library": "metadata",
    "github": "metadata", "youtube": "metadata", "tavily": "excerpt", "cppreference": "excerpt",
}

_KIND_RICHNESS = {"full_text": 3, "excerpt": 2, "summary": 1, "abstract": 1, "metadata": 0}
"""A later, poorer copy of a page must not supersede a richer one: once Dewey has
fetched an article's full text, the next search returning its 2-sentence summary
is not a new version of that page (iteration 02)."""

_STOPWORDS = frozenset(
    "a an and are as at be by does do for from how in is it its of on or that the this to was what when where "
    "which who why will with you your can could should would about into than then there their they".split()
)
_TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|mc_eid|ref|ref_src)$", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    """One stable key per page: lowercase scheme/host, no fragment, no
    tracking parameters, sorted query, no trailing slash on non-root paths."""
    parts = urlsplit(url.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)))
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


CHUNKER_VERSION = 2
"""1: paragraph packing. 2: section-aware -- a new passage starts at each section
heading and every passage carries "Section: <heading>." (contextual chunk
headers; Anthropic "Contextual Retrieval", 2024). Loop iteration 05, E19: the
Wikipedia "Insertion" heading ended the previous chunk, so the passage that
explains insertion never contained the word and ranked below unrelated ones."""

_HEADING_MAX = 60


def _split_long(para: str, max_chars: int) -> list[str]:
    if len(para) <= max_chars:
        return [para]
    pieces: list[str] = []
    sentence_buf = ""
    for sentence in re.split(r"(?<=[.!?])\s+", para):
        while len(sentence) > max_chars:
            if sentence_buf:
                pieces.append(sentence_buf)
                sentence_buf = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if len(sentence_buf) + len(sentence) + 1 > max_chars:
            pieces.append(sentence_buf)
            sentence_buf = sentence
        else:
            sentence_buf = f"{sentence_buf} {sentence}".strip()
    if sentence_buf:
        pieces.append(sentence_buf)
    return pieces


def _is_heading(line: str) -> bool:
    line = line.strip()
    return 0 < len(line) <= _HEADING_MAX and not line.endswith((".", ":", ";", ",", "?", "!")) and not line.startswith("$")


def _sections(text: str) -> list[tuple[str | None, list[str]]]:
    """(heading, paragraphs) groups. A heading is a short, unpunctuated first
    line of a paragraph (how Dewey's fetcher lays out Wikipedia sections) or a
    wiki-markup '== Heading ==' line."""
    text = re.sub(r"(?m)^\s*(=+)\s*(.+?)\s*\1\s*$", lambda m: f"\n\n{m.group(2)}\n", text)
    groups: list[tuple[str | None, list[str]]] = [(None, [])]
    for raw in re.split(r"\n\s*\n", text):
        lines = [l for l in raw.splitlines() if l.strip()]
        if not lines:
            continue
        if _is_heading(lines[0]) and (len(lines) > 1 or len(lines[0].split()) <= 6):
            groups.append((lines[0].strip(), []))
            lines = lines[1:]
            if not lines:
                continue
        groups[-1][1].append(" ".join(" ".join(lines).split()))
    return [g for g in groups if g[1]]


def chunk_text(text: str, max_chars: int = MAX_PASSAGE_CHARS) -> list[str]:
    """Section-aware, paragraph-packed passages of at most `max_chars` (prefix
    included). Text without headings chunks exactly as plain paragraph packing."""
    passages: list[str] = []
    for heading, paragraphs in _sections(text):
        prefix = f"Section: {heading}. " if heading else ""
        budget = max_chars - len(prefix)
        buf = ""
        for para in paragraphs:
            for piece in _split_long(para, budget):
                if buf and len(buf) + len(piece) + 2 > budget:
                    passages.append(prefix + buf)
                    buf = piece
                else:
                    buf = f"{buf}\n\n{piece}" if buf else piece
        if buf:
            passages.append(prefix + buf)
    return passages


def _stem(token: str) -> str:
    """Plural-only stemming, the same rule as graph/canonical.py: "reactions" and
    "reaction" must be one term (loop iteration 05, E16 -- photosynthesis
    questions failed term coverage on plurals alone)."""
    if len(token) <= 3 or token.endswith(("ss", "us", "is")):
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("ses", "xes")):
        token = token[:-2]
    elif token.endswith("s"):
        token = token[:-1]
    # Light derivational stemming so "deleted" / "deletion" / "deleting" and
    # "insertion" / "inserted" meet, as they already do in the porter-stemmed FTS
    # index (loop iteration 05: reranking lost the Deletion section for "deleted").
    for suffix in ("ation", "ion", "ing", "ed", "al"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def query_words(text: str) -> list[str]:
    """Original (unstemmed) content words, for FTS5 queries: the index applies
    its own porter stemmer, so pre-stemmed input ("travers") never matched
    (loop iteration 05 -- query("traversal") returned nothing)."""
    seen: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+", text.lower()):
        if token not in _STOPWORDS and len(token) > 1 and token not in seen:
            seen.append(token)
    return seen


def content_terms(text: str) -> list[str]:
    """Lowercased, plural-stemmed content words, stopwords dropped, first-occurrence order."""
    seen: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+", text.lower()):
        if token in _STOPWORDS or len(token) <= 1:
            continue
        token = _stem(token)
        if token not in seen:
            seen.append(token)
    return seen


def need_fingerprint(need_text: str) -> str:
    """Same need, same fingerprint, regardless of case, punctuation, word
    order or stopwords ("What is a BST?" == "bst: what is it")."""
    return _sha(" ".join(sorted(content_terms(need_text))))[:32]


def _fts_query(text: str) -> Optional[str]:
    """User/LLM text is never passed to FTS5 raw (quotes, `-`, `AND`, `(`
    are query syntax there). Content terms are quoted and OR-ed; BM25 then
    rewards passages matching more of them."""
    terms = query_words(text)
    return " OR ".join(f'"{t}"' for t in terms) if terms else None


class Document(BaseModel):
    """A source as retrieved. Provenance fields mirror
    `backend.main_block.reasoning_engine.evidence.models.RetrievedResource` so either can map to the other."""

    url: str
    title: str
    provider: str
    source_type: str
    source_role: Optional[str] = None
    acquisition_mode: Optional[str] = None
    licence_note: Optional[str] = None
    content_kind: Optional[str] = None
    published: Optional[str] = None
    retrieved_at: str = Field(default_factory=lambda: _now().isoformat())


class IngestResult(BaseModel):
    document_id: str
    version: int
    status: str  # "new" | "new_version" | "unchanged" | "kept_richer"
    passages_added: int


class PassageHit(BaseModel):
    passage_id: str
    text: str
    score: float  # BM25 with sign flipped: higher = more relevant
    document_id: str
    url: str
    title: str
    provider: str
    source_type: str
    source_role: Optional[str]
    retrieved_at: str
    entity_ids: list[str]
    content_kind: Optional[str] = None
    position: int = 0
    """0 = the document's lead passage."""


class LedgerEntry(BaseModel):
    fingerprint: str
    need_text: str
    researched_at: str
    providers: list[str]
    outcome: str  # "found" | "weak_results" | "nothing_found" | "providers_failed"
    passages_added: int
    next_retry_at: str

    @property
    def retry_due(self) -> bool:
        return datetime.fromisoformat(self.next_retry_at) <= _now()


class ArchiveStore:
    """Async SQLite store. Use as `async with ArchiveStore(path) as archive:`."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = str(path or os.environ.get("DEWEY_ARCHIVE_PATH") or DEFAULT_ARCHIVE_PATH)
        self._db: Optional[aiosqlite.Connection] = None

    async def __aenter__(self) -> "ArchiveStore":
        await self.open()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA)
        # Archives created before content_kind existed (iteration 01) get the column added.
        columns = [r[1] for r in await (await self._db.execute("PRAGMA table_info(documents)")).fetchall()]
        if "content_kind" not in columns:
            await self._db.execute("ALTER TABLE documents ADD COLUMN content_kind TEXT")
        if "chunker_version" not in columns:
            await self._db.execute("ALTER TABLE documents ADD COLUMN chunker_version INTEGER")
        # Rows ingested before content_kind existed: each provider's output kind is
        # fixed (see Retriever.content_kind), so the backfill is exact, not a guess.
        for provider, kind in _PROVIDER_CONTENT_KIND.items():
            await self._db.execute(
                "UPDATE documents SET content_kind=? WHERE content_kind IS NULL AND provider=?", (kind, provider)
            )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ArchiveStore is not open")
        return self._db

    async def ingest(self, document: Document, text: str, *, entity_ids: list[str] | None = None) -> IngestResult:
        """Store a document's extracted text as passages. Re-ingesting the
        same URL with identical text is a no-op; changed text becomes a new
        version and the previous version stops being returned by `query`."""
        url = canonical_url(document.url)
        content_hash = _sha(" ".join(text.split()))
        latest = await (
            await self.db.execute(
                "SELECT id, version, content_hash, content_kind, chunker_version FROM documents "
                "WHERE canonical_url=? ORDER BY version DESC LIMIT 1",
                (url,),
            )
        ).fetchone()
        if latest and latest[2] == content_hash and (latest[4] or 1) >= CHUNKER_VERSION:
            return IngestResult(document_id=latest[0], version=latest[1], status="unchanged", passages_added=0)
        # Same text split by an older chunker: re-split as a new version (the old
        # passages stop being served), so section headers reach archived pages too.
        if latest and _KIND_RICHNESS.get(latest[3] or "", -1) > _KIND_RICHNESS.get(document.content_kind or "", -1):
            return IngestResult(document_id=latest[0], version=latest[1], status="kept_richer", passages_added=0)

        version = latest[1] + 1 if latest else 1
        doc_id = str(uuid.uuid4())
        entities = json.dumps(sorted(set(entity_ids or [])))
        await self.db.execute("BEGIN")
        try:
            if latest:
                await self.db.execute("UPDATE documents SET superseded=1 WHERE canonical_url=?", (url,))
            await self.db.execute(
                "INSERT INTO documents (id, canonical_url, version, title, provider, source_type, source_role, "
                "acquisition_mode, licence_note, content_kind, chunker_version, published, retrieved_at, content_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id, url, version, document.title, document.provider, document.source_type,
                    document.source_role, document.acquisition_mode, document.licence_note,
                    document.content_kind, CHUNKER_VERSION, document.published, document.retrieved_at, content_hash,
                ),
            )
            added = 0
            for position, passage in enumerate(chunk_text(text)):
                cursor = await self.db.execute(
                    "INSERT OR IGNORE INTO passages (id, document_id, position, text, text_hash, entity_ids) VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), doc_id, position, passage, _sha(passage), entities),
                )
                if cursor.rowcount:
                    await self.db.execute(
                        "INSERT INTO passages_fts (rowid, text, title) VALUES (?,?,?)",
                        (cursor.lastrowid, passage, document.title),
                    )
                    added += 1
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return IngestResult(document_id=doc_id, version=version, status="new_version" if latest else "new", passages_added=added)

    async def query(self, text: str, *, limit: int = 8, entity_id: str | None = None) -> list[PassageHit]:
        """Best-matching passages from current (non-superseded) documents."""
        match = _fts_query(text)
        if match is None:
            return []
        sql = (
            "SELECT p.id, p.text, -bm25(passages_fts) AS score, d.id, d.canonical_url, d.title, d.provider, "
            "d.source_type, d.source_role, d.retrieved_at, p.entity_ids, d.content_kind, p.position "
            "FROM passages_fts JOIN passages p ON p.rowid = passages_fts.rowid "
            "JOIN documents d ON d.id = p.document_id "
            "WHERE passages_fts MATCH ? AND d.superseded = 0 "
        )
        params: list = [match]
        if entity_id is not None:
            sql += "AND EXISTS (SELECT 1 FROM json_each(p.entity_ids) WHERE value = ?) "
            params.append(entity_id)
        sql += "ORDER BY bm25(passages_fts) LIMIT ?"
        params.append(limit)
        rows = await (await self.db.execute(sql, params)).fetchall()
        return [
            PassageHit(
                passage_id=r[0], text=r[1], score=r[2], document_id=r[3], url=r[4], title=r[5], provider=r[6],
                source_type=r[7], source_role=r[8], retrieved_at=r[9], entity_ids=json.loads(r[10]),
                content_kind=r[11], position=r[12],
            )
            for r in rows
        ]

    async def term_document_frequencies(self, terms: list[str]) -> tuple[dict[str, int], int]:
        """How many current passages contain each term (FTS match), and the total
        current passage count -- archive-level IDF for reranking."""
        total = (await (await self.db.execute(
            "SELECT count(*) FROM passages p JOIN documents d ON d.id = p.document_id WHERE d.superseded = 0"
        )).fetchone())[0]
        out: dict[str, int] = {}
        for term in terms:
            row = await (await self.db.execute(
                "SELECT count(*) FROM passages_fts JOIN passages p ON p.rowid = passages_fts.rowid "
                "JOIN documents d ON d.id = p.document_id WHERE passages_fts MATCH ? AND d.superseded = 0",
                (f'"{term}"',),
            )).fetchone()
            out[term] = row[0]
        return out, total

    async def record_research(
        self,
        need_text: str,
        *,
        providers: list[str],
        outcome: str,
        passages_added: int,
        retry_after: timedelta,
    ) -> LedgerEntry:
        now = _now()
        entry = LedgerEntry(
            fingerprint=need_fingerprint(need_text),
            need_text=need_text,
            researched_at=now.isoformat(),
            providers=providers,
            outcome=outcome,
            passages_added=passages_added,
            next_retry_at=(now + retry_after).isoformat(),
        )
        await self.db.execute(
            "INSERT INTO research_ledger (fingerprint, need_text, researched_at, providers, outcome, passages_added, "
            "next_retry_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET need_text=excluded.need_text, "
            "researched_at=excluded.researched_at, providers=excluded.providers, outcome=excluded.outcome, "
            "passages_added=excluded.passages_added, next_retry_at=excluded.next_retry_at",
            (entry.fingerprint, entry.need_text, entry.researched_at, json.dumps(providers), outcome, passages_added, entry.next_retry_at),
        )
        await self.db.commit()
        return entry

    async def ledger_entry(self, need_text: str) -> Optional[LedgerEntry]:
        row = await (
            await self.db.execute(
                "SELECT fingerprint, need_text, researched_at, providers, outcome, passages_added, next_retry_at "
                "FROM research_ledger WHERE fingerprint=?",
                (need_fingerprint(need_text),),
            )
        ).fetchone()
        if row is None:
            return None
        return LedgerEntry(
            fingerprint=row[0], need_text=row[1], researched_at=row[2], providers=json.loads(row[3]),
            outcome=row[4], passages_added=row[5], next_retry_at=row[6],
        )

    async def outdated_documents(self) -> list[dict]:
        """Current documents split by an older chunker (url, title, provider, kind)."""
        rows = await (
            await self.db.execute(
                "SELECT canonical_url, title, provider, source_type, source_role, content_kind FROM documents "
                "WHERE superseded=0 AND coalesce(chunker_version, 1) < ?",
                (CHUNKER_VERSION,),
            )
        ).fetchall()
        return [dict(zip(("url", "title", "provider", "source_type", "source_role", "content_kind"), r)) for r in rows]

    async def stats(self) -> dict:
        async def one(sql: str) -> int:
            return (await (await self.db.execute(sql)).fetchone())[0]

        return {
            "documents": await one("SELECT count(*) FROM documents WHERE superseded=0"),
            "document_versions": await one("SELECT count(*) FROM documents"),
            "passages": await one("SELECT count(*) FROM passages p JOIN documents d ON d.id=p.document_id WHERE d.superseded=0"),
            "ledger_entries": await one("SELECT count(*) FROM research_ledger"),
        }
