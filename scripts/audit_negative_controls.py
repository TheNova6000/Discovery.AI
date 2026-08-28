"""Two negative-control experiments for `audit_synthesis` (docs/Memory.md's
content-provenance pass): Session 1 and Session 3's already-captured answers and
known material, verbatim from the real sessions' logged output. No new
investigation, no Neo4j. Exactly 2 LLM calls.

Acceptance bar (agreed before running):
- Session 1: synthesis was 1:1 with its 4 investigated children -> expect
  essentially everything "investigated".
- Session 3: this session's actual problem is claim RELATIONSHIPS (competing
  explanations flattened into false parity), NOT provenance -> expect
  essentially everything "investigated" too. If the auditor instead marks the
  contested/competing content (e.g. the regulatory-capture/"enshittification"
  claims) as "uninvestigated" just because it's contentious or hard to reconcile
  with the others, that would mean we accidentally built a truth/consensus
  detector instead of a provenance auditor -- a real, worth-reporting failure,
  not something to paper over.

One nuance already known before running: session 3's closing paragraph
("Conversely, companies fail or stagnate when...") was hand-classified as
Category C (reasonable inference from investigated material, not itself
investigated) in the original by-hand audit -- it's fine, and expected, if the
auditor marks that specific paragraph "uninvestigated". That's a correct,
narrow result, not a negative-control failure, since no child investigated
failure modes.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.questions import audit_synthesis  # noqa: E402
from backend.questions.llm_config import has_any_provider_key  # noqa: E402

# ---------------------------------------------------------------------------
# Session 1 -- Global Payment System
# ---------------------------------------------------------------------------

SESSION1_KNOWN = [
    "Sub-question: What is the underlying infrastructure and messaging mechanism that enables cross-border payments between "
    "different national banking systems?\n"
    "Answer: Cross-border payments between different national banking systems rely on a combination of correspondent banking "
    "networks, financial messaging standards, and payment rails.\n\n"
    "1. Messaging Mechanisms: The primary secure messaging network is SWIFT (Society for Worldwide Interbank Financial "
    "Telecommunication), which transmits standardized payment instructions (such as MT or ISO 20022 XML messages like pacs.008) "
    "between financial institutions. SWIFT itself does not move funds; it securely transmits the instructions to transfer money. "
    "Alternative messaging standards or newer instant cross-border links are also emerging.\n"
    "2. Underlying Infrastructure (Correspondent Banking): Because direct accounts between every bank in the world are "
    "impractical, banks use correspondent banking relationships. To send money from Country A (Currency A) to Country B "
    "(Currency B), the sending bank typically uses a chain of intermediary banks (correspondents) where accounts (nostro/vostro "
    "accounts) are held.\n"
    "3. Settlement Systems: Final settlement occurs through real-time gross settlement (RTGS) systems in the respective "
    "countries (e.g., Fedwire/CHIPS in the US, TARGET2 in the eurozone) or via multi-currency clearing and settlement platforms "
    "like CLS (Continuous Linked Settlement) for major foreign exchange transactions.",
    "Sub-question: How are foreign exchange (FX) and currency conversion handled and settled within cross-border payment "
    "flows?\n"
    "Answer: In cross-border payment flows, foreign exchange (FX) and currency conversion involve several sequential steps: "
    "pricing, execution, clearing, and settlement.\n\n"
    "1. Pricing and Quoting: When a payer initiates a cross-border payment in currency A to a beneficiary in currency B, the "
    "sending institution (or payment provider) provides an FX rate. This rate typically includes a wholesale market exchange "
    "rate plus a retail markup or margin (spread).\n"
    "2. Execution (Trading): The financial institution executing the transaction must acquire the target currency (currency B) "
    "by selling the source currency (currency A) in the FX market. For smaller retail flows, providers aggregate transactions "
    "and execute them in batches (netting); for large corporate flows, spot or forward contracts are executed individually.\n"
    "3. Clearing: The currencies must be routed through appropriate clearing mechanisms. For major currencies (USD, EUR, GBP, "
    "JPY), this often happens via correspondent banking networks using accounts held with correspondent banks (nostro/vostro "
    "accounts) or through specialized payment market infrastructures like CLS (Continuous Linked Settlement) which mitigates "
    "Herstatt risk (settlement risk) by ensuring simultaneous payment-versus-payment (PvP) settlement.\n"
    "4. Settlement: Final settlement occurs when the respective central bank money or commercial bank money changes hands in "
    "each currency jurisdiction. In traditional correspondent banking, the sending bank's account at its correspondent is "
    "debited, and the receiving bank's account is credited. In newer fintech or alternative rails, local liquidity pools "
    "pre-funded in multiple countries allow local payouts to be made instantly without traditional correspondent chains.",
    "Sub-question: How do compliance, anti-money laundering (AML), know-your-customer (KYC), and sanctions screening operate "
    "within global payment flows?\n"
    "Answer: Compliance, AML, KYC, and sanctions screening operate at multiple critical checkpoints throughout a global "
    "payment flow to prevent illicit finance and ensure legal adherence:\n\n"
    "1. Onboarding & KYC (Customer Verification): Before a transaction can even be initiated, payment service providers (PSPs) "
    "and financial institutions must verify the identity of their customers (both senders and beneficiaries). This involves "
    "collecting official identification, verifying addresses, and establishing the source of funds or nature of the business "
    "relationship.\n"
    "2. Transaction Monitoring & AML: Once a payment is initiated, transaction monitoring systems (TMS) continuously scan "
    "real-time payment messages and batch files for suspicious patterns, including unusual transaction volumes, structuring, "
    "or rapid movement of funds across high-risk jurisdictions.\n"
    "3. Sanctions Screening: Payment instructions are screened against domestic and international watchlists -- such as OFAC "
    "in the U.S., the EU consolidated list, and UN Security Council sanctions lists. This screening occurs both pre-transaction "
    "and in-flight.\n"
    "4. Intermediary and Correspondent Banking Controls: Each institution in the payment chain conducts its own layered "
    "screening and filtering. If a payment triggers a potential match, the transaction is intercepted, placed on hold, and "
    "manually reviewed by compliance specialists; confirmed violations are frozen and reported (SARs) to regulators such as "
    "FinCEN.",
    "Sub-question: What are the alternative payment rails and emerging technologies (such as blockchain networks, "
    "stablecoins, CBDCs, and instant cross-border linkages) that bypass or complement traditional correspondent banking?\n"
    "Answer: Alternative payment rails and emerging technologies are modernizing global finance by bypassing or complementing "
    "traditional correspondent banking systems (such as SWIFT). Key categories include:\n\n"
    "1. Blockchain Networks & Public Ledgers: Decentralized layer-1 and layer-2 networks (e.g., Ethereum, Solana, Polygon) "
    "enable peer-to-peer value transfer globally without relying on a chain of intermediary correspondent banks.\n"
    "2. Stablecoins: Cryptocurrencies whose value is pegged to a fiat currency (predominantly USD, e.g., USDT, USDC), "
    "allowing 24/7/365 cross-border remittances and B2B settlements at a fraction of traditional wire costs.\n"
    "3. Central Bank Digital Currencies (CBDCs): Digital forms of a country's sovereign currency issued directly by the "
    "central bank. Wholesale CBDCs facilitate instant interbank and cross-border settlements between central banks; retail "
    "CBDCs are designed for public use. Projects like Project mBridge demonstrate multi-CBDC platforms for direct "
    "cross-border FX delivery-versus-payment.\n"
    "4. Instant Cross-Border Linkages: Bilateral and multilateral integrations of domestic instant payment systems (e.g. "
    "Singapore's PayNow linked with Thailand's PromptPay, the Eurozone's TIPS infrastructure), cutting cross-border "
    "settlement times from days to seconds.",
]

SESSION1_ANSWER = (
    "A global payment system is a vast, multi-layered ecosystem of institutions, standards, networks, and technologies "
    "designed to transfer value securely and efficiently across individuals, businesses, and international borders. Based on "
    "the comprehensive investigation of its core components, a global payment system operates through four primary pillars:\n\n"
    "1. Underlying Infrastructure & Messaging: Traditional cross-border flows rely on correspondent banking networks (where "
    "banks maintain reciprocal nostro/vostro accounts) and secure financial messaging standards like SWIFT and ISO 20022 to "
    "transmit payment instructions. Final settlement happens through domestic Real-Time Gross Settlement (RTGS) systems or "
    "multi-currency platforms like CLS.\n"
    "2. Foreign Exchange (FX) & Currency Conversion: Cross-border transactions often require converting one sovereign currency "
    "to another. This involves pricing (wholesale rates plus retail spreads), execution (spot or batch trades), clearing via "
    "correspondent or PvP (payment-versus-payment) mechanisms, and final multi-currency settlement.\n"
    "3. Compliance, AML, KYC, and Sanctions Screening: Global payments are strictly regulated. Institutions enforce rigorous "
    "Know Your Customer (KYC) onboarding, real-time transaction monitoring for Anti-Money Laundering (AML), and rigorous "
    "in-flight screening against domestic and international sanctions lists (such as OFAC) to intercept illicit finance, "
    "freeze blocked assets, and file Suspicious Activity Reports (SARs).\n"
    "4. Alternative Rails & Emerging Technologies: To reduce the friction, high costs, and delays of traditional correspondent "
    "banking, the global payment landscape is increasingly adopting alternative rails. These include blockchain networks, "
    "fiat-pegged stablecoins (USDC, USDT), wholesale and retail Central Bank Digital Currencies (CBDCs), and multilateral "
    "instant cross-border payment linkages connecting domestic real-time payment systems directly.\n\n"
    "Together, these mechanisms ensure that money moves safely, compliantly, and rapidly across the globe, balancing "
    "traditional institutional trust with modern cryptographic and instant digital efficiencies."
)

# ---------------------------------------------------------------------------
# Session 3 -- Company Dominance
# ---------------------------------------------------------------------------

SESSION3_KNOWN = [
    "Sub-question: How do network effects create defensible moats that lead to market dominance?\n"
    "Answer: Network effects create defensible moats by creating a self-reinforcing feedback loop where the value of a "
    "product or service increases for every existing and future user as more people adopt it. This dynamic generates market "
    "dominance through several specific mechanisms:\n\n"
    "1. High Switching Costs & Lock-in: As a network grows, the utility a user derives from it often exceeds any "
    "alternative, making defection costly.\n"
    "2. The Winner-Take-All Dynamic: In markets with strong network effects, the leading platform captures the vast "
    "majority of new supply and demand, starving smaller rivals of the critical mass needed to survive.\n"
    "3. Data and Feedback Loops: Increased usage generates proprietary data that improves the product, creating a "
    "compounding advantage where the dominant player becomes better simply by being larger.\n"
    "4. Ecosystem & Complementary Asset Attraction: A large user base attracts third-party developers and merchants who "
    "build tools around the platform, deepening its moat.",
    "Sub-question: How do economies of scale and structural cost advantages enable companies to achieve and sustain market "
    "dominance?\n"
    "Answer: Economies of scale and structural cost advantages enable companies to achieve and sustain market dominance by "
    "driving down unit costs as production volume increases, creating powerful barriers to entry.\n\n"
    "1. Cost Advantages and Margin Expansion: As fixed costs are distributed across a larger volume of output, marginal "
    "cost declines, allowing dominant firms to price lower or enjoy higher margins to reinvest.\n"
    "2. Barrier to Entry and Scale Deficits for Entrants: New entrants face prohibitive capital expenditures to achieve "
    "comparable efficiency, forcing them into a structural disadvantage.\n"
    "3. Network and Ecosystem Reinforcement: Scale compounds with other advantages -- high volume attracts supplier "
    "discounts and deepens customer lock-in through integrated ecosystems.",
    "Sub-question: How do strategic pricing models, vertical integration, and regulatory strategies enable dominant "
    "companies to sustain market power and deter new entrants?\n"
    "Answer: Dominant platforms sustain market power and deter new entrants through a reinforcing loop of strategic "
    "pricing, vertical integration, and regulatory capture:\n\n"
    "1. Strategic Pricing & Subsidization: Dominant companies use predatory or subsidized pricing to rapidly scale and "
    "achieve network effects, then extract rents once switching costs are prohibitive (the core mechanism of "
    "'enshittification').\n"
    "2. Vertical Integration: By entering adjacent markets or acquiring potential competitors, dominant firms control "
    "critical infrastructure and gatekeeping functions, favoring their own internal services.\n"
    "3. Regulatory Capture: Dominant firms shape regulatory frameworks to protect their status, lobbying for complex "
    "compliance standards that create insurmountable regulatory moats for smaller startups.",
    "Sub-question: How do organizational culture, agile execution, and capital allocation capabilities distinguish "
    "companies that successfully scale and dominate from those that fail or stagnate?\n"
    "Answer: Companies that successfully scale and dominate markets differentiate themselves through an interdependent "
    "triad of organizational culture, agile execution, and capital allocation capabilities:\n\n"
    "1. Culture as an Operating System: Dominant companies (such as Amazon or Netflix) cultivate a culture of "
    "psychological safety, high accountability, customer obsession, and decentralized decision-making.\n"
    "2. Agile Execution & Architectural Speed: Elite executors align organizational structures and technical architectures "
    "to minimize cycle times, continuously testing hypotheses and deploying improvements quickly.\n"
    "3. Dynamic Capital Allocation: Dominant firms practice dynamic resource reallocation -- aggressively starving "
    "declining business units to fund high-upside bets -- while failing companies fall into incrementalism and rigid "
    "budgeting.",
]

SESSION3_ANSWER = (
    "Companies become dominant while others fail through the compounding interplay of structural moats, strategic "
    "execution, and organizational adaptability. Based on the extensive analysis above, market dominance is forged and "
    "sustained across four primary dimensions:\n\n"
    "1. Defensible Moats & Scale Dynamics: Dominant firms establish powerful self-reinforcing loops, notably network "
    "effects (where utility increases with adoption, creating winner-take-all dynamics and high switching costs) and "
    "economies of scale (where volume drives down unit costs and expands profit margins to fund continuous reinvention).\n"
    "2. Strategic Market Control & Defenses: Beyond natural scale, dominant players actively preserve their status through "
    "strategic pricing models (such as subsidizing growth to lock in users and later extracting rents), vertical "
    "integration (owning gatekeeping infrastructure and self-preferencing internal services), and regulatory capture "
    "(shaping compliance frameworks to deter startups).\n"
    "3. Internal Agility & Execution: Superior external market position is underpinned by internal operational "
    "capabilities -- specifically, an organizational culture of customer obsession and decentralized autonomy, agile "
    "execution architectures that minimize cycle times, and dynamic capital allocation that continuously starves legacy "
    "units to fund high-upside bets.\n\n"
    "Conversely, companies fail or stagnate when they fall into incrementalism, lack structural moats or network feedback "
    "loops, fail to scale efficiently against entrenched incumbents, or succumb to bureaucratic latency and rigid capital "
    "allocation. Dominance is therefore not a single static advantage, but an integrated, self-reinforcing system of "
    "structural power and organizational velocity."
)


def _report(label: str, expected: str, audit) -> None:
    investigated = [c for c in audit.claims if c.origin == "investigated"]
    uninvestigated = [c for c in audit.claims if c.origin == "uninvestigated"]
    print("\n" + "=" * 70)
    print(label)
    print(f"expected: {expected}")
    print("=" * 70)
    print(f"Total: {len(audit.claims)}   Investigated: {len(investigated)}   Uninvestigated: {len(uninvestigated)}")
    if uninvestigated:
        print("\n--- UNINVESTIGATED ---")
        for c in uninvestigated:
            print(f"  - {c.text}")


async def run() -> None:
    if not has_any_provider_key():
        print("[fail] No LLM provider key found in .env")
        raise SystemExit(1)

    session1_audit = await audit_synthesis(SESSION1_ANSWER, SESSION1_KNOWN)
    _report("SESSION 1 (negative control)", "~all investigated", session1_audit)

    session3_audit = await audit_synthesis(SESSION3_ANSWER, SESSION3_KNOWN)
    _report(
        "SESSION 3 (negative control)",
        "~all investigated (its real problem is claim relationships, not provenance; "
        "the closing 'conversely, companies fail...' paragraph may legitimately come "
        "back uninvestigated -- that's a correct inference-flag, not a failure)",
        session3_audit,
    )


if __name__ == "__main__":
    asyncio.run(run())
