# Tuni'n — Component Research (2026-10-28)

Inline research pass over the components the user named: chat model, reasoning
engine, research engine (Dewey), LLM, learning-method framework. Every
"verified" below was run on this machine today; everything else is cited and
marked as unverified.

## 0. Naming (decided 2026-10-28)

- **Tuni'n** = the whole product / learning portal. `backend/dewey/*` moved into
  `backend/tunin/` (`coverage`, `lessons`, `curriculum` → `course`); UI and
  mascot assets renamed (`frontend/assets/tunin/`).
- **Dewey** = the research engine: web search, fetch, extraction, source
  indexing (after the Dewey Decimal System). Existing "Dewey Source Pack"
  retriever work keeps its name because it *is* that engine.
- **Discovery.AI** = the reasoning engine (recursive Ground/Master agents,
  claims, graph). Unchanged.

## 1. LLM: Gemma 4 via Gemini API — VERIFIED live

| Model id | Result today | Use |
|---|---|---|
| `gemma-4-26b-a4b-it` (MoE, 4B active) | text 5.7 s; JSON-schema 2.2 s; through `structured_call` 7.4 s, clean | first in `GROUND_MODEL_CHAIN` |
| `gemma-4-31b-it` (dense) | one 500 INTERNAL, then JSON-schema OK 16–32 s | first in `MASTER_MODEL_CHAIN` |

- Same `GEMINI_API_KEYS` pool (9 keys configured). Groq/Cerebras remain fallbacks.
- **Found and fixed:** instructor's default tool-calling mode made Gemma 26B
  degenerate (a list item repeating "-algorithms" hundreds of times). Gemma now
  always uses `Mode.GENAI_STRUCTURED_OUTPUTS` (Gemini constrained JSON decoding)
  — `backend/questions/llm_client.py`.
- **Found and fixed:** `aiohttp 3.9.5` lacks `ClientConnectorDNSError`, which
  google-genai's async client references → the SDK crashed inside its own error
  handler. Upgraded locally to 3.14.5, pinned `aiohttp>=3.10,<4`.
- Quota: Google publishes free limits per project in AI Studio, not in the docs.
  Third-party sources claim ~15 RPM / ~1.5k RPD for Gemma 4 — **unverified**;
  "no specific quota" should not be assumed in code. The existing passive
  `_PROVIDER_STATUS` 429 tracking already handles exhaustion.

## 2. Research engine (Dewey) — what exists vs. what's missing

### Exists (`backend/evidence/retrievers`, interface `Retriever.search(query, max_results) -> list[RetrievedResource]`)

| Retriever | Key | Status from repo history |
|---|---|---|
| Wikipedia | none (needs identifying UA + browser TLS via curl_cffi) | built; 403 from this machine per root Memory.md |
| arXiv | none | built; API 200 live |
| Semantic Scholar | optional | built |
| Open Library | none | built |
| CppReference | none (curated page list, robots/licence checked) | built |
| GitHub | optional token | built |
| Tavily | **required** (paid tier beyond free) | built; self-skips without key |
| YouTube | **required** | built; self-skips without key |

`RetrievedResource` already carries provenance: `url`, `retrieved_at`,
`source_type`, `source_role`, `acquisition_mode`. Good foundation; keep it.

### Missing (the gaps that make it a real research engine)

1. **General web search with no key.** `duckduckgo_search 8.1.1` is already
   installed (successor package: `ddgs`). Unofficial scraping of DDG — can
   break if DDG changes; must be one provider among several, never the only one.
   Stronger option: a self-hosted **SearXNG** (free, open source, JSON API) —
   needs Docker, which this machine lacks today.
2. **Fetch + main-content extraction** of arbitrary result pages. Recommended:
   `httpx`/`curl_cffi` fetch → **trafilatura** extraction (best-scoring
   heuristic extractor in published article benchmarks; academic comparison says
   no extractor dominates, Readability close). `beautifulsoup4` is installed as a
   fallback. Must add: robots.txt check, SSRF guard (block private/loopback/
   link-local IPs, redirect re-check), size/time caps, content-type allowlist.
