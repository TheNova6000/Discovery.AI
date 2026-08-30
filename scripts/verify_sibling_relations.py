"""Ad-hoc verification -- sibling-relation extraction pass (docs/Architecture.md
§0.22). Not a numbered Phases.md deliverable.

Root cause this fixes: `extract_relations` was only ever called with the ONE
entity currently being investigated ("entity under discussion") and that
entity's own answer text. Real literature (DocRED-style document-level RE,
GraphRAG's and LightRAG's production prompts, the documented entity-salience/
primacy bias in LLM extraction -- see docs/Architecture.md §0.22 for citations)
converges on the same diagnosis: anchoring extraction on one named "topic"
entity systematically suppresses relations between the OTHER entities
co-occurring in the same text, producing a hub-and-spoke graph instead of a
real network -- exactly the "always trees" symptom reported live.

Acceptance test (agreed before running), same text, two calls:

  1. OLD call shape: extract_relations("Client", known_text) with no sibling
     list. Expected (the bug): relations found, if any, all involve "Client" --
     "Client Bank -> Merchant Bank" (a real relation stated plainly in the
     text) should be MISSING.
  2. NEW call shape: extract_relations("Client", known_text,
     sibling_entity_names=["Client Bank", "Merchant Bank", "Merchant"]).
     Expected (the fix): a "Client Bank -[forwards_to/routes_to/...]->
     Merchant Bank" relation (or equivalent direct link between two entities
     that are NOT "Client") should now appear.

Graded by reading the actual extracted (source, relationship, target) triples
for a genuine sibling-to-sibling edge, not by asserting exact wording -- same
discipline as verify_working_framing.py and verify_dimension_steering.py.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions.llm_config import has_any_provider_key  # noqa: E402
from backend.questions.relation_extraction import extract_relations  # noqa: E402

KNOWN_TEXT = """\
A client wants to pay a merchant for goods purchased online. The client
initiates the payment from their own account. The client's bank receives the
payment request and forwards the funds to the merchant's bank over a clearing
network. The merchant's bank then credits the merchant's account once the
funds arrive, completing the transaction.
"""


def _print_candidates(label: str, candidates) -> None:
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    if not candidates:
        print("(no relations extracted)")
    for c in candidates:
        print(f"  {c.source_entity!r} -[{c.relationship_type}]-> {c.target_entity!r}  ({c.justification})")


def _has_non_client_sibling_edge(candidates) -> bool:
    return any(
        c.source_entity.strip().casefold() != "client" and c.target_entity.strip().casefold() != "client"
        for c in candidates
    )


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    old_shape = await extract_relations("Client", KNOWN_TEXT)
    _print_candidates("OLD call shape (no sibling_entity_names)", old_shape)

    new_shape = await extract_relations(
        "Client",
        KNOWN_TEXT,
        sibling_entity_names=["Client Bank", "Merchant Bank", "Merchant"],
    )
    _print_candidates("NEW call shape (sibling_entity_names given)", new_shape)

    print("\n" + "=" * 70)
    print("Checks to make by reading the above:")
    print("  1. OLD shape: any relation NOT involving 'Client' at all is a bonus,")
    print("     not expected -- the bug is that extraction anchors on the named")
    print("     entity, so it's fine (expected) if OLD finds zero sibling edges.")
    print("  2. NEW shape: should contain a direct edge between two entities that")
    print("     are BOTH not 'Client' (e.g. 'Client Bank' -> 'Merchant Bank') --")
    print(f"     found: {_has_non_client_sibling_edge(new_shape)}")
    print("  3. NEW shape should not have lost the genuine Client-anchored")
    print("     relations OLD shape found (no regression in recall).")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
