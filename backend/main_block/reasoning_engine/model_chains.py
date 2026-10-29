"""The reasoning engine's model fallback chains (moved out of the shared LLM
config during the main-block restructure). Keys and transport stay in
`backend/llm`; which models the reasoning engine uses, and in what order, is
the reasoning engine's own setting."""

from __future__ import annotations

# Ground-tier fallback chain: three independent free daily pools, all with real
# structured-output support via instructor.from_provider() (native SDKs, not
# litellm's generic passthrough — see docs/Memory.md for why that path was dropped).
# See Implimentation-Research/Free-LLM-APIs.md for why these three, and why not
# Claude/OpenAI (no usable free tier for this project).
GROUND_MODEL_CHAIN: list[str] = [
    # Gemma 4 first (Tuni'n, 2026-10-28): open-weights Gemma 4 served through the
    # Gemini API on the same GEMINI_API_KEYS pool, with its own free-tier quota
    # separate from the Gemini models'. Verified live the same day: the 26B MoE
    # (4B active) returned valid JSON-schema output in 2-6s; the dense 31B
    # returned valid JSON but also one 500 INTERNAL, so it sits in the master
    # chain only, where latency matters less.
    # Revised the same day after a live BST investigation: the 26B's ground-level
    # reasoning text came back garbled ("beinanswerableable with a truths-based
    # truth"), so the 31B leads here too, Groq's pool is interleaved next so both
    # 9-key pools share load, and the 26B is a later fallback.
    # Groq first (user decision 2026-10-28, after live run 3: Gemma 4 31B failed
    # ~half its calls that day -- 60x 500 INTERNAL, 36x 503 high demand -- and the
    # Aug-30 demo that felt fast also ran Groq first). Gemma stays as fallback.
    "groq/openai/gpt-oss-20b",
    "google/gemma-4-31b-it",
    "google/gemma-4-26b-a4b-it",
    # Groq first (hackathon-day reliability, docs/Memory.md): Gemini's free-tier
    # daily quota (500/day, account-wide) is exhausted as of today and Cerebras
    # needs billing set up — both fail every single call right now, and each
    # failed attempt still costs real wall-clock time (a fast 429/402, but not
    # free) before falling through. Putting the provider that actually works
    # first means most calls succeed on attempt 1 instead of paying that latency
    # tax every time. Revert this ordering once Gemini's quota resets tomorrow —
    # it's a today-specific fix, not a permanent priority change.
    # (groq/openai/gpt-oss-20b moved up, above -- verified against live
    # GET /v1/models to support `structured_outputs`, not just `json_mode`.)
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
    # Gemma 4 first -- see GROUND_MODEL_CHAIN. The 26B MoE backs up the dense
    # 31B on the same pool before falling through to other providers.
    # Groq first -- same user decision as GROUND_MODEL_CHAIN above.
    "groq/openai/gpt-oss-120b",
    "google/gemma-4-31b-it",
    "google/gemma-4-26b-a4b-it",
    # Groq first — same today-specific reliability reordering as GROUND_MODEL_CHAIN
    # above; revert once Gemini's daily quota resets.
    # (groq/openai/gpt-oss-120b moved up, above -- step up from the ground
    # chain's 20b, verified against live GET /v1/models for structured_outputs.)
    "google/gemini-2.5-flash",
    "cerebras/gpt-oss-120b",
]
