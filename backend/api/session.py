from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GraphNodeOut(BaseModel):
    id: str
    label: str
    kind: Literal["abstraction", "entity"] = "entity"


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    label: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "agent"]
    text: str
    intent_action: Optional[str] = None


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
        self._nodes: dict[str, GraphNodeOut] = {}
        self._edges: list[tuple[str, str, str]] = []

    def add_node(self, name: str, kind: Literal["abstraction", "entity"] = "entity") -> None:
        if name not in self._nodes:
            self._nodes[name] = GraphNodeOut(id=name, label=name, kind=kind)
        if kind == "entity" and name not in self.known_entities:
            self.known_entities.append(name)

    def add_edge(self, source: str, target: str, label: str = "") -> None:
        self.add_node(source)
        self.add_node(target)
        edge = (source, target, label)
        if edge not in self._edges:
            self._edges.append(edge)

    def add_message(self, role: Literal["user", "agent"], text: str, intent_action: Optional[str] = None) -> None:
        self.messages.append(ChatMessage(role=role, text=text, intent_action=intent_action))
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
            "edges": [{"source": s, "target": t, "label": l} for s, t, l in self._edges],
            "current_entity": self.current_entity,
            "current_abstraction": self.current_abstraction,
            "current_dimension": self.current_dimension_name,
            "messages": [m.model_dump() for m in self.messages],
        }


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
# Still process-memory-only: restarting the server loses history for everyone,
# same tradeoff as before, just no longer shared across users.
_STORES: dict[str, SessionStore] = {}


def get_store(user_id: str) -> SessionStore:
    if user_id not in _STORES:
        _STORES[user_id] = SessionStore()
    return _STORES[user_id]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    intent_action: str
    graph: dict


class SwitchSessionRequest(BaseModel):
    session_id: str = Field(min_length=1)
