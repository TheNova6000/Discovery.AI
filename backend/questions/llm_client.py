from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import TypeVar

import instructor
from pydantic import BaseModel

from .llm_config import _SERVER_DEFAULT_ENV, PROVIDER_ENV_VAR, PROVIDER_KEY_POOLS, get_current_user_key

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
# couple of extra times is cheap insurance -- IF the failures are that kind of
# flake. The assumption below this comment used to claim quota/billing failures
# are near-instant, so a second pass "mostly just buys Groq more rolls of the
# dice." Confirmed live (2026-08-29) that assumption is false under today's
# conditions: a single structured_call across all 3 providers x both passes
# took 3m52s to fail, averaging well over PER_PROVIDER_TIMEOUT_SECONDS per
# attempt -- these are NOT fast failures right now. _is_quota_error below is
# the actual fix: skip the second pass when every failure in the first one was
# quota/billing, since re-trying the same exhausted keys seconds later cannot
# succeed and only doubles a wait that's already too long.
CHAIN_ATTEMPTS = 2


def _is_quota_error_text(text: str) -> bool:
    text = text.lower()
    return any(
        marker in text
        for marker in ("429", "402", "rate_limit", "rate limit", "quota", "payment_required", "payment required")
    )


def _is_quota_error(exc: Exception) -> bool:
    return _is_quota_error_text(str(exc))


# Shared-pool health, passively derived from real structured_call attempts --
# never from a dedicated probe call, which would burn real quota (Gemini's
# free tier is a mere 20 requests/day) just to learn something a normal
# request already tells us for free. Module-level, not per-request: this is
# server-wide "is the pool everyone shares currently up" state, not anything
# scoped to one user. Cleared to "ok" the moment ANY call on that provider
# succeeds again -- no separate recovery/reset logic needed.
_PROVIDER_STATUS: dict[str, dict] = {}

# Matches both "...try again in 3m10.94s" (Groq) and "...retry in 7.97s"
# (Gemini) shapes -- the minutes group is optional so a sub-minute retry
# window (no "Xm" prefix) still parses. Best-effort: a provider error text
# that doesn't match this shape just means no reset estimate, not a crash.
_RETRY_SECONDS_PATTERN = re.compile(r"(?:try again|retry) in (?:(\d+)m)?([\d.]+)s", re.IGNORECASE)


def _parse_retry_seconds(text: str) -> float | None:
    match = _RETRY_SECONDS_PATTERN.search(text)
    if not match:
        return None
    minutes = float(match.group(1)) if match.group(1) else 0.0
    return minutes * 60 + float(match.group(2))


def _record_provider_result(provider: str, *, ok: bool, used_shared_pool: bool, error_text: str | None = None) -> None:
    """Bring-your-own-key attempts never update this -- a user's personal key
    succeeding or failing says nothing about whether the pool everyone ELSE is
    on is healthy (docs/Architecture.md's BYOK section: separate quota,
    separate credential entirely).
    """
    if not used_shared_pool:
        return
    now = datetime.now(timezone.utc)
    if ok:
        _PROVIDER_STATUS[provider] = {"status": "ok", "checked_at": now.isoformat(), "detail": None, "reset_estimate": None}
        return
    detail = (error_text or "")[:300]
    retry_seconds = _parse_retry_seconds(detail)
    reset_estimate = (now + timedelta(seconds=retry_seconds)).isoformat() if retry_seconds is not None else None
    status = "quota_exhausted" if _is_quota_error_text(detail) else "error"
    _PROVIDER_STATUS[provider] = {
        "status": status,
        "checked_at": now.isoformat(),
        "detail": detail,
        "reset_estimate": reset_estimate,
    }


def get_provider_status() -> dict:
    """Read-only snapshot for GET /provider_status (app.py) -- empty for any
    provider this process hasn't actually attempted against the shared pool
    yet, which is a real, distinct state from "confirmed ok."
    """
    return dict(_PROVIDER_STATUS)


