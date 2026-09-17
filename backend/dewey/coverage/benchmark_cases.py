"""The Dewey Source Pack coverage-checker benchmark -- persisted permanently
(docs/Memory.md, 2026-09-17: "The 27 hand-labeled cases are now valuable.
Preserve them permanently"). Originally hand-labeled inline in
`scripts/evaluate_coverage_checker_precision.py` (Experiment C); moved here
so any current or future checker (`lexical_candidate_checker_v0`, and later
`semantic_coverage_checker_v1`) can be scored against the same real,
unmodified ground truth, and so the benchmark itself is a first-class,
reviewable artifact rather than a script-local constant.

Ground truth is a human judgment call, stated as such -- each case's
`covered` label is what a person reading the claim text would reasonably
conclude about whether THAT SPECIFIC concept is genuinely explained (not
just present as a word), and `note` records why, so a disagreement with a
future reader is a real discussion, not an unstated assumption.

`category` follows the design conversation's own proposed taxonomy. The
original 5 categories (meaningful / mentioned_only / negated / shallow /
adversarial_unrelated) are all that exist as of this writing -- the design
conversation's fuller proposed 10-category taxonomy (adding: exact
definition vs. exact explanation as distinct categories, cross-domain phrase
collision as distinct from adversarial_unrelated, related-but-distinct
concept, contradictory evidence, multi-claim partial coverage) is a real,
explicit TODO for Phase C.3, not yet represented here -- expand `CASES`
rather than starting a second list when that work happens.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkCase:
    text: str
    concept: str
    covered: bool
    category: str
    note: str


CASES: list[BenchmarkCase] = [
    # --- pointer ---
    BenchmarkCase(
        "In C++, a pointer is a variable that stores the memory address of another variable.",
        "pointer", True, "meaningful", "real definition, mechanism stated",
    ),
    BenchmarkCase(
        "This resource mentions pointers only in passing while discussing arrays.",
        "pointer", False, "mentioned_only", "explicitly says 'in passing' -- no real content",
    ),
    BenchmarkCase(
        "The document does not explain what a pointer is.",
        "pointer", False, "negated", "explicit negation",
    ),

    # --- reference ---
    BenchmarkCase(
        "A reference in C++ is an alias for an existing variable, established at declaration and immutable afterward.",
        "reference", True, "meaningful", "real definition, mechanism stated",
    ),
    BenchmarkCase(
        "Unlike Java, C++ has a distinct reference type, though this document does not go into how it differs from a pointer.",
        "reference", False, "mentioned_only", "existence stated, explanation explicitly withheld",
    ),
    BenchmarkCase(
        "Python's garbage collector automatically manages memory using reference counting and cycle detection.",
        "reference", False, "adversarial_unrelated",
        "about Python GC, not C++ references -- 'reference counting' contains the literal substring 'reference'",
    ),

    # --- dereference ---
    BenchmarkCase(
        "Dereferencing a pointer with the * operator accesses the value stored at the address the pointer holds.",
        "dereference", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "The article title mentions dereference operators but the retrieved snippet was truncated before any explanation.",
        "dereference", False, "mentioned_only", "explicitly truncated/no explanation",
    ),

    # --- pointer arithmetic ---
    BenchmarkCase(
        "Incrementing a pointer by one actually advances it by sizeof(T) bytes, enabling array traversal via pointer arithmetic.",
        "pointer arithmetic", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "Pointer arithmetic is a common source of undefined behavior; no further detail was found in this resource.",
        "pointer arithmetic", False, "shallow", "names a risk, states no real mechanism -- explicitly says no further detail found",
    ),

    # --- array/pointer decay ---
    BenchmarkCase(
        "An array name decays to a pointer to its first element when passed to a function, losing its size information.",
        "array/pointer decay", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "Arrays and pointers are related in C++.",
        "array/pointer decay", False, "shallow", "vague, contentless mention",
    ),

    # --- dynamic allocation (the real, exact text from the live 2026-09-17 run) ---
    BenchmarkCase(
        "The new operator allocates memory on the heap and returns a pointer to the newly constructed object; delete releases it.",
        "dynamic allocation", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "The resource explains how the new operator allocates and initializes objects dynamically, but it does not cover delete, malloc, free, or smart pointers.",
        "dynamic allocation", True, "meaningful",
        "REAL case from the live run -- genuinely explains `new`, the disclaimer is about OTHER things, not this concept",
    ),
    BenchmarkCase(
        "Memory can be allocated in various ways in C++.",
        "dynamic allocation", False, "shallow", "vague, contentless mention",
    ),

    # --- stack and heap ---
    BenchmarkCase(
        "Automatic (stack) storage duration objects are destroyed when they go out of scope, while heap-allocated objects persist until explicitly freed.",
        "stack and heap", True, "meaningful", "real mechanism stated for both",
    ),
    BenchmarkCase(
        "This resource discusses object lifetime without clearly distinguishing stack from heap allocation.",
        "stack and heap", False, "negated", "explicit hedge that the distinction isn't made",
    ),

    # --- lifetime/ownership ---
    BenchmarkCase(
        "An object's lifetime begins when its constructor completes and ends when its destructor is invoked; ownership determines which code is responsible for that destruction.",
        "lifetime/ownership", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "Ownership models are important in modern C++ but are outside the scope of this reference page.",
        "lifetime/ownership", False, "negated", "explicit scope exclusion",
    ),

    # --- smart pointer (the real, exact text from the live 2026-09-17 run -- the actual bug) ---
    BenchmarkCase(
        "std::unique_ptr owns a dynamically allocated object exclusively and automatically deletes it when it goes out of scope, implementing RAII.",
        "smart pointer", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "The resource explains how the new operator allocates and initializes objects dynamically, but it does not cover delete, malloc, free, or smart pointers.",
        "smart pointer", False, "negated",
        "REAL false-positive case from the live run -- explicit negation, 'smart pointers' only appears as something NOT covered",
    ),
    BenchmarkCase(
        "Smart pointers such as unique_ptr and shared_ptr are recommended over raw pointers.",
        "smart pointer", False, "mentioned_only", "names the concept and a recommendation, no explanation of how they work",
    ),

    # --- dangling/invalid access ---
    BenchmarkCase(
        "A dangling pointer results from dereferencing memory that has already been freed, leading to undefined behavior.",
        "dangling/invalid access", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "Invalid pointer access is undefined behavior; no further detail was found in this resource.",
        "dangling/invalid access", True, "shallow", "minimal but real, accurate definitional fact -- shallow, still genuinely covered",
    ),
    BenchmarkCase(
        "The document briefly references dangling pointers as an interesting topic for further reading.",
        "dangling/invalid access", False, "mentioned_only", "explicitly deferred to 'further reading' -- not explained here",
    ),

    # --- memory leak ---
    BenchmarkCase(
        "A memory leak occurs when dynamically allocated memory is never freed, causing the program to consume increasing memory over time.",
        "memory leak", True, "meaningful", "real mechanism stated",
    ),
    BenchmarkCase(
        "Memory leaks are a well-known C++ pitfall.",
        "memory leak", False, "shallow", "vague, contentless mention",
    ),
]
