"""The lexical candidate checker -- the same mechanism that used to be
`check_concept_coverage` in `scripts/evaluate_source_pack_quality.py`,
renamed and reframed per the user's own explicit instruction (docs/Memory.md,
2026-09-17 Experiment C follow-up): "rename/reframe the current checker as
lexical candidate detection."

**Honest capability boundary, stated once here rather than implied:** this
checker can ONLY ever output `CoverageStatus.ABSENT` or
`CoverageStatus.MENTIONED` (see `schema.py`). It has no way to tell a real
definition from a vague, contentless mention -- Experiment C
(`scripts/evaluate_coverage_checker_precision.py`, docs/Architecture.md
§0.86) measured the previous, unnamed version of this same logic at
precision 0.48 / recall 1.00 / zero true negatives against a 27-case
hand-labeled benchmark that (in hindsight) was asking a lexical checker a
semantic question: whether a concept was genuinely EXPLAINED, not just
MENTIONED. Under this module's own honest ontology, a real but shallow or
mention-only reference to a concept SHOULD register as `MENTIONED` -- that
is a true, not a false, positive for what this checker actually claims. The
two real, structural error classes a purely lexical checker over-claims on
are the ones this version fixes:

  1. Negation -- "does not cover smart pointers" naively substring-matches
     "smart pointer". Fixed by splitting text into clauses (on `.`, `;`,
     `but`) and checking each clause's own negation cues independently, so a
     genuine positive mention in one clause of a sentence isn't suppressed
     by a negation in another clause of the SAME sentence (the real
     "explains new... but does not cover smart pointers" case from the live
     2026-09-17 run needed exactly this -- a single global negation check
     over the whole sentence would wrongly suppress the genuine "new" match
     too).
  2. Domain collision -- "reference counting" (Python GC) triggering a match
     for the C++ concept "reference". Fixed with a small, explicit,
     per-concept exclusion-phrase list: if a clause matches AND also
     contains one of that concept's known colliding phrases, it's excluded.

Neither fix helps a mention_only/shallow claim (e.g. "arrays and pointers
are related in C++") -- and it shouldn't: that IS a genuine, non-negated
mention, so `MENTIONED` is the correct, honest answer. Whether "mentioned"
is good enough for a given use case is a product decision
(`ConceptCoverageRequirement` in `schema.py`), not this checker's to make.
Telling `MENTIONED` apart from `DEFINED`/`EXPLAINED`/etc. needs real semantic
judgment and is out of scope for v0 -- that is exactly the job reserved for
a future `semantic_coverage_checker_v1.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.dewey.coverage.schema import (
    ConceptCoverageResult,
    CoverageEvidence,
    CoverageStatus,
)

CHECKER_NAME = "lexical-candidate-v0"

# Splits on sentence-ending punctuation and on "but" (bare, or after a
# comma) -- the real, minimal set of cues found necessary to correctly
# separate the live run's own dual-purpose sentence ("...dynamically, but it
# does not cover delete, malloc, free, or smart pointers.") into an
# unnegated clause (about `new`) and a negated one (about the rest),
# verified against the full 27-case benchmark in `verify_coverage.py`, not
# assumed sufficient.
_CLAUSE_SPLIT_RE = re.compile(r"[.;]|,\s*but\b|\bbut\b", re.IGNORECASE)

# Real negation/hedge cues found necessary to pass the persisted benchmark
# (`benchmark_cases.py`) -- each one is backed by an actual case, not
# speculative. This list is deliberately small and will legitimately miss
# novel phrasings; that is this checker's stated, honest limit, not a bug to
# silently patch by guessing more phrases without a benchmark case behind
# them.
_NEGATION_CUES: tuple[str, ...] = (
    "does not", "doesn't", "do not", "don't",
    "no further", "not found",
    "not covered", "does not explain", "not explain",
    "outside the scope",
    "not go into",
    "not discuss",
    "no explanation",
    "without clearly",
)

# Per-concept phrases that, if present in the SAME clause as a lexical
# match, mean the match is really about a different, colliding concept --
# not a deliberately exhaustive list, only the real collisions this
# project has actually found (Experiment C's Python-GC-vs-C++-reference
# adversarial case). Extend only when a new real collision is found, the
# same discipline `_NEGATION_CUES` follows.
DEFAULT_EXCLUSION_PHRASES: dict[str, list[str]] = {
    "reference": ["reference counting", "reference cycle", "garbage collect"],
}


def _split_clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


def _clause_is_negated(clause: str) -> bool:
    lower = clause.lower()
    return any(cue in lower for cue in _NEGATION_CUES)


def _word_boundary_pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary-anchored (at the START only) case-insensitive match for
    `phrase`, allowing any word-character suffix after it. Two real,
    benchmark-driven reasons this isn't a plain `\\bphrase\\b`:

    1. `EXPECTED_CONCEPTS` (scripts/evaluate_source_pack_quality.py)
       deliberately uses partial-word stems for some variants (e.g.
       `"dereferenc"` to match "dereference"/"dereferencing"/"dereferenced"
       in one pattern) -- a trailing `\\b` right after the stem would never
       match, since the real text continues with more word characters at
       exactly that position. Confirmed as a real regression while building
       this checker: an initial `\\bphrase\\b` + optional-`s` version
       dropped recall from 1.00 to 0.92 on the persisted benchmark by
       failing the real "Dereferencing a pointer..." case.
    2. Ordinary inflection ("pointer"/"pointers", "decay"/"decays") needs to
       keep matching too.

    The leading `\\b` is what actually does the safety work word-boundaries
    are for: it stops "new" from matching inside "renewed" (no boundary
    between the 'e' and 'n'), while still letting "new" match "newest" or
    "delete" match "deletion" -- a real, and correct, trade-off since this
    checker's job is candidate detection, not exact-word grammar.
    """
    escaped = re.escape(phrase.strip())
    return re.compile(rf"\b{escaped}\w*", re.IGNORECASE)


