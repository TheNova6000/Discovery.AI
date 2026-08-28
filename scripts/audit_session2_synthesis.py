"""One isolated experiment (docs/Memory.md's content-provenance design pass): run
`audit_synthesis` against Session 2's ALREADY-CAPTURED answer and known material —
verbatim from the real session's logged output, not re-run. No new investigation,
no Neo4j, no new schema family. One LLM call.

Acceptance bar (agreed before running): the policy-tools content should come back
"investigated" (it's exactly what the one real child investigated), and the five
transmission-channel claims (interbank markets, bank-lending pass-through, asset
prices, exchange rates, forward guidance) should come back "uninvestigated" — not
because they're false, but because no child ever looked at them and no evidence
was gathered for them. If the auditor instead marks everything "investigated," or
marks things incorrectly, that's real evidence about whether an LLM auditor can
do this task at all — not a reason to redesign the architecture on the spot.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import audit_synthesis  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402

KNOWN = [
    "Sub-question: What specific policy tools and mechanisms does a central bank use to set and influence short-term interest rates?\n"
    "Answer: A central bank primarily uses several specific policy tools and mechanisms to influence and set short-term interest rates:\n\n"
    "1. Open Market Operations (OMOs): The central bank buys or sells short-term government securities (such as Treasury bills) in the "
    "open market. Buying securities injects reserves into the banking system, increasing the supply of funds and pushing short-term "
    "interest rates (like the federal funds rate) down. Selling securities drains reserves, tightening liquidity and pushing rates up.\n\n"
    "2. Policy Rate / Interest on Reserves (IOR): Central banks set a target for a benchmark overnight interest rate and use administered "
    "rates—such as interest paid on commercial bank reserves held at the central bank—to establish a floor or anchor for "
    "short-term market rates. Banks will not lend in the interbank market below what they can risk-free earn by keeping funds at the "
    "central bank.\n\n"
    "3. Standing Facilities (Discount Window / Lending Facility): These facilities allow eligible financial institutions to borrow "
    "reserves directly from the central bank, typically overnight, to address acute liquidity shortfalls. The lending rate (discount rate) "
    "often acts as a ceiling for short-term market interest rates, as banks can borrow directly from the central bank rather than paying "
    "higher rates in the market.\n\n"
    "4. Reserve Requirements: By mandating the minimum fraction of customer deposits that commercial banks must hold as reserves (either "
    "in vault cash or at the central bank), the central bank structurally alters the baseline demand for liquid funds, though many modern "
    "central banks now operate under \"ample reserves\" frameworks where direct reserve requirement ratios play a lesser day-to-day role "
    "than administered rates."
]

ANSWER = (
    "Building upon the fundamental mechanisms of policy rates, open market operations, and standing facilities, the central bank's "
    "control of interest rates ripples through the broader economy via several interconnected channels:\n\n"
    "1. The Interbank and Wholesale Funding Markets: Changes to the central bank's policy rate directly alter the cost of overnight "
    "interbank borrowing. Because banks rely on wholesale markets for short-term liquidity management, shifts in the overnight rate "
    "immediately benchmark other short-term instruments like commercial paper, repurchase agreements (repos), and short-term certificate "
    "of deposits.\n\n"
    "2. Bank Lending and Deposit Rates (The Pass-Through Channel): As wholesale funding costs shift, commercial banks adjust the interest "
    "rates they offer on consumer and corporate deposits as well as the rates they charge on loans (such as prime rates, adjustable-rate "
    "mortgages, and credit card APRs). Higher central bank rates increase the cost of credit, dampening borrowing and spending by "
    "households and businesses; lower rates reduce borrowing costs, stimulating economic activity.\n\n"
    "3. Asset Prices and Wealth Effects: Interest rates dictate the discount rate used to value financial assets. Higher rates reduce the "
    "present value of future corporate cash flows, often leading to lower stock prices and tighter financial conditions. Conversely, "
    "lower rates boost asset valuations, fostering a positive wealth effect that encourages consumer spending and business investment.\n\n"
    "4. The Exchange Rate Channel: Higher domestic interest rates relative to foreign counterparts attract international capital seeking "
    "higher yields, increasing demand for the domestic currency and leading to appreciation. An appreciated currency makes imports cheaper "
    "and exports more expensive, which can help cool domestic inflation. Lower rates tend to have the opposite effect, depreciating the "
    "currency and supporting export-oriented sectors.\n\n"
    "5. Expectations and Forward Guidance: Central banks do not just influence current rates; they actively manage future rate "
    "expectations through forward guidance. By signaling their future policy path, they influence longer-term interest rates (like "
    "10-year Treasury yields or fixed mortgages) immediately, long before any actual policy rate change takes effect."
)


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    audit = await audit_synthesis(ANSWER, KNOWN)

    investigated = [c for c in audit.claims if c.origin == "investigated"]
    uninvestigated = [c for c in audit.claims if c.origin == "uninvestigated"]

    print("=" * 70)
    print(f"Total atomic claims extracted: {len(audit.claims)}")
    print(f"Investigated: {len(investigated)}   Uninvestigated: {len(uninvestigated)}")
    print("=" * 70)

    print("\n--- INVESTIGATED ---")
    for c in investigated:
        print(f"\n[investigated] {c.text}")

    print("\n--- UNINVESTIGATED ---")
    for c in uninvestigated:
        print(f"\n[uninvestigated] {c.text}")

    print("\n" + "=" * 70)
    print("Expected: policy-tools content -> investigated.")
    print("Expected: interbank/bank-lending/asset-price/exchange-rate/forward-")
    print("guidance content -> uninvestigated (not false — just not traced to KNOWN).")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
