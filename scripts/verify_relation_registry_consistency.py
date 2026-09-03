"""Ad-hoc verification -- RELATION_TYPES registry-consistency check (GitHub
issue #2, docs/Architecture.md §0.35). Not a numbered Phases.md deliverable.

Root cause this guards against: `normalize_relationship_type()`
(backend/questions/relation_extraction.py) and `RELATION_TYPES`
(backend/questions/relation_types.py) are two independently hand-maintained
tables. §0.35's adversarial test found they'd already drifted apart once,
silently: `_RELATIONSHIP_TYPE_SYNONYMS` maps detects/spots/monitors to
"DETECTS", but RELATION_TYPES has no `detects` entry -- normalization
succeeds, family classification silently fails, and nothing before this
script would have said so.

Per the explicit decision on issue #2/#3: this script's job is to make that
class of failure DETECTABLE, not to fix `DETECTS`. Finding the known,
already-tracked `DETECTS` gap is the proof this works -- it should keep
finding it (and printing it as "known, tracked") until issue #3 is resolved
separately, at which point this script flips to reporting zero known gaps
and someone must consciously remove the KNOWN_TAXONOMY_GAPS entry, which is
itself the regression check that the fix didn't reintroduce a new gap.

Two things are checked, on purpose, separately:

  1. Real current state: does _RELATIONSHIP_TYPE_SYNONYMS still fully agree
     with RELATION_TYPES, modulo the declared KNOWN_TAXONOMY_GAPS allowlist?
  2. The checking mechanism itself, on a synthetic case that isn't in either
     real table -- proves this catches a NEW, undeclared drift generally,
     not just the one gap it already knows about.

Exit code: 1 only for an UNKNOWN (undeclared) violation -- a known, tracked
gap is a valid state (this epic's own invariant 2) and does not fail the run.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions.relation_extraction import (  # noqa: E402
    KNOWN_TAXONOMY_GAPS,
    check_registry_consistency,
)
from backend.questions.relation_types import get_relation_info  # noqa: E402


def _check_real_tables() -> bool:
    """Returns True iff there is no UNKNOWN (undeclared) drift."""
    print("=" * 70)
    print("1. Real current state: _RELATIONSHIP_TYPE_SYNONYMS vs RELATION_TYPES")
    print("=" * 70)

    violations = check_registry_consistency()
    if not violations:
        print("  No violations at all -- every canonical synonym-table output")
        print("  resolves in RELATION_TYPES. (If this is unexpected, issue #3")
        print("  may have been fixed -- remove its KNOWN_TAXONOMY_GAPS entry.)")
        return True

    known = [v for v in violations if v in KNOWN_TAXONOMY_GAPS]
    unknown = [v for v in violations if v not in KNOWN_TAXONOMY_GAPS]

    for v in known:
        print(f"  [known, tracked]   {v!r} -- not in RELATION_TYPES. See {KNOWN_TAXONOMY_GAPS[v]}")
    for v in unknown:
        print(f"  [UNKNOWN, NEW]     {v!r} -- not in RELATION_TYPES, and not in KNOWN_TAXONOMY_GAPS.")

    if unknown:
        print(f"\n  {len(unknown)} undeclared violation(s) -- either add the missing")
        print("  RELATION_TYPES entry, or declare the gap explicitly in")
        print("  KNOWN_TAXONOMY_GAPS with a tracking issue.")
        return False

    print(f"\n  {len(known)} known, tracked gap(s) found -- exactly the expected,")
    print("  already-filed drift. No undeclared violations.")
    return True


def _check_mechanism_catches_new_drift() -> bool:
    """Synthetic case, touching neither real table, proving the underlying
    resolution logic (get_relation_info) would flag a genuinely new drift
    the same way it flagged `detects` -- not just replaying one known case.
    """
    print("\n" + "=" * 70)
    print("2. Mechanism check: does get_relation_info() reject an unregistered")
    print("   canonical string in general, not just this one known case?")
    print("=" * 70)

    fake_canonical = "TOTALLY_MADE_UP_RELATION_NOT_IN_ANY_REAL_TABLE"
    resolved = get_relation_info(fake_canonical)
    caught = resolved is None
    print(f"  get_relation_info({fake_canonical!r}) -> {resolved!r}")
    print(f"  Correctly unresolved: {caught}")
    return caught


def run() -> None:
    real_ok = _check_real_tables()
    mechanism_ok = _check_mechanism_catches_new_drift()

    print("\n" + "=" * 70)
    print("Result")
    print("=" * 70)
    print(f"  No undeclared registry drift: {real_ok}")
    print(f"  Detection mechanism works on a novel case: {mechanism_ok}")

    if not (real_ok and mechanism_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