@dataclass
class ClauseDiagnostic:
    """One clause's own real verdict, kept separate from the concept-level
    `ConceptCoverageResult` so a diagnostic report can show WHY a clause was
    included or suppressed -- not just the final aggregate status. Built for
    `diagnose_concept`; `check_concept` uses the same underlying pass but
    only keeps the `included` clauses as `CoverageEvidence`."""

    clause: str
    matched_variants: list[str] = field(default_factory=list)
    negated: bool = False
    excluded_by: str | None = None
    included: bool = False


def _diagnose_clauses(
    variants: list[str],
    text: str,
    exclusion_patterns: list[re.Pattern[str]],
    exclusions: list[str],
) -> list[ClauseDiagnostic]:
    variant_patterns = [(v, _word_boundary_pattern(v)) for v in variants if v.strip()]
    diagnostics: list[ClauseDiagnostic] = []
    for clause in _split_clauses(text):
        matched = [v for v, p in variant_patterns if p.search(clause)]
        if not matched:
            continue
        diag = ClauseDiagnostic(clause=clause, matched_variants=matched)
        if _clause_is_negated(clause):
            diag.negated = True
            diagnostics.append(diag)
            continue
        collision = next(
            (exclusions[i] for i, ep in enumerate(exclusion_patterns) if ep.search(clause)),
            None,
        )
        if collision is not None:
            diag.excluded_by = collision
            diagnostics.append(diag)
            continue
        diag.included = True
        diagnostics.append(diag)
    return diagnostics


def _resolve_exclusions(
    concept: str, exclusion_phrases: list[str] | None
) -> tuple[list[str], list[re.Pattern[str]]]:
    exclusions = (
        DEFAULT_EXCLUSION_PHRASES.get(concept, [])
        if exclusion_phrases is None
        else exclusion_phrases
    )
    return exclusions, [_word_boundary_pattern(e) for e in exclusions]


