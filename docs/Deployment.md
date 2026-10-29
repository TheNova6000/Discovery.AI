# Running Discovery.AI offline and online

One repository, two ways to run it. The **same files** serve both; which mode
a page uses is decided by where it is served from (`frontend/runtime-config.js`),
and which features the backend switches on is decided by environment variables.

| | **Offline** (local / your own machine or VM) | **Online** (public website) |
|---|---|---|
| Link | `http://localhost:8000` (or your VM's address) | Website **https://discovery-ai.vercel.app** · API **https://discovery-ai-bosm.onrender.com** |
| Frontend | served by the backend itself (same origin) | Vercel (static), calls the Render API |
| Backend | `uvicorn backend.api.app:app` on your machine | Render web service (`render.yaml`) |
| Login | off | Google login via Supabase |
| Graph | Neo4j: local Docker or your own Aura instance | Neo4j Aura |
| Sessions | in memory | Postgres (`DATABASE_URL`, Supabase) |
| Dewey Archive / research jobs / chat sessions | SQLite files at the repo root, **kept between runs** | SQLite on Render's disk, **reset on every deploy/restart** (see Caveats) |

## How the frontend picks a mode
`frontend/runtime-config.js` is loaded by every page before anything else:

- served from `localhost`, `127.0.0.1`, a LAN/VM IP, or `file://` → **offline**:
  backend = same origin, login off;
- served from `*.vercel.app` (production and branch previews) → **online**:
  backend = Render, login on;
- `?mode=offline` / `?mode=online` on any page URL forces a mode for testing.

To point the website at another backend or Supabase project, edit the `ONLINE`
block in that one file. Nothing else in the frontend hard-codes a backend.

## Offline: run it locally
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in NEO4J_* and at least one key pool (GROQ_API_KEYS / GEMINI_API_KEYS)
# leave SUPABASE_URL, CORS_ORIGINS, DATABASE_URL blank -> no login, same origin, in-memory sessions
uvicorn backend.api.app:app --reload
# open http://localhost:8000
```
Neo4j Aura note: for instances created from 2025 on, `NEO4J_USER` is the
**instance id** (the first part of `neo4j+s://<id>.databases.neo4j.io`), not `neo4j`.

To run with no network at all for page reading, set `DEWEY_FETCH=off`; the
Archive still answers from what it already holds.

## Online: the public website
Set up once with the runbook in `README.md` ("Deploying publicly, with Google
login"). After that:

- **Backend (Render)** builds from `render.yaml`. Environment to check after this
  release:
  - `NEO4J_URI`, `NEO4J_USER` (instance id for new Aura instances), `NEO4J_PASSWORD`:
    the old Aura instance referenced in earlier configs no longer exists.
  - `GROQ_API_KEYS`, `GEMINI_API_KEYS` (comma-separated pools); single-key
    `GROQ_API_KEY` / `GEMINI_API_KEY` still work.
  - `SUPABASE_URL`, `DATABASE_URL`, `CORS_ORIGINS` (must include `https://discovery-ai.vercel.app`).
- **Frontend (Vercel)** serves `frontend/` as static files; no build step.
- Deploys happen when `main` changes (and Vercel builds a preview for each branch).

## What runs where
| Component | Code | Offline | Online |
|---|---|---|---|
| Discovery.AI demo UI (chat, graph, roadmap, docs) | `frontend/*.html`, routes in `backend/api/app.py` | ✓ | ✓ |
| Main block: reasoning engine + research engine + door | `backend/main_block/` (routes `/mainblock/...`) | ✓ | ✓ |
| Tuni'n chat model API | `backend/chat/` (routes `/tunin/chat/...`) | ✓ | ✓ (API only; its UI is the owner's upcoming frontend) |

## Caveats (online)
- **Ephemeral disk on Render's free tier:** the Dewey Archive, research jobs and
  chat sessions are SQLite files, so online they start empty after each deploy or
  restart, and the Archive re-grows from searches. Offline they persist. A
  Postgres-backed store (the Archive already sits behind `ArchiveStore`) is the
  path to persistence online.
- **Free-tier limits:** Render sleeps after inactivity (first request can take
  about a minute); Gemma/Groq free quotas vary day to day, and the key pool falls
  through providers when one is exhausted.
- **Long research jobs** run in the web process; one at a time
  (`MAINBLOCK_MAX_CONCURRENT_JOBS=1`) protects free quota and memory.
