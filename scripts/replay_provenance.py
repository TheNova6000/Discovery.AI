"""Replay `trace_claim` against the three real learning sessions' already-persisted
SQLite state (docs/Memory.md's provenance workstream). Zero new API calls — this
is exactly the "verify against existing traces before deciding storage" step
agreed on. Prints each session's provenance tree so the structural classification
can be checked by eye against the A/B/C/D audit already done by hand:

  Session 1 (payment system)   -> expected: synthesized root, 4 direct/derived
                                   children, no visible content gap.
  Session 2 (central bank)     -> expected: DERIVED root (only 1 child) whose
                                   answer text visibly covers far more than that
                                   one child investigated — the exact gap found
                                   by hand, now visible structurally instead.
  Session 3 (company dominance) -> expected: synthesized root, 4 clean children,
                                   no coverage gap (the unresolved problem here is
                                   relationships between claims, not provenance —
                                   out of scope for this tool by design).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.agents import ClaimProvenance, find_root_agent_id, trace_claim  # noqa: E402

SESSIONS = [
    ("Session 1 — Global Payment System", "session_global_payment_system.sqlite3"),
    ("Session 2 — Central Bank Rates", "session_central_bank_rates.sqlite3"),
    ("Session 3 — Company Dominance", "session_dominant_companies.sqlite3"),
]


def _print_tree(node: ClaimProvenance, indent: int = 0) -> None:
    pad = "  " * indent
    answer_preview = (node.answer or "")[:80].replace("\n", " ")
    print(f"{pad}[{node.provenance_type}] {node.question_text}")
    if node.answer:
        print(f"{pad}   answer preview: {answer_preview}...")
    if node.evidence:
        print(f"{pad}   evidence: {len(node.evidence)} claim(s)")
    for child in node.derived_from:
        _print_tree(child, indent + 1)


async def run() -> None:
    for label, db_path in SESSIONS:
        if not pathlib.Path(db_path).exists():
            print(f"[skip] {label}: {db_path} not found")
            continue
        root_id = await find_root_agent_id(db_path)
        trace = await trace_claim(root_id, db_path=db_path)

        print("\n" + "=" * 70)
        print(label)
        print("=" * 70)
        _print_tree(trace)
        print(f"\n  Root provenance_type: {trace.provenance_type}")
        print(f"  Direct children investigated: {len(trace.derived_from)}")
        answer_len = len(trace.answer or "")
        child_answer_len = sum(len(c.answer or "") for c in trace.derived_from)
        print(f"  Root answer length: {answer_len} chars vs. sum of children's answer lengths: {child_answer_len} chars")


if __name__ == "__main__":
    asyncio.run(run())