def check_concept(
    concept: str,
    variants: list[str],
    text: str,
    *,
    exclusion_phrases: list[str] | None = None,
) -> ConceptCoverageResult:
    """Score ONE concept against ONE body of text. `variants` are the real
    keyword/phrase variants for this concept (the same shape
    `EXPECTED_CONCEPTS` in `scripts/evaluate_source_pack_quality.py` already
    uses). `exclusion_phrases` overrides `DEFAULT_EXCLUSION_PHRASES` for this
    concept when given; pass `[]` explicitly to disable exclusion for a
    concept that has a default.
    """
    exclusions, exclusion_patterns = _resolve_exclusions(concept, exclusion_phrases)
    clauses = _diagnose_clauses(variants, text, exclusion_patterns, exclusions)
    evidence = [
        CoverageEvidence(
            text_span=d.clause,
            reason="non-negated clause contains a real lexical match with no domain-collision exclusion",
        )
        for d in clauses
        if d.included
    ]

    return ConceptCoverageResult(
        concept=concept,
        status=CoverageStatus.MENTIONED if evidence else CoverageStatus.ABSENT,
        evidence=evidence,
        confidence=0.6,
        checker=CHECKER_NAME,
    )


def diagnose_concept(
    concept: str,
    variants: list[str],
    text: str,
    *,
    exclusion_phrases: list[str] | None = None,
) -> dict:
    """The full, human-readable breakdown behind one `check_concept` verdict
    -- every clause that matched a keyword variant, whether it was kept,
    negated, or suppressed by a domain-collision exclusion, and why. Built
    for a coverage diagnostic report (one topic, every concept, full
    transparency), not for the pass/fail path -- `check_concept` stays the
    stable, minimal API `verify_coverage.py` and
    `evaluate_source_pack_quality.py` depend on; this is strictly additive.
    """
    exclusions, exclusion_patterns = _resolve_exclusions(concept, exclusion_phrases)
    clauses = _diagnose_clauses(variants, text, exclusion_patterns, exclusions)
    included = [d for d in clauses if d.included]
    negated_skipped = [d for d in clauses if d.negated]
    collision_excluded = [d for d in clauses if d.excluded_by is not None]

    return {
        "concept": concept,
        "status": (CoverageStatus.MENTIONED if included else CoverageStatus.ABSENT).value,
        "checker": CHECKER_NAME,
        "matched_clauses": [d.clause for d in included],
        "negated_clauses_skipped": [
            {"clause": d.clause, "matched_variants": d.matched_variants} for d in negated_skipped
        ],
        "collision_excluded_clauses": [
            {"clause": d.clause, "excluded_by": d.excluded_by, "matched_variants": d.matched_variants}
            for d in collision_excluded
        ],
        "no_lexical_candidate_found": not clauses,
    }


def check_concept_coverage(
    expected_concepts: dict[str, list[str]],
    *,
    entity_names: list[str],
    supported_claim_texts: list[str],
) -> tuple[list[str], list[str]]:
    """Drop-in replacement for the old
    `evaluate_source_pack_quality.check_concept_coverage` -- same signature,
    same (found, missing) return shape, so
    `scripts/evaluate_source_pack_quality.py` can import this instead of
    keeping its own copy of the logic. A discovered entity NAME is treated
    as an unconditional mention (real, structural evidence -- the entity was
    actually discovered and persisted), not run through negation/exclusion
    checks, since a graph node's name is never a negated sentence fragment.
    """
    combined_text = " ".join(supported_claim_texts)
    found: list[str] = []
    missing: list[str] = []
    for concept, variants in expected_concepts.items():
        patterns = [_word_boundary_pattern(v) for v in variants if v.strip()]
        found_in_names = any(
            any(p.search(name) for p in patterns) for name in entity_names
        )
        result = check_concept(concept, variants, combined_text)
        if found_in_names or result.status == CoverageStatus.MENTIONED:
            found.append(concept)
        else:
            missing.append(concept)
    return found, missing
