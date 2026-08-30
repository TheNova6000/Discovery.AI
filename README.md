# Discovery.AI

**We built an AI knowledge system that refuses to reduce knowledge to a tree.**

Ask a question in plain language. Discovery.AI recursively investigates it — deciding, one step at a
time, whether to answer directly, break it into a sharper sub-question, or admit it's hit a real
boundary — and builds a persistent, typed knowledge graph in Neo4j from what it actually finds: real
entities, real typed relationships, real retrieved evidence with honest confidence scores.

The part that makes it different from every other "AI knowledge graph" demo: **the same world model can
be explored at different scopes, through different relationship lenses, without ever forking into a
second graph.** Topology — whether a region reads as a tree, a network, a DAG, a cycle, or a mesh — is
never assigned. It's derived, live, from which relationship *types* connect which entities.

## The core example

Enter `Authorization` inside a real, live payment investigation, and it holds two genuinely different,
both-true topologies at once:

```
COARSE SCOPE (Authorization's siblings)
Risk Checks --PRECEDES--> Authorization --PRECEDES--> Capture --PRECEDES--> Clearing --PRECEDES--> Settlement

                              │
                          enter Authorization
                              ▼

FINE SCOPE (Authorization's own internals)
Enforcement --QUERIES--> Engine --EVALUATES--> Policies --EXPRESS--> XACML
```

Same entity. Same world model. Zero duplication. The temporal chain doesn't disappear when you step
inside — it stays visible as dimmed context, honestly.

## Architecture

![Discovery.AI architecture: natural-language question flows through investigation into a persistent world model (nodes, typed relationships, evidence and confidence), which branches into composition, interaction, and temporal relation families feeding Graph Spaces, networks, and flows; a separate view/projection layer (focus, enter space, projection) reads that same world model with zero writes and zero LLM calls, producing the bounded view rendered by Cytoscape.](docs/assets/architecture-diagram.jpg)

**World Model ≠ View.** The graph in Neo4j is written once, by investigation, and never rebuilt when a
user zooms, enters a box, or switches projection — those are reads over the same stored facts, never a
new graph.

