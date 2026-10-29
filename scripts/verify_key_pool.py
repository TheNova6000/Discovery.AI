"""Verifies structured_call's shared-pool scheduling (2026-10-28) with a fake
instructor client -- no network, no quota:

  1. round-robin: consecutive calls start on different pooled keys
  2. cap: a failing provider is tried on at most MAX_KEYS_PER_PROVIDER keys
     before the chain falls through to the next provider
  3. cooldown: a key that timed out / hit quota is skipped on the next call
  4. all keys cooling -> provider skipped instantly (no timeout wait)
  5. a 503 "high demand" is model-wide -> remaining keys skipped
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import BaseModel  # noqa: E402

import backend.llm.client as lc  # noqa: E402


class Out(BaseModel):
    ok: bool


CALLS: list[tuple[str, str]] = []
FAILING_PROVIDERS: set[str] = set()
OVERLOADED_PROVIDERS: set[str] = set()


class _FakeCompletions:
    def __init__(self, model: str, key: str):
        self.model, self.key = model, key

    async def create(self, **_kwargs):
        provider = self.model.split("/", 1)[0]
        CALLS.append((provider, self.key))
        if provider in OVERLOADED_PROVIDERS:
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
        if provider in FAILING_PROVIDERS:
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")
        return Out(ok=True)


class _FakeClient:
    def __init__(self, model: str):
        provider = model.split("/", 1)[0]
        key = os.environ.get(lc.PROVIDER_ENV_VAR[provider], "")
        self.chat = type("C", (), {"completions": _FakeCompletions(model, key)})()


def _install_fakes() -> None:
    lc.instructor.from_provider = lambda model, **_kw: _FakeClient(model)
    lc.PROVIDER_KEY_POOLS["google"] = [f"g{i}" for i in range(9)]
    lc.PROVIDER_KEY_POOLS["groq"] = [f"q{i}" for i in range(9)]
    lc._KEY_CURSOR.clear()
    lc._KEY_COOLDOWN_UNTIL.clear()


CHAIN = ["google/gemma-4-31b-it", "groq/openai/gpt-oss-20b"]


async def _call() -> Out:
    return await lc.structured_call(system_prompt="s", user_prompt="u", response_model=Out, model_chain=CHAIN)


async def main() -> int:
    _install_fakes()
    failures = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal failures
        print(("[PASS] " if cond else "[FAIL] ") + msg)
        failures += 0 if cond else 1

    CALLS.clear()
    await _call()
    await _call()
    check(CALLS == [("google", "g0"), ("google", "g1")], f"#1 round-robin start keys {CALLS}")

    FAILING_PROVIDERS.add("google")
    CALLS.clear()
    await _call()
    google_tries = [k for p, k in CALLS if p == "google"]
    check(len(google_tries) == lc.MAX_KEYS_PER_PROVIDER, f"#2 capped at {lc.MAX_KEYS_PER_PROVIDER} google keys {google_tries}")
    check(CALLS[-1][0] == "groq", "#2 fell through to groq and succeeded")

    CALLS.clear()
    await _call()
    retried = [k for p, k in CALLS if p == "google"]
    check(not set(retried) & set(google_tries), f"#3 cooled keys {google_tries} skipped, tried {retried}")

    for k in lc.PROVIDER_KEY_POOLS["google"]:
        lc._KEY_COOLDOWN_UNTIL[("google", k)] = asyncio.get_running_loop().time() + 999
    CALLS.clear()
    await _call()
    check([p for p, _ in CALLS] == ["groq"], f"#4 all google keys cooling -> straight to groq {CALLS}")

    lc._KEY_COOLDOWN_UNTIL.clear()
    FAILING_PROVIDERS.clear()
    OVERLOADED_PROVIDERS.add("google")
    CALLS.clear()
    await _call()
    check([p for p, _ in CALLS] == ["google", "groq"], f"#5 503 overload -> one google try, then groq {CALLS}")

    # 6-8 (2026-10-29, website): a saved personal key is tried first, then the shared pool;
    # the final error lists every provider's failure, not just the last one.
    from backend.llm.config import set_current_user_keys
    lc._KEY_COOLDOWN_UNTIL.clear()
    OVERLOADED_PROVIDERS.clear()
    FAILING_PROVIDERS.clear()
    set_current_user_keys({"google": "users-own-key"})
    CALLS.clear()
    await _call()
    check(CALLS == [("google", "users-own-key")], f"#6 working saved key is used first and alone {CALLS}")

    class SavedKeyFails(_FakeCompletions):
        pass
    orig_create = _FakeCompletions.create

    async def saved_key_401(self, **kw):
        if self.key == "users-own-key":
            CALLS.append(("google", self.key))
            raise RuntimeError("401 API key not valid")
        return await orig_create(self, **kw)

    _FakeCompletions.create = saved_key_401
    CALLS.clear()
    await _call()
    check(CALLS[0] == ("google", "users-own-key") and CALLS[1][0] == "google" and CALLS[1][1].startswith("g"),
          f"#7 dead saved key -> shared pool tried next {CALLS[:2]}")

    FAILING_PROVIDERS.update({"google", "groq"})
    try:
        await _call()
        check(False, "#8 expected failure")
    except RuntimeError as exc:
        text = str(exc)
        check("google (your saved key): 401 API key not valid" in text and "groq (shared pool): 429" in text,
              f"#8 error names every provider's failure: {text[text.find('Failures'):][:160]}")
    _FakeCompletions.create = orig_create
    # 9-10 (2026-10-29, website): a whole comma-separated pool pasted into one Settings
    # field was sent to providers as ONE invalid key. Now it is normalised on save and
    # used as the user's own pool.
    from backend.api.session import SettingsUpdateRequest
    req = SettingsUpdateRequest(groq_api_key=' "k1", k2 ,\n k3 ', gemini_api_key="", cerebras_api_key=None)
    check(req.groq_api_key == "k1,k2,k3" and req.gemini_api_key == "" and req.cerebras_api_key is None,
          f"#9 saved keys normalised: {req.groq_api_key!r} (\"\" and None keep their meaning)")
    lc._KEY_COOLDOWN_UNTIL.clear(); FAILING_PROVIDERS.clear()

    async def first_two_bad(self, **kw):
        if self.key in ("bad1", "bad2"):
            CALLS.append(("google", self.key))
            raise RuntimeError("401 API key not valid")
        return await orig_create(self, **kw)

    _FakeCompletions.create = first_two_bad
    set_current_user_keys({"google": "bad1,bad2,good3"})
    CALLS.clear()
    await _call()
    check(CALLS == [("google", "bad1"), ("google", "bad2"), ("google", "good3")],
          f"#10 a saved list is the user's own pool, tried in order: {CALLS}")
    _FakeCompletions.create = orig_create
    set_current_user_keys({})

    print(f"\n{failures} check(s) failed." if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
