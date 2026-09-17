"""Verification-hygiene tooling, Phase S0.1 (2026-09-17) -- a safe,
machine-readable report of what this environment actually has configured for
the 9 scripts `scripts/run_all_verifications.py` categorizes as
`environment_blocked`.

**Never prints a secret value.** Every check below reports presence
(True/False) only -- whether an env var is set and non-empty -- never its
content, never even a partial/masked value. This script makes no network
call itself; it only reads `os.environ` (via `backend.questions.llm_config`,
already the real, live source of truth this project's own provider chain
reads from) and inspects which real scripts import which real gate.

Ground truth, read directly from source rather than assumed:
- All 9 environment_blocked scripts gate on the exact same function,
  `backend.questions.llm_config.has_any_provider_key()` -- confirmed by
  grepping every one of the 9 scripts directly (see REQUIRING_SCRIPTS below).
  None of them requires a SPECIFIC provider; any one of Gemini/Groq/Cerebras
  is sufficient, since `GROUND_MODEL_CHAIN`/`MASTER_MODEL_CHAIN`
  (`backend/questions/llm_config.py`) each already fall back across all
  three.
- 2 of the 9 (`verify_graph_persistence.py`, `verify_phase5.py`) also import
  `backend.graph` (Neo4j) -- but Neo4j reachability is NOT this environment's
  blocker (confirmed: `scripts/verify_r5_3.py`/`verify_zoom_and_explain.py`
  connect to the same real Neo4j instance successfully in this same
  environment). Naming this so a future reader doesn't have to re-derive it.
- 2 of the 9 (`verify_phase5.py`, indirectly `verify_graph_persistence.py`
  via `GroundAgent(gather_evidence=True)`) also touch the Evidence Engine's
  Tavily/YouTube retrievers -- both OPTIONAL, both already degrade
  gracefully with zero results when their key is missing (Rules.md's
  graceful-degradation discipline, already real and already tested) -- never
  a hard requirement, confirmed by reading both retrievers' own source.

**A real, pre-existing, narrow inconsistency found while writing this,
flagged here rather than silently fixed** (fixing it would touch
`backend.questions.llm_config`'s actual provider-detection logic, outside
this slice's scope): `has_any_provider_key()` treats `COHERE_API_KEY` as
sufficient on its own, and `.env.example` lists it as one of four "zero-cost
LLM providers" to configure -- but `PROVIDER_KEY_POOLS` has no `"cohere"`
entry and neither `GROUND_MODEL_CHAIN` nor `MASTER_MODEL_CHAIN` contains a
`cohere/...` model string (Memory.md's own Phase 2 entry records `cohere`
being dropped: the separate `cohere` package was never installed). A user
who sets ONLY `COHERE_API_KEY` would see this preflight (and
`has_any_provider_key()` itself) report "configured," then watch every real
call fail anyway. Reported below as its own line, not smoothed over.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.evidence.config import TAVILY_API_KEY, YOUTUBE_API_KEY  # noqa: E402
from backend.questions.llm_config import PROVIDER_KEY_POOLS, has_any_provider_key  # noqa: E402

# The exact 9 scripts scripts/run_all_verifications.py found environment_blocked
# on 2026-09-17, confirmed by grep against each script's own source (see the
# module docstring above) -- not a guess, not "every verify_*.py".
REQUIRING_SCRIPTS: list[dict] = [
    {"script": "verify_dimension_composability.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
    {"script": "verify_dimension_steering.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
    {"script": "verify_graph_persistence.py", "requires_neo4j": True, "requires_evidence_retrievers": False},
    {"script": "verify_phase2.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
    {"script": "verify_phase3.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
    {"script": "verify_phase4.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
    {"script": "verify_phase5.py", "requires_neo4j": True, "requires_evidence_retrievers": True},
    {"script": "verify_sibling_relations.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
    {"script": "verify_working_framing.py", "requires_neo4j": False, "requires_evidence_retrievers": False},
]

# Real per-provider facts, cited from backend/questions/llm_config.py and
# Implimentation-Research/Free-LLM-APIs.md/docs/Memory.md -- not invented.
PROVIDER_FACTS: dict[str, dict] = {
    "google": {
        "env_vars": ["GOOGLE_API_KEYS", "GOOGLE_API_KEY", "GEMINI_API_KEYS", "GEMINI_API_KEY"],
        "model_chain_entries": ["google/gemini-flash-lite-latest", "google/gemini-2.5-flash"],
        "free_tier_note": "Gemini free tier: 500 requests/day, account-wide (observed exhausted mid-session at least once, Memory.md).",
        "functional": True,
    },
    "groq": {
        "env_vars": ["GROQ_API_KEYS", "GROQ_API_KEY"],
        "model_chain_entries": ["groq/openai/gpt-oss-20b", "groq/openai/gpt-oss-120b"],
        "free_tier_note": "Daily token cap per account (observed exhausted mid-session at least once, Memory.md).",
        "functional": True,
    },
    "cerebras": {
        "env_vars": ["CEREBRAS_API_KEYS", "CEREBRAS_API_KEY"],
        "model_chain_entries": ["cerebras/gpt-oss-120b"],
        "free_tier_note": "Free tier historically required billing details to be added to keep working (Memory.md).",
        "functional": True,
    },
    "cohere": {
        "env_vars": ["COHERE_API_KEY"],
        "model_chain_entries": [],
        "free_tier_note": "NOT actually wired into GROUND_MODEL_CHAIN or MASTER_MODEL_CHAIN -- the `cohere` package was never installed (Memory.md, Phase 2). Listed in .env.example and counted by has_any_provider_key(), but setting only this key will NOT make any real call succeed.",
        "functional": False,
    },
}


def build_report() -> dict:
    cohere_configured = bool(os.environ.get("COHERE_API_KEY"))
    provider_status = {
        name: {
            "configured": bool(PROVIDER_KEY_POOLS.get(name)) if name != "cohere" else cohere_configured,
            "key_count": len(PROVIDER_KEY_POOLS.get(name, [])) if name != "cohere" else int(cohere_configured),
            "functional": facts["functional"],
            "env_vars_checked": facts["env_vars"],
            "free_tier_note": facts["free_tier_note"],
        }
        for name, facts in PROVIDER_FACTS.items()
    }

    functional_providers_configured = [
        name for name, status in provider_status.items() if status["configured"] and status["functional"]
    ]

    tavily_configured = bool(TAVILY_API_KEY)
    youtube_configured = bool(YOUTUBE_API_KEY)

    return {
        "any_functional_provider_configured": bool(functional_providers_configured),
        "functional_providers_configured": functional_providers_configured,
        "providers": provider_status,
        "has_any_provider_key_reports": has_any_provider_key(),
        "cohere_only_would_be_a_false_positive": (
            provider_status["cohere"]["configured"] and not functional_providers_configured
        ),
        "optional_evidence_retrievers": {
            "tavily_configured": tavily_configured,
            "youtube_configured": youtube_configured,
            "note": "Both optional -- every environment_blocked script that touches evidence retrieval degrades gracefully (zero results, not a crash) when these are unset. Never the blocking factor on their own.",
        },
        "environment_blocked_scripts": REQUIRING_SCRIPTS,
        "network_requirement": "Outbound HTTPS to whichever provider(s) are configured (generativelanguage.googleapis.com / api.groq.com / api.cerebras.ai), plus the real Neo4j instance for the 2 scripts marked requires_neo4j (confirmed separately reachable in this environment today -- not this report's blocker).",
    }


if __name__ == "__main__":
    report = build_report()
    print(json.dumps(report, indent=2))
    print("\n--- summary ---", file=sys.stderr)
    if report["any_functional_provider_configured"]:
        print(f"At least one functional provider IS configured: {report['functional_providers_configured']}", file=sys.stderr)
        print("The 9 environment_blocked scripts should now be able to run (network permitting).", file=sys.stderr)
    else:
        print("No functional provider is configured. Set at least one of GEMINI_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY in .env.", file=sys.stderr)
        if report["cohere_only_would_be_a_false_positive"]:
            print("NOTE: COHERE_API_KEY is set, but it is not wired into any real model chain -- it will not fix this.", file=sys.stderr)
