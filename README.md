# Discovery.AI

Ask a question, and the system recursively investigates it — decomposing it into
sub-questions, answering them, and building a live graph of what it explored
along the way. Backend: FastAPI + Neo4j + a multi-provider LLM fallback chain.
Frontend: a single static `frontend/index.html` (Cytoscape.js graph, no build
step).

## Local / VM dev (no login)

This is how the project has run so far — zero auth, one shared session store.
Nothing about the deployment steps below changes this: every new capability is
off unless you explicitly configure it.

```
pip install -r requirements.txt
cp .env.example .env   # fill in NEO4J_* and at least one LLM provider key
uvicorn backend.api.app:app --reload
```

Open `http://localhost:8000`.

## Deploying publicly, with Google login

Stack: **Vercel** (static frontend) + **Render** (FastAPI backend) +
**Supabase Auth** (Google sign-in) + **Neo4j Aura** (managed graph DB, since
Render doesn't host Neo4j itself).

All of this is additive — `SUPABASE_JWT_SECRET` unset means the backend skips
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
   | `SUPABASE_JWT_SECRET` | the JWT Secret from step 3.4 |
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
