# Free Cloud Compute & Hosting (verified 2026)

The core problem this solves: **the agent runtime and Neo4j need to run continuously (potentially for hours/days of background investigation), and a weak personal laptop can't do that.** The fix is to host everything on a free always-on cloud VM instead of the laptop — the laptop becomes just a terminal/browser for checking in.

## Options, evaluated honestly

| Option | Real free tier? | Catch |
|---|---|---|
| **Oracle Cloud "Always Free" (Ampere A1, ARM)** | Yes, perpetual, no time limit | **Quietly halved June 15, 2026**: now 2 OCPUs / 12GB RAM total (down from the old 4/24) — still enough for Neo4j + FastAPI + agent runtime together. Needs a real (non-prepaid) credit/debit card for a $1 verification hold at signup — no charge unless you explicitly upgrade. |
| **Neo4j AuraDB Free** | Yes, no card, 200k nodes / 400k relationships | **Auto-pauses after 3 days of inactivity; permanently deleted after 90 days paused.** A real trap for a "resumable, persistent" prototype that isn't used daily — avoid unless you're pinging it constantly. |
| **GitHub Student Developer Pack** | Yes | DigitalOcean's credit was **retired Aug 2026**. Still includes Azure for Students, MongoDB Atlas credits, JetBrains, Codespaces boost. Needs school-email/enrollment verification. |
| **GitHub Codespaces** | 120 core-hours/month free personal quota (~60 hrs on a 2-core box) | Good for development, **not a persistent public endpoint** — closes when you're not using it. |
| **GitHub Actions** | 2,000 free minutes/month, jobs capped ~6 hrs each | Usable as a **cron-triggered batch runner** (e.g. "run one investigation pass every N hours"), not an always-on service. |
| **Fly.io free tier** | **Gone** (2024) — now just a 2 VM-hour/7-day trial | Not usable as ongoing hosting. |
| **Railway free tier** | **Gone** (2023) — one-time $5 credit only | Not usable as ongoing hosting. |
| **Render free web service** | Still exists | **Spins down after 15 min idle**, 30-60s cold start on next request — workable for the frontend/API but bad for anything that needs to stay "awake" doing background agent work. |
| **Azure for Students** | $100 credit, **no card required**, school-email verified, valid 12 months | Real and low-friction — good backup if Oracle's card requirement is a blocker. |
| **AWS Educate** | No longer grants cloud credits since 2023 (training content only now) | Not usable. |
| **Google Colab / Kaggle Notebooks** | Real free GPU bursts (Colab ~15-30 GPU-hrs/week dynamically, ~12hr session cap; Kaggle separate 30 hrs/week) | **No persistent public endpoint**, sessions disconnect after ~90 min idle — only good for occasional heavy one-off batch jobs, not hosting the app. |

## Recommended free architecture

**Run everything on one Oracle Cloud Always Free VM (2 OCPU / 12GB RAM ARM), self-hosting Neo4j Community in Docker instead of using AuraDB.** This sidesteps AuraDB's pause/delete trap entirely and runs genuinely 24/7 for $0 forever:

```
Oracle Cloud "Always Free" VM (Ampere A1, 2 OCPU / 12GB RAM)
├── docker-compose:
│   ├── Neo4j Community (self-hosted — same docker-compose.yml already in this repo)
│   ├── FastAPI backend + agent runtime (asyncio + SQLite, as already designed)
│   └── (LanceDB is just local files — no extra service needed)
└── Reachable over the internet via the VM's public IP (open port 8000/443 in the security list)
```

- **Backup path** if Oracle's card requirement is a hard blocker: Azure for Students' $100 credit → a small B1s VM, same Docker Compose setup. $100 covers many months at B1s pricing.
- **Heavy batch bursts** (e.g. a big one-off multi-agent investigation you want to run fast rather than throttled by the VM's 2 cores): rotate Colab and Kaggle notebooks, pointing them at the same Neo4j instance over its public bolt port, then let results settle back into the persistent graph on the VM.
- **Scheduled light jobs** (e.g. "check for new abstraction-expansion requests every few hours" instead of a laptop staying on): GitHub Actions cron workflow, 2,000 free minutes/month, calling into the VM's API.

This means the laptop's weakness stops mattering entirely — it only needs to SSH in or hit a browser UI; all real computation and the always-on Neo4j instance live on the free VM.
