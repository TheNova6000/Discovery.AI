# Discovery.AI

**We built an AI knowledge system that refuses to reduce knowledge to a tree.**

## Inspiration

Every AI-generated "knowledge graph" we'd seen was secretly a tree wearing a graph's name — ask it a
relational question and it still answers with a hierarchy, because somewhere in the pipeline, "discovered
in this order" quietly became "structured this way." We wanted to know if that was fixable, or fundamental.

## What it does

Discovery.AI takes a natural-language question, recursively investigates it with a real agent (decompose,
answer, or admit a boundary — one step at a time, never planned in a single batch), and builds a **persistent,
typed knowledge graph** in Neo4j from what it finds — real entities, real typed relationships, real retrieved
evidence with honest confidence scores.

The part that makes it different: **the same world model can be explored at different scopes, through
different relationship lenses, without ever forking into a second graph.**

- **Scope** — "Enter" any entity and its own compositional subgraph becomes the view, while everything it
  genuinely connects to outside itself stays visible as context, never hidden without saying so.
- **Projection** — Filter the current scope down to one relation family (structure / flow / causal /
  dependency / network) — a pure lens over already-known facts. Zero new LLM calls, zero graph writes. A
  family with nothing to show says so honestly instead of quietly investigating more.
- **Topology, derived, never stored** — Whether a region of the graph reads as a tree, a network, a DAG, a
  cycle, or a mesh is never a property the system assigns. It falls out of which relationship *types*
  connect which entities. Change the scope or the lens, and the same nodes can present an entirely different,
  equally true shape.

## The core moment

Enter `Authorization` inside a live payment investigation, and it holds two genuinely different, both-true
topologies at once:

```
COARSE SCOPE (Authorization's siblings)
Risk Checks --PRECEDES--> Authorization --PRECEDES--> Capture --PRECEDES--> Clearing --PRECEDES--> Settlement

                              │
                          enter Authorization
                              ▼

FINE SCOPE (Authorization's own internals)
Enforcement --QUERIES--> Engine --EVALUATES--> Policies --EXPRESS--> XACML
```

Same entity. Same world model. Zero duplication. The temporal chain doesn't disappear when you step inside —
it becomes the surrounding context, dimmed but present, honestly.

## How we built it

**Stack:** FastAPI, Neo4j, a free-tier LLM fallback chain (Groq / Gemini / Cerebras via Instructor) with
per-agent-level model tiers, Cytoscape.js for the graph UI, vanilla JS/HTML/CSS with no build step.

**Architecture, in one diagram:**

```
Natural language → Intent → Investigation → Relation extraction → Identity resolution
                                                                          │
                                                                          ▼
                                                                    WORLD MODEL
                                                              (nodes, typed relations,
                                                               evidence, confidence)
                                                                          │
                                                   ┌──────────────────────┼──────────────────────┐
                                                   ▼                      ▼                      ▼
                                                SCOPE               PROJECTION             NAVIGATION
                                        (compositional reach)   (relation family)     (focus/enter/exit)
                                                   └──────────────────────┼──────────────────────┘
                                                                          ▼
                                                                    BOUNDED VIEW
                                                              (honest about what's
                                                               left out, never silent)
                                                                          │
                                                                          ▼
                                                                  Tree / DAG / Network /
                                                                  Cycle / Mesh / Nested
```

The critical design discipline: at every layer, we treated "what the system knows" (Neo4j) and "what's
currently shown" (session view state) as strictly separate. A view operation — focus, enter a space, switch
a projection — is provably incapable of writing to the graph. We didn't just design that invariant; we wrote
scripts that verify it directly against the live database on every change.

## What we're proudest of: the failures we found and fixed, on camera

We didn't discover this architecture worked by building it and hoping. We built a **synthetic topology test
suite** — ten deliberately adversarial graph shapes (tree, network, DAG, cycle, nested boxes, cross-space
edges, a workflow with a retry cycle, a nested workflow, a hub, a mesh) — and fed them straight into the
renderer with no LLM, no database, no investigation in the loop. **10/10 passed.**

Then we ran the harder test: real natural-language questions, real investigations, no manual graph editing.

- A tree-shaped question produced a genuine tree. ✅
- A network-shaped question ("how do PayPal, Mastercard, banks, and merchants interact") produced a genuine
  network — and incidentally re-triggered a real bug we'd fixed earlier in development, where an *interaction*
  edge (`PayPal USES Mastercard`) was being drawn as *containment* (Mastercard trapped inside PayPal's own
  box). Verified fixed, live, with fresh model output.
- A sequence-shaped question ("the complete lifecycle of a payment... show where branches converge") **broke**
  — it produced a flat decomposition tree with zero temporal ordering, even though the agent's own reasoning
  text correctly described the sequence in prose. We traced the failure to one specific layer: the
  relation-extraction prompt asked the model for "actor, causal, or functional" relationships and never once
  mentioned sequence as a category, even though `PRECEDES`/`FOLLOWS` already existed in our own relation
  registry. We changed exactly one paragraph in that prompt — nothing else — and re-verified directly against
  Neo4j that a genuine `PRECEDES` chain now extracts where none did before.

That's the whole thesis in miniature: when something looked like a tree, we didn't patch the renderer — we
found which pipeline stage actually lost the information, fixed that one thing, and proved the fix with a
database query, not a screenshot.

## What's next

We mined our own accumulated graph (278 nodes, 253 edges across every topic we'd ever investigated) and found
non-tree structure had already been forming *on its own* — a genuine 5-node cycle in the payment domain,
convergence points that correctly resolved to the same node across five separately-run investigations, nested
spaces we hadn't deliberately tested for. We also found that 28% of every relationship we've ever extracted
falls outside our own relation-type registry — real, meaningful relations (`FORWARDS_TO`, `ROUTES_REQUEST_TO`)
that the registry's exact-string matching just doesn't recognize as variants of what it already knows.

We deliberately chose *not* to patch that in by hand. The next research direction is predicate identity: a
principled layer that decides when two different verbs mean the same relationship — conservative by design,
because a wrong merge silently corrupts what the graph claims, while an honestly-unmapped relation just says
"we haven't classified this yet." After that: a learning layer that asks not just "what's connected to X" but
"what do I need to understand before X makes sense" — turning the graph from a map into an environment.

## What we learned

Being honest about limits made the project stronger, not weaker. Our navigation layer (`Focus`) still can't
show *everything* about a mesh or a DAG within a small, readable radius — no algorithm can do that without
abandoning the point of a bounded view. What we could do, and did, is make that boundary honest: every node
with real structure just outside the current view now carries a visible marker saying so, instead of silently
implying the view is complete. **A viewport is allowed to be incomplete. It is not allowed to imply
completeness when it is bounded.**

## Built with

Python · FastAPI · Neo4j · Groq · Google Gemini · Cerebras · Instructor · Cytoscape.js · JavaScript ·
Supabase (auth + session storage) · SQLite