async def structured_call(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    model_chain: list[str],
    mode: "instructor.Mode | None" = None,
) -> T:
    """Shared Instructor call-with-fallback used by every LLM call in this module.

    `mode` (docs/Memory.md's relation-extraction schema-flakiness chase): an
    opt-in override of Instructor's per-provider default tool-calling mode --
    e.g. `instructor.Mode.JSON_SCHEMA`, which maps to a provider's actual
    constrained-decoding structured-output path where one exists (confirmed
    registered for Groq and Cerebras), unlike the default `Mode.TOOLS` (plain
    function-calling, which a smaller model can and did drift away from --
    observed live, repeatedly, emitting `{subject, predicate, object}` instead
    of `RelationExtraction`'s actual `source_entity`/`target_entity`/
    `relationship_type`/`justification` fields). Deliberately best-effort per
    provider, not blanket: not every provider in a chain supports every mode
    (Google's registry has none of Instructor's v2 modes at all), so
    constructing the client with the requested mode is tried first and falls
    back to that provider's own default silently on any failure -- a caller
    that doesn't pass `mode` gets byte-for-byte the original behavior.

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
    # Confirmed live (2026-08-29): a user reported saving their own keys and
    # still seeing the exact same shared-pool 402 error, with no way for
    # either of us to tell from the outside whether their key was ever
    # actually tried. Rather than guess again, record which source (their own
    # key vs. the shared pool) was used for each provider and surface it
    # directly in the error text this function raises -- that error is what
    # ends up in the chat reply the user already sees, so this makes "was my
    # key even attempted" answerable from the UI itself, no log access needed.
    source_log: list[str] = []
    for chain_pass in range(1, CHAIN_ATTEMPTS + 1):
        pass_had_non_quota_error = False
        for model in model_chain:
            provider = model.split("/", 1)[0]
            env_var = PROVIDER_ENV_VAR.get(provider)
            user_key = get_current_user_key(provider)
            if user_key:
                # Bring-your-own-key (docs/Architecture.md): this call runs on
                # THIS user's own quota for this provider, not the shared server
                # pool -- a single attempt, no round-robin, since there's only
                # one key to try.
                attempts: list[str | None] = [user_key]
                if chain_pass == 1:
                    source_log.append(f"{provider}=your saved key (…{user_key[-4:]})")
            else:
                key_pool = PROVIDER_KEY_POOLS.get(provider) or []
                if chain_pass == 1:
                    source_log.append(f"{provider}=shared server pool" if key_pool else f"{provider}=server default key")
                # No pool configured for this provider -> fall back to the
                # server's OWN original key, explicitly (never "whatever's
                # currently in the env var"). That distinction matters now: a
                # prior request in this same process may have set this exact
                # env var to a DIFFERENT user's personal key a moment ago: this
                # is what stops that key from silently leaking into a later,
                # keyless request instead of the server's shared credential.
                attempts = list(key_pool) if key_pool else [_SERVER_DEFAULT_ENV.get(env_var) if env_var else None]

            for key_index, key in enumerate(attempts):
                if key is not None and env_var is not None:
                    os.environ[env_var] = key
                try:
                    if mode is not None:
                        try:
                            client = instructor.from_provider(model, async_client=True, mode=mode)
                        except Exception:  # noqa: BLE001 - unsupported mode for this provider, not a real failure
                            client = instructor.from_provider(model, async_client=True)
                    else:
                        client = instructor.from_provider(model, async_client=True)
                    result = await asyncio.wait_for(
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
                    _record_provider_result(provider, ok=False, used_shared_pool=not user_key, error_text=reason)
                    if not _is_quota_error(exc):
                        pass_had_non_quota_error = True
                    last_error = exc
                    continue
                else:
                    _record_provider_result(provider, ok=True, used_shared_pool=not user_key)
                    return result

        if not pass_had_non_quota_error:
            # Every failure this pass was quota/billing (429/402) -- the same
            # keys are still exhausted seconds later, so a second identical
            # pass cannot succeed and would just double an already-long wait.
            # Only skip when the WHOLE pass was quota errors: a mixed pass
            # (e.g. one provider's genuine transient/flaky failure alongside
            # another's exhausted quota) still deserves the extra pass for the
            # flaky one, per CHAIN_ATTEMPTS's original reliability rationale.
            break

    raise RuntimeError(
        f"structured_call failed on every provider/key across {CHAIN_ATTEMPTS} chain passes in "
        f"{model_chain} (key source per provider: {', '.join(source_log)}): {last_error}"
    ) from last_error
