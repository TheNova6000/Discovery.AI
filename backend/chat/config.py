"""The chat model's own configuration -- deliberately separate from the
reasoning engine's GROUND/MASTER chains (owner's rule, 2026-10-28: "dont
combine chat model with discovery.ai reasoning agent ... keep them different").

The chat model talks to learners and extracts the course brief; it never
researches. Research questions go through backend.main_block. Only the shared
provider-pool transport (key rotation, cooldowns, timeouts) is reused.

Override with TUNIN_CHAT_MODELS="provider/model,provider/model,...".
"""

from __future__ import annotations

import os

DEFAULT_CHAT_MODEL_CHAIN: list[str] = [
    # Conversational turns are short and latency-sensitive: fast models first.
    "groq/openai/gpt-oss-20b",
    "google/gemma-4-26b-a4b-it",
    "google/gemini-flash-lite-latest",
]


def chat_model_chain() -> list[str]:
    override = os.environ.get("TUNIN_CHAT_MODELS", "")
    chain = [m.strip() for m in override.split(",") if m.strip()]
    return chain or list(DEFAULT_CHAT_MODEL_CHAIN)
