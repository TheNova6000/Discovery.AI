from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.questions import get_family

from . import db


class GraphNodeOut(BaseModel):
    id: str
    label: str
    kind: Literal["abstraction", "entity"] = "entity"
    boundary_kind: Optional[Literal["subject", "entity"]] = None
    """docs/Architecture.md §0.21/§0.22: the agent's own Subject-vs-Entity
    judgment, when it made one -- distinct from `kind` above (session-mirror
    plumbing: abstraction vs. entity NODE type), carried through so the
    frontend can render a compound "box" around what this boundary governs."""


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    label: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "agent"]
    text: str
    intent_action: Optional[str] = None
    entity_name: Optional[str] = None
    """Which entity this reply was about, at the moment it was generated --
    NOT re-derived from session.current_entity later, since that can move on
    to a different topic by the time a "Resources" panel is opened. Only ever
    set on agent messages; None for a reply with no real subject (no_action,
    "I don't have an entity in focus yet")."""


class PendingAction(BaseModel):
    """docs/Architecture.md §0.20 — a single, structured, machine-executable
    offer the assistant made in its last reply. Exists so a bare "yes"/"no"
    resolves deterministically (see `_classify_confirmation` in app.py) instead
    of being handed to `parse_intent`, which has no way to know what a
    content-free confirmation refers to and — confirmed live — will fabricate a
    full `new_investigation` out of it rather than admit it doesn't know.
    """

    action: Literal["new_investigation", "investigate_deeper"]
    entity_name: str
    question_text: Optional[str] = None
    dimension_name: Optional[str] = None
    dimension_description: Optional[str] = None
    scope_hint: Optional[str] = None
    created_at: str


