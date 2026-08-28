from __future__ import annotations

import asyncio
import os
from typing import TypeVar

import instructor
from pydantic import BaseModel

from .llm_config import PROVIDER_ENV_VAR, PROVIDER_KEY_POOLS

T = TypeVar("T", bound=BaseModel)

# A provider that hangs (no exception, just never returns) is worse than one that
# errors fast — it silently blocks the entire fallback chain forever instead of
# moving on. Discovered live: "google/gemini-flash-latest" hung indefinitely at the
# raw SDK level with no timeout of its own (see docs/Memory.md). Every attempt is
# now bounded so a hang degrades into "try the next provider," same as any other
# failure (docs/Rules.md §3).
PER_PROVIDER_TIMEOUT_SECONDS = 30

# Hackathon-day reliability finding (docs/Memory.md): Groq's smaller ground-tier
# model (gpt-oss-20b) intermittently produces malformed tool calls in ways that
# look like stochastic generation slips, not a deterministic block — observed
# live, in the same session, missing a required field on one call and emitting a
# wrong-cased tool name on the next. A fresh sample of the same prompt is
# unlikely to repeat the same slip, so re-running the WHOLE provider/key chain a
# couple of extra times is cheap, high-leverage insurance: Gemini/Cerebras fail
# near-instantly when genuinely exhausted (quota/billing), so extra passes mostly
# just buy Groq more rolls of the dice, not real wall-clock cost.
CHAIN_ATTEMPTS = 2


async def structured_call(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    model_chain: list[str],
) -> T:
    """Shared Instructor call-with-fallback used by every LLM call in this module.

    Extracted from what was `generate_question`'s inline loop so the Ground Agent's
    decision call (docs/Phases.md Phase 3) can reuse the exact same fallback-chain
    behavior without a second copy of it. Per docs/Rules.md rule 2, this lives in
    `backend/questions` (not `backend/agents`) — only this module and
    `backend/evidence` are allowed to call external LLM APIs.

    Credit-maxing key rotation (added for hackathon-day reliability, docs/Memory.md):
    for each provider in `model_chain`, every key in that provider's
    `PROVIDER_KEY_POOLS` entry is tried in turn (round-robin across however many
    free-tier accounts are configured for that provider) before moving on to the
    next provider — not just one key per provider. A provider with no configured
    pool falls back to whatever credential is already sitting in its env var
    (unchanged, single-key behavior). Known simplification: this mutates the
    provider's env var in place, so two concurrent calls to the SAME provider
    could race on which key is "current" — acceptable here since every key in a
    pool is independently valid for that provider, so a race just means an
    attempt used a different-but-still-working key, not a crash.
    """
    last_error: Exception | None = None
    for chain_pass in range(1, CHAIN_ATTEMPTS + 1):
        for model in model_chain:
            provider = model.split("/", 1)[0]
            env_var = PROVIDER_ENV_VAR.get(provider)
            key_pool = PROVIDER_KEY_POOLS.get(provider) or []
            # No configured pool -> single attempt using whatever's already in the
            # env (e.g. a provider this project doesn't rotate keys for yet).
            attempts: list[str | None] = list(key_pool) if key_pool else [None]

            for key_index, key in enumerate(attempts):
                if key is not None and env_var is not None:
                    os.environ[env_var] = key
                try:
                    client = instructor.from_provider(model, async_client=True)
                    return await asyncio.wait_for(
                        client.chat.completions.create(
                            response_model=response_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            max_retries=2,
                        ),
                        timeout=PER_PROVIDER_TIMEOUT_SECONDS,
                    )
                except Exception as exc:  # noqa: BLE001 - collapse any provider/SDK/timeout error into our boundary
                    # Printed, not swallowed: a silent fallback here is exactly what let
                    # the google/... provider fail on every single call since Phase 2
                    # without anyone noticing (groq/... quietly covered for it every
                    # time) — see docs/Memory.md's Phase 5 entry.
                    reason = "timed out" if isinstance(exc, asyncio.TimeoutError) else str(exc)
                    # A provider's raw error text can contain arbitrary Unicode (seen live:
                    # an LLM's own generated content, echoed back inside a JSON-parse error,
                    # used a Unicode non-breaking hyphen U+2011). Windows' default console
                    # codec (cp1252) can't encode that, and an uncaught UnicodeEncodeError
                    # HERE would abort the entire fallback chain from inside the error
                    # handler itself — the opposite of what this handler exists to do.
                    # Sanitize before printing so a logging statement can never be the
                    # reason a recoverable provider failure becomes an unrecoverable one.
                    safe_reason = reason.encode("ascii", errors="backslashreplace").decode("ascii")
                    key_note = f" (key {key_index + 1}/{len(attempts)})" if key is not None else ""
                    pass_note = f" [chain pass {chain_pass}/{CHAIN_ATTEMPTS}]" if chain_pass > 1 else ""
                    print(f"[questions] provider {model!r}{key_note}{pass_note} failed, trying next: {safe_reason}")
                    last_error = exc
                    continue

    raise RuntimeError(
        f"structured_call failed on every provider/key across {CHAIN_ATTEMPTS} chain passes in "
        f"{model_chain}: {last_error}"
    ) from last_error
