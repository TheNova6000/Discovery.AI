"""Agent runtime (Phase 3): SQLite-backed, resumable agent state store.

Deliberately schema-agnostic — `backend/agents` owns the AgentState shape and
(de)serializes it to/from JSON; this module only persists and retrieves opaque JSON
blobs by agent_id (docs/Rules.md rule 7). The task queue and typed pub/sub message
bus mentioned in docs/Architecture.md arrive in Phase 4 alongside MasterAgent.
"""

from .exceptions import StateStoreError
from .state_store import DEFAULT_DB_PATH, init_db, load_state, save_state

__all__ = [
    "DEFAULT_DB_PATH",
    "init_db",
    "load_state",
    "save_state",
    "StateStoreError",
]
