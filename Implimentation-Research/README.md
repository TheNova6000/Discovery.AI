# Implementation Research — Running This on $0 as a Student

This folder is a separate research track from `/docs` (the main PRD/Architecture/Rules/Phases/Design). Those docs assume a Claude API + Neo4j-Docker-locally stack, which costs real money at real usage and assumes a machine that can run things continuously. This folder answers a different question:

> **How do you actually run this as a B.Tech student with no AI API budget and a laptop too weak to run an LLM workload for hours/days at a time?**

Research was done live (web search against current 2026 pricing/free-tier pages, not assumptions) across three areas:

1. **[Free-LLM-APIs.md](./Free-LLM-APIs.md)** — which LLM providers have a real, no-card free tier good enough for the agent/Question Engine workload.
2. **[Free-Hosting-Compute.md](./Free-Hosting-Compute.md)** — where to run the backend + Neo4j so it's not sitting on your laptop.
3. **[India-Government-Programs.md](./India-Government-Programs.md)** — whether any Indian government/student-specific program is realistically usable (short answer: not this month, for a solo project).
4. **[Zero-Cost-Stack.md](./Zero-Cost-Stack.md)** — the consolidated, practical answer: what to actually set up, in order.

**Bottom line up front:** it's genuinely possible to run this for ₹0/month — a free Oracle Cloud VM running everything 24/7, with LLM calls round-robining across 2-3 free API providers. No Indian government program is worth pursuing for this right now; the global free tiers are faster and more reliable.
