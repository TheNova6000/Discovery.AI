# Discovery.AI

*Compressed submission draft, sized for Devpost fields. Master version with full technical narrative: `docs/DevpostSubmission.md`.*

## Inspiration

Most AI knowledge systems quietly turn every investigation into a tree — ask a relational question and the
answer still comes back as a hierarchy, because "discovered in this order" silently became "structured this
way." But real knowledge isn't a tree. A payment system has hierarchy, interactions, flows, dependencies, and
cycles all at once, sometimes in the same ten nodes. We wanted to know if that was a fixable engineering
problem or a fundamental limit of AI-built knowledge graphs — and built Discovery.AI to find out.

## What it does

Discovery.AI takes a natural-language question and recursively investigates it, building a persistent, typed
knowledge graph in Neo4j — real entities, real typed relationships, real retrieved evidence with honest
confidence scores. Composition relationships create nested "spaces" (boxes); interaction, temporal, and causal
relationships stay as ordinary graph edges crossing those boundaries freely. Users can **focus** on an entity
(context stays visible), **enter its own space** (step inside, context becomes dimmed background), or **switch
projection** to filter the current view down to one relationship family — all without ever duplicating the
underlying world model. Topology isn't assigned; it's derived from whichever relationship types happen to
connect a given region of the graph.

## The core example

```
Payment System
   ├── Risk Checks
   ├── Authorization
   │      ├── Enforcement
   │      ├── Engine
   │      └── Policies → XACML
   └── Capture
```

At the coarse scope, `Authorization` sits in a temporal chain:

`Risk Checks → Authorization → Capture`

Enter `Authorization`, and the *same node* reveals a completely different internal topology:

`Enforcement → Engine → Policies → XACML`

No duplicated entities. No second graph. One world model, two honestly different, both-true views.

## How we built it

FastAPI + Neo4j backend, a free-tier LLM fallback chain (Groq/Gemini/Cerebras via Instructor), Cytoscape.js
for the graph UI. Every relationship carries a type and a **family** (composition/interaction/temporal/causal/
dependency) drawn from one shared registry, so the renderer never has to guess what a relationship means.
Relations carry attached evidence and a stated (never self-reported) confidence formula. "Graph Spaces" let
any entity's own compositional subgraph become the view; "projections" filter by relation family with zero new
LLM calls; a bounded-reachability layer keeps navigation readable while explicitly disclosing — never hiding
— whatever real structure falls outside the current view.

## What we're proudest of

We didn't just build this and hope it worked — we tried to break it, on camera. We fed the renderer ten
deliberately adversarial synthetic graphs (tree, network, DAG, cycle, nested boxes, cross-space edges, a
workflow with a retry cycle, a hub, a mesh) with no LLM and no database in the loop. **10/10 passed.**

Then we ran real investigations and found real bugs. Early on, we saw PayPal incorrectly *containing*
Mastercard on screen. Instead of patching the visualization, we traced it: the renderer was treating every
outgoing relationship as containment. We fixed the actual rule — only compositional relationships create
boxes; `USES`, `ROUTES_TO`, and everything else stay ordinary crossing edges — and re-verified it live with
fresh model output.

Later, a payment-lifecycle question exposed a subtler failure: the agent's own reasoning correctly described a
sequence of steps, but the graph stored zero ordering between them — a flat tree where a chain should have
been. We traced it to the exact layer responsible: the relation-extraction prompt asked for actor/causal/
functional relationships and never once mentioned sequence as a category. We changed one paragraph, nothing
else, and re-verified directly against the database that a real `PRECEDES` chain now extracts where none did
before.

## What's next

We mined our own accumulated graph and found non-tree structure had already been forming on its own — a real
cycle, convergence points that correctly resolved across five separate investigations, nested spaces we'd
never deliberately tested. We also found 28% of every relationship we've ever extracted falls outside our own
naming registry — real relations, just unrecognized surface variants. We chose not to patch that by hand; the
next step is a principled way to decide when two different words mean the same relationship, conservatively,
before it's added to what the graph claims.

## The pitch

Discovery.AI doesn't try to predict the shape of knowledge before it sees it. It discovers typed relationships
and lets topology emerge from them. A tree is one possible view. A network is another. A workflow is another.
A graph can contain another graph. The underlying world stays exactly the same.

## Built with

Python · FastAPI · Neo4j · Groq · Google Gemini · Cerebras · Instructor · Cytoscape.js · JavaScript · Supabase
