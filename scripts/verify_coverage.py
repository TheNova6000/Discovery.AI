"""Regression test for `backend.dewey.coverage.lexical_candidate_checker_v0`
against the persisted benchmark (`backend/dewey/coverage/benchmark_cases.py`)
-- a real `verify_*` (pass/fail) script, not an `evaluate_*` diagnostic,
matching this project's own established convention, since this script
asserts a specific outcome (precision/recall must not regress below a
stated, measured baseline) rather than just reporting numbers.

Baseline is the REAL, MEASURED result for this checker version, not a
guessed target:
    precision = 0.59  (13 TP, 9 FP, 5 TN, 0 FN out of 27 cases)
    recall    = 1.00
This is an improvement over the unnamed pre-rename checker's own measured
result (Experiment C, docs/Architecture.md §0.86: precision 0.48, recall
1.00, zero true negatives) -- negation + domain-collision handling fixed 5
of the original 14 false positives and produced this checker's first ever
true negatives (5), at zero recall cost. The remaining 9 false positives are
NOT a bug: 8 are `mentioned_only`/`shallow` cases where the checker's
`MENTIONED` verdict is lexically correct (a real keyword genuinely appears,
non-negated) but the human ground truth was judging a different, semantic
question ("was this genuinely explained?") that a lexical checker cannot
answer -- exactly the honest scope boundary `lexical_candidate_checker_v0`'s
own module docstring states. The 9th (`lifetime/ownership`, category
`negated`) is a real, named limit of clause-level negation: "Ownership
models are important... but [it is] outside the scope of this page" splits
into a clause that mentions "ownership" and a separate clause carrying the
negation, and clause-level splitting cannot see that the second clause
retroactively scopes out the first. Closing that gap needs cross-clause or
real semantic judgment -- explicitly deferred to a future
`semantic_coverage_checker_v1.py`, not patched here with a special case.

This script fails loudly if a future change to the checker or the benchmark
drops precision or recall below these numbers, so any regression is caught
before merge -- but it does NOT fail merely because the numbers don't reach
1.00, since 1.00 precision is not an honest target for a lexical checker.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.dewey.coverage.benchmark_cases import CASES  # noqa: E402
from backend.dewey.coverage.lexical_candidate_checker_v0 import check_concept  # noqa: E402
from backend.dewey.coverage.schema import CoverageStatus  # noqa: E402
from scripts.evaluate_source_pack_quality import EXPECTED_CONCEPTS  # noqa: E402

MIN_PRECISION = 0.59
MIN_RECALL = 1.00


def run() -> tuple[int, int]:
    true_positive = false_positive = true_negative = false_negative = 0
    disagreements: list[dict] = []

    for case in CASES:
        variants = EXPECTED_CONCEPTS[case.concept]
        result = check_concept(case.concept, variants, case.text)
        checker_says_mentioned = result.status == CoverageStatus.MENTIONED

        if case.covered and checker_says_mentioned:
            true_positive += 1
        elif case.covered and not checker_says_mentioned:
            false_negative += 1
            disagreements.append({"kind": "FN", "case": case})
        elif not case.covered and checker_says_mentioned:
            false_positive += 1
            disagreements.append({"kind": "FP", "case": case})
        else:
            true_negative += 1

    total = len(CASES)
    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0

    print(f"Benchmark size: {total} hand-labeled cases across {len(EXPECTED_CONCEPTS)} concepts")
    print(f"TP={true_positive} FP={false_positive} TN={true_negative} FN={false_negative}")
    print(f"precision={precision:.4f} (min {MIN_PRECISION})  recall={recall:.4f} (min {MIN_RECALL})")

    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s) with human ground truth (expected -- see this file's own module docstring):")
        for d in disagreements:
            c = d["case"]
            print(f"  [{d['kind']}] concept={c.concept!r} category={c.category!r} note={c.note!r}")

    passed = 0
    failed = 0

    if precision >= MIN_PRECISION:
        print(f"\nPASS: precision {precision:.4f} >= baseline {MIN_PRECISION}")
        passed += 1
    else:
        print(f"\nFAIL: precision {precision:.4f} < baseline {MIN_PRECISION} -- real regression")
        failed += 1

    if recall >= MIN_RECALL:
        print(f"PASS: recall {recall:.4f} >= baseline {MIN_RECALL}")
        passed += 1
    else:
        print(f"FAIL: recall {recall:.4f} < baseline {MIN_RECALL} -- real regression")
        failed += 1

    return passed, failed


if __name__ == "__main__":
    passed, failed = run()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
