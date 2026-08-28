from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# instructor's "google" provider (Provider.GENAI, the current, non-deprecated
# google-genai SDK) reads GOOGLE_API_KEY, not GEMINI_API_KEY. We only keep one key
# in .env (GEMINI_API_KEY, matching Google AI Studio's own naming) and mirror it here
# so both env var names work regardless of which SDK a given instructor version uses.
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

# Ground-tier fallback chain: three independent free daily pools, all with real
# structured-output support via instructor.from_provider() (native SDKs, not
# litellm's generic passthrough — see docs/Memory.md for why that path was dropped).
# See Implimentation-Research/Free-LLM-APIs.md for why these three, and why not
# Claude/OpenAI (no usable free tier for this project).
GROUND_MODEL_CHAIN: list[str] = [
    # Groq first (hackathon-day reliability, docs/Memory.md): Gemini's free-tier
    # daily quota (500/day, account-wide) is exhausted as of today and Cerebras
    # needs billing set up — both fail every single call right now, and each
    # failed attempt still costs real wall-clock time (a fast 429/402, but not
    # free) before falling through. Putting the provider that actually works
    # first means most calls succeed on attempt 1 instead of paying that latency
    # tax every time. Revert this ordering once Gemini's quota resets tomorrow —
    # it's a today-specific fix, not a permanent priority change.
    "groq/openai/gpt-oss-20b",  # verified against live GET /v1/models — supports
    # `structured_outputs`, not just `json_mode`.
    "google/gemini-flash-lite-latest",  # "google/" -> Provider.GENAI -> google-genai
    # SDK (current). "gemini/" -> Provider.GEMINI -> google-generativeai (deprecated
    # upstream, Aug 2026). Model alias avoids hardcoding a version number that gets
    # deprecated (gemini-2.5-flash-lite already was, mid-2026).
    "cerebras/gpt-oss-120b",  # verified against live GET /v1/models (only two models
    # offered: gemma-4-31b, gpt-oss-120b).
]

# For rare, higher-stakes calls (Master-level structural decisions, synthesis
# across many children — Rules.md rule 3 names both explicitly). Written in Phase 2
# but never actually exercised until Phase 3/4's synthesize_answer() first called
# it live — which immediately surfaced two real bugs, fixed here:
# 1. "google/gemini-flash-latest" hangs indefinitely (verified at the raw
#    google-genai SDK level, not an instructor issue) — no exception, no timeout,
#    just never returns. Replaced with "gemini-2.5-flash", verified working
#    directly against the live API. (structured_call now also wraps every
#    provider attempt in a timeout so a hang like this can no longer block the
#    whole fallback chain forever — see llm_client.py.)
# 2. "cohere/command-r" needs the separate `cohere` package, which was never
#    actually installed (COHERE_API_KEY was set, but that's not enough — nothing
#    ever called this chain to notice). Dropped rather than fixed: adding a whole
#    new provider SDK just to keep a never-proven fallback slot isn't worth it when
#    Cerebras's gpt-oss-120b (already integrated, already has a working key, a
#    genuinely large model) covers the same "third independent pool" role.
MASTER_MODEL_CHAIN: list[str] = [
    # Groq first — same today-specific reliability reordering as GROUND_MODEL_CHAIN
    # above; revert once Gemini's daily quota resets.
    "groq/openai/gpt-oss-120b",  # step up from GROUND_MODEL_CHAIN's 20b variant,
    # same family, verified against live GET /v1/models to support structured_outputs.
    "google/gemini-2.5-flash",
    "cerebras/gpt-oss-120b",
]


def has_any_provider_key() -> bool:
    return any(
        os.environ.get(key)
        for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "COHERE_API_KEY")
    )


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

PROVIDER_ENV_VAR: dict[str, str] = {
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}
