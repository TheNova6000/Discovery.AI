# The ₹0/month Stack — Concrete Plan

Consolidating [Free-LLM-APIs.md](./Free-LLM-APIs.md), [Free-Hosting-Compute.md](./Free-Hosting-Compute.md), and [India-Government-Programs.md](./India-Government-Programs.md) into one setup order. This is a budget-tier substitution for `/docs/Architecture.md`'s consolidated stack — the layer boundaries, folder structure, and Rules.md guardrails from the main docs don't change, only which concrete provider fills the "LLM provider" and "hosting" rows.

## What changes from the main Architecture.md

| Layer | Main Architecture.md (paid) | Zero-cost substitution |
|---|---|---|
| LLM provider | Claude API, tiered by level | **Gemini Flash-Lite / Groq / Cerebras round-robin** (ground level), **Gemini 2.5 Flash / Cohere trial** (master level) — see Free-LLM-APIs.md |
| Graph store hosting | Local Docker on your machine | **Self-hosted Neo4j Community, in Docker, on a free Oracle Cloud VM** — not AuraDB Free (it pauses/deletes on inactivity) |
| Backend/agent runtime hosting | Local Docker on your machine | Same free Oracle Cloud VM, same docker-compose.yml already in this repo |
| Everything else (LanceDB, FastAPI, Cytoscape.js, asyncio+SQLite, litellm, Instructor) | Unchanged | Unchanged — these were already free/local and don't need substitution |

litellm (already the chosen LLM adapter in Architecture.md) supports Gemini/Groq/Cerebras/OpenRouter/Cohere natively, so no architectural rework is needed — only the provider config and an API-key rotation/fallback wrapper.

## Setup order

1. **Get free API keys** (all no-card, ~10 minutes total):
   - Google AI Studio → Gemini API key (aistudio.google.com)
   - Groq Console → API key (console.groq.com)
   - Cerebras Cloud → API key
   - Cohere trial key (for rare master-level calls)
2. **Sign up for Oracle Cloud Free Tier** (needs a real, non-prepaid card for a $1 verification hold — no charge). Provision one Ampere A1 instance, 2 OCPU / 12GB RAM, Always Free shape.
   - If the card requirement is a hard blocker: use GitHub Student Developer Pack → Azure for Students ($100 credit, no card, needs college email) → a small B1s VM instead.
3. **On the VM**: install Docker + Docker Compose, `git clone` this project (or `scp` it over), run the existing `docker-compose.yml` (it already defines the Neo4j service — no changes needed there).
4. **Point the backend's `.env` at the round-robin LLM config** instead of a single Claude key: `GEMINI_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `COHERE_API_KEY`. Build the litellm client with fallback-on-429 across them (Free-LLM-APIs.md — every free tier is capped low enough to hit limits during real use, so build this in from day one, not as an afterthought).
5. **Open the VM's port** (8000 or 443) in Oracle's security list so the FastAPI backend/Cytoscape.js frontend is reachable from your laptop's browser.
6. **For occasional heavy runs** (a big multi-agent investigation you want to run fast): use a Colab or Kaggle notebook that connects to the VM's Neo4j bolt port over the internet, do the heavy LLM/embedding work there using their free GPU/CPU burst, and let results write back into the persistent graph on the VM.
7. **For scheduled light background work** (e.g. periodic boundary-expansion checks) instead of keeping a laptop on: a GitHub Actions cron workflow hitting the VM's API, within the 2,000 free minutes/month.

## What this does NOT solve

- **Rate limits will be hit regularly.** This is a real constraint of running on free tiers, not a bug — the system should treat a 429 as an expected, handled condition (Rules.md's error-handling conventions already require graceful degradation; extend that same principle to LLM calls, not just retriever calls).
- **No Indian government program shortcuts this** (see India-Government-Programs.md) — don't spend time chasing IndiaAI Compute or NVIDIA Inception for this project; they're gated for startups/institutions, not solo students.
- **This is still a single small VM.** It's fine for a personal research tool investigating one abstraction at a time with a small spawn budget (which Rules.md already mandates for other reasons) — it is not going to comfortably run a large, broad, many-agent investigation. That's a feature, not a gap: the spawn-budget and lazy-generation rules in Rules.md exist partly *because* real production systems hit cost problems at scale, and they double as the thing that keeps this runnable on a free 2-core VM.
