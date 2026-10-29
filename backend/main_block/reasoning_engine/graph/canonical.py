"""Deterministic entity-name canonicalisation (loop iteration 02, E4).

Live BST runs created "BST Property" and "the BST property", "BST" next to
"Binary search tree", and "BinarySearchTreeOperations" next to "BST operations"
-- because `find_or_create_entity` only matched exact names. This is the cheap,
no-LLM first stage of EDC's Canonicalize step (Zhang & Soh, EMNLP 2024): reduce
each name to a canonical key, and expand acronyms against existing multi-word
entities. Cases that need meaning rather than spelling ("root" vs "root node",
"BST Invariant" vs "BST Property") are left for an LLM merge decision
(Mem0-style ADD/MERGE/NOOP), never guessed here.
"""

from __future__ import annotations

import re

_ARTICLES = frozenset({"the", "a", "an"})
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_TOKEN = re.compile(r"^[A-Z][A-Z0-9]{1,5}s?$")


def _singular(token: str) -> str:
    if len(token) <= 3 or token.endswith(("ss", "us", "is")):
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("ses") or token.endswith("xes"):
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def name_tokens(name: str) -> list[str]:
    """camelCase split, lowercase, punctuation and articles dropped, singular."""
    spaced = _CAMEL.sub(" ", name)
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t and t not in _ARTICLES]
    return [_singular(t) for t in tokens]


def canonical_key(name: str) -> str:
    return " ".join(name_tokens(name))


def acronym_of(name: str) -> str | None:
    """Initials of a multi-word name ("Binary search tree" -> "bst"); None for one word."""
    tokens = name_tokens(name)
    return "".join(t[0] for t in tokens) if len(tokens) >= 2 else None


def acronym_tokens(name: str) -> list[str]:
    """Tokens written as acronyms in the original name ("BST operations" -> ["bst"])."""
    out = []
    for raw in re.split(r"[^A-Za-z0-9]+", name):
        if _ACRONYM_TOKEN.match(raw):
            out.append(raw.rstrip("s").lower() if raw.endswith("s") and raw[:-1].isupper() else raw.lower())
    return out


def expand_acronyms(name: str, expansions: dict[str, str]) -> str:
    """Canonical key with acronym tokens replaced by the canonical key of the
    entity they abbreviate (`expansions`: acronym -> that entity's key)."""
    acronyms = set(acronym_tokens(name))
    words: list[str] = []
    for token in name_tokens(name):
        words.append(expansions[token] if token in acronyms and token in expansions else token)
    return " ".join(words)