- **Composition** relationships create nested "Graph Spaces" (boxes an entity's own subgraph lives inside)
- **Interaction, temporal, causal, dependency** relationships stay as ordinary edges, crossing box
  boundaries freely — an interaction never gets mistaken for containment
- **Focus** (a small, readable, bounded neighborhood) and **Enter Space** (step inside an entity's own
  compositional subgraph) are two parameterizations of one general bounded-reachability primitive, not two
  separate mechanisms
- **Projections** filter the current view down to one relation family (structure / flow / causal /
  dependency / network) — zero new LLM calls, zero graph writes, and an honest "nothing of this kind here
  yet" message instead of silently investigating more
- A bounded view is allowed to be incomplete; it is **never allowed to imply completeness** — any node
  with real structure just outside the current view carries a visible disclosure marker

## What we actually verified (not just claimed)

- **10/10** on a synthetic topology test suite — tree, network, DAG, cycle, nested boxes, cross-space
  edges, a workflow with a retry cycle, a nested workflow, a hub, and a mesh — fed directly into the
  renderer with no LLM, no database, and no investigation in the loop
- A real natural-language investigation ("how do PayPal, Mastercard, banks, and merchants interact")
  produced a genuine network, and incidentally regression-tested a real bug we'd found and fixed earlier:
  an *interaction* edge (`PayPal USES Mastercard`) had been rendering as *containment* (Mastercard trapped
  inside PayPal's own box) — fixed by making only compositional relationships create boxes
- A real investigation about a payment lifecycle **broke**: the agent's own reasoning correctly narrated a
  sequence of steps, but the graph stored a flat tree with zero ordering between them. Traced to the exact
  cause — the relation-extraction prompt never mentioned sequence as a category — fixed with one
  paragraph, and re-verified directly against Neo4j that a genuine `PRECEDES` chain now extracts where
  none did before
- Mined the project's own accumulated graph (278 nodes, 253 edges across every topic ever investigated)
  and found non-tree structure had already formed on its own: a real 5-node cycle, convergence points that
  correctly resolved to the same node across five separately-run investigations, and nodes routinely
  participating in more than one relation family at once
- The full write-up of every verification pass — including the ones that failed on the first attempt — is
  live on the deployed app's own `/docs#reports` page and in `docs/Memory.md`

## Docs map

| File | What's in it |
|---|---|
| `docs/Architecture.md` | The numbered research/design log (§0.1–§0.34): every architectural decision, why it was made, and what it's grounded in |
| `docs/Memory.md` | The detailed, chronological verification record — every test, every result, every bug found and fixed |
| `docs/DemoScript.md` | The exact live demo sequence, verified reproducible without depending on LLM provider quota |
| `docs/DevpostSubmission.md` / `docs/DevpostSubmission_Short.md` | The submission narrative, full and compressed |
| `/docs` on the deployed app | The public-facing version: theory, architecture, the topology test matrix with live diagrams, and a running reports log |

## Tech stack

Python · FastAPI · Neo4j · Groq / Google Gemini / Cerebras (free-tier LLM fallback chain via Instructor) ·
Cytoscape.js (graph rendering, fCoSE layout) · Supabase (auth + session storage) · SQLite (agent state) ·
vanilla JS/HTML/CSS, no build step

## Running it locally

This is how the project has run so far — zero auth, one shared session store. Nothing about the
deployment steps below changes this: every new capability is off unless you explicitly configure it.

**Prerequisites:** Python 3.9+, Docker (for a local Neo4j — or point at an existing Neo4j/Aura instance
instead), and a free API key from at least one LLM provider (Groq, Gemini, or Cerebras — all have a
no-cost tier, links are in `.env.example`).

**1. Start Neo4j** (the graph database everything gets written to):

```
docker compose up -d
```

This runs Neo4j 5 Community on `bolt://localhost:7687` with the same credentials `.env.example` already
expects (`neo4j` / `changeme-local-dev`) — nothing to configure. Its own browser UI is at
`http://localhost:7474` if you want to inspect the graph directly with Cypher.

**2. Install dependencies and configure at least one LLM key:**

```
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and paste in at least one of `GEMINI_API_KEY` / `GROQ_API_KEY` / `CEREBRAS_API_KEY` (each
is free to get). Leave `NEO4J_*` as the defaults if you used step 1's Docker container.

**3. Start the backend:**

```
uvicorn backend.api.app:app --reload
```

**4. Open the app** — the actual chat/graph interface is at **`http://localhost:8000/chat`**
(`http://localhost:8000` alone is just the marketing landing page; `/docs` is the architecture write-up).

**5. Use it** — type a real question ("How does an online payment work?") and wait; a full investigation
takes anywhere from a few seconds to a couple of minutes depending on how deep it decomposes and which LLM
provider responds. Once a graph exists, try natural-language navigation directly in the chat box:
`Enter PayPal` (step inside an entity's own subgraph), `Show only the network view` (filter to one
relation family), `Go back` (undo the last navigation) — none of these trigger a new investigation, they're
instant reads over what's already been discovered.

## Deploying publicly, with Google login

Stack: **Vercel** (static frontend) + **Render** (FastAPI backend) +
**Supabase Auth** (Google sign-in) + **Neo4j Aura** (managed graph DB, since
Render doesn't host Neo4j itself).

All of this is additive — `SUPABASE_URL` unset means the backend skips
auth entirely (`backend/api/auth.py`), and a blank `CONFIG` block in
`frontend/index.html` means the frontend skips the login gate entirely. You're
turning features on, not migrating off anything.

I can't create these accounts or click through OAuth/security screens for
you (see the constraints in-chat) — but every step below is copy-paste, no
guessing required.

### 1. Neo4j Aura (managed graph database)

1. [console.neo4j.io](https://console.neo4j.io) → **New Instance** → Free tier.
2. Save the generated password immediately (shown once). Note the **Connection
   URI** (`neo4j+s://xxxxx.databases.neo4j.io`).

### 2. Google Cloud OAuth client

1. [console.cloud.google.com](https://console.cloud.google.com) → create/select
   a project.
2. **APIs & Services → OAuth consent screen** → External → fill app name +
   support email → save.
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID** →
   Application type: **Web application**.
4. You'll add the **Authorized redirect URI** in step 3 below (it comes from
   Supabase) — come back and add it after step 3, then save.
5. Copy the **Client ID** and **Client Secret**.

### 3. Supabase project (auth + the callback URL Google needs)

1. [supabase.com/dashboard](https://supabase.com/dashboard) → **New project**.
2. **Authentication → Sign In / Providers → Google** → toggle on → paste the
   Client ID + Client Secret from step 2.
3. Copy the **Callback URL** Supabase shows on that same page
   (`https://<project-ref>.supabase.co/auth/v1/callback`) → go back to the
   Google Cloud OAuth client from step 2 → paste it into **Authorized redirect
   URIs** → save.
4. **Project Settings → API** → copy the **Project URL**, the **anon public**
   key, and the **JWT Secret**.

### 4. Render (backend)

1. [render.com](https://render.com) → **New → Web Service** → connect the
   `TheNova6000/Discovery.AI` GitHub repo. Render will detect `render.yaml`
   in the repo root (from this change) and pre-fill the build/start commands —
   accept it, or set manually:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn backend.api.app:app --host 0.0.0.0 --port $PORT`
2. Under **Environment**, set:
   | Key | Value |
   |---|---|
   | `NEO4J_URI` | the Aura Connection URI from step 1 |
   | `NEO4J_USER` | `neo4j` |
   | `NEO4J_PASSWORD` | the Aura password from step 1 |
   | `GEMINI_API_KEY` / `GROQ_API_KEY` / `CEREBRAS_API_KEY` | your existing keys |
   | `SUPABASE_URL` | the Project URL from step 3.4 |
   | `DATABASE_URL` | Supabase project -> Settings -> Database -> Connection string (URI format) |
   | `CORS_ORIGINS` | leave blank for now — set after step 5 gives you the Vercel URL |
3. Deploy. Note the resulting URL (`https://discovery-ai-backend-xxxx.onrender.com`).

### 5. Vercel (frontend)

1. In `frontend/index.html`, fill in the `CONFIG` block near the top of the
   `<script>` section:
   ```js
   const CONFIG = {
     SUPABASE_URL: 'https://xxxxxxxx.supabase.co',   // step 3.4
     SUPABASE_ANON_KEY: 'eyJ...',                     // step 3.4, anon public key
     BACKEND_URL: 'https://discovery-ai-backend-xxxx.onrender.com', // step 4
   };
   ```
   Commit and push this.
2. [vercel.com](https://vercel.com) → **New Project** → import
   `TheNova6000/Discovery.AI` → set **Root Directory** to `frontend` → Framework
   preset: **Other** (no build step needed, it's a static file) → Deploy.
3. Note the resulting URL (`https://discovery-ai.vercel.app`).

### 6. Close the loop

Go back to Render (step 4) and set `CORS_ORIGINS` to the Vercel URL from step
5, e.g. `https://discovery-ai.vercel.app` (comma-separate multiple origins if
you add a custom domain later). Redeploy the Render service so it picks up
the new env var.

### 7. Verify

Open the Vercel URL. You should see the **AUTHENTICATION REQUIRED** gate →
**Sign in with Google** → after consent, land back in the app signed in (your
email shown top-right). Ask a question — it should reach the Render backend,
which reaches Aura and your LLM providers, exactly like the local demo did.

Each signed-in Google account gets its own private set of sessions
(`backend/api/session.py`'s `get_store(user_id)`) — two people using the
deployed app can't see each other's investigation graphs.