3. **Provider registry** — retrievers are a flat `DEFAULT_RETRIEVERS` list with no
   per-provider status, quotas, key requirements or health, and no way to show
   them in a frontend. Needed for "all API keys required + frontend".
4. **Academic coverage**: OpenAlex now **requires a free API key** (since
   Feb 2026; $1/day free usage, ID/DOI lookups free). Crossref needs no key
   (polite pool via `mailto`). Neither has a retriever yet.
5. **Caching** of search/fetch results (SQLite), so re-research doesn't re-hit
   providers and quota stays bounded.
6. **User uploads** (PDF/Markdown syllabus): `pypdf` installed; no upload path.
7. **JS-rendered pages**: Playwright — heavy (browser binaries); keep optional,
   off by default, only after fetch+trafilatura proves insufficient.
8. **DigitalOcean Web Search/Fetch** (from the pasted recommendation): paid,
   availability unverified — fits as an *optional* registry provider later, not
   the primary. No credentials present.

### Rules the engine must keep (master prompt §4.2, §18)
Respect robots.txt and ToS; no CAPTCHA/paywall/auth bypass; identifying
User-Agent; per-host rate limits; treat fetched text as untrusted (never as
instructions to the LLM); a failed retrieval is never a claim.

## 3. Reasoning engine (Discovery.AI) — state

Phases 0–5 and R0–R5 VERIFIED per docs/Phases.md: graph interface, question
engine, recursive Ground agent, Master + spawn budget, evidence engine,
`POST /research` with `ResearchResponse`. **Live blocker:** the configured
Neo4j Aura host does not resolve from this machine (`0d1f3514.databases.neo4j.io`),
and Docker is absent, so graph-backed investigation cannot run locally. The
research engine should feed it without needing Neo4j itself.

## 4. Chat model (discovery) — state

`backend/tunin/discovery.py` (untracked, compiles, never run): staged
deterministic extraction + optional LLM refinement into `CourseDesignBrief`.
The "Study Techniques by Course Depth" PDF gives a better intake script:
4–5 questions (why, prior knowledge, target outcome, time) + an optional 2–3
question diagnostic, and places the learner at depth **D1–D4**, per concept.

## 5. Learning-method framework (the two PDFs) — fits curriculum + learner model

- **Bloom levels L1–L6 per concept** (Remember → Create), 19 chatbot-ready
  techniques each tagged with levels and a "pick when" signal.
- **Signal → technique table** (e.g. right answer + weak explanation → Feynman /
  self-explanation; same mistake repeated → contrasting cases / Socratic;
  40–70 % → tiered hints; >90 % fast → desirable difficulty).
- **Mastery gating** at ~70 % on prerequisites → insert remedial block.
- **Depth D1–D4** sets baseline technique mix; answers adjust it; spaced
  retrieval and retrieval practice at every depth.

Implication: `curriculum.py`'s flat `LEARNING_METHODS` registry should become a
data table (technique → levels, depths, signals) and the learner model should
track **highest Bloom level passed per concept**, not just a 0–1 mastery number.

## Sources
- Gemma on Gemini API (model ids): https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- Gemma 4 free-tier claims (unverified): https://apidog.com/blog/gemini-api-free-tier/ , https://gemma4.dev/deploy/gemma-4-gemini-api
- OpenAlex auth/limits: https://developers.openalex.org/guides/authentication , https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ
- Wikimedia User-Agent policy / 403s: https://meta.wikimedia.org/wiki/API_Policy_Update_2024 , https://phabricator.wikimedia.org/T400119
- Extractor benchmarks: https://trafilatura.readthedocs.io/ , https://chuniversiteit.nl/papers/comparison-of-web-content-extraction-algorithms , https://arxiv.org/pdf/2605.21097
- Keyless search options (DDG/ddgs, SearXNG): https://pypi.org/project/zero-api-key-web-search/ , https://toolregistry-hub.readthedocs.io/en/latest/tools/websearch/searxng/
