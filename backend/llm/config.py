from __future__ import annotations

import contextvars
import os

from dotenv import load_dotenv

load_dotenv()

# instructor's "google" provider (Provider.GENAI, the current, non-deprecated
# google-genai SDK) reads GOOGLE_API_KEY, not GEMINI_API_KEY. We only keep one key
# in .env (GEMINI_API_KEY, matching Google AI Studio's own naming) and mirror it here
# so both env var names work regardless of which SDK a given instructor version uses.
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

# GROUND_MODEL_CHAIN / MASTER_MODEL_CHAIN moved to
# backend/main_block/reasoning_engine/model_chains.py: they are the reasoning
# engine's settings. This shared module keeps only keys and provider plumbing,
# so the chat model (own chain in backend/chat/config.py) can't pick them up.



def _collect_keys(*env_names: str) -> list[str]:
    """Gather every available key for one provider from one or more env vars, each
    of which may itself hold a comma-separated list (credit-maxing: round-robin
    across multiple free-tier accounts for the same provider, e.g.
    GOOGLE_API_KEYS="key1,key2,key3"). De-duplicates while preserving order so the
    same key set in both a plural and singular env var doesn't get tried twice.
    """
    keys: list[str] = []
    for name in env_names:
        raw = os.environ.get(name)
        if raw:
            keys.extend(k.strip() for k in raw.split(",") if k.strip())
    seen: set[str] = set()
    unique: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


# Maps a model string's provider prefix ("google/...", "groq/...",
# "cerebras/...") to (the pool of keys available for it, the env var
# structured_call must set before each attempt — instructor.from_provider()'s
# underlying native SDK reads credentials from the environment at client
# construction time, not as a constructor argument).
PROVIDER_KEY_POOLS: dict[str, list[str]] = {
    "google": _collect_keys("GOOGLE_API_KEYS", "GOOGLE_API_KEY", "GEMINI_API_KEYS", "GEMINI_API_KEY"),
    "groq": _collect_keys("GROQ_API_KEYS", "GROQ_API_KEY"),
    "cerebras": _collect_keys("CEREBRAS_API_KEYS", "CEREBRAS_API_KEY"),
}


def has_any_provider_key() -> bool:
    """Real, functional check -- true iff at least one of the three providers
    GROUND_MODEL_CHAIN/MASTER_MODEL_CHAIN actually use has a key available,
    via the exact same PROVIDER_KEY_POOLS the real call chain reads from
    (Phase S0.1, 2026-09-17: the previous version checked only the singular
    env var names, GEMINI_API_KEY/GROQ_API_KEY/CEREBRAS_API_KEY, and never
    the plural multi-key rotation names this project's own documented
    convention uses -- GEMINI_API_KEYS etc., Architecture.md §0.38.1 --
    silently misreporting "no key" whenever only the plural form was set,
    confirmed against this project's own real .env. It also counted
    COHERE_API_KEY as sufficient on its own, though `cohere` is not wired
    into either model chain -- dropped; deliberately not checked here."""
    return any(PROVIDER_KEY_POOLS[provider] for provider in ("google", "groq", "cerebras"))

PROVIDER_ENV_VAR: dict[str, str] = {
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}

# The server's own key for each provider, captured once at import time, before
# anything ever mutates these env vars. Bring-your-own-key support (below)
# needs this: after a request that supplied its own key finishes, the env var
# must be explicitly reset to this known-good baseline, not just left as
# "whatever's currently in it" — otherwise a later, keyless request could
# silently inherit and use a PREVIOUS user's personal key. The existing
# pool-rotation behavior above never needed this because every key in a pool
# is equally "the server's own"; a personal key is not interchangeable with
# those, so leaking it forward is a real cross-user credential leak, not a
# harmless race.
_SERVER_DEFAULT_ENV: dict[str, str | None] = {name: os.environ.get(name) for name in PROVIDER_ENV_VAR.values()}

# Request-scoped, not process-global: a `ContextVar` is copied per-asyncio-Task
# at creation, so two concurrent requests (two different FastAPI request
# handlers, each its own Task) each see only their own value here, with zero
# risk of one request's personal key becoming visible inside another's task
# purely by virtue of being set. This solves "which key does THIS request want"
# safely; it does NOT by itself make the underlying os.environ mutation in
# llm_client.py safe -- that safety instead comes from there being no `await`
# between setting the env var and constructing the SDK client that reads it
# (see llm_client.py's structured_call), so no other task's code can run in
# between and observe or clobber it.
_current_user_keys: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "current_user_keys", default={}
)


def set_current_user_keys(keys: dict[str, str]) -> None:
    """Called once per request (app.py), before any LLM call happens for it.
    `keys` maps provider name ("groq"/"google"/"cerebras") to that user's own
    key for it -- only for providers they've actually saved one for. Missing
    entries fall back to the shared server pool, unchanged from today's
    behavior.
    """
    _current_user_keys.set(keys)


def get_current_user_key(provider: str) -> str | None:
    return _current_user_keys.get().get(provider)
