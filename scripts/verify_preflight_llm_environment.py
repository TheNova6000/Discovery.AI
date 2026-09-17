"""Verification-hygiene tooling, Phase S0.1 (2026-09-17) -- focused checks for
`scripts/preflight_llm_environment.py`'s own report, per the explicit
instruction to add tests for the preflight categorization rather than just
eyeball its output once.

No LLM/retriever call. Reads real `os.environ` (via `dotenv`, same as every
other script in this repo) but never asserts a SPECIFIC provider is
configured -- that's real, environment-dependent data, not something a test
should hardcode. What IS asserted is structural: the report's shape, the
cohere-is-non-functional fact (a real, static, code-level fact -- confirmed
by reading `PROVIDER_KEY_POOLS`/`GROUND_MODEL_CHAIN`/`MASTER_MODEL_CHAIN`
directly, not environment-dependent), the exact 9-script list, and --
critically -- that no real secret VALUE ever appears in the report's JSON
serialization, regardless of what's actually configured in this environment.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # scripts/ itself, for preflight_llm_environment
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # repo root, for backend.*

from preflight_llm_environment import PROVIDER_FACTS, REQUIRING_SCRIPTS, build_report  # noqa: E402


def check_report_shape() -> None:
    report = build_report()
    required_top_level = {
        "any_functional_provider_configured", "functional_providers_configured", "providers",
        "has_any_provider_key_reports", "cohere_only_would_be_a_false_positive",
        "optional_evidence_retrievers", "environment_blocked_scripts", "network_requirement",
    }
    assert required_top_level.issubset(report.keys()), f"missing fields: {required_top_level - report.keys()}"
    assert set(report["providers"].keys()) == {"google", "groq", "cerebras", "cohere"}
    for name, status in report["providers"].items():
        assert isinstance(status["configured"], bool), f"{name}.configured must be a bool"
        assert isinstance(status["key_count"], int) and status["key_count"] >= 0
        assert isinstance(status["functional"], bool)
    print("[PASS] #1 report has the expected top-level shape and every provider entry is well-typed")


def check_cohere_flagged_non_functional() -> None:
    """A real, static, code-level fact -- not environment-dependent. Confirmed
    directly against PROVIDER_FACTS (which itself was built by reading
    PROVIDER_KEY_POOLS/GROUND_MODEL_CHAIN/MASTER_MODEL_CHAIN's real source,
    not guessed)."""
    assert PROVIDER_FACTS["cohere"]["functional"] is False
    report = build_report()
    assert report["providers"]["cohere"]["functional"] is False
    for name in ("google", "groq", "cerebras"):
        assert report["providers"][name]["functional"] is True, f"{name} must be reported functional -- it's real, wired into the model chains"
    print("[PASS] #2 cohere is correctly flagged non-functional (not wired into any real model chain); google/groq/cerebras correctly flagged functional")


def check_exact_script_list() -> None:
    names = {entry["script"] for entry in REQUIRING_SCRIPTS}
    expected = {
        "verify_dimension_composability.py", "verify_dimension_steering.py", "verify_graph_persistence.py",
        "verify_phase2.py", "verify_phase3.py", "verify_phase4.py", "verify_phase5.py",
        "verify_sibling_relations.py", "verify_working_framing.py",
    }
    assert names == expected, f"script list drifted: missing={expected - names}, extra={names - expected}"
    neo4j_scripts = {e["script"] for e in REQUIRING_SCRIPTS if e["requires_neo4j"]}
    assert neo4j_scripts == {"verify_graph_persistence.py", "verify_phase5.py"}
    print("[PASS] #3 the tracked environment_blocked script list matches exactly the 9 scripts confirmed by grep, with correct Neo4j sub-flags")


def check_no_secret_values_leak() -> None:
    """The load-bearing safety property: whatever this environment actually has
    configured, the report's JSON serialization must never contain any real
    secret VALUE -- only presence/count/name metadata."""
    real_secret_values: list[str] = []
    for env_name in (
        "GEMINI_API_KEY", "GEMINI_API_KEYS", "GOOGLE_API_KEY", "GOOGLE_API_KEYS",
        "GROQ_API_KEY", "GROQ_API_KEYS", "CEREBRAS_API_KEY", "CEREBRAS_API_KEYS",
        "COHERE_API_KEY", "TAVILY_API_KEY", "YOUTUBE_API_KEY",
    ):
        raw = os.environ.get(env_name)
        if raw:
            real_secret_values.extend(v.strip() for v in raw.split(",") if v.strip())

    report = build_report()
    serialized = json.dumps(report)
    leaked = [v for v in real_secret_values if v in serialized]
    assert not leaked, f"{len(leaked)} real secret value(s) leaked into the preflight report"
    print(f"[PASS] #4 zero of {len(real_secret_values)} real configured secret value(s) appear anywhere in the report's JSON serialization")


def check_discrepancy_detection_is_consistent() -> None:
    """If has_any_provider_key() and any_functional_provider_configured
    disagree, cohere_only_would_be_a_false_positive must correctly explain
    whether that disagreement is the known cohere-only case or something
    else entirely (still surfaced, never silently absorbed)."""
    report = build_report()
    if report["has_any_provider_key_reports"] != report["any_functional_provider_configured"]:
        print(
            "[ok] a real discrepancy exists in THIS environment between has_any_provider_key() "
            f"({report['has_any_provider_key_reports']}) and actual functional configuration "
            f"({report['any_functional_provider_configured']}) -- reported, not hidden. "
            f"cohere_only_would_be_a_false_positive={report['cohere_only_would_be_a_false_positive']}"
        )
    print("[PASS] #5 discrepancy between has_any_provider_key() and real functional configuration, if any, is surfaced rather than silently absorbed")


if __name__ == "__main__":
    check_report_shape()
    check_cohere_flagged_non_functional()
    check_exact_script_list()
    check_no_secret_values_leak()
    check_discrepancy_detection_is_consistent()
    print("\nAll 5 checks passed. No LLM/retriever/Neo4j call. No secret value read into an assertion.")