class SessionState:
    """One conversation's graph + chat transcript. Real graph structure is still
    persisted to Neo4j on every investigation (`persist_to_graph=True`); this is a
    fast in-memory mirror for the live UI so the demo doesn't depend on a Neo4j
    round-trip shaping itself perfectly under time pressure — Neo4j is still
    genuinely exercised underneath every "New chat" and every reload.
    """

    def __init__(self) -> None:
        self.session_id: str = str(uuid.uuid4())
        self.title: str = "New session"
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.current_entity: Optional[str] = None
        self.current_abstraction: Optional[str] = None
        self.current_dimension_name: Optional[str] = None
        self.current_dimension_description: Optional[str] = None
        self.known_entities: list[str] = []
        self.messages: list[ChatMessage] = []
        self.pending_action: Optional[PendingAction] = None
        # docs/Architecture.md §0.24 (Focus vs. Enter Space): `current_entity`
        # above is FOCUS -- a 1-hop neighborhood shown within whatever context
        # it was found in. `current_space` is a genuinely different thing --
        # which entity's own compositional subgraph is currently the rendered
        # root, dropping outside context but still showing cross-space
        # relations. None means "not inside any entered space," the default,
        # unchanged rendering behavior. `space_history` is the stack "Back"
        # pops -- entering a new space pushes the previous one (or None).
        self.current_space: Optional[str] = None
        self.space_history: list[Optional[str]] = []
        # docs/Architecture.md §0.27: which relation-family lens is applied to
        # the CURRENT view -- None/"all" means unfiltered (today's default).
        # Setting this NEVER touches Neo4j or triggers investigation; it's
        # pure view state, same status as current_space -- the architectural
        # invariant §0.27 exists to prove (G_after == G_before across a view
        # switch) depends on this never becoming anything more than that.
        self.current_projection: Optional[str] = None
        self._nodes: dict[str, GraphNodeOut] = {}
        self._edges: list[tuple[str, str, str]] = []

    def add_node(
        self,
        name: str,
        kind: Literal["abstraction", "entity"] = "entity",
        boundary_kind: Optional[Literal["subject", "entity"]] = None,
    ) -> None:
        if name not in self._nodes:
            self._nodes[name] = GraphNodeOut(id=name, label=name, kind=kind, boundary_kind=boundary_kind)
        elif boundary_kind is not None:
            # A node is often first added via add_edge (default kind, no
            # boundary_kind known yet) before _sync_decomposition later learns
            # its real boundary_kind from Neo4j -- update in place rather than
            # requiring callers to add nodes and edges in a particular order.
            self._nodes[name].boundary_kind = boundary_kind
        if kind == "entity" and name not in self.known_entities:
            self.known_entities.append(name)

    def add_edge(self, source: str, target: str, label: str = "") -> None:
        self.add_node(source)
        self.add_node(target)
        edge = (source, target, label)
        if edge not in self._edges:
            self._edges.append(edge)

    def add_message(
        self,
        role: Literal["user", "agent"],
        text: str,
        intent_action: Optional[str] = None,
        entity_name: Optional[str] = None,
    ) -> None:
        self.messages.append(ChatMessage(role=role, text=text, intent_action=intent_action, entity_name=entity_name))
        # Title the session after the first user message so the history list is
        # actually readable ("How does the electric grid work?") instead of every
        # entry saying "New session".
        if role == "user" and self.title == "New session":
            self.title = text if len(text) <= 60 else text[:57] + "..."

    def to_payload(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "nodes": [n.model_dump() for n in self._nodes.values()],
            # "family" (docs/Architecture.md §0.25): computed from the single
            # relation-type registry, not stored -- lets chat.html check
            # `edge.family === "composition"` instead of keeping its own
            # hardcoded copy of what used to be a hand-synced compositional set.
            "edges": [{"source": s, "target": t, "label": l, "family": get_family(l)} for s, t, l in self._edges],
            "current_entity": self.current_entity,
            "current_abstraction": self.current_abstraction,
            "current_dimension": self.current_dimension_name,
            "current_space": self.current_space,
            "current_projection": self.current_projection,
            "messages": [m.model_dump() for m in self.messages],
        }

    def to_row(self, user_id: str) -> dict:
        """Maps onto the `sessions` table's columns exactly (see db.py) — the
        JSONB columns need pre-serialized JSON text, not raw Python objects,
        since no jsonb type codec is registered on the asyncpg pool.
        """
        return {
            "session_id": self.session_id,
            "user_id": user_id,
            "title": self.title,
            "current_entity": self.current_entity,
            "current_abstraction": self.current_abstraction,
            "current_dimension_name": self.current_dimension_name,
            "current_dimension_description": self.current_dimension_description,
            "known_entities": json.dumps(self.known_entities),
            "nodes": json.dumps([n.model_dump() for n in self._nodes.values()]),
            "edges": json.dumps([{"source": s, "target": t, "label": l} for s, t, l in self._edges]),
            "messages": json.dumps([m.model_dump() for m in self.messages]),
            "pending_action": json.dumps(self.pending_action.model_dump()) if self.pending_action else None,
            "current_space": self.current_space,
            "space_history": json.dumps(self.space_history),
            "current_projection": self.current_projection,
        }

    @classmethod
    def from_row(cls, row: dict) -> "SessionState":
        state = cls()
        state.session_id = row["session_id"]
        state.title = row["title"]
        state.created_at = row["created_at"].isoformat()
        state.current_entity = row["current_entity"]
        state.current_abstraction = row["current_abstraction"]
        state.current_dimension_name = row["current_dimension_name"]
        state.current_dimension_description = row["current_dimension_description"]
        state.known_entities = json.loads(row["known_entities"])
        for n in json.loads(row["nodes"]):
            state._nodes[n["id"]] = GraphNodeOut(**n)
        state._edges = [(e["source"], e["target"], e["label"]) for e in json.loads(row["edges"])]
        state.messages = [ChatMessage(**m) for m in json.loads(row["messages"])]
        raw_pending = row.get("pending_action")
        state.pending_action = PendingAction(**json.loads(raw_pending)) if raw_pending else None
        state.current_space = row.get("current_space")
        raw_space_history = row.get("space_history")
        state.space_history = json.loads(raw_space_history) if raw_space_history else []
        state.current_projection = row.get("current_projection")
        return state


