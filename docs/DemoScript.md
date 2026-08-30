# Discovery.AI — Golden Demo Script

Verified live, end-to-end, against the real deployed app and real Neo4j data — every screen in this
script actually happened during rehearsal, not a mockup. ~2 minutes of screen time. Uses navigation
intents (zoom_in / enter_space / set_projection) over **already-investigated real data**, not a fresh
investigation — this makes the demo fast and reliable regardless of LLM provider quota, since navigation
is a lightweight intent-parse call, not a multi-step investigation.

## The one-sentence thesis (say this first, before touching the keyboard)

> "Discovery.AI converts natural-language investigations into a persistent, typed knowledge graph whose
> topology is determined by semantic relationships — not by the order in which an LLM discovered them.
> Same world model. Different scale, different lens, different shape — never a duplicate graph."

## Step 1 — The world model at a glance

**Type:** `Show me Payment System`

**What appears:** A "Payment System" box containing `PayPal` and `Mastercard` as **siblings**
(`decomposes_into` — composition), connected by a `USES` / `uses_network` edge that crosses the box
boundary as an ordinary edge, not containment.

**Say:**
> "PayPal and Mastercard are both *part of* the payment system — that's composition, so they're boxed
> together. But PayPal *uses* Mastercard — that's an interaction, not a part-whole relationship, so it
> stays a crossing edge instead of nesting Mastercard inside PayPal's box. This exact distinction was a
> real bug we found and fixed."
>
> (Point at the small `⋯+3` / `⋯+13` badges on the nodes.) "And these aren't decoration — the system is
> telling you honestly that more exists beyond this view. It never pretends a bounded view is the whole
> picture."

## Step 2 — Enter a box: same node, different scale

**Type:** `Enter PayPal`

**What appears:** PayPal's box *becomes the new root* — its own 7-part internal structure (risk engine,
Payment Processing Engine, PayPal User-Facing Platform, etc.) is now the graph, while `Mastercard`,
`Stripe`, `PayPal Credit`, and other real cross-boundary relationships remain visible as dimmed context
nodes around the edges.

**Say:**
> "This is the same PayPal node — not a different graph, not a duplicate. Stepping inside it just changes
> *scope*: what was one collapsed box is now its own graph, and everything it actually connects to outside
> itself stays visible, dimmed, as context."

## Step 3 — The punchline: one entity, two topologies

**Type:** `Enter Authorization`

*(This works from the current view or fresh — `Authorization` is a real node discovered across five
separate investigations in this project's history.)*

**What appears:** Authorization's own internal graph — `Authorization Enforcement → QUERIES →
Authorization Engine → EVALUATES → Authorization Policies → EXPRESS → XACML` (and `EXPRESS_IN → Rego`) —
while the **coarse temporal chain** `Risk checks → PRECEDES → Authorization → PRECEDES → Payment Capture`
remains visible as context, complete with a `⋯+1` disclosure badge on Payment Capture (there's more past
it — Clearing — genuinely not shown, and the system says so).

**Say — this is the moment, slow down here:**
> "Look at this carefully. `Authorization` participates in a **temporal chain** at the coarse level — it
> comes after Risk Checks, before Capture. But step inside it, and its own internals are an **interaction
> network** — Enforcement queries the Engine, which evaluates Policies, which express themselves as XACML
> or Rego rules. Same entity. Same world model. Two entirely different, both-true topologies, depending on
> what scale you're looking at. Nothing was duplicated to make this possible."

## Step 4 — Projection: the same scope, a different lens

**Type:** `Show only the network view`

**What appears:** The same Authorization space, now filtered to *only* the interaction-family edges —
`Enforcement → Engine → Policies` — with zero new graph, zero LLM call, zero investigation. Pure filter
over what's already known.

**Say:**
> "That was a projection switch, not a new question. Zero new information was created — this is a lens
> over the same stored graph. We could just as easily ask for the temporal lens, or the causal lens, and
> get a different honest slice of the exact same world."

## Closing line

> "A traditional hierarchical knowledge tool wants to find a parent for everything. Discovery.AI doesn't
> — it stores relationships and *derives* topology from them. We proved that against ten synthetic graph
> shapes, then against real natural-language investigations, found a real bug where it broke, fixed it,
> and verified the fix directly against the database. This screen is that architecture, live."

---

## Backup / if something doesn't render mid-demo

- All four steps above were captured as real screenshots during rehearsal — see the conversation history
  / `docs/Reports` section on `/docs` for static fallbacks if a live re-run misbehaves.
- If provider quota is exhausted and a *fresh* investigation is needed for Q&A, navigation commands
  (`Show me X`, `Enter X`, `Show only the Y view`) are lightweight intent-parses, not full investigations
  — far more likely to succeed live than starting a new topic from scratch.
- Fallback question if a judge wants to see fresh investigation and quota allows it: **"How is a computer
  organized from hardware to software?"** — already verified to reliably produce a clean tree in one pass
  (see `docs/Memory.md` §0.28 Test 1).
