"""Phase 8.1 verification -- ResearchPolicy abstraction + exploratory-mode
compatibility (docs/Phases.md Phase 8.1, docs/Architecture.md §0.40).

Governing principle for this phase (the user's own framing, preserved here):
add the abstraction before changing behavior. Every check below is either
(a) a structural/attribute-resolution check -- pure Python, no LLM/retriever/
Neo4j call, same "fast, deterministic, hand-built-fixture" shape as
scripts/verify_phase6.py -- proving the new `policy` injection point produces
IDENTICAL GroundAgent configuration to what every existing caller already got
before this phase existed, or (b) a value-pinning check against the real
production constants EXPLORATORY_POLICY's numbers were read off of (not
invented -- see backend/agents/policy.py's own docstrings for exactly where
each value came from).

What this script deliberately does NOT do: assert anything about actual LLM
output, question text, or graph content -- an investigation's prose is not
byte-for-byte deterministic (different free-tier providers/keys/retries can
legitimately answer the same question differently), so asserting exact
content here would be a flaky test pretending to be a regression guard. What
IS provably deterministic, and what actually matters for "did this phase
change behavior," is the CONTROL-FLOW configuration -- max_depth,
max_sequential_steps, gather_evidence, max_results_per_retriever -- which is
exactly what every check below verifies.

A separate, real smoke test (this file's __main__ block prints instructions
for it rather than running it here, since it needs a live Neo4j + LLM key,
neither guaranteed in every environment this script runs in) confirms one
real /chat investigation still completes end-to-end through the new
policy-routed code path.

Five checks:
  1. EXPLORATORY_POLICY's values match the real numbers every existing /chat
     investigation already ran at (pins against silent drift).
  2. GroundAgent(policy=EXPLORATORY_POLICY) resolves to IDENTICAL attributes
     as the old-style GroundAgent(max_depth=2, max_sequential_steps=3, ...)
     construction it replaced in backend/api/app.py.
  3. GroundAgent constructed with NO policy and NO explicit kwargs at all --
     i.e. every caller that has never heard of `policy` (verify_phase3.py,
     verify_phase4.py, verify_phase5.py, master_agent.py's own spawn site) --
     is completely unaffected: same class defaults as before this phase.
  4. A "learning"-mode-shaped policy (every require_* flag set True) still
     only changes the fields GroundAgent actually reads -- the not-yet-wired
     fields have zero effect on resolved attributes, proving no learning
     behavior is accidentally activated by this phase.
  5. EXPLORATORY_POLICY is frozen (immutable) -- can't be accidentally
     mutated by a caller holding a reference to the shared singleton.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents.ground_agent import (  # noqa: E402
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_SEQUENTIAL_STEPS,
    GroundAgent,
)
from backend.agents.policy import EXPLORATORY_POLICY, ResearchPolicy  # noqa: E402
from backend.evidence.engine import DEFAULT_MAX_RESULTS_PER_RETRIEVER  # noqa: E402
from backend.questions import Question, QuestionLevel  # noqa: E402

_QUESTION = Question(
    text="How does an online payment work?",
    rationale="fixture",
    dimension_id="none",
    level=QuestionLevel.MASTER,
    entity_name="online payment",
    abstraction_name="online payment",
)


def check_exploratory_policy_matches_production_values() -> None:
    # These are the exact numbers backend/api/app.py's _run_investigation used
    # before this phase (formerly DEMO_MAX_DEPTH=2, DEMO_MAX_STEPS=3,
    # gather_evidence=True) plus the Evidence Engine's own existing default.
    # If EXPLORATORY_POLICY's values ever drift from these, this fails loudly
    # instead of silently changing live /chat behavior.
    assert EXPLORATORY_POLICY.mode == "exploratory"
    assert EXPLORATORY_POLICY.max_depth == 2
    assert EXPLORATORY_POLICY.max_sequential_steps == 3
    assert EXPLORATORY_POLICY.gather_evidence is True
    assert EXPLORATORY_POLICY.max_results_per_retriever == DEFAULT_MAX_RESULTS_PER_RETRIEVER
    print("[PASS] check_exploratory_policy_matches_production_values: EXPLORATORY_POLICY == real /chat production values")


def check_policy_injection_matches_old_style_construction() -> None:
    old_style = GroundAgent(
        _QUESTION,
        gather_evidence=True,
        max_depth=2,
        max_sequential_steps=3,
        max_results_per_retriever=DEFAULT_MAX_RESULTS_PER_RETRIEVER,
    )
    new_style = GroundAgent(_QUESTION, policy=EXPLORATORY_POLICY)

    assert old_style.max_depth == new_style.max_depth == 2
    assert old_style.max_sequential_steps == new_style.max_sequential_steps == 3
    assert old_style.gather_evidence == new_style.gather_evidence is True
    assert old_style.max_results_per_retriever == new_style.max_results_per_retriever == DEFAULT_MAX_RESULTS_PER_RETRIEVER
    print("[PASS] check_policy_injection_matches_old_style_construction: policy= produces identical config to the pre-Phase-8.1 explicit-kwargs call it replaced")


def check_no_policy_preserves_every_existing_callers_defaults() -> None:
    # Every caller that predates this phase (scripts/verify_phase3.py,
    # verify_phase4.py, verify_phase5.py, master_agent.py's spawn site) never
    # passes `policy` at all -- this is the single most important check in
    # this file: does the new parameter's mere EXISTENCE change anything for
    # code that doesn't know about it?
    untouched = GroundAgent(_QUESTION)
    assert untouched.policy is None
    assert untouched.max_depth == DEFAULT_MAX_DEPTH
    assert untouched.max_sequential_steps == DEFAULT_MAX_SEQUENTIAL_STEPS
    assert untouched.gather_evidence is False  # GroundAgent's own original default
    assert untouched.max_results_per_retriever == DEFAULT_MAX_RESULTS_PER_RETRIEVER
    print("[PASS] check_no_policy_preserves_every_existing_callers_defaults: policy=None (every pre-existing caller) is byte-for-byte today's old behavior")


def check_inert_learning_fields_have_zero_effect_on_wired_attributes() -> None:
    # A "learning"-shaped policy with every not-yet-wired flag flipped on --
    # GroundAgent must not react to ANY of these, since nothing reads them yet
    # (Phase 8.2+'s job). This is the "no learning behavior accidentally
    # activated" acceptance criterion, made concrete.
    learning_shaped = ResearchPolicy(
        mode="learning",
        max_depth=2,
        max_sequential_steps=3,
        gather_evidence=True,
        max_results_per_retriever=DEFAULT_MAX_RESULTS_PER_RETRIEVER,
        require_prerequisites=True,
        require_examples=True,
        require_misconceptions=True,
        require_evidence_validation=True,
        confidence_threshold=0.9,
    )
    agent = GroundAgent(_QUESTION, policy=learning_shaped)
    # Only the four wired fields exist as GroundAgent attributes at all --
    # confirms there is no hidden read of require_*/confidence_threshold
    # anywhere in __init__ today.
    assert agent.max_depth == 2
    assert agent.max_sequential_steps == 3
    assert agent.gather_evidence is True
    assert agent.max_results_per_retriever == DEFAULT_MAX_RESULTS_PER_RETRIEVER
    assert not hasattr(agent, "require_prerequisites")
    assert not hasattr(agent, "confidence_threshold")
    print("[PASS] check_inert_learning_fields_have_zero_effect_on_wired_attributes: require_*/confidence_threshold are genuinely inert, not silently read")


def check_exploratory_policy_is_frozen() -> None:
    try:
        EXPLORATORY_POLICY.max_depth = 99  # type: ignore[misc]
    except Exception:  # dataclasses.FrozenInstanceError, a subclass of AttributeError
        print("[PASS] check_exploratory_policy_is_frozen: mutation correctly rejected")
    else:
        raise AssertionError("EXPLORATORY_POLICY accepted mutation -- the shared singleton is not actually frozen")


if __name__ == "__main__":
    check_exploratory_policy_matches_production_values()
    check_policy_injection_matches_old_style_construction()
    check_no_policy_preserves_every_existing_callers_defaults()
    check_inert_learning_fields_have_zero_effect_on_wired_attributes()
    check_exploratory_policy_is_frozen()
    print("\nAll 5 checks passed. This covers policy/attribute-resolution logic only --")
    print("no LLM, retriever, or Neo4j call was made. Separately confirm one real")
    print("investigation still completes end to end (this phase's own live smoke test):")
    print('  curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" \\')
    print('    -d \'{"message": "How does an online payment work?"}\'')
    print("and confirm 200 + a real graph write, same as docs/Architecture.md §0.39.2's original run.")