class SessionStore:
    """All sessions one user has seen, in-memory (no persistence across restarts —
    matches PRD.md's original "solo user" scope, just now one store per
    authenticated user instead of one for the whole process; see `get_store`
    below). Exactly one session is "current" (what /chat and /graph act on);
    "New chat" creates another and switches to it, without discarding the
    previous one — that's the actual feature being asked for: reset the live
    view, keep history.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.order: list[str] = []  # most-recent-first
        self.current_id: str = ""
        self.new_session()

    def current(self) -> SessionState:
        return self.sessions[self.current_id]

    def new_session(self) -> SessionState:
        state = SessionState()
        self.sessions[state.session_id] = state
        self.order.insert(0, state.session_id)
        self.current_id = state.session_id
        return state

    def switch(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            raise KeyError(session_id)
        self.current_id = session_id
        return self.sessions[session_id]

    def delete(self, session_id: str) -> SessionState:
        """Removes a session outright (not a soft-hide) -- returns whatever
        session is current AFTER the delete, since deleting the current one
        means something else must become current for /chat and /graph to keep
        acting on. Falls back to a brand-new session only when that was the
        very last one, same as a fresh SessionStore's own constructor.
        """
        if session_id not in self.sessions:
            raise KeyError(session_id)
        del self.sessions[session_id]
        self.order.remove(session_id)
        if self.current_id == session_id:
            self.current_id = self.order[0] if self.order else ""
            if not self.current_id:
                return self.new_session()
        return self.current()

    def list_sessions(self) -> list[dict]:
        return [
            {
                "session_id": sid,
                "title": self.sessions[sid].title,
                "created_at": self.sessions[sid].created_at,
                "is_current": sid == self.current_id,
            }
            for sid in self.order
        ]


# One store per authenticated user (LOCAL_DEV_USER_ID for the no-auth local/VM
# demo — see backend/api/auth.py), so a real multi-user deployment can't have
# one signed-in Google account's investigation graph show up for another's.
# In-memory dict doubles as a per-process cache in front of Postgres (db.py) —
# fast for every request after the first, and the only thing at all when
# DATABASE_URL isn't set (unchanged from before: process-memory-only, lost on
# restart). When it IS set, a cache miss (first time this process sees this
# user — e.g. right after Render's free tier spins back up) rehydrates from
# the database instead of starting that user over from nothing.
_STORES: dict[str, SessionStore] = {}


async def get_store(user_id: str) -> SessionStore:
    if user_id in _STORES:
        return _STORES[user_id]

    store = SessionStore()
    if db.enabled():
        rows = await db.fetch_sessions(user_id)
        if rows:
            loaded = [SessionState.from_row(r) for r in rows]
            store.sessions = {s.session_id: s for s in loaded}
            store.order = [s.session_id for s in loaded]  # fetch_sessions is already most-recent-first
            store.current_id = store.order[0]
        else:
            # Brand new user: the SessionStore constructor already created one
            # blank session — persist it now so it isn't silently lost if this
            # process gets recycled before the user's first message does.
            await persist(user_id, store.current())
    _STORES[user_id] = store
    return store


async def persist(user_id: str, session: SessionState) -> None:
    await db.upsert_session(session.to_row(user_id))


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    intent_action: str
    graph: dict


class SwitchSessionRequest(BaseModel):
    session_id: str = Field(min_length=1)


class SettingsUpdateRequest(BaseModel):
    """A field left as None means "don't change this key"; an explicit empty
    string clears it back to using the shared server pool. Never round-tripped
    back to the client in plaintext -- GET /settings only ever returns whether
    each is set, not the value."""

    groq_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    cerebras_api_key: Optional[str] = None
    cohere_api_key: Optional[str] = None


class CursorPathIn(BaseModel):
    """A visitor's own recorded cursor path from their first ~2 minutes on the
    home page -- (t_ms, nx, ny) triples, nx/ny normalized to [0,1]. No PII, no
    DOM/keypress/identity data, no cross-session linkage: purely an anonymous
    motion trace, stored so it can be looped back as ambient background motion
    for later visitors (docs/Memory.md's cursor-flow redesign)."""

    samples: list[list[float]] = Field(default_factory=list)
