"""Ad-hoc verification -- GitHub issue #5 (docs/Architecture.md §0.35 point 5):
`STORES`/`HOLDS` must never resolve as compositional. Not a numbered
Phases.md deliverable.

This is a regression guard, not a bug fix. §0.35 found `STORES` (`In-Memory
Caches -> active player states`) and `HOLDS` (`In-Memory Caches -> hot,
mutable state`) look like an obvious merge candidate for `contains`
(COMPOSITION) on string similarity alone -- but checking the real examples
shows genuine ambiguity: a cache holding transient runtime state is a
functional/data relationship, not structural part-whole composition. A wrong
merge here would silently misclassify it as COMPOSITION, which then
incorrectly drives Graph Space box/nesting (§0.25) -- the same corruption
class §0.36 named for `ACQUIRED` vs `CONTAINS`, for a different reason
(functional vs. structural here, event vs. state there).

Nothing in the current pipeline performs this merge today -- confirmed
directly by reading `_RELATIONSHIP_TYPE_SYNONYMS`
(relation_extraction.py) and `RELATION_TYPES` (relation_types.py) side by
side: `stores`/`holds` are not synonym-table targets, and are not
`RELATION_TYPES` keys. This script exists to keep that true on purpose
going forward, not by accident -- same reasoning §0.35 itself gave for why
this needed tracking rather than a silent pass.

Deliberately zero LLM calls, zero Neo4j dependency (same as
verify_relation_registry_consistency.py) -- this tests the deterministic
normalization/registry layer, which is exactly where a future
predicate-identity merge would have to write its answer. `canonicalize_relation`'s
own behavior (voice/direction only, never touches vocabulary) was already
verified 8/8 in §0.18 and isn't re-tested here, same precedent
verify_relation_claims.py follows for the same call.

Two things are checked, on purpose, separately (same shape as issue #2's
script):

  1. Real current state: are `stores`/`holds` unmapped and non-compositional
     today, at every layer a merge could happen in?
  2. The check's own teeth: does this script's logic actually catch the
     dangerous merge if it existed, proven against a synthetic case that
     touches neither real table -- not just asserting today's strings differ.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions.relation_extraction import normalize_relationship_type  # noqa: E402
from backend.questions.relation_types import (  # noqa: E402
    RELATION_TYPES,
    RelationFamily,
    RelationTypeInfo,
    get_relation_info,
    is_compositional,
)

WATCHED = ["stores", "holds"]


def _check_real_state() -> bool:
    print("=" * 70)
    print("1. Real current state: are STORES/HOLDS unmapped and non-compositional?")
    print("=" * 70)
    ok = True

    for verb in WATCHED:
        # Layer A: behavioral proof no synonym-table rewrite happened -- a
        # rewrite (like 'spots' -> 'DETECTS') produces something OTHER than
        # the input's plain uppercase; pure passthrough is the observable
        # signature of "not a synonym-table target" without reaching into
        # relation_extraction.py's private _RELATIONSHIP_TYPE_SYNONYMS dict
        # from outside its module.
        canonical = normalize_relationship_type(verb)
        is_plain_passthrough = canonical == verb.upper()
        print(f"  normalize_relationship_type({verb!r}) -> {canonical!r} " f"(plain passthrough: {is_plain_passthrough})")
        ok = ok and is_plain_passthrough

        # Layer B: never CONTAINS, never any compositional canonical form.
        canonical_is_contains = canonical.strip().lower() == "contains"
        ok = ok and not canonical_is_contains

        # Layer C: the registry itself doesn't classify the canonical form as
        # COMPOSITION -- covers both "not registered at all" (today's honest
        # TAXONOMY_GAP state) and "registered but wrongly compositional"
        # (the actual danger this guard exists for).
        compositional = is_compositional(canonical)
        info = get_relation_info(canonical)
        print(f"  is_compositional({canonical!r}) = {compositional} (expected False); " f"registry entry: {info}")
        ok = ok and not compositional

    print(f"\n  All real-state checks passed: {ok}")
    return ok


def _check_mechanism_catches_the_dangerous_merge() -> bool:
    """Synthetic case, touching neither real table: builds a local
    RELATION_TYPES-shaped dict where `stores` WAS wrongly merged into
    COMPOSITION, and confirms the same is_compositional()-style logic would
    flag it -- proving this guard has teeth against the actual danger, not
    just against today's (already-safe) strings.
    """
    print("\n" + "=" * 70)
    print("2. Mechanism check: would this guard actually catch the dangerous merge?")
    print("=" * 70)

    hypothetical_registry: dict[str, RelationTypeInfo] = dict(RELATION_TYPES)
    hypothetical_registry["stores"] = RelationTypeInfo(RelationFamily.COMPOSITION, inverse_of="is_part_of")

    def hypothetical_is_compositional(relationship_type: str) -> bool:
        info = hypothetical_registry.get(relationship_type.strip().lower())
        return info is not None and info.family == RelationFamily.COMPOSITION

    would_be_flagged = hypothetical_is_compositional("stores")
    print(f"  If 'stores' were wrongly merged into COMPOSITION: is_compositional -> {would_be_flagged}")
    print(f"  A regression test asserting is_compositional('stores') == False would then fail: {would_be_flagged}")
    return would_be_flagged


def run() -> None:
    real_ok = _check_real_state()
    mechanism_ok = _check_mechanism_catches_the_dangerous_merge()

    print("\n" + "=" * 70)
    print("Result")
    print("=" * 70)
    print(f"  STORES/HOLDS remain unmapped and non-compositional today: {real_ok}")
    print(f"  This guard would catch the dangerous merge if introduced: {mechanism_ok}")

    if not (real_ok and mechanism_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
