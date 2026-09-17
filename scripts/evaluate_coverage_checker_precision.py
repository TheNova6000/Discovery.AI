"""Dewey Source Pack v0.1 -- Experiment C: does the coverage checker deserve
trust? (docs/Memory.md, 2026-09-17)

Zero LLM calls, zero network, zero quota risk -- deliberately, since the
whole point is to validate the MEASUREMENT TOOL before spending any more
real quota trusting its output (Experiment A/B, deferred until this one
either confirms or corrects the checker). A small, hand-labeled benchmark
(`check_concept_coverage` from `evaluate_source_pack_quality.py`, extracted
as a standalone, pure function for exactly this purpose) against real,
realistic claim text -- including the EXACT real false-positive text found
in the live 2026-09-17 run ("...does not cover delete, malloc, free, or
smart pointers"), now a permanent regression case in this benchmark rather
than a one-off bug report.

Ground truth is a human judgment call, stated as such -- each case's
`covered` label is what a person reading the claim text would reasonably
conclude about whether THAT SPECIFIC concept is genuinely explained (not
just present as a word), and `note` records why, so a disagreement with a
future reader is a real discussion, not an unstated assumption.

This benchmark is deliberately small (per the design conversation's own
"even 20-40 carefully constructed cases would reveal whether the evaluator
is trustworthy" -- not attempting statistical rigor at this size, just a
real, honest first read on precision/recall).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from evaluate_source_pack_quality import EXPECTED_CONCEPTS, check_concept_coverage  # noqa: E402

# Each case: (claim_text, concept_key, human_ground_truth_covered, category, note)
# `category` matches the design conversation's own proposed taxonomy
# (mentioned_only / negated / shallow / meaningful / adversarial_unrelated),
# recorded for transparency even though the checker itself only ever
# produces a binary in/out today.
BenchmarkCase = tuple[str, str, bool, str, str]

CASES: list[BenchmarkCase] = [
    # --- pointer ---
    ("In C++, a pointer is a variable that stores the memory address of another variable.",
     "pointer", True, "meaningful", "real definition, mechanism stated"),
    ("This resource mentions pointers only in passing while discussing arrays.",
     "pointer", False, "mentioned_only", "explicitly says 'in passing' -- no real content"),
    ("The document does not explain what a pointer is.",
     "pointer", False, "negated", "explicit negation"),

    # --- reference ---
    ("A reference in C++ is an alias for an existing variable, established at declaration and immutable afterward.",
     "reference", True, "meaningful", "real definition, mechanism stated"),
    ("Unlike Java, C++ has a distinct reference type, though this document does not go into how it differs from a pointer.",
     "reference", False, "mentioned_only", "existence stated, explanation explicitly withheld"),
    ("Python's garbage collector automatically manages memory using reference counting and cycle detection.",
     "reference", False, "adversarial_unrelated", "about Python GC, not C++ references -- 'reference counting' contains the literal substring 'reference'"),

    # --- dereference ---
    ("Dereferencing a pointer with the * operator accesses the value stored at the address the pointer holds.",
     "dereference", True, "meaningful", "real mechanism stated"),
    ("The article title mentions dereference operators but the retrieved snippet was truncated before any explanation.",
     "dereference", False, "mentioned_only", "explicitly truncated/no explanation"),

    # --- pointer arithmetic ---
    ("Incrementing a pointer by one actually advances it by sizeof(T) bytes, enabling array traversal via pointer arithmetic.",
     "pointer arithmetic", True, "meaningful", "real mechanism stated"),
    ("Pointer arithmetic is a common source of undefined behavior; no further detail was found in this resource.",
     "pointer arithmetic", False, "shallow", "names a risk, states no real mechanism -- explicitly says no further detail found"),

    # --- array/pointer decay ---
    ("An array name decays to a pointer to its first element when passed to a function, losing its size information.",
     "array/pointer decay", True, "meaningful", "real mechanism stated"),
    ("Arrays and pointers are related in C++.",
     "array/pointer decay", False, "shallow", "vague, contentless mention"),

    # --- dynamic allocation (the real, exact text from the live 2026-09-17 run) ---
    ("The new operator allocates memory on the heap and returns a pointer to the newly constructed object; delete releases it.",
     "dynamic allocation", True, "meaningful", "real mechanism stated"),
    ("The resource explains how the new operator allocates and initializes objects dynamically, but it does not cover delete, malloc, free, or smart pointers.",
     "dynamic allocation", True, "meaningful", "REAL case from the live run -- genuinely explains `new`, the disclaimer is about OTHER things, not this concept"),
    ("Memory can be allocated in various ways in C++.",
     "dynamic allocation", False, "shallow", "vague, contentless mention"),

    # --- stack and heap ---
    ("Automatic (stack) storage duration objects are destroyed when they go out of scope, while heap-allocated objects persist until explicitly freed.",
     "stack and heap", True, "meaningful", "real mechanism stated for both"),
    ("This resource discusses object lifetime without clearly distinguishing stack from heap allocation.",
     "stack and heap", False, "negated", "explicit hedge that the distinction isn't made"),

    # --- lifetime/ownership ---
    ("An object's lifetime begins when its constructor completes and ends when its destructor is invoked; ownership determines which code is responsible for that destruction.",
     "lifetime/ownership", True, "meaningful", "real mechanism stated"),
    ("Ownership models are important in modern C++ but are outside the scope of this reference page.",
     "lifetime/ownership", False, "negated", "explicit scope exclusion"),

    # --- smart pointer (the real, exact text from the live 2026-09-17 run -- the actual bug) ---
    ("std::unique_ptr owns a dynamically allocated object exclusively and automatically deletes it when it goes out of scope, implementing RAII.",
     "smart pointer", True, "meaningful", "real mechanism stated"),
    ("The resource explains how the new operator allocates and initializes objects dynamically, but it does not cover delete, malloc, free, or smart pointers.",
     "smart pointer", False, "negated", "REAL false-positive case from the live run -- explicit negation, 'smart pointers' only appears as something NOT covered"),
    ("Smart pointers such as unique_ptr and shared_ptr are recommended over raw pointers.",
     "smart pointer", False, "mentioned_only", "names the concept and a recommendation, no explanation of how they work"),

    # --- dangling/invalid access ---
    ("A dangling pointer results from dereferencing memory that has already been freed, leading to undefined behavior.",
     "dangling/invalid access", True, "meaningful", "real mechanism stated"),
    ("Invalid pointer access is undefined behavior; no further detail was found in this resource.",
     "dangling/invalid access", True, "shallow", "minimal but real, accurate definitional fact -- shallow, still genuinely covered"),
    ("The document briefly references dangling pointers as an interesting topic for further reading.",
     "dangling/invalid access", False, "mentioned_only", "explicitly deferred to 'further reading' -- not explained here"),

    # --- memory leak ---
    ("A memory leak occurs when dynamically allocated memory is never freed, causing the program to consume increasing memory over time.",
     "memory leak", True, "meaningful", "real mechanism stated"),
    ("Memory leaks are a well-known C++ pitfall.",
     "memory leak", False, "shallow", "vague, contentless mention"),
]


def run() -> None:
    true_positive = false_positive = true_negative = false_negative = 0
    disagreements: list[dict] = []

    for text, concept, ground_truth, category, note in CASES:
        variants = EXPECTED_CONCEPTS[concept]
        found, _ = check_concept_coverage({concept: variants}, entity_names=[], supported_claim_texts=[text])
        checker_says_covered = concept in found

        if ground_truth and checker_says_covered:
            true_positive += 1
        elif ground_truth and not checker_says_covered:
            false_negative += 1
            disagreements.append({"concept": concept, "category": category, "checker": "not_covered", "truth": "covered", "note": note, "text": text})
        elif not ground_truth and checker_says_covered:
            false_positive += 1
            disagreements.append({"concept": concept, "category": category, "checker": "covered", "truth": "not_covered", "note": note, "text": text})
        else:
            true_negative += 1

    total = len(CASES)
    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else None
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else None

    print(f"Benchmark size: {total} hand-labeled cases across {len(EXPECTED_CONCEPTS)} concepts\n")
    print(f"True positives:  {true_positive}")
    print(f"False positives: {false_positive}")
    print(f"True negatives:  {true_negative}")
    print(f"False negatives: {false_negative}")
    print(f"\nPrecision: {precision:.2f}" if precision is not None else "\nPrecision: n/a")
    print(f"Recall:    {recall:.2f}" if recall is not None else "Recall:    n/a")

    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s) between the mechanical checker and human judgment:")
        for d in disagreements:
            print(f"  [{d['category']}] concept={d['concept']!r} checker={d['checker']!r} truth={d['truth']!r}")
            print(f"    reason: {d['note']}")
            print(f"    text: {d['text']!r}")
    else:
        print("\nNo disagreements -- every case matched human judgment.")


if __name__ == "__main__":
    run()
