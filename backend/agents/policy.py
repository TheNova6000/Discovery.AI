from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Phase 8.1 (docs/Phases.md, docs/Architecture.md §0.40, docs/PRD.md §9.3a):
# the abstraction introduced BEFORE any behavior changes, per that decision's
# own governing principle. Every field below is either (a) wired to a real
# GroundAgent/Evidence Engine parameter today, with its EXPLORATORY_POLICY
# value taken directly from what backend/api/app.py's real /chat investigation
# path already used (never invented), or (b) explicitly marked inert -- a
# forward-looking placeholder for Phase 8.2+'s "learning" mode that nothing
# reads yet. Rule from PRD.md §9.3a: never pretend a value is controlled by
# policy today when it isn't.
ResearchMode = Literal["exploratory", "learning"]


@dataclass(frozen=True)
class ResearchPolicy:
    """Orchestration policy layered over the unchanged GroundAgent/Evidence
    Engine/Graph Interface machinery (Architecture.md §0.40) -- not a fork of
    the engine, a set of knobs controlling how much of it a given investigation
    uses. `exploratory` (EXPLORATORY_POLICY below) is today's existing,
    unchanged default; a `learning` preset belongs to Phase 8.2+, once the
    Learning Research Planner and completeness model (PRD.md §9.3a) exist to
    actually act on the fields marked inert below -- defining them now, with
    honest values, is this phase's whole job.
    """

    mode: ResearchMode

    # --- Wired: GroundAgent reads these directly (ground_agent.py __init__) ---
    max_depth: int
    """Recursion depth bound (GroundAgent.max_depth). Exploratory value (2)
    matches app.py's former DEMO_MAX_DEPTH constant, now retired in favor of
    this field -- same number, not a new default invented for this phase."""

    max_sequential_steps: int
    """Breadth bound: how many sequential sub-questions ONE GroundAgent
    pursues at its own level before being forced to conclude
    (GroundAgent.max_sequential_steps). Exploratory value (3) matches app.py's
    former DEMO_MAX_STEPS -- note this is NOT GroundAgent's own class default
    (DEFAULT_MAX_SEQUENTIAL_STEPS = 4, ground_agent.py): the real, live
    production path already ran at 3, not 4, before this phase existed. This
    field preserves the real number, not the class default that was never
    actually used by /chat.

    Why 2/3 specifically (docs/Memory.md, the Amazon investigation diagnosis):
    an earlier depth=1/steps=1 cut, bundled under time pressure with a real
    latency fix (routing master-level decisions to MASTER_MODEL_CHAIN), turned
    out to be the wrong lever -- it silently discarded CORRECT decompose
    verdicts (decide_next_step correctly reasoned a sub-component was
    distinct and independently investigable, and was overruled by the budget,
    not by its own judgment). The model-tier fix was the actual reliability
    win; max_depth/max_sequential_steps only need to be large enough for a
    genuinely broad question to finish decomposing before the budget kicks
    in -- 2/3 is what was actually verified working (3 still degrades to a
    fast single-child answer for narrow questions; the budget is a ceiling,
    not a target)."""

    gather_evidence: bool
    """Whether real retriever API calls run per question (GroundAgent.gather_evidence).
    Exploratory value (True) matches every real /chat investigation today."""

    # --- Wired: Evidence Engine reads this directly (backend/evidence/engine.py) ---
    max_results_per_retriever: int
    """gather_evidence's own `max_results_per_retriever` param. Exploratory
    value (2) matches backend/evidence/engine.py's existing
    DEFAULT_MAX_RESULTS_PER_RETRIEVER -- carried through, not reinvented."""

    # --- NOT wired anywhere yet: inert placeholders for Phase 8.2+'s "learning"
    # mode. Nothing in GroundAgent, the Evidence Engine, or anywhere else reads
    # these fields today -- setting them to anything has zero effect until a
    # later phase's Coverage/completeness model (Phase 8.3, PRD.md §9.3a)
    # actually checks them. Documented here, not implemented, per this phase's
    # explicit scope boundary.
    require_prerequisites: bool = False
    require_examples: bool = False
    require_misconceptions: bool = False
    require_evidence_validation: bool = False
    confidence_threshold: float = 0.0

    # --- Deliberately NOT a field on this policy: spawn_budget/broad_spawn_budget.
    # Those belong to MasterAgent (backend/agents/master_agent.py,
    # DEFAULT_SPAWN_BUDGET=3/DEFAULT_BROAD_SPAWN_BUDGET=6), which is real code
    # but is NOT part of today's live investigation path -- a repo-wide search
    # confirms MasterAgent is only ever instantiated in scripts/verify_phase4.py,
    # never by backend/api/app.py's real /chat flow (which drives GroundAgent
    # directly). Including a spawn-budget field on this policy would imply it
    # controls live behavior when it controls nothing running today; left out
    # rather than added-but-inert, since unlike the fields above it has no
    # future Phase 8.x consumer specified yet either.


EXPLORATORY_POLICY = ResearchPolicy(
    mode="exploratory",
    max_depth=2,
    max_sequential_steps=3,
    gather_evidence=True,
    max_results_per_retriever=2,
)
"""Today's existing, unchanged Discovery.AI behavior, now named and reusable
instead of living as loose constants in backend/api/app.py. Every numeric
value here was read off the real production code path (see each field's own
docstring above for exactly where), not invented for this phase."""
