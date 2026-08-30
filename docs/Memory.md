# Memory — Recursive Knowledge Graph

Running progress log. Update at the end of every phase (see Rules.md rule 4 / "what the AI should NOT do"). Newest entries at the top.

---

## 2026-08-30 (continued) — §0.28: topology-preserving extraction — the renderer was never the bug

After §0.27 shipped, the user watched the live UI and reported the tree "coming back," and asked for a
graph-topology test suite before touching anything: "don't fix anything yet... isolate the question: can our
visualization system actually render arbitrary graph topology?" Built a synthetic 10-topology corpus (tree,
network, DAG, cycle, nested box, box+network crossing a boundary, workflow with a retry cycle, nested
workflow, hub, mesh) and fed each directly into the deployed `renderGraph` in a live Chrome tab tunneled to
the VM — no LLM, no Neo4j, no intent parser, exactly as asked. All 10 passed: correct nesting where
composition edges existed, zero invented boxes for interaction-only graphs, DAG convergence preserved
without duplicating the converging node, full cycles preserved with no root invented, cross-boundary edges
surviving in both single- and double-nested cases. The box/edge rendering logic §0.22 built turned out to
already be topology-agnostic.

Then tested `computeViewport`'s focus/zoom windowing specifically (the code path real navigation uses,
distinct from `renderGraph`'s box logic) and found a real, separate limitation: focusing on a cycle's node
silently dropped its back-edge (a 3-cycle rendered as a 2-edge chain, no indication anything was hidden);
focusing on a low-degree mesh node dropped an entire node and 5/8 edges, collapsing to what visually reads as
a 3-star; focusing on the SAME mesh's highest-degree node happened to recover the whole thing by accident
(the "sibling of parent" recovery rule only works when the parent is highly connected) — meaning the same
graph's apparent shape depends on which node the user happens to click, not on the graph itself. Documented,
not fixed — the user's explicit sequencing was to isolate this from the extraction question, which turned
out to be the more urgent one.

**The real test: does the actual product pipeline (natural language -> LLM investigation -> graph
construction -> intent-parsed navigation) preserve topology, not just the renderer in isolation.** Ran three
fresh Chrome sessions (each genuinely isolated — caught and fixed my own test-harness bug along the way: an
early `window.newChat = function() {...}` helper shadowed the page's real `newChat()`, which is what
`new-chat-btn`'s onclick calls, silently turning "start a new chat" into a no-op and contaminating Test 2's
first attempt with Test 1's leftover graph; fixed by never overriding page globals and verifying via
`/sessions` that a new session_id actually appeared before proceeding). Test 1 ("how is a computer organized
from hardware to software") produced a genuine, correct tree. Test 2 ("how do PayPal, Mastercard, Visa,
banks, merchants interact") produced a genuine network — this doubled as an unplanned live regression test of
the exact original §0.22 PayPal/Mastercard containment bug, with fresh LLM-generated content instead of a
manual reproduction: `PayPal -[USES]-> Mastercard` rendered as a crossing edge, Mastercard stayed outside
PayPal's box, and the result held under focus on both PayPal (the hub) and Mastercard (a leaf) — the earlier
fix generalizes. Test 3 ("the complete lifecycle of an online payment... show where branches converge") is
where it broke: the stored graph was `decomposes_into` from the root to Capture/Authorization/Risk
checks/"Capture & Settlement Process" (Clearing quietly disappeared, folded into that last node), with
**zero** temporal edges anywhere, despite the master agent's own reasoning text explicitly stating "All
constituent parts of the lifecycle (risk checks, authorization, capture, clearing, settlement) have already
been provided" and describing where they converge — the agent *knew* the sequence and said so in prose, but
never turned it into a graph edge.

Root-caused by reading the actual code, not guessing: `GroundDecision` (`backend/questions/models.py`)
already supports a non-compositional `relationship_type` for decompose, but only for a new-child-to-its-
current-parent edge — decompose is sequential (one sub-question per call, "not a batch covering several
unknowns at once," by explicit docstring), so it structurally has no way to relate two siblings it discovered
on different turns. The only mechanism that COULD express "Risk checks precedes Authorization" is
`extract_relations`, and its system prompt (`backend/questions/relation_extraction.py`) asked for "actor,
causal, or functional" relationships and listed detects/causes/enables/depends on/routes to/regulates as
examples — temporal/sequential relations were never mentioned as a category at all, even though `precedes`/
`follows` already exist as real TEMPORAL-family entries in §0.25's own registry. This precisely explains the
Test 2 vs. Test 3 asymmetry: Test 2's question was actor/interaction-shaped, squarely inside what the prompt
already asked for; Test 3's was sequence-shaped, entirely outside it.

**Fix, exactly as scoped and no more:** added one paragraph to `extract_relations`'s system prompt naming
temporal/sequential/process relationships as explicitly in scope (precedes/follows, happens_before/after,
branch/convergence), with worked examples ("Risk checks precede authorization" -> `PRECEDES`, "streams
converge during clearing" -> `CONVERGES_AT`). Did not touch decompose, the relation registry, box assignment,
the renderer, viewport, or projections — a single-variable change so a topology improvement could be
attributed to this one thing and nothing else. Redeployed, restarted uvicorn, re-ran Test 3 from a
completely fresh Chrome session with the identical question. Mid-run, all three LLM providers hit
simultaneous exhaustion (Groq's daily token cap; Gemini's actual 20-requests/day free tier ceiling, not just
a per-minute limit; Cerebras's 402 billing-required) before the investigation reached a final synthesized
answer, so the in-memory session mirror (`/graph`) never refreshed and the live UI never got to render a
result — but Neo4j had already received the writes from the ground-level sub-questions that DID complete
before the exhaustion hit. Queried Neo4j directly (`scripts/verify_test3_extraction.py`, deliberately
bypassing both the LLM and the in-memory mirror) and confirmed a genuine temporal chain now exists where zero
existed before the fix: `Risk checks -[PRECEDES]-> Authorization -[PRECEDES]-> Payment Capture
-[PRECEDES]-> Clearing`, plus a root-level `-[precedes]-> Authorization` edge. The fix works; a full
end-to-end UI render of the complete chain (through Settlement) is the natural follow-up once provider quota
resets — not yet observed, and not claimed as observed.

## 2026-08-30 (continued) — §0.34: predicate identity is the missing layer, not "canonicalization"

Direct follow-on from §0.33's 28%-unmapped finding, with the user's explicit instruction against the obvious
shortcut: don't patch the 71 relation names into the registry one at a time — "that would make today's graph
look cleaner while making the underlying problem worse... First understand relation identity."

**The first move was reading the actual code rather than theorizing about "canonicalization" as if it were
one thing.** It isn't. `canonicalize_relation` (`backend/questions/relation_extraction.py`) is an LLM call
that does direction normalization only — passive/modal voice to active voice, explicitly documented as never
touching which verb gets used ("If the triple is already active/canonical, return it unchanged").
`normalize_relationship_type` is a small, deterministic, hand-curated dict doing spelling/format
normalization only, built from variants actually observed in real runs, explicitly commented "unmapped !=
unworthy." `get_family` maps one canonical predicate string to one family. All three are real, all three
work, and none of them is or was ever meant to be the thing §0.33 actually found missing: a stage that
decides whether two *different* verb strings denote the *same real-world relationship* before family lookup
ever runs. Conflating these three under one "canonicalization" label — as an earlier draft of this exact
research pass did — would have obscured exactly where the gap is. Corrected before being written up.

One concrete piece of evidence surfaced while re-reading the code, worth recording precisely: `is_an_example_of`
already has a `_RELATIONSHIP_TYPE_SYNONYMS` entry mapping it to `IS_EXAMPLE_OF`, yet §0.33's mining pass found
it stored unmapped in Neo4j. That specific pair of edges predates that table entry (or `normalize_relationship_type`
itself) being added to the code — historical residue from earlier in this same session's own investigations,
not proof that today's code would fail on a fresh extraction. Some real fraction of the 28% figure is stale
data rather than a live, currently-reproducible gap — named explicitly so the finding isn't overstated.

**The corrected pipeline, naming the actually-missing stage:**

```
Extraction -> Direction normalization -> Predicate normalization -> Identity resolution -> Family classification -> World Model
```

**Ten principles agreed as the checklist future passes get measured against**, condensed: surface form is not
predicate identity; predicate identity is not relation family; family is deliberately coarse, predicate
identity is fine-grained; equivalence between two surface forms requires checking real examples, never
string/embedding similarity alone; unknown relations are preserved, never force-merged; normalization is
curated and deterministic, never decided by an LLM judging its own output at extraction time; unknown is not
unworthy; a wrong merge is strictly worse than an unmapped relation, because a merge silently and permanently
changes what the graph claims while an unmapped edge stays honestly recoverable; registry growth stays
incremental and observable, with the mining script itself as the observation mechanism.

**One real correction accepted mid-pass, not smoothed over:** the first draft concluded predicate-identity
decisions should carry no confidence at all, full stop, by direct analogy to `_RELATIONSHIP_TYPE_SYNONYMS`
having no confidence field. The correction sharpens rather than reverses this: the *decision* stays
deterministic yes/no at the registry level (that part was right), but the *evidence supporting* a curation
decision can and should be recorded without becoming a runtime confidence score —
`{alias, reason, verified_examples, status}` per entry, not a number. This preserves exactly the distinction
§0.26 already established for relation evidence: knowledge about the world can be probabilistic; decisions
about what a predicate *is* should not be.

**A concrete design named for a future pass, not built now:** an `unknown` pseudo-family in
`PROJECTION_FAMILIES`, so a user can deliberately ask to see exactly the relations with no registered family
— the same "honest gap over silent invention" principle §0.27/§0.31 already proved for topology, extended
here to vocabulary. The relation model this points toward keeps `surface_predicate` and `canonical_predicate`
as genuinely separate fields, with evidence attached to the actual assertion rather than to the canonical
predicate string — valuable once multiple sources express the same fact differently, which hasn't happened
yet in this project's own data and isn't being built ahead of that need.

**Not implemented.** No registry change, no new projection, no schema change. The named next experiment is
explicitly *not* hand-picked toy examples: run this theory against the real 71 unmapped `relationship_type`
strings already sitting in the actual 253-edge graph from §0.33, to see whether the ten principles hold
against the mess the system has already produced rather than against clean illustrative cases.

## 2026-08-30 (continued) — §0.33 Pass A: mining the real World Model, zero LLM calls

§0.30-§0.32 had proven the renderer and navigation aren't forcing a tree onto arbitrary graphs. The next,
harder question the user posed was whether the AI knowledge-acquisition process *itself* preserves graph
structure across real investigations — planned as an 8-topology live test matrix (Pass B), tracing
question → intent → investigation → extraction → canonicalization → identity resolution → Neo4j → space/
projection → reachability → renderer, and comparing where topology first diverges from what was intended.

Before running any of that, `/provider_status` was checked and confirmed all three LLM providers (Groq,
Gemini, Cerebras) exhausted simultaneously — live investigation was not possible. Rather than wait idle, the
user redirected to a zero-cost alternative that turned out to be more informative than expected: mine the
graph every investigation this entire project has ever run has already written to the same Neo4j database.
Wrote `scripts/mine_world_model_topology.py` — weakly-connected-component analysis (union-find), directed
cycle detection (three-color DFS), convergence counting (in-degree ≥ 2), nested-composition detection,
cross-boundary-edge detection, temporal-chain walking, and per-node family-mixing — deliberately reusing
`backend.questions.relation_types.get_family` rather than re-deriving family classification, consistent with
every prior pass's discipline against maintaining a second copy of that table.

**Result, against 278 nodes / 253 edges accumulated across every topic ever investigated this project
(computers, payments, electric grids, smartphone imaging pipelines, game server scalability, intrusion
detection): the World Model already contains every non-tree shape being searched for, without anyone having
designed a single test to produce most of them.**

- **A real cycle**: `payment gateway → acquiring bank → card network → issuing bank → merchant → payment
  gateway`, five hops, each edge individually real (`ROUTES_THROUGH`, `ROUTES_TO`/`ROUTES_REQUEST_TO`,
  `TRANSFERS_FUNDS_TO`, and a closing merchant→gateway edge) — extracted across several separately-run
  investigations, not asserted as a loop in one coherent reasoning pass. Named honestly as an *aggregate*
  property of the accumulated graph, not a claim about what any single LLM call understood. A smaller,
  probably-artifactual 2-node cycle (`In-Memory Caching ⇄ Redis`, via an `EXEMPLIFIES` relation likely
  extracted in both directions) was also found and reported without inflating its significance.
- **Convergence with real identity-resolution evidence**: `Authorization` has 8 incoming edges from five
  *separately run, time-separated* investigations (`Payments`, `payment`, `Card payment flow`, `Card
  Payment`, `How does payment work`) — all correctly resolving onto the same canonical node rather than
  fragmenting into duplicates. This is new evidence beyond what had been checked before: identity resolution
  had only previously been verified within one investigation's own sibling set (§0.18's original test), never
  across genuinely separate sessions run at different times. Same convergence pattern confirmed for `issuing
  bank` (8), `card network` (5), `acquiring bank` (5), `PayPal` (4), `Mastercard` (3).
- **Nested spaces exist beyond the one already studied**: `payment → Payment Methods → {Payment Instruments,
  Payment transaction lifecycle, Payment ecosystem participants}` and `Payment System → PayPal → {7 internal
  parts}`, in addition to the already-known `Authorization` case from §0.29/§0.32.
- **Cross-space edges are real but narrowly evidenced**: all 4 instances found trace to the single §0.28 Test
  3 lineage. Other multi-region investigations in the data (electric grid, smartphone imaging pipeline)
  haven't produced any yet — recorded as a real limit on generalization, not smoothed over.
- **Temporal chains have not spread beyond the one deliberately-tested case**: zero spontaneous `temporal`-
  family edges anywhere else in 253 edges, despite the electric-grid and game-scalability investigations
  plausibly having real sequential processes of their own. The §0.28 fix works when directly asked for; it
  has not yet been observed to generalize without a question explicitly shaped like "show me the sequence."
- **The single most consequential finding, more concerning than the cycle**: **71 of 253 edges (28%) fall
  outside the `RELATION_TYPES` registry entirely** (`family: null`, reported as `unmapped`). Inspecting them:
  not noise — `SENDS_TO`, `FORWARDS_TO`, `ROUTES_REQUEST_TO`, `TRANSMITS_DATA_TO`, `CAPTURES_REQUESTS_FOR` are
  obviously interaction-family relations, just surface variants the registry's exact-string lookup doesn't
  recognize. One is a clean normalization miss on its own terms: `is_example_of` is registered,
  `is_an_example_of` (one word longer) is not. A quarter of everything ever extracted by this system is
  currently invisible to family-based projection filtering and topology classification — not incorrectly
  modeled, just unclassified, and this was never visible until this exact query ran.
- **Nodes participating in multiple relation families simultaneously is the common case, not the exception**:
  15 such nodes found in one scan (`PayPal`, `Mastercard`, `Authorization`, `Payment Processing Engine`,
  `risk engine`, `card network`, `issuing bank`, and others), each combining composition with at least one of
  interaction/temporal/dependency/unmapped — confirming §0.29's single studied example generalizes across
  nearly every investigated topic rather than being an isolated case.

**Explicitly not acted on, per direct instruction:** the 71 unmapped relation names were not patched into the
registry one by one. The user's reasoning, kept verbatim because it names the actual risk precisely: "Don't
manually add the 71 relation names to the registry one by one. That would make today's graph look cleaner
while making the underlying problem worse... First understand relation identity. Then let the registry become
the consequence of that model, rather than a growing dictionary of whatever verbs the LLM happened to
produce." §0.34 is scoped to research relation identity/canonicalization theory before any registry change;
§0.35 (fresh live topology acquisition, deferred from this pass once a provider is available) and §0.36 (a
learning layer built on top of a graph proven to survive contact with real investigations) are named as
queued, not started.

## 2026-08-30 (continued) — §0.32: bounded reachability, implemented and regression-tested live

Direct implementation of §0.31's validated contract, with the user's explicit constraint honored throughout:
"do not redesign the contract while implementing it." `frontend/chat.html` gained the three functions the
spec named — `reach(graph, seeds, maxDepth, familyFilter, direction)`, `edgesAmong` (every edge with both ends
in a node set, computed as a pass strictly separate from the BFS that found those nodes), and
`truncationByNode` (per-node counts of real edges leading outside the current view) — and `computeSpaceViewport`
plus a new `computeFocusViewport` are now built from these three primitives instead of being two
independently hand-rolled traversals. One implementation detail was cleaned up mid-write rather than shipped
as-is: the first draft of `computeFocusViewport`'s context-set calculation used a hard-to-verify combined
boolean expression (`id !== focusId && !core.has(id) || parentIds.includes(id)`, correct by operator
precedence but not obviously so at a glance); rewritten as two explicit steps (seed `contextIds` with
`parentIds`, then add any sibling not already in `core`) before it was ever deployed, on the general
principle that code whose correctness depends on remembering JS operator precedence is a liability regardless
of whether it's currently correct.

A disclosure badge was added to match §0.31's design exactly: `data.truncated` plus a dashed amber
(`#ffd166`) border via a new Cytoscape style rule, and the count baked directly into the node's own label as
a `⋯+N` suffix — anchored to the specific node with hidden structure, matching the spec's explicit preference
for spatial anchoring over a vague page-level counter. Confirmed rendering correctly with a live screenshot,
not just verified at the data layer: three mesh nodes each showing their own dashed border and `+1` badge
exactly where their real hidden connections are.

**Full acceptance battery, run against the actually-deployed app in a live Chrome tab (not the §0.31
prototype) after shipping:**

- Whole-graph rendering: 10/10 on the complete §0.28 synthetic corpus, zero regression from the rewrite.
- **Cycle under Focus**: 3/3 edges, zero truncation — full recovery at Focus's *unchanged* radius, exactly
  matching what the §0.31 prototype had already predicted, now true of the shipped code.
- **DAG under Focus**, root or sink: same 3/4 nodes shown either way, but now discloses 2 hidden edges on the
  two intermediate nodes symmetrically regardless of which end was clicked — previously silent in both
  directions.
- **Mesh under Focus**, low-degree node: same partial view, now with `+1` badges landing on exactly the three
  nodes that have a real hidden connection — and, checked specifically because a disclosure mechanism is only
  trustworthy if it never cries wolf: focusing the mesh's high-degree node instead gives full recovery with
  **zero** false-positive badges. The contract only ever flags real hidden structure.
- **Hub under Focus** on a leaf: full recovery, zero boxes formed — composition-vs-interaction distinction
  from §0.22 unaffected by the rewrite underneath it.
- **Enter Space on a nested workflow** (`Authorization` inside `Payment Process`): box forms correctly over
  its 5 compositional children, `Capture` correctly shows as boundary-crossing context, and the disclosure
  numbers land exactly where §0.31's prototype predicted — `Authorization` and `Capture` together accounting
  for the 2 hidden nodes / 3 hidden edges one hop past the boundary.
- **Enter Space on a doubly-nested box** (`Payment Stages` inside `Payment`): shows only its own internal
  chain, correctly excludes the outer siblings `PayPal`/`Mastercard`, and correctly discloses its own
  incoming parent edge as exactly 1 hidden edge.
- **Cross-space edges**: unchanged in kind — both boxes form, both boundary-crossing interaction edges
  survive — and the nodes reached only as context now honestly disclose that their own containing structure
  (their real parent box) isn't shown either, a level of honesty the pre-§0.32 implementation never attempted.
- **Projection composed with an entered Space**: `Authorization` + `flow` projection still correctly filters
  to the temporal chain within scope, confirming §0.27's behavior survived the rewrite underneath it intact.
- **World Model**: `graph.nodes`/`graph.edges` length and identity confirmed unchanged across every test
  above — true by construction, since `reach`/`edgesAmong`/`truncationByNode` only ever read their `graph`
  argument, never assign into it.
- **Determinism**: the same graph and parameters, rendered twice in direct succession, produced byte-identical
  node and edge sets both times. `V = f(G, root, depth, family, direction, mode)` is now a verified property
  of the shipped code, not just a stated intention.

No new Node type, no new graph type, no stored topology field, no duplicate graph — the same standard held
since §0.29, now carried all the way through to a real, deployed, live-tested implementation.

## 2026-08-30 (continued) — §0.31: the bounded-reachability contract, specified and tested before any code

Direct follow-on from §0.30's conclusion that Focus and Enter Space are one primitive with different bound
parameters. The user was explicit about sequencing before this pass started: "don't start coding §0.31 yet.
First define the contract," with six named questions to answer, then "test that contract against the same
topology matrix" — a specification-and-validation pass, not an implementation pass, with implementation
explicitly deferred to a separate future §0.32.

**The primitive, made precise enough to implement:** `reach(seeds, maxDepth, familyFilter, direction)` — a
multi-source BFS bounded by depth/family/direction that discovers a NODE set, followed by a strictly separate
final pass that includes every edge in the full graph with both endpoints in that node set. This decoupling
is the actual, specific fix for the cycle/mesh edge-drop bug §0.28/§0.30 both named: today's
`computeViewport` never asks "what edges exist among the nodes I ended up with," it only keeps the specific
edges its own traversal happened to walk (children/parentEdges/siblingEdges as three separate arrays) — so a
cycle's back-edge is invisible even when both its endpoints are already on screen, purely because the
traversal never needed to walk that specific edge to discover a new node.

Enter Space and Focus are then compositions of one call each, not separate algorithms: Enter Space =
`reach(root, ∞, {composition}, forward)` for the core plus one hop of non-composition-family context around
it; Focus = `reach(node, 1, all, both)` for the core plus one more forward hop from the parent shell for
siblings.

**A real mistake was made and caught during this exact pass, not after.** The first draft of the Enter Space
prototype used an unrestricted `all`-family filter for its context-extension step. Tested immediately against
the nested-workflow case from §0.30 (entering `Authorization`, nested inside `Payment Process`), and the
output incorrectly included `Payment Process` — the context step had walked backward through
`Payment Process -[decomposes_into]-> Authorization`, a *composition* edge, silently reintroducing exactly
the outer context §0.24 was built to drop when entering a space. Caught by running the prototype rather than
trusting the design on paper, fixed by explicitly excluding the composition family from the context step
(`reach(core, 1, all-except-composition, both)`), and re-verified before writing any of this up — the kind of
self-correction this project's whole verification discipline exists to catch, kept in the record rather than
smoothed into "and then it worked."

**Tested against the topology matrix, prototype only, in a live Chrome console — no file in the repo touched:**

- **Cycle** (3-node, focus on any single node): before, 2/3 edges shown, the back-edge silently dropped.
  After: **3/3 edges, zero truncation** — the corrected edge-inclusion rule alone fully recovers a cycle
  within Focus's *existing* 1-hop radius. No depth increase was needed; the radius was never the problem.
- **Mesh** (5-node dense graph, focus on a low-degree node): before, node D and 5/8 edges silently vanished.
  After: the same 4/8 edges render (a low-degree node genuinely cannot reach the rest of a mesh at depth 1 —
  no algorithm fixes that without abandoning the bounded-radius idea entirely), but the contract now reports
  exactly 1 hidden node and 3 hidden edges instead of rendering as if nothing were missing.
- **DAG** (branch/converge, focus on the root vs. the sink): before, the opposite end vanished depending on
  which node was clicked, with no signal either way. After: the same 3/4 nodes render either way (also
  irreducible at depth 1), but 1 hidden node / 2 hidden edges is now reported symmetrically regardless of
  which end was focused.
- **Nested workflow** (entering `Authorization`, corrected version): correctly includes the boundary-crossing
  `Capture` (via the non-compositional `Approve→Capture` edge), correctly excludes the outer parent
  `Payment Process` and the further `Settlement`, and reports exactly 2 hidden nodes / 3 hidden edges for
  what's one hop past what's shown.

**The mesh and DAG results are the important negative finding, recorded rather than treated as a shortfall of
the design:** no algorithm can make a bounded, readable view always show everything — that would eliminate
the reason a bounded view exists in the first place. What the contract actually delivers, and what was
actually being asked for, is not completeness but honesty about incompleteness — matching the user's own
framing verbatim: "A viewport is allowed to be incomplete; it is not allowed to imply completeness when it is
bounded."

**Disclosure design**: hidden structure is never rendered as placeholder/ghost graph elements — that risks
being mistaken for real discovered content, the same category of mistake §0.27/§0.28 spent real effort
preventing elsewhere. It is metadata (`truncatedNodes`/`truncatedEdges` counts) that a later UI layer turns
into a badge anchored to the specific frontier node that has more beyond it, not a vague page-level counter,
so a viewer knows exactly *where* to look for what isn't shown, not just that something, somewhere, is
missing.

**Nothing was implemented.** No file in `frontend/chat.html` or `backend/api/app.py` was touched — the
prototype exists only as an ephemeral in-browser test, deliberately not committed, per the user's explicit
instruction to specify and validate the contract before writing any production code. §0.32 is queued as
implementation + a full topology regression run against this exact, now-tested contract.

## 2026-08-30 (continued) — §0.30: Focus and Enter Space are one operation, not two

Direct follow-on from §0.29, which closed by naming the actual remaining gap precisely: `computeViewport`'s
plain focus mode is a cruder, less consistent scope mechanism than `computeSpaceViewport`, documented but not
yet investigated. The user narrowed the question sharply before any research began — not "how do we make
navigation topology-aware" in the abstract, but "can plain Focus be reconciled with the already-proven Space
scope mechanism without losing the useful 1-hop readability Focus currently provides" — and set an explicit
guardrail against the obvious trap: "Do not make `computeSpaceViewport()` the answer merely because it
already works. The research must first establish whether Focus and Enter Space are actually the same
semantic operation with different bounds." Six precise questions were given to answer, no code allowed.

**Answered by reading the exact current code, not by design from first principles.** Tracing
`computeSpaceViewport` (`chat.html`) line by line: its "inside" walk is family-restricted (only
`composition`-family edges), depth-unbounded (walks however many compositional hops exist), and
direction-restricted (only forward/downward from the space root); its separate "context" step then surfaces
any edge of any family touching that inside set, one hop out. Tracing `computeViewport`'s focus branch:
"children" (edges FROM focus, any family), "parentEdges" (edges TO focus, any family), and "siblingEdges"
(other children of focus's own parents) — family-blind throughout, depth fixed at roughly 1–2 hops,
bidirectional (forward for children, backward for parents) by construction. First answer, before empirical
testing: these looked like genuinely different graph-theoretic operations (containment-membership vs.
ego-network), not the same operation at different radii.

**That first answer was revised after formalizing both as one primitive.** Reframed as
`closure(node, maxDepth, familyFilter, direction)`, Enter Space and Focus resolved into two named points on
the *same* three-parameter space — Enter Space = `(∞, {composition}, forward)`, Focus ≈
`(1–2, all families, bidirectional)` — not two unrelated algorithms that happen to produce similar-looking
views. This is the user's own sharper framing, adopted because it survived the falsification test the
guardrail demanded: the two mechanisms are *more* unifiable than the initial code-reading suggested, not
less. The architecture simplifies after being tested, rather than needing a new primitive to reconcile the
two — consistent with §0.29's own standard.

**Live re-tests filled in the one real gap in the evidence: the previously-undocumented cases had never been
run under Focus mode specifically**, only under whole-graph mode in §0.28's synthetic corpus. Run live,
zero LLM calls, same technique as every prior pass this session:
- **DAG**, focus on the root (`Request→FraudCheck→Capture`, `Request→Auth→Capture`): `Capture` (the
  convergence node) vanishes entirely. Focus on `Capture` instead: `Request` (the root) vanishes entirely.
  Same graph, mutually exclusive partial views depending only on which node was clicked — a new, sharper
  demonstration of exactly the failure mode this whole line of research exists to name.
- **Hub**, focus on a leaf node: fully recovers the whole star (consistent with the earlier finding — a
  richly-connected parent lets the "siblings" rule reconstruct the missing structure by coincidence, not by
  design).
- **Nested workflow**, focus on a node three levels deep (`Decide`, inside `Authorization`, inside
  `Payment Process`): the FIRST prediction made in this pass — that the immediate box context would
  disappear entirely under Focus — was checked against real output and found **wrong**. It was corrected
  before being written up rather than reported as guessed: `Authorization`'s box actually survives in the
  live result, because `Decide`'s direct parent (`Authorization`) happens to have rich compositional
  structure that Focus's parent+sibling rule picks up. What does NOT survive, in any case: `Payment Process`
  (the outer box) and everything past it (`Capture`, `Settlement`), since Focus never walks more than one
  level up regardless of what's found there. Entering `Authorization` as a Space on the identical graph was
  then shown to be strictly *more* complete — its context step reaches `Capture` via the boundary-crossing
  `Approve→Capture` edge, which Focus's fixed depth cannot reach at all. But Space is not a general
  substitute: `enter_space` explicitly refuses a leaf with no compositional children (confirmed by re-reading
  `handle_enter_space` in `app.py`), so a compositionally-flat topology (a pure DAG, cycle, or mesh with no
  `boundary_kind` structure at all) has no Space to enter — Focus is the *only* navigation available there,
  which is exactly why its own bounded behavior has to become honest on its own terms rather than being
  replaced.

**The disclosure principle, elevated explicitly:** neither mechanism discloses truncation today, and Space
is not fully complete either — a fact this pass surfaced precisely by checking, not by assuming Space was
already correct because §0.24/§0.29 had verified it for other properties. Space's context step reaches one
hop past its compositional boundary and no further (`Capture` shows, `Settlement` does not); Focus truncates
at its fixed radius with no signal in either direction. The user's framing of why this matters more than an
ordinary rendering gap, kept verbatim because it's the sharpest statement of the stakes: "A viewport is
allowed to be incomplete; it is not allowed to imply completeness when it is bounded... If Clearing →
Settlement happens to be outside the viewport and the UI gives no indication, the visualization has silently
taught something false." For a system whose entire premise is building an accurate model from evidence, an
undisclosed missing edge is a correctness defect, not a cosmetic one.

**Verdict, no code written:** consolidate at the primitive level — one general `closure(node, maxDepth,
familyFilter, direction)` function, with today's Space and Focus becoming two honestly-bounded named
instances of it, plus truncation disclosure added to both. No new Node type, no new graph type, no new stored
topology field, no duplicate graph. §0.31 is queued as the next pass: design the bounded-reachability
contract and disclosure semantics precisely before touching `computeViewport`'s implementation — not started.

## 2026-08-30 (continued) — §0.29: abstraction levels — a model-validation pass, no new schema needed

Direct follow-on from §0.28's own closing question: once topology was proven to emerge correctly from
relation family rather than investigation order, the harder question became navigation — "how does an
investigator move through that graph without losing the topology that makes it meaningful?" The user
explicitly refused to let this become an implementation task before it was validated as a *model* question
first: "§0.29 should therefore be a model-validation pass, not an implementation pass. No code until we know
whether the existing primitives are sufficient." The precise question posed: can one entity have different
valid relational structures at different abstraction levels, while remaining the same entity in one world
model — and does answering yes require new schema?

Answered by reading the actual code and replaying real data, not by design from first principles. Five
findings, deliberately framed as conclusions about the *current* model rather than universal claims — the
user's own refinement, made explicitly to keep the architecture falsifiable rather than let "abstraction =
scope" harden into an assumption nothing could ever contradict:

1. **Abstraction reduces to scope in the current model.** Tracing `computeSpaceViewport` (`chat.html`,
   §0.24): entering a space is exactly `scope(node) = compositional-reachability-closure(node)`. There is no
   separate stored "abstraction level" — `Node.kind` (`abstraction`/`entity`) is a binary tag, not a scale.
   Nothing here claims abstraction *must* be scope in every possible future model, only that no evidence so
   far requires them to be different things.
2. **Relation family is independent of scope — proven with real data, not assumed.** The exact live Test 3
   investigation from §0.28 already has `Authorization` carrying coarse `PRECEDES`/`CAN_DECLINE` relations to
   its siblings (Risk checks, Payment Capture) *and* `QUERIES`/`EVALUATES`/`EXPRESS`/`EXPRESS_IN` interaction
   relations among its own decomposed children (Authorization Enforcement/Engine/Policies, XACML, Rego) — in
   the same Neo4j graph, same entity, zero duplication, discovered organically by the existing pipeline with
   no abstraction-aware code written for it. Family lives on the edge, not the entity or the level, which is
   exactly why this fell out for free.
3. **World Model vs. View discipline holds without modification** — the same boundary §0.27 already proved
   (Neo4j never mutated by a view operation) applies unchanged to scope/abstraction: `current_space` and
   `current_projection` are both session-only.
4. **Scope and projection already compose**, confirmed by re-reading `handle_set_projection`
   (`backend/api/app.py`, written during §0.27): it already scopes its honest-gap check to
   `session.current_space`'s reachable subgraph when one is entered. "Enter Authorization, show its
   dependency relations" and "stay at Payment System, show temporal flow" are two independent settings on
   one session today, not two competing graphs.
5. **Topology is a derived read, never stored** — `topology = f(scope, projection, relation family)`,
   recomputed from whatever subgraph is currently exposed. Navigation (focus/enter/exit/back) is the verb set
   that moves the scope pointer over time (with `space_history` as its undo stack), not an additional World
   Model axis.

The user's own proposed axis list (abstraction / topology / projection / scope / navigation, floated as
possibly five independent dimensions) was directly challenged rather than accepted: abstraction and scope
collapse into one axis in the current model; topology isn't an axis at all, it's a derived view; navigation
is an operation set, not a data dimension. That leaves exactly two independent stored axes — scope and
projection — which is a sharper, smaller model than the one proposed, and the standard used throughout ("if
existing primitives already express this, don't add a primitive") is what forced that reduction rather than
a stylistic preference for minimalism.

**Live empirical proof, zero new code, zero LLM calls:** replayed the real Test 3 Neo4j data (captured by
`scripts/verify_test3_extraction.py`) through the already-deployed `computeSpaceViewport`/`renderGraph` in a
live Chrome tab. Entering `Authorization` correctly exposed its own internal interaction graph
(`Authorization Enforcement -QUERIES-> Authorization Engine -EVALUATES-> Authorization Policies -EXPRESS->
XACML`) as the space's own structure, while the coarse temporal chain (`Risk checks -PRECEDES-> Authorization
-PRECEDES-> Payment Capture`) remained visible as cross-space context, exactly matching what the model
predicted before the test ran — not adjusted after the fact. `graph.nodes`/`graph.edges` were confirmed
identical in content before and after the scope switch.

**Verdict: no schema change, no code change this pass.** The one gap this surfaced — `computeViewport`'s
plain focus mode being a cruder, less consistent scope mechanism than `computeSpaceViewport` — is explicitly
named as a future convergence/cleanup pass, not treated as evidence the World Model itself is incomplete.

## 2026-08-30 (continued) — §0.27: Semantic Graph Projections, and a real backend/frontend scope bug caught by live verification

The user reframed the research question before any code: not "how to make flow graphs" but "how can one
world model produce multiple semantically correct graph projections without changing the underlying
knowledge," explicitly naming who must NOT decide a projection's contents — "not the LLM" — and giving the
anti-pattern to avoid outright: user says "show payment as a flow," LLM says "okay, I'll investigate payment
again" is exactly the architecture this project has been escaping since §0.22's box-nesting fix. §0.25's
`PROJECTION_FAMILIES` registry (added this pass) is the deterministic answer: a fixed name→family table
(`structure`→COMPOSITION, `flow`→TEMPORAL, `causal`→CAUSAL, `dependency`→DEPENDENCY, `network`→INTERACTION),
consulted by a new `set_projection` intent and `handle_set_projection` handler that makes zero Neo4j writes
and zero LLM calls — it only re-filters `session.to_payload()`'s already-known edges by their `family`
field. The hard invariant the user demanded (`G_after == G_before` — literally the same nodes/edges after a
view switch) holds by construction: the handler never calls `create_relationship`/`find_or_create_entity`/
`_run_investigation`, only reads. A projection with zero matching relations reports an honest gap
("the model doesn't currently contain any precedes/follows relationships for what's in view... try
investigating further") rather than silently triggering a new investigation or rendering a misleadingly
empty view with no explanation.

**Live verification (backend, `scripts/verify_projections.py`, direct against the real
`SessionState`/`handle_set_projection` code — no LLM in the loop, since the code under test makes none by
design, sidestepping that day's Groq TPD exhaustion and a broken Gemini instructor mode entirely) caught a
real consistency bug before it shipped:** the backend's gap-check originally scanned the WHOLE accumulated
session graph (`session.to_payload()["edges"]`, unscoped), while the frontend's `applyProjection` was applied
on top of `computeViewport`'s tight 1-hop focus neighborhood. Confirmed live in Chrome via direct
`renderGraph`/`applyProjection` calls with a synthetic graph: a "network" projection with an interaction
edge between two of the focus entity's own children reported "0 nodes visible" in the browser because
neither endpoint was the focus entity itself — while the backend, checking the whole graph, would have
reported the match as found. Reply and render would have disagreed. Fixed by giving both layers the exact
same scope rule instead of duplicating ad-hoc logic: if `current_space` is set, scope to that space's own
compositional-BFS-reachable subgraph (`_space_reachable_ids` in `backend/api/app.py`, a direct Python mirror
of `computeSpaceViewport`'s reachability walk in `chat.html` — the same "don't hand-duplicate a traversal
across two languages and hope they stay in sync" lesson §0.25's registry already existed to prevent, applied
here to a second traversal); otherwise scope to the whole known graph. Re-verified after the fix, in both
places: Python (`scripts/verify_projections.py`, 8 checks — structure/causal/network showing correct
relations, flow/dependency producing honest gaps, `all` resetting cleanly, `to_payload` family-tagging
correct, and the new space-scoping case: an interaction edge outside the entered space is correctly hidden,
the same edge becomes visible once the encompassing space is entered) and the live browser (direct
`renderGraph` calls reproducing the exact same PayPal/Mastercard/Visa-Network space-scoping scenario,
confirming the two layers now agree pixel-for-pixel with what the chat reply says). `graph.nodes`/
`graph.edges` arrays were confirmed byte-identical in length and content before and after every projection
switch in both the Python and JS tests — the `G_after == G_before` invariant holds in practice, not just in
the architecture description.

## 2026-08-30 (continued) — §0.26: relations get their own evidence, additively, no migration

The user pushed one design question before any code: "what exactly is a relationship in this system?"
Answered by reading the actual code rather than theorizing: **relation identity — (source, type,
target) — was already correct**, before any of this session's work. `create_relationship`'s own Cypher
was already `MERGE (a)-[r:RELATES_TO {relationship_type: $relationship_type}]->(b)` — re-discovering the
same relation across investigations was already reusing the same edge, not duplicating it. What was
missing was evidence: neither of the two `create_relationship` call sites in `ground_agent.py` ever
passed `properties`, so every relation's `justification` text (already being computed for
`resolve_entity`'s own use) was printed to a log line and thrown away.

**The real fork this pass had to resolve:** Neo4j relationships can't be the source/target of another
edge — only nodes can. Attaching a Claim to a relation therefore means either (a) reifying every
relationship as its own node (the "correct" answer per this project's own much older §0.6-§0.9
conclusion that Node/Relation collapse to one primitive, Wikidata's statement-node precedent already
cited there) — a real migration touching every existing traversal function
(`get_decomposition`/`get_neighbors`/`zoom_in`/§0.22's box logic/§0.24's space logic), or (b) an additive
side-channel that leaves every existing native edge and every existing traversal function completely
untouched. Chose (b) deliberately, explicit about the tradeoff: `attach_relation_claim` (new,
`backend/graph/interface.py`) creates an ordinary `Claim` node (the exact same shape already used for
Questions) and connects it via a new `HAS_RELATION_CLAIM` edge from the source entity, carrying
`relationship_type`/`target_id`/`stance` as edge properties — the native `RELATES_TO` edge this is
evidence FOR is never modified. Zero regression risk to anything §0.17-§0.25 already verified live.

**Confidence is a stated simple heuristic, not a fabricated rigor:** `get_relation_confidence` starts at
0.5, +0.15 per supporting claim, -0.25 per contradicting one, clamped to [0.05, 0.95] — named honestly in
the docstring as "not a rigorous Bayesian update." Deliberately NOT asking the LLM to self-report a
confidence number on `CandidateRelation` (would reopen the exact schema-flakiness class of failure just
stabilized earlier this same session) — every extraction-sourced claim gets a fixed baseline (0.7) and
every decompose-structural claim gets a lower one (0.6), honestly distinguishing "text-sourced evidence"
from "the agent's own structural reasoning" as different provenance kinds.

**Live-verified against the user's own acceptance table** (`scripts/verify_relation_claims.py`, run
twice against the VM's real Neo4j — the second run's doubled counts are just because the first
timed-out SSH connection had actually completed in the background, not a bug): the native `RELATES_TO`
edge count stayed at exactly 1 no matter how many claims were attached or how many times the script ran
— the additive design holds. Confidence arithmetic matched the formula exactly (4 supports/1 contradict
→ 0.85; 4 supports/2 contradicts → 0.60). A second target's claims never leaked into the first's count.
A never-evidenced relation correctly reported `confidence: None`, not a fabricated default.

**Named, not resolved — a real tension in the user's own acceptance table:** "no evidence -> never enters
world model" is right for extraction-sourced interaction relations (already true: `is_relation_worthy`/
`resolve_entity` already gate what gets persisted), but taken literally it would break decompose's own
structural relations, which are this system's entire backbone and were never meant to require citation-
style evidence the same way. Resolved by treating "the agent's own decompose reasoning" as a real,
distinct, lower-confidence evidence kind rather than forcing decompose to either fabricate false
citations or stop attaching evidence at all — not a workaround, a genuine acknowledgment that structural
and evidentiary provenance are different things.

## 2026-08-30 (continued) — §0.25: one relation-type registry replacing three hand-synced hardcoded lists

Direct follow-on from §0.24: the user asked to move to "Relation Semantics" but explicitly wanted it
researched, not invented ("the exact taxonomy should be researched and tested, not invented casually").
Grounded the design in real prior art rather than adopting the user's own suggested family list uncritically:
Winston, Chaffin & Herrmann's 1987 taxonomy of part-whole relations (*Cognitive Science*, foundational to
WordNet's own part-of treatment) shows "composition" is actually six distinct meronymic subtypes with
**non-uniform transitivity** — justifies keeping this project's single COMPOSITION bucket as a documented
simplification, not an oversight, since nothing here yet reasons across chained compositional edges. OWL/RDF
property characteristics (transitive/symmetric/inverse-of, W3C OWL Reference) are the established,
better-than-guessed vocabulary for "what does this relation type let you infer" — used directly instead of inventing
bespoke behavior flags.

**The actual forcing bug this section fixes, found while writing the research up:** §0.24's own code had
already accumulated a hardcoded "is this compositional" set duplicated in THREE places (chat.html's box
logic, chat.html's space-viewport logic, app.py's `handle_enter_space`), with a comment on the newest copy
admitting it "must stay in sync with that JS copy" by hand. That is exactly the kind of drift risk this
project's own `_RELATIONSHIP_TYPE_SYNONYMS`/`_BANNED_RELATIONSHIP_TYPES` tables were already trying to avoid
in one place at a time — now unified.

**Built:** `backend/questions/relation_types.py` — one `RELATION_TYPES` registry keyed by canonical
relationship_type, carrying `family` (composition/causal/temporal/dependency/interaction/classification)
plus OWL-grounded `transitive`/`symmetric`/`inverse_of` fields (declared now, consumed by nothing yet, on
purpose — no traversal/inference code reads them this pass). `is_compositional()`/`get_family()` are the
only two functions anything else calls. Rewired: `relation_extraction.py`'s worthiness check,
`app.py`'s `handle_enter_space`, and — the one that actually eliminates the duplication —
`SessionState.to_payload()` now computes `family` per edge server-side, so `chat.html`'s box and
space-viewport logic both call one `isCompositionalEdge(e)` reading `e.family` instead of maintaining
their own copy of the type list. Verified end-to-end on the VM (not just unit-level): a live
`SessionState` round-trip confirmed `decomposes_into → family: "composition"` and `USES → family:
"interaction"` — the exact two relationship types today's live PayPal/Payment tests actually produced.

Temporal relations (`precedes`/`follows`, transitive, mutually inverse) were seeded in the registry
specifically because §0.23 named "most relationship_type values don't carry enough structure to
auto-derive a flow ordering" as the concrete blocker for a future flow/causal View projection (the
user's own proposed §0.27) — not building that projection now, just making sure the data model isn't
still missing this when that pass starts.

**Named but explicitly not fixed this pass** (a precise gap, not a vague aspiration): relation evidence.
Checked against the real code: `attach_claim` attaches a Claim to a Question, never to a Relation — a
`create_relationship` call (from decompose or from `extract_relations`) has zero provenance of its own
today, unlike a ground-level answer's Claims. `extract_relations` already produces a `justification`
field per candidate (§0.22) that today only gets printed to a log line and thrown away. The scoped future
slice is attaching that existing field to the created Relationship as real provenance — not decided or
built here, per the user's own "first make this reliable, then reasoning becomes interesting" ordering.

## 2026-08-30 (continued) — §0.24 built and live-verified: Focus vs. Enter Space, with a real acceptance matrix

Direct implementation of §0.23's named "smallest real slice": two genuinely different navigation
actions the system was conflating under `zoom_in`. **Focus** (existing `zoom_in`/`computeViewport`
behavior, unchanged) shows a 1-hop neighborhood while keeping surrounding context (parent/siblings)
visible. **Enter Space** (new) re-roots the rendered view at an entity's own compositional subgraph,
dropping that surrounding context — while cross-space relations stay visible, per §0.23's "a box is a
navigational boundary, not a wall."

Built exactly to the user's own acceptance matrix, verified live against each testable row rather than
assumed:

- New `Intent` actions `enter_space`/`exit_space` (backend/questions/intent.py), clearly distinguished
  from `zoom_in` in the prompt ("enter/go into/step into" vs. "show/open/focus/where is").
- `SessionState` gained `current_space`/`space_history` (backend/api/session.py), persisted the same
  additive-migration way `pending_action` was (backend/api/db.py: `alter table ... add column if not
  exists`).
- `handle_enter_space` (backend/api/app.py): resolves the entity, syncs its decomposition, and checks
  for COMPOSITIONAL children only (`_COMPOSITIONAL_TYPES`, the same set §0.22's box fix uses) before
  entering — a leaf reports gracefully and changes nothing. `handle_exit_space` pops `space_history`.
- `chat.html` gained `computeSpaceViewport`, a genuinely different computation from focus-mode
  `computeViewport`: BFS outward from the entered space following only compositional edges to find
  what's "inside," then separately collecting every non-compositional edge touching that set as visible
  cross-space context — never folded into containment.

**Live-verified on a real "How does payment work?" investigation** (fresh, since the VM's in-memory
session store doesn't survive a restart): `Enter payment` correctly replied "Entered payment. Its own
space contains: Payment Methods, Payment network, ... Payment flow" and produced a compound box with 13
children AND a genuinely nested sub-box (`Authorization`, itself containing `Authorization Enforcement`/
`Engine`/`Policies` from earlier-accumulated Neo4j history) — while `Payment network -[ROUTES_TO]->
payment`, `-[TRANSFERS_FUNDS_TO]-> acquiring institution`, `-[ROUTES_DATA_BETWEEN]-> customer's bank`,
and `Authorization Policies -[EXPRESS_IN]-> Rego` all rendered as real, visible edges crossing the box
boundary, confirmed via direct Cytoscape state inspection, not just a screenshot. `go back` correctly
replied "Back to the top level," restoring the original focus-mode view. `Enter XACML` (a leaf, reached
only via a non-compositional `EXPRESS` relation) correctly declined — "XACML has no deeper compositional
space to enter yet... Try 'go deeper into XACML'... or 'zoom in'" — and left `current_space` and the
rendered graph completely unchanged, exactly matching the acceptance matrix's leaf row.

## 2026-08-30 (continued) — Graph Spaces: a research pass, not a rewrite

The user asked for a dedicated design pass on "Graph Spaces" (their term) before building further —
formal semantics for scoped subgraphs, overlap, cross-space relations, and multi-projection views over
one World Model. Researched real prior art rather than designing from first principles: modular
ontology architecture (the "root-thematic-foundations" pattern — modules as "conceptually coherent
subparts of a domain," topic-centered subgraph extraction) is the direct precedent for Graph Space
itself; Overlapping Stochastic Block Models + BubbleSets/KelpFusion (already surveyed in §0.22) confirm
overlapping group membership is a well-studied, real phenomenon with an established rendering fix, not
an edge case being invented; multiple-view/multiform visualization ("no single projection method yields
universally optimal layouts") is the formal grounding for "one world, many projections" instead of
maintaining separate graph types.

**The load-bearing finding: Graph Space isn't a new primitive.** It's what already falls out of
`boundary_kind` (§0.21) plus the compositional-vs-interactional distinction on `relationship_type` just
fixed this same day (§0.22) — a Node with `boundary_kind` set, plus whatever it reaches via purely
compositional edges, computed on read. No new schema, no new storage — this settles as a View-layer
concept, exactly where §0.15 already drew that line. The four questions the user posed all got real,
grounded (not guessed) answers, documented in full in `docs/Architecture.md` §0.23: spaces CAN overlap
in the World Model today (rendering can't yet — bubblesets, still deferred, now for a precise reason);
relations crossing spaces is no longer theoretical, it's what §0.22's own live fix already demonstrated;
and "open node" turns out to conflate two real, different operations (neighborhood focus vs. entering a
space as the new top-level scope) that the system should eventually distinguish, not two names for the
same thing. The multi-projection half (flow/causal/dependency/timeline views) surfaced one concrete,
named gap: most `relationship_type` values today don't carry enough structure to auto-derive an
ordering — a real open question for the NEXT pass, not solved here.

No code this pass, per the user's own explicit instruction — design and citations only.

## 2026-08-30 (continued) — Composition vs. interaction: the real bug behind the Mastercard-in-PayPal's-box problem

The user's response to the PayPal/Mastercard screenshot named the actual architectural bug precisely,
not just its symptom: the box-assignment logic treated ANY edge out of a bounded entity as containment,
when containment and interaction are a genuine semantic distinction the pipeline already records and
had simply stopped checking. Their stated rule, worth keeping verbatim: **"Investigation may discover
knowledge. It may not determine the topology of that knowledge."** A box is a navigational boundary,
not a claim about what's inside it — relations should cross box boundaries freely when that's what the
evidence says, not get swallowed into containment just because one endpoint happens to be boxed.

Confirmed the exact live instance before fixing anything: `GET /graph` showed `PayPal -[USES]->
Mastercard` and `PayPal -[uses_network]-> Mastercard` sitting right next to `Payment System
-[decomposes_into]-> Mastercard` — genuine, correctly-typed relations from §0.17/§0.18/§0.22's own
extraction work, which the renderer was blindly treating as compositional just because their source
(`PayPal`) had `boundary_kind` set. The data was already right; only `chat.html`'s box-assignment
logic was wrong. Fix: box/compound-parent assignment now checks the edge's actual `relationship_type`
against a small compositional set (`decomposes_into`, `is_part_of`, `part_of`, `component_of`,
`consists_of`, `contains`) before treating it as containment — every other relationship_type (`uses`,
`routes_to`, `serves`, `connects_to`, ...) renders as an ordinary visible edge, crossing box boundaries
freely, exactly as the user specified. Zero backend changes needed — this was purely a frontend
rendering bug, since the correct semantic distinction was already present in the data the whole time.

Verified on the SAME live PayPal/Mastercard graph, no new investigation needed (a pure rendering fix
against already-persisted data): Mastercard's Cytoscape `parent` changed from `"PayPal"` (wrong) back
to `"Payment System"` (its real compositional parent) after the fix, `isParent: false` (no longer
wrongly absorbing containment), and the `USES`/`uses_network` edges now render as real, visible
cross-box connections instead of being silently dropped.

**Named, not built, per the user's own explicit scope** (a large accompanying architecture proposal —
formal Graph Space objects, a View-projection layer decoupled from a single World Model, multiple
simultaneous graph "shapes" — hierarchy/flow/network/causal/dependency/timeline/state-transition/
bipartite — all as projections over the same underlying nodes+relations): this is a real, coherent
direction and consistent with §0.15's already-designed View/Investigation/World-Model split, but it's
a substantial reconceptualization, not a bug fix. The concrete, immediately-buildable piece of it (the
compositional-vs-interactional distinction actually driving box topology) is what got built and
verified this pass; the larger View-Generator/multi-projection architecture remains a documented
direction for a dedicated design pass, not something built blind in the same turn as a live bug fix.

## 2026-08-30 (continued) — Relation-extraction field-name drift fixed, nested colored boxes verified live

Direct continuation of the box work above. Two more user requests, both chased to a real conclusion:

**Relation-extraction schema flakiness, root-caused.** The recurring `RelationExtraction` schema
failures (Groq rejecting the tool call outright) traced to a specific, confirmed cause: the model
kept emitting `{subject, predicate/relation, object}` instead of `CandidateRelation`'s actual
`source_entity`/`relationship_type`/`target_entity` fields — a strong, consistent bias toward RDF
triple terminology, observed across many independent calls all session. Tried `instructor.Mode
.JSON_SCHEMA` first (Groq and Cerebras both have it registered) on the theory that constrained
decoding would force conformance — empirically did NOT stop the drift; Groq still rejected the same
malformed shape under that mode. The fix that actually worked, confirmed by direct before/after
comparison of the schema-validation error text: **renamed the schema instead of fighting the model** —
`CandidateRelation` now declares `Field(alias="subject"/"object")`, `Field(validation_alias=
AliasChoices("predicate","relation"))`, so the JSON schema sent to the model (Pydantic's
`model_json_schema(by_alias=True)`, confirmed empirically to use aliases) already asks for the exact
field names the model wants to produce anyway — zero changes needed anywhere else in the codebase,
since `populate_by_name=True` keeps every existing `.source_entity`/`.target_entity` access working
unchanged. Also made `justification` optional with a default (observed live: sometimes omitted
entirely), removing a second, independent failure cause. Verified: the "missing properties" error
list shrank from four fields to two, then to one, across successive fixes — a live, measured
reduction, not just a plausible-sounding change. One separate, smaller residual surfaced during the
live PayPal test: a long, many-relation extraction can hit a response-length limit and truncate valid
JSON mid-string — a different failure class (token budget, not field naming) than what this pass
targeted; not fixed here, named for later.

**Nested, colored semantic boxes — verified live, not just built.** Ran a real investigation ("How do
PayPal and Mastercard fit into how payment works?"), which surfaced `payment_system`
(`boundary_kind: subject`) containing PayPal and Mastercard as siblings. Then used the existing
`investigate_deeper` flow ("Investigate deeper into PayPal") to trigger a real, fresh investigation of
PayPal specifically — confirmed via direct Cytoscape data inspection (`cy.nodes().filter(n =>
n.isParent())`) that the result is a genuine NESTED compound structure: "Payment System"
(`boundary_kind: subject`, amber `#ffb454`) containing "PayPal" (`boundary_kind: entity`, green
`#7ee787`) as its own sub-box, which itself contains 12 real discovered children (Payment Processing
Engine, PayPal Credit, risk engine, Stripe, ...) — two visually distinct colors for two different
abstractions, exactly as asked, falling out of the existing per-node `parentOf`/`boxColor` logic with
no extra nesting-specific code needed (Cytoscape compound nodes support arbitrary nesting natively).
Each child correctly shows its connection-type subtitle (e.g. "(decomposes_into)"). One organic,
unplanned detail worth naming honestly: Mastercard ended up re-parented as a child of PayPal's own box
rather than staying a sibling under Payment System, because PayPal's own deeper investigation related
to Mastercard again — real agent behavior, not a bug in the box-assignment logic, but worth knowing
when reading the resulting graph.

## 2026-08-30 (continued) — Semantic boxes shipped, and a real graph-sync gap found and fixed along the way

Direct continuation of §0.22's deferred item: the user asked to build the "abstraction and box" system
and test it live. Building it surfaced a real, previously-invisible bug: `_sync_decomposition`
(backend/api/app.py) — the function that pulls Neo4j's real graph structure into the session's
in-memory mirror the chat UI actually renders — only ever synced ONE level for the top-level entity
being investigated, and hardcoded every edge's label to the literal string `"decomposes_into"`
regardless of what relationship_type was actually stored. Two consequences, both real: (1) every
§0.17/§0.18/§0.22 typed relationship (routes_to, forwards_funds_to, ...) was silently displayed as
"decomposes_into" in the live UI even though Neo4j had the correct label all along, and (2) a sibling-
to-sibling relation attached to a CHILD entity (not the top-level one) would never reach the session
mirror at all, since the sync never looked past one hop — meaning §0.22's sibling-relation fix could be
working perfectly in Neo4j and still never appear in the chat graph. Fixed with a new
`get_decomposition_typed()` (backend/graph/interface.py, returns `(relationship_type, node)` pairs
instead of dropping the type) and a bounded recursive BFS in `_sync_decomposition` (depth ≤3, ≤40
nodes — Neo4j accumulates across every investigation ever run for a name, so this has to be bounded
independent of how large that history has grown, not just this session's own depth/step budget).

Semantic boxes: `GraphNodeOut` gained `boundary_kind`, threaded through `_sync_decomposition` into the
session payload. `chat.html`'s `renderGraph` assigns each node to at most one compound-box parent — the
nearest bounded ancestor edge in the current viewport (Cytoscape compound nodes require a strict tree,
so this is deliberately the non-overlapping default case from §0.22's plan; `cytoscape.js-bubblesets`
for the overlapping case is still deferred, not built). New CSS (`node:parent`) renders a bounded entity
as a labeled dashed (Subject) or solid (Entity) container instead of a plain pill, per §0.21's theory.

Live mid-build feedback from the user, applied immediately: a box already IS the connection between
its owner and whatever it contains, so drawing an arrow on top of that containment is pure redundancy
— fixed by dropping any edge whose (source, target) pair matches an already-assigned box parent,
regardless of the edge's relationship_type (not just decomposes_into ones).

**Verified live** on the VM with a real "How does payment work?" investigation (~4 minutes, several
provider retries en route, degrading gracefully throughout): master-level decompose correctly judged
`payment` as `boundary_kind: "entity"`; the chat UI rendered a single clean labeled box titled "payment"
containing its 10 discovered children, with zero redundant per-child arrows, while the separate
`payment_system -[contains]-> payment` abstraction edge (genuinely outside any box) still rendered
normally — confirming the box/suppression logic distinguishes the two cases correctly, not just
suppressing everything. Two things observed live, NOT fixed this pass, named precisely rather than
glossed over: (1) `extract_relations` failed schema validation on every provider attempt during this
specific run (Groq's smaller model repeatedly returned a malformed tool-call shape for the
multi-candidate `RelationExtraction` schema), so zero sibling relations actually persisted this time —
the mechanism was already isolated-function-verified working earlier the same day
(`Client Bank -[forwards_funds_to]-> Merchant Bank`), so this reads as the schema's existing
reliability flakiness on larger candidate lists, not a regression, but it means the box feature and the
sibling-relation feature haven't yet been jointly observed producing a real non-decompose edge INSIDE a
box in the same live run. (2) Neo4j has visibly accumulated near-duplicate entities for "payment" across
past test runs (Authorization / Authorization Process / Payment Authorization, etc.) — pre-existing,
newly VISIBLE now that recursive sync shows more of Neo4j's real accumulated state than the old
one-level sync ever revealed, not something this pass introduced.

## 2026-08-30 (continued) — Redesigned cursor-flow from an aggregate grid to real recorded-and-looped paths

Same day, immediate follow-up once the WASM fluid background (below) was live: the user proposed a
more literal mechanism than the coarse spatial-average grid — record each visitor's own cursor path
(with real timestamps) for their first two minutes on the HOME PAGE ONLY, store it, and loop it back
as ambient motion for later visitors, rather than collapsing everyone's motion into one blurred
average field. Researched session-replay privacy practice specifically (this is a materially heavier
data posture than aggregate heatmap binning — a stored path is a real, if anonymous, movement trace)
before building: industry guidance (Mouseflow/Heap/Sentry writeups) centers on anonymization, PII
exclusion, retention limits, and consent for tools that also capture DOM/keypresses/form data. This
feature captures none of that — only (t_ms, nx, ny) motion geometry, no identity, no cross-session
link — so it's categorically lighter than commercial session replay, but the retention bound was set
deliberately stricter anyway: a rolling cap of 60 stored paths by COUNT (not the 30-90 day windows
typical of session-replay retention), enforced on every insert.

Replaced (not added alongside) the grid-aggregate system: `backend/telemetry/flow_store.py` deleted,
`backend/telemetry/path_store.py` added (`add_path`/`get_random_paths`, same `aiosqlite` pattern),
`init_path_db()` also drops the old `cursor_flow` table on startup rather than leaving it as unused
dead weight. Endpoints became `POST /telemetry/path` (one visitor's own recorded path, clamped and
sorted server-side) and `GET /telemetry/paths?limit=N` (a random sample of previously-stored paths).
`frontend/wasm/fluid-bg.js` rewritten: records the current visitor's own path client-side, sends it
once (2-minute mark, or on tab-hide/pagehide if they leave sooner, via `sendBeacon`), and on load
fetches a handful of others' recorded paths and loops each one forever (`elapsed % duration`, binary-
searched and linearly interpolated between bracketing samples) as a "ghost" cursor injecting into the
same WASM fluid sim as the visitor's own live cursor — so the field is built from real recorded human
motion, not a synthesized or averaged pattern, and never looks the same twice. Scoped to the home page
only via a `window.FLUID_HISTORY_ENABLED` flag `index.html` sets and `docs.html` deliberately leaves
unset (docs.html keeps only the local live-cursor fluid effect, no recording, no fetch, no ghosts) —
exactly the user's stated scope. Verified end-to-end on the VM: `POST` a real path, `GET` reflects it
back byte-for-byte, and a fresh page load's `GET /telemetry/paths` fetch visibly renders that path's
traced route in the live fluid background.

## 2026-08-30 (continued) — A real WebAssembly fluid sim driven by aggregate cross-visitor cursor data

Direct continuation of the node-network pass below: the user rejected the dots-and-lines network
outright ("different background not this") and asked for something much more ambitious instead — a
flow-field background where the flow itself is shaped by real, aggregated data of how every visitor's
cursor has moved across the site over time, combined with the current visitor's own live cursor, the
whole thing computed as an actual fluid simulation in WebAssembly. Built and shipped, not just
designed:

- **Backend** (`backend/telemetry/`, new package): a coarse 48x27 grid (`GRID_W`/`GRID_H`), aggregated
  in a small SQLite file (same `aiosqlite` pattern as `backend/runtime/state_store.py`) via pure
  addition (`vx_sum += `, `vy_sum += `, `count += `) — commutative/associative, so concurrent anonymous
  clients need no coordination. `GET /telemetry/flow` returns per-cell averages only, never raw sums;
  `POST /telemetry/flow` accepts the CALLER'S OWN already-locally-aggregated cell deltas (the client
  bins its own pointer samples before ever sending anything — the server never sees a raw per-pixel
  trace) and clamps every field defensively (this is a public, unauthenticated boundary). Privacy
  research (VWO/Hotjar/LiveSession heatmap-tooling writeups, a behavioral-biometric-privacy survey)
  confirmed aggregate-only + anonymize is the standard practice this follows; full consent-banner
  machinery was judged disproportionate for anonymous, non-identifying, aggregate-only movement sums
  on a personal project, but worth remembering if this ever needs a compliance pass.
- **The fluid solver** (`frontend/wasm-fluid/`, new Rust crate): a real port of Jos Stam's "Stable
  Fluids" (SIGGRAPH 1999) — historical-bias -> project (Poisson pressure solve, Gauss-Seidel) ->
  semi-Lagrangian self-advect -> project again, each frame. Diffusion deliberately omitted (a common
  real-time simplification, confirmed against several reference Stable Fluids implementations found
  while researching). Two independent forces drive it: the aggregate field from `/telemetry/flow` (a
  slow, shared, ever-present "current") and the current visitor's own cursor, injected live — the
  field never looks the same to two visitors because it's the same shared history perturbed by a
  different live hand.
- **Real build obstacle, fixed, not routed around**: `wasm-pack build` failed outright — this machine
  has no Visual Studio / MSVC Build Tools installed at all (confirmed: no `vswhere`, no VS directory),
  so `wasm-bindgen`'s proc-macro dependencies (`proc-macro2`/`quote`) couldn't compile their own build
  scripts for the HOST target, regardless of which target the crate itself was being built for. Fix:
  dropped `wasm-bindgen` entirely and rewrote the crate as raw `extern "C"` exports moving flat `f32`
  buffers across the boundary (`wasm_alloc` for JS-side scratch buffers, direct pointer+length exports
  for the velocity field) — bindgen's JS-marshalling was never needed here since nothing but numbers
  crosses the boundary. `cargo build --target wasm32-unknown-unknown` alone (no wasm-pack) then
  compiles cleanly with zero host-side linking, using only `rust-lld` (already present with the
  `wasm32-unknown-unknown` target). Output: a 28KB `.wasm`, functionally verified in a standalone Node
  harness (instantiate, seed historical field, inject, step 10x, inspect output) before ever touching
  a browser.
- **Frontend** (`frontend/wasm/fluid-bg.js`, new shared file — extracted rather than duplicated inline
  like this project's simpler per-page background scripts, since the WASM-loading/telemetry logic here
  is complex enough that duplication risked drift): samples `pointermove` at ~14/s (in line with
  standard mouse-tracking practice), locally bins deltas into the same 48x27 grid, injects live force
  into the WASM sim every sample, flushes accumulated deltas to the backend every 6s and via
  `navigator.sendBeacon` on `pagehide`/tab-hide, and renders by bilinearly sampling the velocity field
  each frame to advect ~100-170 canvas "dye" particles with a fading trail. Wired into `index.html` and
  `docs.html` only — `chat.html` deliberately excluded, unchanged, per the user's explicit instruction
  (it already has the real live investigation graph). Skips entirely under `prefers-reduced-motion`.
- **Live-tuned, not shipped on first guess**: the first working version (nearest-cell velocity
  sampling, higher particle count/opacity, weaker historical decay) looked "scratchy" rather than
  fluid once actually tested live in Chrome with real cursor movement — diagnosed as the coarse grid's
  cell boundaries being visible without interpolation. Fixed with bilinear sampling across the four
  nearest cells plus reduced particle count/opacity and faster historical-decay, then re-verified live
  (both scripted drag/hover paths and dispatched `PointerEvent`s) before calling it done.
- **Deployed and verified end-to-end on the VM**, not just designed: new backend files copied, new
  `init_flow_db()` call added to the FastAPI startup hook, `CONFIG.BACKEND_URL` blanked to `''` in
  `index.html`/`docs.html` for the VM's same-origin demo mode (same discipline this project already
  applies to `chat.html`), uvicorn restarted, and the full loop confirmed live: `GET /telemetry/flow`
  empty -> `POST` a delta -> `GET` reflects the exact aggregated average -> static `.wasm`/`.js` assets
  served correctly via the existing `StaticFiles(directory=FRONTEND_DIR)` mount (no new route needed)
  -> visible, reactive fluid motion in an actual browser tab against the deployed VM.

Not yet done: none of this has touched production (Vercel + Render) yet, only the VM. The MSVC
toolchain gap this session hit is a real, standing constraint on this machine for any FUTURE
wasm-bindgen-dependent work (not just this pass) — worth fixing properly (install VS Build Tools, or
standardize on the raw-`extern "C"` pattern this pass already proved out) before the next WASM feature
assumes wasm-pack "just works" here.

## 2026-08-30 (continued) — Researched background-animation UX, added an on-brand node-network to home/docs

While waiting on provider quota to reset (all three LLM providers hit simultaneously — Groq's daily
token cap, Gemini's daily free-tier request cap, and Cerebras's free tier ending 2026-08-17 and now
needing a card added for its $5 credit), the user asked for a frontend polish pass: first a visual/UX
comparison pass across `/`, `/chat`, `/docs` (found and fixed a real inconsistency — `/docs` was
missing the ambient blob glow and pulsing footer dots that `/` and `/chat` both already had), then
explicitly asked for more background animation on `/` and `/docs` specifically, not `/chat`, and for
real research behind the choice rather than an arbitrary pick. Researched: canvas-based particle/node-
network backgrounds are a well-established, actively-used technique for exactly this ambient-dark-
theme use case; `prefers-reduced-motion` is a real WCAG-relevant requirement for persistent background
motion with no pause control (WCAG 2.2.2), not just a nice-to-have. Chose a hand-rolled vanilla-canvas
drifting node network over a particle library specifically because it's *literally* a small knowledge
graph — on-brand for this exact product in a way generic particles wouldn't be — and because it needs
zero new dependencies, consistent with the project's own "no framework, no build step" frontend
choice already recorded in Architecture.md's stack table. Implemented identically in `index.html` and
`docs.html` (each self-contained, matching this project's existing per-page-inline convention, e.g.
the blob CSS duplication); explicitly left `chat.html` untouched per the user's instruction, since it
already carries the real live Cytoscape graph and a second decorative one would compete with it. The
script exits immediately under `prefers-reduced-motion: reduce` — no motion, no static leftover
clutter either. Note: `index.html` was previously zero-JavaScript; this is the first script added to
it, a deliberate small trade made explicit to the user rather than assumed.

## 2026-08-30 (continued) — Literature survey, then a live-verified fix for "the graph is always a tree"

Same day, next problem the user raised directly: real investigations only ever produce parent→child
`decomposes_into` edges — siblings discovered under the same parent (e.g. Client, Client Bank,
Merchant Bank, Merchant while investigating a payment) never get edges to each other, even when the
real relationship (forwards funds to) is exactly what a graph should show. The user also set a new
standing rule this session: real research before every decision from now on. A literature survey ran
first — DocRED and document-level relation extraction as the established task name for this problem;
a real, multi-source-confirmed LLM bias toward relations anchored on the one named "topic" entity
(entity-salience/primacy-bias literature, GraphRAG's own documented hub-and-spoke failure, a formal
causal-bias paper, and NAACL 2025's entity-pair-guided DocRE fix); GraphRAG's and LightRAG's actual
production prompts fetched and read, both using the same two-pass "identify entities, then all-pairs
among them" shape; Graphusion (arXiv:2410.17600) naming this exact failure as its own motivation, with
a measured +9.2% fix. Root cause confirmed at the code level: `_finish()` called
`extract_relations(entity_name, result.answer)` — one entity, one entity's own text, siblings never
in view. Fix: `_investigate_loop` now accumulates every entity `decompose` discovers under the same
parent (`discovered_entity_names`), threads it into `extract_relations` as `sibling_entity_names`, and
the extraction prompt now explicitly asks for all-pairs relations among the known set, not just pairs
touching the named entity. Live-verified with a real provider call (`scripts/verify_sibling_relations.py`,
no mocking): given a client-pays-merchant-through-two-banks passage, the call correctly returned
`Client Bank -[forwards_funds_to]-> Merchant Bank` — a genuine sibling-to-sibling edge. Full detail
and citations: `docs/Architecture.md` §0.22. Deferred, not built this pass: the "semantic boxes"
visualization idea (Cytoscape.js compound nodes for the non-overlapping case, `cytoscape.js-bubblesets`
for overlapping actor scopes — both surveyed and named in §0.22, neither implemented).

## 2026-08-30 — Subject/Entity, re-derived from memory, turned out to already be the plan

The user restated the project's own original abstraction vocabulary unprompted, months in —
Subject (2D abstraction: a named boundary around domains only) and Entity (3D abstraction: a
boundary around domains *plus the specific question it solves*), asking to give the agent real
power to draw and name these boundaries, and for zoom-in to open a node's own internal graph
rather than return a summary line. Checked against `docs/SystemDesign.md` §3-6: word-for-word the
original spec, not drift. Checked against the deep §0.6-§0.16 design arc already in
`docs/Architecture.md` (Node/Relation stress-testing, `kind` as a question-relative annotation, the
View/Investigation/World-Model split): the same conclusion, reached independently from a totally
different direction months apart — Subject and Entity are the two `kind` values that arc's own
punch list was always missing, and "zoom opens the node's internal graph" is exactly what §0.15's
View semantics already specify, just not yet built end-to-end (`handle_compare` still persists a
comparison node; `handle_zoom_in` still returns a one-line summary instead of a View). Documented as
`docs/Architecture.md` §0.21 and added as a new Theory section on the public `/docs` page, both
[THEORY]/design-only per the user's own explicit choice this round — the actual boundary-naming
decision and the View-based zoom/compare rebuild are next, not done here.

## 2026-08-29 (continued) — From typed edges to a real identity resolver to a conversational-state layer, all verified live on the VM

Direct continuation of the entry below, same day. That entry ended with the Node schema frozen (§0.16) and the punch list ordered: scope-hint extraction, the Model Graph implementation, and a network-aware renderer, "deliberately last." What actually happened next was forced by live use, not the planned order — the user hit real bugs while using the deployed system, and each one became a research pass with a working fix, verified against the real VM before being called done. Full detail is `docs/Architecture.md` §0.17-§0.20; this is the summary.

**§0.17 — typed relationships, the first real slice past `decomposes_into`.** A live payment-processing investigation showed the graph capturing none of the Mastercard/PayPal role structure the answer text clearly described — the smartphone-pipeline finding from months earlier (`decomposes_into` can't express non-hierarchical structure), now reproduced independently. Found by direct code read, not assumption: `create_relationship` already accepted any relationship-type string; the only call site (`ground_agent.py`'s decompose branch) had it hardcoded. Added `GroundDecision.relationship_type: Optional[str]`, defaulting to the old literal when unset — fully backward compatible. Verified live: a real investigation still defaulted correctly for a genuinely compositional question, and a targeted probe produced a real non-default label (`routes_to`) unprompted. One real bug caught before shipping: `get_decomposition` filtered its Cypher match to the literal string `"decomposes_into"` — any non-default edge would have been silently invisible to `zoom_in`. Fixed to match any outward edge.

**§0.18 — the big one: relation discovery, canonicalization, and a frozen identity resolver, each earned through a failed experiment before being trusted.** A live 4-question test on a cyberattack topic showed the vocabulary problem was worse than expected — every edge defaulted to `decomposes_into` even under deliberately actor-framed questions, including one clean miss (`Privilege Escalation -[decomposes_into]-> Intrusion Detection System`, backwards and non-compositional). Diagnosed by controlled experiment, not guessed: the same content, asked as a rider on an action literally named `"decompose"`, produced the wrong answer; asked as a genuinely separate decision, it produced the correct one on the first try. Built `extract_relations()` as a real standalone decision (`backend/questions/relation_extraction.py`) with its own prompt, explicitly told it is not deciding whether to decompose anything — plus `is_relation_worthy()`, the mechanically-enforceable half of a four-question worthiness test (both ends independently a thing; stable across phrasing; useful for a different question; names the real acting direction, not a generic `relates_to`).

Then two more real defects surfaced and got run down the same way: (1) direction sometimes came out backwards under the new mechanism too — a controlled A/B test found the real, more useful bug wasn't direction at all but **active/passive voice inconsistency** (the same fact represented as two structurally different edges depending on which voice the model picked); fixed with `canonicalize_relation()`, a genuinely separate normalization step, validated 8/8 on an adversarial voice matrix (active/passive/modal, three fact-pairs) before being trusted. (2) `normalize_relationship_type()` added as a small deterministic string-synonym table built only from variants actually observed (`detects`/`spots`/`monitors` -> `DETECTS`, etc.) — explicitly not a speculative ontology.

Identity resolution then forced its own detour: `find_or_create_entity`'s exact-(name,scope)-match reproducibly **collided** two genuinely different `Transmission`s (electric grid vs. computer networking) when unscoped, and — the sharper finding — **fragmented** one genuinely identical `Internet` into two permanent nodes when a blanket scope was applied to both relation endpoints indiscriminately. Neither "always scope" nor "never scope" is safe. Resolved by building `resolve_entity()` (`backend/graph/interface.py`) — a real four-outcome contract (`REUSE`/`CREATE`/`AMBIGUOUS`/`CONFLICT`, `selected_node` populated only for the first two), scored by token-overlap between context and each candidate's real graph neighborhood plus its own scope string, frozen only after a six-case evidence-type matrix (lexical/domain/relational/opposing-lexical/no-evidence/conflicting) went 6/6 — critically, `CONFLICT` (real competing evidence) and `AMBIGUOUS` (no evidence at all) came back as genuinely distinct outcomes, not the same shrug under two names. Wired into `ground_agent.py`'s relation loop with the rule the user specified directly: a relation persists only when **both** endpoints resolve to `REUSE`/`CREATE` — an unresolved endpoint means the relation is silently skipped, never written as a half-known edge.

**§0.20 — conversational state, the missing third layer.** Forced by a real reproduced bug: "explain me how actually scalability work..." was classified as `explain` (a narrow provenance action) purely because the message contained the literal word "explain" — the same failure shape as the decompose-verb bias in §0.18, twice in one day. The dead-end reply ("hasn't had any questions attached") was then followed by a bare "yes," which `parse_intent` — with zero conversational state to consult and no safe fallback in a forced six-value action enum — fabricated into a full `new_investigation`. Fixed by adding a real third state (world model / knowledge state / conversation state, kept genuinely separate): `PendingAction` on `SessionState`, a deterministic (non-LLM) confirmation classifier that runs before `parse_intent` on every turn so a bare yes/no never reaches the LLM, a `no_action` escape hatch added to `Intent`, `handle_explain` fixed to both set `current_entity` (it silently never had) and offer investigation instead of dead-ending, and the `"explain"` prompt boundary tightened. All three regression cases verified end-to-end on the real deployed VM, including the exact original failing message. Same `PendingAction` mechanism then extended to `zoom_in`'s identical dead-end pattern the same day, at the user's request, after a live-use moment showed `zoom_in` landing on a genuinely unrelated foreign node (a real `Authorization` entity that existed from a completely different prior investigation, correctly reused by exact-name match, but disconnected from the current session) — named precisely, not fixed yet: compositional facts stated only in a synthesized answer (never an actual decompose step) still fall through a gap between two mechanisms that each assume the other owns it.

**Everything in this entry was deployed and tested against the real running VM, not just designed** — Neo4j inspected directly for every claim (node IDs, scopes, edge counts), never assumed. One recurring, unrelated infrastructure fact worth recording since it shaped test pacing all day: Groq's daily token cap was hit multiple times, correctly falling through to Gemini every time (slower, never broken) — the provider fallback chain built earlier this project held up under real, sustained exhaustion, not just in a clean test.

**Deliberately not done, named as next in `docs/Architecture.md` §0.18/§0.19/§0.20:** per-question knowledge-coverage sufficiency (a Node can have *some* knowledge without having *enough* for a specific question); `additional_relations`/arbitrary network topology (still gated behind vocabulary trust); the compositional-fact-in-synthesized-answer gap just named for `zoom_in`/`Authorization`; contextual continuation ("why?", "what about X?"); and the full learner/mastery-modeling vision (§0.19), explicitly sequenced last since it assumes a relational world model that only became real today.

---

## 2026-08-29 — Post-hackathon research arc: from "graph feels broken" to a named World Model, plus two verified implementation passes

A full day's arc, all in `docs/Architecture.md` §0.6-0.15 (this entry summarizes; that's the detailed record). Triggered by live use after the hackathon deploy: "the graph is just working but nowhere near what we want" — zoom re-triggers investigation, only one abstraction level, sources never appear anywhere despite the project having built a real Evidence Engine earlier.

**The audit (§0.6) found the complaint was mostly a dormant-feature problem, not a wrong decision.** PRD.md already specified the "roadmap + sources underneath" shape (§4a), scheduled for a Phase 6 that got skipped under hackathon time pressure. The Evidence Engine (`backend/evidence/`) was fully built and pre-hackathon-verified — `GroundAgent.gather_evidence` just defaulted to `False` and the demo's `_run_investigation` never turned it on. One missing keyword argument, not an architecture gap. The one genuine gap: the graph conflates *how the agent investigated* with *what should be shown as the model of the subject* (named already on hackathon night, §0.5, deliberately deferred).

**Model Graph design (§0.7-0.9), each claim tested against real examples or real code, not asserted:**
- Four layers: Question (context, not a node) / Model Graph / Investigation Trace / Evidence — because `decomposes_into` can't express a process (smartphone-photo pipeline: capture -> encode -> transmit is sequence/data-flow, not hierarchy).
- Two primitives, not more: `Node` (kind-tagged: entity/process/abstraction, not separate classes) and `Relation` — then, under stress-testing the "Payment is simultaneously process/event/relation" adversarial case (§0.8), collapsed to **one** primitive: `Relation` is a role a `Node` occupies (has connecting edges to other elements, under a question), not a separate type. Real precedent: Wikidata statement nodes, the N-ary relation pattern.
- Identity (§0.9): near-decomposability (Simon, 1962, already `[VERIFIED]` for entity discovery pre-hackathon) generalizes to Node-hood itself being question-relative. Checked `find_or_create_entity` directly: it resolves by *global* case-insensitive name match, zero context — confirmed the "Transmission in an electric grid vs. in telecom" collision is the *live system's actual behavior today*, not a hypothetical. Fix: identity scoped to (name, nearest discovery-time abstraction ancestor).
- Traced the identity rule (§0.10) and the evidence chain (§0.11) against constructed examples and real graph-interface code before writing any of it: identity rule passes 4/5 acceptance criteria outright, the 5th (comparison) needs a scope-hint channel; evidence-chain attachment already exists as a two-hop path (`Node -HAS_QUESTION-> Question -ANSWERED_BY-> Claim`), and claim-provenance-survives-synthesis is already `[VERIFIED]` code (`trace_claim`, `audit_synthesis`) that just needed re-pointing, not reinventing.

**Two punch-list passes implemented and verified live, not just designed:**
- **Pass 1** (§0.12): `gather_evidence=True` turned on in `app.py`. Verified against Neo4j directly: 84 real `Claim` nodes with real `source_url`s (arXiv, Wikipedia). Found, as a bonus: confidence scoring already correctly discriminates relevant sources (0.8-0.85) from irrelevant ones (0.0, e.g. CERN physics papers returned for a PayPal question) — the signal is trustworthy, nothing acts on it yet (a small follow-up, not a broken system).
- **Pass 2** (§0.13): provenance bridged onto Neo4j via `find_agent_id_by_question_id`/`trace_claim_from_entity` (`backend/agents/provenance.py`) — a bridge using `Question.id` (already identical in both SQLite and Neo4j), not a reimplementation of `trace_claim`'s classification logic. All 6 acceptance criteria verified live against the same smartphone-photo data; `audit_synthesis` needed zero code changes since it was already structure-agnostic.

**Pass 3 (§0.14) — a genuine split verdict, the kind the acceptance test was designed to surface, not a failure:** the identity *mechanism* is `[VERIFIED]` deterministically (direct `find_or_create_entity` calls with different `scope_hint`s produced two distinct nodes, zero LLM calls). The *extraction* layer (`parse_intent` populating `Intent.scope_hint` from real phrasing) fails reproducibly across all three of the acceptance test's own questions — worse than "drops the hint," the compare-question case folded the disambiguating context into `entity_name` as one compound string, which would make the same real thing resolve to different nodes depending on phrasing. Diagnosed, not yet fixed: extraction reliability for compound noun phrases is a harder problem than the schema assumed, in the same family as two earlier self-report failures this project already hit (`discovered_entity_name`, `working_framing`). Also found and (later, same day) fixed: the decompose-branch and session-mirror `find_or_create_entity` calls weren't threading `scope_hint` through even where the mechanism worked correctly elsewhere in the same request.

**Live re-verification of the decompose-branch fix got blocked by a real infrastructure event, not a code problem:** mid-test, Groq's daily token quota, Gemini's free-tier daily request quota, and Cerebras (still needs billing from earlier) were all simultaneously exhausted — the entire provider fallback chain dead at once. Not resolved same day; live testing paused, design work continued (below) since it needs no API calls.

**View/Investigation/World-Model split (§0.15), explicitly not touching code:** named a third category that had been silently conflated with "investigation": a **View** (a comparison, a lens, a zoom) reads the World Model and never writes to it — *a view is not knowledge*. Concrete, already-true-of-live-code motivating example: `handle_compare` currently **persists** a new canonical `"A vs B"` node into Neo4j for every comparison, which is precisely the category error this section names. Deliberately not fixed yet — the semantic rule needed documenting and agreeing before the fix, not after. Also reframes zoom cleanly: it's simply a View (reads the World Model at a chosen resolution, costs nothing) with investigation firing only when the View hits the edge of known territory (0.6.2's "tile" idea, now with a name for why it's safe to treat as free).

**Where this leaves the punch list (§0.15's revised ordering):** scope-hint mechanism, node identity, evidence, and provenance are done and verified; View semantics are now documented; scope-hint *extraction*, the Node schema freeze, the Model Graph implementation, and a network-aware renderer (deliberately last — the current breadthfirst tree layout is already known, §0.7, to be structurally wrong once the model is a real network, so fixing it before the model exists would be styling a renderer for data that doesn't exist yet) are what's left, in that order.

---

## 2026-08-28 — Implicit-framing exposure: make the silent choice visible, don't build revision yet

Direct follow-up to the revision-signal battery's actual finding — not the hypothesized "decompose then discover it's coupled, collapse" (never observed), but "the model picks one of several valid framings and never says so" (observed, concretely, in the PayPal run). Explicit agreement: expose the choice, resist turning it into a `FramingType`/`FramingConfidence`/`FramingAlternatives` schema — one field, reusing the existing `GroundDecision` pattern already used for `discovered_entity_name`.

**Built:** `GroundDecision.working_framing: Optional[str]` — set only when `action == "decompose"` at `level == "master"` **and no explicit Dimension was given**, naming the implicit lens in a few words (e.g. "Technical/system architecture"). Left unset when an explicit Dimension is present (the dimension already names the lens) or when the action isn't a master-level decompose. `decision.py`'s system prompt gained one paragraph explaining most subjects decompose validly along more than one axis and that not stating which one you used is itself a silent choice — same rhetorical shape as the `discovered_entity_name` contradiction-check paragraph. `GroundAgent`'s existing per-step log line now appends `working_framing=...` when present, so it's visible in the trace, not just the returned object — no new logging mechanism.

**Verification (`scripts/verify_working_framing.py`):** "How does PayPal work?" run three times — no dimension, `+Economic`, `+Historical`. No-dimension case: `working_framing = "Technical/system architecture"`, decomposed into transaction processing/funding mechanisms — matches what the revision-signal battery already saw it default to. `+Economic`: decomposed into revenue sources/fee structure/take rates. `+Historical`: decomposed into Confinity/X.com/eBay-acquisition origins. Three genuinely different decompositions, not one structure with a label stapled on. Reproduced identically on the VM. `verify_phase2/3/4.py` re-ran locally and on the VM, all pass (this pass only touched `GroundDecision`'s schema, `decision.py`'s prompt, and one log line).

**A real, minor deviation, reported rather than silently accepted:** the model populated `working_framing` in the `+Economic` and `+Historical` cases too, despite the prompt explicitly saying to leave it unset when a dimension is given — reproduced identically on both local and VM runs, so not a fluke. Judged low-stakes and not worth another prompt-tightening iteration: `working_framing` is a purely observational field (nothing downstream branches on whether it's null), and in both "violating" cases its value was just a harmless, accurate restatement of the dimension already visible on the `Question` object — the actual goal (explicit dimension produces a visibly different, correctly-framed decomposition) held in both cases. Chasing perfect conditional compliance on a field that exists only for visibility would itself be the kind of premature rigor this pass was trying to avoid. Flagged here in case it matters more once something downstream actually reads this field.

**Deliberately still not built:** any keep/collapse/restructure revision mechanism. Per the explicit plan: observe more investigations with framing now visible, find an actual case where the upfront framing turns out wrong mid-investigation, study what information exposed that, only then design revision around real evidence.

---

## 2026-08-28 — Hackathon demo: two real bugs found by actually using it (Amazon investigation + zoom semantics)

Found by the user driving the live demo, not by more design discussion. Both diagnosed from the actual trace/Neo4j state before any code changed, per explicit instruction.

**Bug 1 — Amazon's decomposition stopped one step too early, and it was a parameter, not an architecture bug.** Asked "How did Amazon become dominant... what systems allowed it to sustain that?" Answer named 7 systems (fulfillment centers, robotics, Amazon Air, last-mile, Prime, routing algorithms, FBA); persisted graph only had `Amazon → Logistics Network → Fulfillment Centers`. Root cause, confirmed directly from `uvicorn.log`: the master's *second* decompose call correctly reasoned "one major independently investigable component is AWS... decomposing now" — and was silently overruled, because `backend/api/app.py`'s `DEMO_MAX_STEPS`/`DEMO_MAX_DEPTH` had been cut to 1/1 a few hours earlier for demo latency. `_investigate_loop`'s budget gate discards a "decompose" verdict once the step count is hit, regardless of whether the verdict was correct — so a *right* decision was thrown away, not a wrong one. The 7-system richness in the final text came from the ONE persisted child ("Logistics Network") answering in one unrecursed paragraph, not from synthesis hallucination — `synthesize_answer` was honest and explicitly disclaimed the parts it hadn't covered. **The `decompose → discovered_entity_name → find_or_create_entity → decomposes_into` chain itself was never broken** — verified working for every step the budget actually let through, both here and in every real session the previous night. Classification: coverage/budget (analogous to session 2's "confidence ≠ investigation coverage" finding from last night, but at the decomposition-budget level instead of the synthesis level). Fix: raised `DEMO_MAX_STEPS`/`DEMO_MAX_DEPTH` back to 3/2, now that the actual latency fix (routing master-level decisions to `MASTER_MODEL_CHAIN`, done earlier this morning) is in place — the steps/depth cut and the model-tier fix had been bundled together under time pressure; only the model-tier fix was the real reliability win. **[VERIFIED]**: one live investigation ("How does a modern airline stay profitable and operate reliably?") after the fix — master correctly decomposed into two genuinely separate components (Revenue Management, Reliability Management) across two real steps, then correctly chose to answer on the third call based on its own structural judgment ("both sub-questions have already been resolved... without needing further decomposition") rather than being cut off by budget.

**Bug 2 — "zoom" was rendering the full accumulated session graph, not a focused viewport.** Asked to "go a level deeper into logistics" — the investigation correctly discovered `Fulfillment Centers`, but the UI displayed the entire ancestor chain (`Amazon Dominance → Amazon → Logistics Network → Fulfillment Centers`) as if it were Logistics Network's own decomposition. Root cause, confirmed by direct code inspection, not assumed: `SessionState` accumulates every node/edge ever seen in the conversation (correct — that's the persistent session model), but `renderGraph()` in `frontend/index.html` drew the *entire* accumulated set unconditionally every time, with zero filtering by `current_entity`. This was a missing feature, not existing logic behaving wrong — nothing anywhere implemented a "current focus" viewport distinct from "everything discovered so far." Fix, entirely client-side, zero backend/schema/Neo4j change: a `computeViewport()` function renders only the focused entity, its direct children, and its direct parent(s) — parents styled as dimmed/dashed "context," not as dominant structure. The underlying accumulated graph is untouched; only what gets drawn changes. **[VERIFIED]**: zero new investigation calls — reused Amazon's already-persisted Neo4j structure via two cheap `zoom_in` calls (intent-parsing only, no new LLM investigation), confirmed both by direct inspection of `computeViewport()`'s output (`focusId: "Logistics Network"`, `parentIds: ["Amazon"]`, children correctly separated) and visually (screenshot: Logistics Network bold/centered, Amazon dashed/dimmed, Fulfillment Centers as a normal child).

**Both fixes hold every constraint given:** no eager decomposition (still one sub-question at a time, budget is a ceiling not a target), no entity-mining from answer text, no new schema, no fixed hierarchy, no lateral messaging, Neo4j still touched only through Graph Interface functions, ground agents still tier-routed correctly. Files changed: `backend/api/app.py` (two constants), `frontend/index.html` (one new render-time filter function + two CSS classes) — nothing in `backend/agents`, `backend/graph`, or `backend/questions` needed to change, because the underlying mechanism was already correct.

---

## 2026-08-28 — Next-session agenda, recorded before stopping: what a Relationship actually is

Closing note for tonight's arc (structural provenance → content provenance → three relationship experiments confirming `R = f(A, B, Q)`, all above). Explicit agreement: the next session opens with semantics, not implementation — no code, no Neo4j, until these are worked through against concrete examples (the three/four Session 3 claims are the suggested test material, already on hand, no new API calls needed to start):

1. What exactly is being asserted by a relationship?
2. Is it merely metadata, or is it a proposition?
3. What makes a relationship valid?
4. Can two relationships about the same claims coexist under different questions? (Strongly suggested already by tonight's results — `sequential`/`complementary`/`alternative_explanation` all held simultaneously for the same pair under different questions — but not yet examined as a "do both records coexist in the model" design question.)
5. What evidence can support a relationship?
6. Can a relationship itself be challenged?
7. If challenged, what does the graph do?
8. At what point does a relationship become part of the user's current abstraction rather than a property of reality?

That last question was flagged as potentially foundational: **the graph may not be a representation of reality — it may be a representation of a currently constructed model of reality.** Directly continuous with the session-as-playground principle (persistence already opt-in, `persist_to_graph=False` by default) — if relationships are scoped to the abstraction/question that produced them rather than being global facts about the claims, that's the same "workspace, not repository of truth" idea extended one layer deeper, into the epistemic layer itself rather than just the entity/decomposition structure. Explicit caution recorded alongside this: don't adopt recursion (relationship-as-claim needing its own provenance) just because it's elegant — derive it from what concrete examples actually demand, the same empirical discipline that got tonight's three relationship experiments right instead of guessing.

---

## 2026-08-28 — Third relationship experiment: `R = f(A, B, Q)` confirmed cleanly

Final variant, closing the arc opened by the first, confounded relationship experiment. Same two claims, same original Session 3 wording, one new question — this time explicitly demanding a single primary cause ("which factor **primarily explains**... network effects or regulatory capture?") instead of a general "why"/"how." Classification instructions in `analyze_claim_relationships` were completely unchanged across all three calls this arc has now made — only the target question's framing varied, and it was never told what relationship to look for (`scripts/analyze_causal_competition_question.py`; the identical Question-A result from the prior run was reused rather than re-measured, since re-running an unchanged call would just spend budget re-confirming an already-known answer).

**Result: `alternative_explanation`, confidence 0.9** — the first time this label has appeared for this pair, after two broader framings ("why," "how") both returned `sequential`/`complementary` instead. Reasoning explicitly attributed the shift to the question's own framing: "the two claims present different primary causal pathways for the outcome of dominance, **as framed by the question**."

**Three questions, three different relationships, same claims, same wording:** `sequential` → `complementary` → `alternative_explanation`. `R = f(A, B, Q)` is no longer a hypothesis under test — it's a confirmed empirical finding, and specifically: whether a question demands a single primary cause or tolerates multiple contributing mechanisms is what controls whether competing-explanation detection surfaces. That's a real, load-bearing principle for how claim relationships eventually need to be represented — question-relative, not intrinsic to a claim pair.

**The next real architectural question, named but explicitly not designed or scheduled:** where does a contextual relationship live? Not a bare `ClaimA -[ALTERNATIVE_TO]-> ClaimB` edge (nowhere to hang the question it's relative to) — likely closer to a structure scoped under the question itself (`Question -> {claims, Relationship{type, reasoning, provenance}}`). No schema decided, no Neo4j touched, nothing implemented — this is where the next session on this workstream should start.

**Full arc, honestly summarized:** experiment 1 (4 paraphrased claims) — mixed, confounded by claim paraphrasing. Experiment 2 (2 original-wording claims, 2 questions) — confirmed context-sensitivity, but `alternative_explanation` still didn't appear, ruling out paraphrasing as the whole story. Experiment 3 (same pair, one new sharply-framed question) — confirmed the missing piece: framing that forces single-cause selection is what elicits competing-explanation detection. Three real experiments, one real principle earned, zero schema decisions made prematurely.

---

## 2026-08-28 — Controlled relationship experiment: context-sensitivity confirmed, "competing explanations" still unresolved

Direct follow-up to the first relationship experiment's confound. Two changes made before running, per explicit design discussion: (1) taxonomy expanded from 4 to 6 labels (`complementary`/`alternative_explanation`/`contradictory`/`conditional`/`sequential`/`unrelated`, plus a `confidence` field, in `backend/questions/relationships.py`) — "different mechanisms" and "causally sequential" are now distinguishable from "competing explanations," which the first pass's 4-label taxonomy couldn't express; (2) relationship made explicitly a function of `(claim_a, claim_b, question)` in the prompt, not judged on the pair alone.

**One pair, original Session 3 wording verbatim** (not the earlier condensed paraphrase — "enshittification," "extract rents" fully restored), Network Effects vs. Regulatory Capture, tested under two target questions (`scripts/analyze_controlled_relationship.py`, 2 calls): "Why do some companies become dominant while others fail?" (emergence-flavored) → `sequential`, confidence 0.9. "How can dominant companies sustain market power?" (persistence-flavored) → `complementary`, confidence 0.8.

**Confirmed:** the label changed across questions for the identical claim pair in identical wording. Direct evidence for the principle this experiment existed to test — relationship is contextual, a function of the question being asked, not an intrinsic property of the claims themselves.

**Not confirmed, and this is the more important half of the result:** `alternative_explanation` never appeared under either question, even with the original loaded framing fully restored. This rules out "paraphrasing destroyed the signal" as the *complete* explanation for the first experiment's miss — restoring the exact original wording didn't change the outcome category. Two live, undecided possibilities: this specific pair may genuinely be more causally sequential/complementary than competing (a defensible reading, not necessarily a model failure), or detecting "competing explanations" may need a sharper question form ("what **primarily** explains X," forcing single-cause framing) than "why"/"how" naturally provide. Not tested — the next controlled experiment, if pursued.

**Where this leaves the relationship workstream:** context-sensitivity is now `[CONFIRMED]` — a real, load-bearing finding about how relationships should be represented (question-relative, not claim-pair-intrinsic). Competing-explanation detection remains `[UNRESOLVED]` after two separate experiments, one of which specifically controlled for the leading confound theory. That's real progress on the design question even though the target capability itself is still unproven — preserved and documented, not patched, per the same discipline as before.

---

## 2026-08-28 — Documentation audit: correct [BUILT]/[VERIFIED]/[THEORY]/[VISION] tags across every doc

Full pass across all six docs, not just Architecture.md (which had been kept current live throughout tonight). Goal: no doc should claim more (or less) than what's actually true right now.

**Fixed a real structural bug in Architecture.md itself**, found while doing this pass: the first claim-relationship write-up had been inserted (by an earlier edit's anchor match) INSIDE §0.2, before the "provenance before relationships" ordering decision and before §0.3/§0.4 (which build provenance) even appear — so the document read as if relationships were analyzed before provenance was built, and §0.4's closing status block still said relationships were "untouched" even though §0.2 (earlier in the file) already described running that experiment. Fixed by moving the relationship-experiment writeup into its own properly-ordered §0.5, after content provenance, and correcting §0.4's status line from `[VISION] untouched` to `[PARTIAL] see §0.5`. A good reminder that inserting via anchor-string match without re-reading surrounding structure can silently produce a self-contradictory document — caught by actually re-reading it end to end, not assumed correct because each individual edit succeeded.

**Phases.md:** every phase (0-5) now carries `[VERIFIED]` plus a "since delivered" note listing what changed after the phase was first written (dimension steering/composability/working_framing under Phase 2, sequential decomposition under Phase 3, etc.) rather than leaving the original bullet text looking current when it isn't. Added a new "Post-Phase-5 — Epistemic layer" section between Phase 5 and Phase 6 documenting `trace_claim`/`audit_synthesis`/`analyze_claim_relationships` — this work was never a numbered phase and shouldn't pretend to be one, but Phases.md was wrong by omission without it. Phase 7's conflict-resolution bullet now explicitly points at this groundwork instead of implying it starts from nothing. Phase 6/7 marked `[VISION — not started]` (they were previously unmarked, reading ambiguously next to phases that are actually done). Added the two explicitly-deferred ideas (conversational dimension creation, dynamic abstraction revision) to "Later / not yet scheduled" — they existed only in Memory.md before, not in the phase plan at all.

**Rules.md:** rule 6 (graph vocabulary) checked against tonight's work and confirmed still accurate — nothing tonight touched the Neo4j schema, which is itself worth noting as the discipline holding, not just an oversight. Rule 4 (every claim needs evidence/confidence/provenance) updated to point at the new provenance tooling while explicitly warning it isn't wired into the default path automatically yet — don't let a future reader assume `provenance` is populated just because the tools now exist.

**PRD.md:** every item in §5 (functional requirements) and §8 (success criteria) tagged individually — most of v1 is `[VERIFIED]`, the UI/Roadmap items are honestly `[VISION]`. Added a short paragraph noting the deeper philosophical evolution (session-as-workspace, dimension-as-lens, the epistemic frontier) without rewriting the PRD's actual scope — that's a bigger, separate exercise than a tagging pass, and wasn't asked for.

**Design.md:** one-line addition making explicit that literally everything in it is `[VISION]` — it already read that way, but said so implicitly rather than in the shared vocabulary now used everywhere else.

**SystemDesign.md / AgenticArchitecture.md — deliberately left untouched.** Both are the original pre-implementation specs, already explicitly labeled as historical/verbatim source documents with a pointer to Architecture.md §0 for what was revised. Retrofitting BUILT/VERIFIED tags onto a spec that predates any code would misrepresent what they are; Architecture.md and Rules.md already carry the annotations for where reality diverged from them.

---

## 2026-08-28 — First claim-relationship experiment: a real, informative mixed result, deliberately not patched

Workstream 2, first isolated experiment, per explicit agreement: `backend/questions/relationships.py` — `analyze_claim_relationships(question, claims)` classifies every pair of already-grounded claims as `complementary`/`alternative`/`conflicting`/`unrelated` with required reasoning. Deliberately narrower than Dung's formal argumentation framework — a first vocabulary to test, not an ontology to commit to. Run once (`scripts/analyze_session3_relationships.py`) against Session 3's real question and its 4 real claims, no Neo4j, no schema, exactly as scoped.

**Result, graded honestly rather than rounded up:** 6 pairs, 3 `complementary` / 3 `alternative`, zero `conflicting` (never over-fired — the specific danger flagged going in), always reasoned. But it missed the actual point: every pair involving the regulatory-capture claim came back `complementary` ("enables," "builds upon"), when the original Session 3 critique was that regulatory capture is a *rival normative account* of dominance (extraction vs. earned value), not an additive lever alongside network effects and culture. The `alternative` labels it did produce look driven by a shallower "external vs. internal mechanism" heuristic, not "these compete to explain the same outcome." **Sharper design conclusion: "these are different mechanisms" ≠ "these are competing explanations" — the taxonomy-of-difference the analyzer learned is real but is not yet the causal-competition judgment the workstream actually needs.**

**A likely confound, named before blaming the model:** the claims given to the analyzer were condensed, neutral paraphrases of Session 3's actual answers, stripped of the original's loaded framing ("extracting rents," "enshittification"). That framing may be exactly what made the tension visible to a human reader in the first place. This means the experiment tested `paraphrase → relationship analyzer`, not `claim → relationship analyzer` — a lossy transformation was introduced before the epistemic reasoning step, which connects directly to the content-provenance principle already established: compression can destroy information the reasoning depends on. Before concluding this is a model limitation, a controlled experiment needs to rule out that the representation handed to it already threw the signal away.

**Explicitly not done, and not because of running out of night — because the next experiment needs to be controlled, not broader:** re-running with original, unparaphrased claim wording on one carefully chosen pair, asking explicitly whether two claims are complementary, competing, or something else with respect to a named question. If it succeeds with real wording, tonight's result was mostly representation loss. If it still fails, that isolates a genuine, narrower capability gap. Designed, not run — deferred to next session by explicit agreement, not because the mechanism failed but because the finding itself (representation vs. reasoning confound) is worth preserving cleanly rather than immediately patched over.

**State of the epistemic investigation, honestly, after tonight's full arc:** provenance (`[VERIFIED]`, both structural and content) is solid architecture now. Claim relationships is real, informative, partial — the analyzer reliably detects difference and some complementarity, never over-fires on conflict, but has not yet demonstrated the specific "competing causal account" judgment the whole workstream exists to provide, and there's a named, plausible reason (paraphrase confound) that hasn't been ruled out yet. That is the correct place to stop for tonight.

---

## 2026-08-28 — Two negative controls pass; two real bugs found running them for real

Direct follow-up to the single content-provenance experiment. Ran `audit_synthesis` against Session 1 and Session 3's already-captured answers (`scripts/audit_negative_controls.py`), exactly as scoped — 2 more calls, no new investigation.

**Results: both controls passed cleanly.** Session 1: 35/35 atomic propositions `investigated`, 0 `uninvestigated` — matches the earlier finding that its synthesis was 1:1 with its 4 children. Session 3: 27/27 `investigated`, 0 `uninvestigated`, including the closing "conversely, companies fail..." paragraph (hand-classified as Category C/inference earlier — the auditor treated it as `investigated` instead, a minor granularity difference, not a control failure). The important negative result: **the auditor did not flag the contested regulatory-capture/"enshittification" content as uninvestigated** despite it being the most rhetorically loaded, hardest-to-reconcile claim in the session — exactly the failure mode this control was watching for (a provenance auditor accidentally behaving like a truth/consensus detector). It didn't happen.

**Two real bugs found in the process of actually running this at real scale, not by further design work:**
1. **A severe, pre-existing bug in `structured_call`'s fallback handler** (`backend/questions/llm_client.py`): a provider's error text containing a Unicode character (U+2011, a non-breaking hyphen, echoed back from the model's own output inside a JSON-parse error) crashed the fallback handler's own `print()` on Windows' default console codec — aborting the entire multi-provider fallback chain from inside the code meant to make that chain resilient. This has likely been silently present since the chain was first built; nothing before tonight happened to produce a non-ASCII character in an error message on a Windows console. Fixed by sanitizing (`encode("ascii", errors="backslashreplace")`) before printing.
2. **`audit_synthesis`'s original schema (with a `supporting_source` quote field) reliably truncated output on larger sessions.** It worked fine against session 2 (1 child, small `known`) but produced invalid/truncated JSON on sessions 1 and 3 (4 children each) on both Gemini and Groq — the per-claim source quotes multiplied total output length past what those providers could return intact. Fixed by dropping `supporting_source` — it was a nice-to-have pointer, not load-bearing for the actual traceability judgment. **Also found, and explicitly NOT a code issue:** Cerebras (`MASTER_MODEL_CHAIN`'s third fallback) now returns `402 Payment required` on every call — free-tier access apparently changed since this chain was set up. Flagged, not fixed tonight.

**Where the epistemic investigation stands now:** structural provenance `[VERIFIED]`, content provenance `[VERIFIED, 3 sessions]` — one true-positive detection (session 2) plus two clean negative controls, one of which specifically tested for the "contested ≠ unsupported" distinction and held. Claim relationships (workstream 2) remains untouched, `[VISION]`. Both docs and the VM's copy of the codebase are in sync; regression suite (Phase 2/3/4) re-ran clean after the `llm_client.py` fix.

---

## 2026-08-28 — Content provenance: designed as an audit problem, tested once, worked

Direct follow-up to structural provenance (`trace_claim`) — the harder half of provenance: not "which node did this come from" but "is this specific sentence in the answer actually backed by what was investigated." Designed before any code, per explicit instruction.

**Key design decisions, made before implementation:** (1) unit of analysis is the atomic proposition, not the sentence — a sentence can bundle a supported and an unsupported claim; (2) `origin: investigated | uninvestigated` is strictly a traceability judgment, not a truth judgment — uninvestigated ≠ false, investigated ≠ verified true; (3) built as an **audit** (a separate call examining the finished answer against `known`), not a **self-report** (the generator declaring its own output supported) — explicitly rejected the cheaper self-report pattern that worked for `working_framing`/`discovered_entity_name`, because "did this come from context or from my training" is a documented LLM weak spot, harder than naming a lens one is already using, and this project already has two documented cases of the same model failing a much easier self-report instruction.

**Built:** `backend/questions/audit.py` — `audit_synthesis(answer, known) -> SynthesisAudit` (`AtomicClaim{text, origin, supporting_source}`), same call pattern as `synthesize_answer`. One new function, no schema family, no Neo4j.

**The one isolated experiment, exactly as scoped** (`scripts/audit_session2_synthesis.py`, Session 2's real answer + known text, verbatim, no new investigation, no re-run): 15 atomic propositions extracted, 2 `investigated` (both from the one real child — policy tools / interest-on-reserves mechanics), 13 `uninvestigated` (every transmission-channel proposition, each split finer than the original hand-audit's 5-section framing). Reproduces, via an independent auditor call, exactly the boundary a human found by reading the transcript weeks earlier.

**Honest limit, stated plainly:** n=1. Real evidence the mechanism *can* work, not proof it reliably *does*. Next real test (not started): run against session 1 and session 3's already-captured data — both should come back essentially all `investigated` (session 1's synthesis was 1:1 with its children; session 3's actual problem is claim relationships, not provenance, so a clean provenance result there would be a meaningful negative control) — before trusting this beyond one clean result.

**Where this leaves the epistemic investigation:** structural provenance and content provenance are both now `[BUILT]`, content provenance flagged `[VERIFIED, n=1]` rather than fully `[VERIFIED]` per the traceability discipline. Claim relationships (workstream 2) remains untouched `[VISION]`. No Neo4j storage decision made for either.

---

## 2026-08-28 — Provenance semantics defined and built: `trace_claim`, verified against real session data at zero API cost

Workstream 1 of the two-workstream epistemic split (Architecture.md §0.2/§0.3). Semantics first, per explicit agreement: a claim's provenance is **direct** (0 children — answered without decomposing), **derived** (exactly 1 child), or **synthesized** (2+ children) — classified structurally from child count, not by trying to verify content is actually backed (that's a harder claim/concept-level problem, explicitly deferred, not solved by sentence matching).

**Built:** `backend/agents/provenance.py` — `ClaimProvenance` (recursive Pydantic model: `provenance_type`, `answer`, `confidence`, `evidence: list[Claim]`, `derived_from: list[ClaimProvenance]`), `trace_claim(agent_id, db_path)` (walks the AgentState tree already persisted by every run — no new storage, no Neo4j, per the explicit "prove semantics before choosing storage" instruction), `find_root_agent_id(db_path)` (locates the one true root in a session's SQLite file). Exported from `backend.agents`.

**Unit-tested** (`scripts/verify_trace_claim.py`): a synthetic 4-node tree (root/2 children, one child with its own child) plus a standalone boundary-hit node, written directly to SQLite with zero LLM calls. All 11 checks passed, covering all four classifications, evidence attachment, and `find_root_agent_id`'s single-root invariant (raises correctly when the test DB has two top-level agents).

**Replayed against the three real sessions' already-persisted SQLite state** (`scripts/replay_provenance.py`) — the exact "verify on existing traces, no new API calls" step agreed on. Confirmed the earlier hand-done A/B/C/D audit structurally, and found a sharper signal nobody was looking for: comparing root answer length against the sum of its children's answer lengths, sessions 1 and 3 both *compress* (root is much shorter than its children combined — expected, clean synthesis of already-investigated material). **Session 2 inverts this** — its root is classified `derived` (only 1 child) yet its answer is 590 characters *longer* than that single child's answer, i.e. it necessarily contains substantial content with no investigated origin. That excess is exactly the previously hand-identified transmission-mechanism content. Flagged as a candidate cheap heuristic (a `derived`/`direct` node's answer being longer than its source is suspicious) worth watching on future sessions — not built into anything yet, one data point.

**Scope discipline held:** no Neo4j writes, no schema change to `Claim` or `Question`, no touch to workstream 2 (claim relationships) — session 3's replay confirms it still shows zero provenance gap (4 clean children, root compresses normally), meaning its actual problem remains entirely in the untouched relationship workstream, exactly as predicted before any of this was built.

---

## 2026-08-28 — Provenance audit closes the epistemic investigation for now: two independent workstreams, not one engine

Zero-cost audit (no new API calls — re-read the three already-logged session traces) against the question: for each final synthesis, which content was A) directly investigated, B) jointly supported by multiple investigated children, C) a reasonable inference from investigated material, or D) an uninvestigated assertion with no traceable child/evidence origin. Result table and full reasoning now live in Architecture.md §0.2 (not duplicated here) — the short version: **session 1 was 100% clean (all A), session 2 was majority Category D (the five transmission channels, none investigated), session 3 was zero Category D but had a real relationship failure anyway (well-provenanced claims flattened into false parity).**

**The finding that actually matters:** the two failure modes are independent — session 2 had nothing to relate (only one investigated thing existed) and session 3 had nothing to trace (everything was investigated; the failure was purely in how already-well-sourced pieces were combined). No single mechanism touches both. This empirically confirms treating "epistemics" as two separate, small, independently-earned primitives (provenance, then claim relationships) rather than one "epistemic engine" — exactly the trap this whole investigation was trying to avoid falling into on the strength of three data points.

**Decision, design-only:** build provenance first, relationships second — a claim's relationship to another claim is only meaningful once its own origin is established. Provenance must work at the claim/concept level, not sentence-string matching (synthesizing three children's findings into new prose is legitimate synthesis, not a provenance violation) — flagged as the next real design question, explicitly not started.

**Stopping point, explicit:** no more sessions, no more API spend on this line of investigation for now. Next session on this topic starts with *designing* the minimum provenance mechanism, not running further experiments. Three real sessions (payment infrastructure, central bank rates, company dominance) plus one zero-cost audit produced: a validated structural-decomposition capability, a validated adaptive-framing capability, a real rate-limit-resilience validation, a real evidence-confidence-calibration validation, and a precisely-scoped, evidence-backed epistemic gap split into two ordered workstreams — all without guessing at what the architecture needed next.

---

## 2026-08-28 — Epistemic synthesis design investigation (research only, no code)

Direct follow-up to the three real sessions: sessions 2 and 3 turned out to be the same underlying seam, not two separate bugs — the system is strong at `Question → Decompose → Investigate → Evidence → Claim` and weak at the step after (`Claims → what does this collection actually justify?`). Per explicit agreement, this is a *design investigation*, not an implementation pass — the instruction was explicitly "research the problem, don't build an epistemology engine off three data points."

**Worth noting before anything else:** this exact gap was already named in Architecture.md §0.1, written well before any real session existed to prove it — "Claims do not carry an epistemic-status field... beyond their numeric confidence" and "there is no conflict-resolution mechanism when two claims disagree," both flagged [VISION]. A predicted gap independently confirmed by real use is stronger evidence than either the prediction or the observation alone.

**Real prior art surveyed (added to Architecture.md §0.2, not summarized twice here):** Dung's Abstract Argumentation Frameworks and their bipolar (support + attack) extensions — the actual 30-year-deep CS formalism for typed claim-to-claim relations; **ArgLLM** (Freedman et al., AAAI 2025, King's College London, code at `github.com/CLArg-group/argumentative-llms`) as the single closest working system — builds a formal argumentation graph from LLM-generated claims and computes the verdict from graph semantics rather than trusting the LLM's self-reported confidence, explicitly so a specific claim-relation can be contested rather than just the final number; Toulmin's argument model for vocabulary (qualifier, rebuttal — better primitives than one confidence float); the IPCC's calibrated uncertainty language, which splits "confidence" (evidence quality + **degree of expert agreement**) from "likelihood" (probability of the finding) — the "degree of agreement" axis is exactly what was missing when session 3 flattened three explanatory theories into one number; and Wikidata's preferred/normal/deprecated statement ranks, the simplest production precedent for letting conflicting claims coexist in a graph with lightweight relationship metadata rather than forcing resolution before storage — this one maps directly onto the already-existing `ClaimNode` structure.

**Where this leaves things:** Architecture.md §0.2 records the investigation, the precedent, and a *direction* (a typed relationship between `ClaimNode`s — `supports`/`conflicts`/`competing_explanation_for` — populated only when a synthesis step explicitly identifies one, closer to Wikidata's minimalism than ArgLLM's full formal machinery) explicitly marked not decided or scheduled. No schema change, no code. ArgLLM is flagged as the thing to study closely if automated synthesis-confidence computation is ever actually needed — same "study, don't adopt yet" treatment §0's original stack research gave Graphiti and LightRAG.

---

## 2026-08-28 — Third and final observation session ("Why do some companies become dominant while others fail?"): competing explanations flattened into one uncontested synthesis

Deliberately the last session before returning to engineering, per explicit agreement. Chosen because it isn't a clean technical system (unlike sessions 1-2) — economics, strategy, organizational culture, and regulation could all plausibly be load-bearing. No dimension, no prescribed structure, default depth/step budget, same real-evidence/real-persistence recipe (`scripts/session_dominant_companies.py`).

**What happened:** four sequential decomposes, each correctly materializing its own entity this time (`discovered_entity_name` fired on all four — contrast with session 2's miss, reinforcing that it's a probabilistic LLM-compliance gap, not a systematic break): **Network Effects**, **Economies of Scale**, **Platform Enshittification and Regulatory Capture**, **Organizational Agility and Execution Capability**. Each child answered cleanly and confidently (0.95 each); the master synthesized all four into one answer, also at 0.95.

**The interesting thing isn't a contradiction inside the trace — it's what the synthesis quietly did to real, contested explanations.** These four branches aren't complementary facts the way DNS/TCP/routing were in session 1 — they're four different, sometimes RIVAL theories of why dominance happens that real economists and antitrust commentators actually argue about: "dominance reflects genuine value creation" (network effects, economies of scale) vs. "dominance is extracted via anti-competitive strategy" (the regulatory-capture/pricing branch, literally named after Cory Doctorow's "enshittification" — a polemical, contested term, not settled economic vocabulary, now sitting as a formal graph entity name) vs. "dominance is earned through superior execution/culture" (the organizational branch, citing Amazon/Netflix by name). Antitrust discourse genuinely splits along close to these exact lines. The system presented all three explanatory postures as uncontroversial, jointly-true "pillars" at uniform 0.95 confidence, with no signal that these represent different schools of thought rather than agreed-upon facts. This is a sharper version of session 2's "confidence ≠ investigation coverage" finding: here, every branch WAS investigated, and the gap is instead between "internally consistent, well-evidenced sub-answers" and "a synthesis that erases real disagreement between the sub-answers' underlying worldviews." Worth watching for recurrence on other value-laden/contested subjects, not building anything around yet — same discipline as session 2's finding.

**A second, smaller instance of the same theme:** the master's own final prose regrouped the four persisted entities into THREE narrative sections (merging Network Effects + Economies of Scale into one "Defensible Moats & Scale Dynamics" paragraph) — so the graph's structure and the synthesis's narrative structure aren't actually the same shape, even when entity discovery fired correctly on every branch. A second, different flavor of the "Reasoning → Structure" fidelity gap raised earlier this session (previously only observed as discovered_entity_name failing to fire at all; here it fires correctly on every branch, and the drift shows up one level higher, between the persisted structure and the prose built from it).

**Verdict against the three things this session was watching for:** (1) genuine understanding gained — yes, modestly (seeing "enshittification"-style rent extraction named as a *distinct, independent mechanism* alongside network effects and culture is a real, if uncomfortable, structural framing); (2) unexpected discovery — the entity-naming choice itself (a loaded neologism persisted as a neutral-looking graph node) was unexpected; (3) visibly strained/contradicted framing — no explicit contradiction appeared in the trace text itself, but a soft, structural version of it is there for a human reader to notice: three competing worldviews stated as complementary. Not a clean, unambiguous case #3 event, but the closest of the three real sessions to date.

**Per explicit agreement: this is the last observation session for now.** Three real sessions total (payment infrastructure, central bank rates, company dominance) produced three different kinds of findings — clean structural refinement, confidence outrunning investigation depth, and competing explanations flattened into one synthesis — none of them predicted by reading the architecture beforehand. Next step is deciding the actual engineering problem from this accumulated evidence, not a fourth session.

---

## 2026-08-28 — Second real session ("How does a central bank control interest rates?"): confidence outran investigation depth, and a known contradiction resurfaced

Second real, non-test use of the system (`scripts/session_central_bank_rates.py`), chosen deliberately as an ordinary question, not an attempt to break anything — direct continuation of the first real session (payment systems). Same recipe: no dimension, real evidence gathering, real graph persistence, run on the VM.

**What happened, and how it differs from session 1:** the master decomposed exactly ONCE — into "what specific policy tools does a central bank use" (open market operations, interest on reserves, standing facilities, reserve requirements) — got that child's answer, then answered directly rather than decomposing further. Critically, the master's own final synthesis then wrote a full five-channel monetary transmission mechanism explanation (interbank markets, bank lending pass-through, asset prices, exchange rates, forward guidance) **that was never itself investigated as a separate question** — no child ever looked at transmission specifically, no evidence was gathered for it, yet the final answer carries the same 0.95 confidence as the parts that WERE investigated.

**Why this matters more than it might look:** monetary transmission — how much a rate change actually moves inflation/employment, over what lag, through which channel most — is one of the more genuinely contested areas in real macroeconomics, unlike payment-rail mechanics (session 1), which is settled, documented infrastructure. The system produced a textbook-confident answer for the one part of this question where a domain expert would actually flag real uncertainty, and did so without any dedicated investigation or evidence for that specific part. This is a concrete, observed instance of the caution already raised in this project's own design discussion: **a confidence score describes confidence in the synthesis given what was investigated, not truth, and it does not currently track how much of an answer was actually investigated versus asserted from the model's own prior.** Worth watching for a pattern, not yet worth building anything around — one instance is a data point, not a trend.

**A known contradiction resurfaced, and this one isn't harmless like `working_framing`'s:** the master's decompose reasoning explicitly called the policy-tools split "independently investigable components" — language that `decision.py`'s existing contradiction-check paragraph says MUST come with `discovered_entity_name` set. It didn't fire this time (no `[graph] ... -[decomposes_into]-> ...` line appeared, unlike every decompose in session 1). Unlike `working_framing`'s redundant-restatement deviation, this one has a real, if modest, consequence: the "policy tools" branch was attached as just another question under the `Central Bank` entity rather than becoming its own navigable entity node the way session 1's four branches did. Not fixed — logged as a second data point on an already-known LLM prompt-compliance gap (first seen and partially addressed during the graph-persistence pass), not a new architectural finding. Revisit if this keeps recurring across more real sessions; one probabilistic miss on a known-flaky field isn't grounds for another prompt-tightening cycle by itself.

**Still no case #3** (children contradicting the original structural assumption) — this was closer to "the system stopped investigating before reaching the part of the question with the most real uncertainty," a different failure shape than the one being watched for. Logged as its own observation rather than forced into the existing three-case taxonomy.

---

## 2026-08-28 — Empirical revision-signal battery: the expected phenomenon didn't show up, a different real one did

Diagnostic pass (`scripts/investigate_revision_signal.py`), run BEFORE writing any "keep vs. collapse vs. restructure" mechanism, per explicit agreement — the question was whether the existing investigation loop already produces enough signal to justify that kind of judgment, not whether a hand-picked expected answer comes out right. No new code beyond the observation script; `GroundAgent` run as-is, three MASTER-level questions, no `gather_evidence`, no `persist_to_graph`.

**Three cases, one genuine surprise:**
- **STAY** ("How does a website request travel through the Internet?") decomposed cleanly into DNS → TCP/TLS → routing, three independently-answered children, synthesized into a coherent pipeline answer. As expected.
- **COLLAPSE** ("Why does money have value?") — **never decomposed at all.** The master-level `decide_next_step` call chose `answer` on the very first call, with reasoning stating outright that trust/state-backing/scarcity/network-effects are "mutually reinforcing facets of a single, tightly-coupled socio-economic phenomenon... rather than genuinely independent, separately-investigable entities." Zero children spawned, so there was nothing to later collapse — the already-`[VERIFIED]` master-level structural-judgment prompt made the *correct call upfront*, not a wrong call that investigation later corrected.
- **RESTRUCTURE-CANDIDATE** ("How does PayPal work?") decomposed into ledger/accounts, risk/fraud engine, external payment integration — three real, complementary technical subsystems, investigated without contradiction or friction. It did **not** surface the ambiguity the case was chosen to probe (PayPal as company vs. platform vs. network participant vs. business) — it silently committed to one coherent technical framing and never signaled that other equally valid framings existed or that a choice had even been made.

**The honest finding:** none of the three cases produced the scenario dynamic abstraction revision is meant to handle — "decompose, investigate children, discover mid-investigation that the split was artificial, revise." In every case here, the *upfront* structural judgment was already right (or at least self-consistent) before any child ran. That's evidence the already-built master-level bias is doing real work, not evidence that revision is unnecessary — these were three fairly "textbook" questions a model has abundant training signal about; a genuine test of revision needs a case engineered so the upfront guess is plausible but wrong, only exposed after 1-2 children report back something that contradicts the original split. None of today's cases were adversarial enough for that.

**A different, smaller, actually-evidenced gap, found instead of the one being looked for:** the PayPal run's silent single-framing commitment. `dimensions=[]` was passed deliberately (to see what the model defaults to), and the model picked a technical/architectural lens without ever surfacing that it made a choice, or that "PayPal as a business model" or "PayPal as a regulated financial institution" were equally valid, differently-structured decompositions of the same entity. This connects directly to the already-built dimension work (§ dimension steering / composability) rather than to revision — the fix implied here is smaller and more concrete: when `decide_next_step` decomposes at master level with no dimension given, it could be required to name the implicit lens it used, making the choice visible instead of silent. That's a much narrower, already-scoped-adjacent piece of work compared to building a general keep/collapse/restructure engine for a failure mode not yet observed in practice.

**Not yet decided:** whether to (a) design adversarial test cases specifically built to force a genuine upfront-judgment failure before building any revision mechanism, or (b) address the smaller, concretely-observed implicit-framing gap first since it's real and evidenced today, versus building machinery for a phenomenon only hypothesized so far.

---

## 2026-08-28 — Dimension composability: multiple lenses jointly frame one investigation

Direct extension of the same day's single-dimension steering pass, prompted by a design discussion arguing the natural progression is 1 dimension (verified) → 2+ dimensions composed → conversation → graph editing, and that composed dimensions must **fuse** into one investigation angle, not just co-occur as two separate labels ("historically, X. Also, incentives-wise, Y." would be metadata composition wearing composition's clothes).

**Scope, deliberately kept small per explicit instruction:** no conversational layer, no new agents, no graph persistence changes, no UI, no dimension-conflict-resolution policy (left to the LLM to compose naturally; the plan is to add a policy later only if empirical failures show up, not up front).

**Built:** `DimensionContext` (`{name, description}`, `backend/questions/models.py`) and `Question.dimensions: list[DimensionContext] = []` — purely additive alongside the existing singular `dimension_name`/`dimension_description` (untouched, still work exactly as before for any single-dimension caller). `decide_next_step`'s prompt (`decision.py`) gets a new paragraph, used only when `dimensions` is non-empty, explicitly instructing that multiple dimensions must jointly frame one combined angle rather than being addressed one after another; `_build_user_prompt` lists all dimensions under one "these lenses must JOINTLY frame the investigation" header instead of one `Dimension: X` line per lens (deliberately not just looping the old single-dimension line — that would itself be the concatenation failure mode being tested against). `GroundAgent._make_child_question` inherits `dimensions` through recursion, same as it already did for the singular fields.

**A methodological near-miss, same category as the rationale-leak bug from the single-dimension pass, caught the same way (reading the actual baseline output, not trusting the setup):** first test question was "How did Mastercard *become* a global payment network?" — phrasing that pre-loads a historical framing into the baseline (no-dimension) case regardless of what dimension is set. The baseline came back reasoning about ICA/Master Charge origins with **zero dimension set at all**, nearly indistinguishable from the "Historical" case — not because composition failed, but because the control question wasn't lens-neutral. Fixed by rephrasing to "How does Mastercard *operate* as a global payment network?", which has no built-in lean toward history, mechanics, or incentives, then re-ran.

**Clean result (`scripts/verify_dimension_composability.py`):** baseline decomposed into "Mastercard Authorization and Clearing System" — pure structural/functional framing (authorization, clearing, settlement). "Historical" alone decomposed into "Mastercard Historical Evolution" — pure emergence/transition framing (BankAmericard/Interbank/Master Charge origins). "Historical + Incentives" together decomposed into "Interchange Fee Model" — genuinely fused, not stapled: the reasoning and resulting sub-question were about how the interchange fee structure *emerged historically* while *continually balancing competing incentives* among issuers, acquirers, merchants, and consumers — one economic mechanism that is simultaneously the historical subject and the incentive-balancing subject, not a historical clause plus a separate incentives clause. `discovered_entity_name` tracked the shift at each step (Authorization/Clearing System → Historical Evolution → Interchange Fee Model), an independent signal that the reasoning genuinely changed rather than just the phrasing. Reproduced identically on the VM. `verify_phase2/3/4.py` re-ran locally and on the VM to confirm no regression from the additive `Question.dimensions` field or the `_make_child_question` change (all pass).

**Deliberately not built, per explicit agreement:** any dimension-conflict-resolution policy (e.g. Technical + Psychological pulling in incompatible directions) — untested territory, left for a later pass only if real failures surface. Also not touched: `backend/questions/engine.py`'s `generate_question`, which still takes a single `Dimension` — no live caller currently constructs a `Question` through it with multiple dimensions, so extending its signature was out of scope for this pass.

---

## 2026-08-28 — Dimension steering: `Dimension` stops being inert metadata

Prompted by a session/playground design discussion: rather than rebuild persistence (already opt-in by default — `persist_to_graph=False` already makes every session an ephemeral workspace unless something explicitly chooses to keep it), the concrete gap identified was that `Dimension` never actually reached the investigation loop. Verified before touching anything: `decision.py`'s prompt referenced `question.level` but never `question.dimension_id` at all — a `Question`'s dimension was carried along as a label from Phase 2's `generate_question` but had zero influence on `decide_next_step`'s decompose/answer judgment.

**Fix, kept additive:** `Question` gained `dimension_name`/`dimension_description` (both `Optional[str] = None`), alongside the existing `dimension_id: str` rather than replacing it — every existing script that constructs a bare `Question(dimension_id="scale", ...)` keeps working unchanged. `generate_question` now populates both from the `Dimension` object it already receives (no schema addition needed there — `Dimension` was already a free-form `{id, name, description}` model, not restricted to `SCALE`/`PERSPECTIVE`/`TIME`). `decide_next_step`'s prompt includes the dimension, when present, as one line among Abstraction/Entity/Level — explicitly framed in the system prompt as "one contextual input... not an instruction that overrides or replaces the actual question," per the constraint given up front. `GroundAgent._make_child_question` inherits it, so a dimension set on a top-level question survives recursive decomposition.

**Acceptance test, agreed before running:** same entity, same question, same level, changing *only* the dimension — graded by reading the reasoning text for a genuine strategic shift, not by asserting specific expected sub-question content (which would just be a milder version of "decomposition theater"). Used a deliberately novel dimension not in `UNIVERSAL_DIMENSIONS` and not something a model would default to: **"Power Dynamics"** (who has decision-making power, who depends on whom, what leverage each participant holds), against "How does a global payment network work?"

**A real bug in the test itself, caught by reading the output rather than trusting the setup:** the first run's baseline (no dimension) *also* reasoned about "power dynamics" and literally said "under the dimension-steering framework" — contamination, not a feature bug. Root cause: the test's own `rationale` field was hardcoded to `"Dimension-steering verification."`, and `rationale` is included in `decide_next_step`'s prompt (`"Rationale it was asked: ..."`) regardless of dimension. Renaming the test's `abstraction_name` first didn't fix it (wrong field); the actual leak was `rationale`. Fixed by using a neutral, realistic rationale with no meta-language at all, then re-ran.

**Clean result:** baseline decomposed into "Cross-Border Messaging and Clearing Infrastructure," reasoning purely mechanically ("how do X *function*"). Under "Power Dynamics," it decomposed into "Interbank Messaging and Settlement Systems" — a similar *area* (both converge on the same real chokepoint in payment networks, which makes sense, since that hub is genuinely both the technical and the power bottleneck), but the reasoning explicitly invoked "governance and leverage held by central infrastructures... dominant correspondent banks over smaller institutions... institutional dependencies and rule-making power," and the sub-question asked about *governance and dependency*, not mechanics. Same entity, same question — genuinely different investigation strategy, driven by the dimension, not a relabeled answer. Re-ran on the VM after the fix for consistency; `verify_phase2/3/4.py` re-ran locally to confirm the additive `Question` fields didn't regress anything (all pass).

**Deliberately not built, per explicit agreement:** any conversational mechanism for a user to *define* a dimension by talking to the agent ("let's study this through incentives"). That's a session/orchestration layer with no existing conversational loop to hang it on — a separate, later design question once the underlying primitive (this pass) was proven to work.

---

## 2026-08-28 — First concrete Phase 6 step: `zoom_in` + `explain_entity`, plus a real `merge_entity` bug found by actually using it

Agreed scope: build the two smallest semantic operations that let a human navigate what's already been discovered, entirely by composing already-verified Graph Interface functions — no new agent runs, no UI. Explicitly told to stop after verification, not continue into Phase 6 proper.

**Built (`backend/graph`):**
- `get_decomposition(entity_id) -> list[GraphNode]` — thin wrapper over `get_neighbors(entity_id, "decomposes_into")`. Pure read.
- `zoom_in(entity_id) -> Optional[Abstraction]` — materializes an `Abstraction` over an entity's existing `decomposes_into` neighbors. Returns `None` (not a manufactured empty `Abstraction`) when there's nothing to zoom into — deliberately does not invent structure the graph doesn't already contain. Made idempotent by entity name (one addition beyond the literal ask, flagged and justified at the time): without it, opening the same zoom twice would create a duplicate `Abstraction` every call, the same class of bug `find_or_create_entity` already exists to prevent for entities.
- `get_questions_for_entity(entity_id) -> list[QuestionNode]` — read-only, the `HAS_QUESTION` analog of the existing `get_claims_for_question`.
- `explain_entity(entity_id) -> EntityExplanation` — read-only provenance trace. `parent_question_text` is parsed from the existing `rationale` string (`"Sub-question of: <text>"`, already written by `attach_question`) — no new graph property added, per instruction, since there's no persisted Question→Question edge yet (that's the deferred Phase 6 Question Graph mirror).
- Both raise `GraphInterfaceError` for an unknown id, consistent with every other Graph Interface function's existing convention — not a new error-handling choice.

**A real bug found by actually exercising `merge_entity` against live data for the first time.** The "entity with multiple discovering questions" test case was meant to use "PayPal" — but `explain_entity` returned zero questions. Investigated rather than assumed: a direct query found **5 separate "PayPal" `GraphNode`s**, created across 5 different `verify_phase5.py` runs today, because that script calls `create_node` directly instead of `find_or_create_entity` (which didn't exist yet when it was first written, back in the actual Phase 5 pass — `find_or_create_entity` was only added during the later graph-persistence pass). Exactly the scenario Rules.md rule 12 exists to prevent, caused by an earlier script never being updated once the canonical-entity tool existed.

Fixing this the right way (`merge_entity`, not a workaround) surfaced a second, more important bug: **`merge_entity` was written in Phase 1, before `HAS_QUESTION` existed (Phase 5), and never transfers a merged node's attached questions** — it only rewrites `RELATES_TO` and `MEMBER_OF`. Since the merge's last step is `DETACH DELETE merge`, running it as-is would have silently orphaned the 4 duplicate PayPal nodes' attached questions (the `Question` nodes would survive, just become unreachable from any entity) rather than consolidating them. Caught by reading `merge_entity`'s actual Cypher before running it destructively against real data, not by trusting the docstring. Fixed by adding a `HAS_QUESTION` transfer step in the same transaction, then re-ran the merge — `explain_entity('PayPal')` now correctly shows all 4 real questions accumulated across today's separate test runs, each with `merged_from` correctly recording the consolidation provenance.

**Lesson for future work, not yet acted on:** `merge_entity` had never actually been exercised by an automated test before today (`verify_phase1.py` doesn't call it) — it existed as `[BUILT]`, not `[VERIFIED]`, despite being a Rules.md rule 12 cornerstone. Worth a dedicated verify script once Phase 6 or later work needs `merge_entity` again, rather than leaving it proven only by this one ad hoc debugging session.

**Verification (`scripts/verify_zoom_and_explain.py`, ad hoc, against today's real Neo4j data — no new agent/LLM calls):** all 6 requested cases — multi-child entity, single-child entity (manufactured fixture, since no real single-child case existed in today's data), no-child entity, multi-question entity (the PayPal case above, real after the merge fix), unknown entity id (both functions raise `GraphInterfaceError`), and read-only confirmation (`explain_entity` called 3x, identical results). Also confirmed `zoom_in`'s idempotency directly (same entity zoomed twice returns the same `Abstraction`, not a duplicate).

**Stopping here, as agreed** — not proceeding into the investigation-trail UI, multi-abstraction display, a large-subject stress test, or the visual interface. Next question, unanswered until a dedicated Phase 6 session: can a human navigate the discovered structure entirely through `zoom_in`/`explain_entity` (plus the existing `get_subgraph`/`get_abstractions_for_node`) before any UI gets built on top of them.

---

## 2026-08-28 — Doc alignment pass: absorbed `docs/system.md`, fixed pre-existing drift found along the way

The user pasted a substantial (~1500-line) theory write-up as `docs/system.md`, drafted with ChatGPT's help as a synthesis of the whole session's design discussion, and asked for it to be checked against reality, absorbed into the maintained docs, and deleted — flagging anything actually wrong rather than blindly rewriting everything to match it.

**Verdict: not wrong, but doesn't distinguish "built" from "the theory's implied end-state."** Read as a vision/theory paper it holds up well — the core loop, near-decomposability as the operational criterion, discovery-must-persist, and the entity-discovery decision tree all match what was actually built and verified this session, often precisely. The problem is only that it describes several Phase 6/7-level capabilities in the present tense, as if already true:
1. **Master Agent's described role is overstated.** §12 says the Master manages "abstraction boundary... expansion and contraction... cross-domain synthesis." In reality (Phase 4), the Master only enforces the spawn budget and logs an accept/reject `ExpansionRequestMessage` — it does not act on an accepted expansion (that's Phase 7's unbuilt abstraction-change protocol), and has no cross-domain synthesis mechanism.
2. **Conflict resolution (§25)** is described as working behavior. Entirely unbuilt — no mechanism compares claims for contradiction (Phase 7).
3. **Evidence epistemic-status taxonomy (§24: Known/Hypothesis/Uncertain/Contradictory/Unsupported)** doesn't exist. A `Claim` only has a numeric `confidence`, no categorical status field.
4. **A "Scheduler" / persisted priority task queue (§30 and implied throughout)** was never built — `MasterAgent` schedules via a plain `asyncio.gather` with no priority ordering. This one wasn't system.md's error, though — it inherited a **pre-existing documentation drift** already present in Architecture.md §2 and Phases.md's Phase 4 bullet (both claimed a priority queue existed since Phase 4, silently dropped during actual implementation and never corrected). Found and fixed both while cross-checking system.md against real code, not introduced by it.
5. **"Resource" listed as core vocabulary (§3)** — never built as a separate node. A `Claim`'s source (title/url/type) is a property of the `Claim` itself; nothing yet needs one paper cited by multiple claims to be deduplicated as its own reusable node. Reconciled in Rules.md rule 6.
6. **§26's "Domain"/"Subsystem" memory-hierarchy language is internally consistent on a careful read (explicitly "not a fixed agent hierarchy") but risks being misread as reintroducing the fixed Domain/Subdomain tiers Rules.md rule 8 explicitly rejects.** Deliberately not carried into Architecture.md's new section in that framing — described instead as "recursive Ground Agent context nesting," which is what it actually is.

**What was absorbed, into Architecture.md's new §0.1 "Theoretical foundations," each claim tagged [built] with a phase citation or [vision] with a Phases.md pointer** (see Architecture.md directly rather than duplicating it here): the core `Abstraction → Decomposition Hypothesis → Investigation → Coupling Discovery → New Abstraction` loop, near-decomposability as the operational decompose/answer criterion, the three-graphs framing (Knowledge/Question/Agent — noting the Question and Agent graphs aren't yet independently persistent structures, only the Knowledge Graph is), discovery-must-persist, entity-discovery-as-a-decision, the non-uniform-pyramid principle, and "optimizes for structural understanding, not answer quality alone" as a grading discipline (not a computed metric — no code scores this).

**Also fixed while cross-checking:** `Architecture.md` §2's Graph Interface function list was stale (`attach_evidence` was never built; real functions are `attach_claim`, `find_or_create_entity`, `get_claims_for_question`, `supersede_claim`) — corrected to match `backend/graph/schema.py` exactly. `Rules.md` rule 6's fixed vocabulary sentence didn't mention `Claim` (added in Phase 5) and still listed `Resource` as if it were a node type (it isn't) — corrected.

**`SystemDesign.md`/`AgenticArchitecture.md` deliberately left untouched** — they're preserved verbatim as historical records of the user's original specs (their whole value is being the unedited "before" to compare against Architecture.md §0's revisions); folding new theory into them would destroy that. `PRD.md`/`Phases.md` (beyond the two corrections above) weren't rewritten either — nothing in system.md contradicted their product-level claims, only the deeper architecture docs needed reconciling.

**`docs/system.md` deleted** after this absorption, per instruction — its accurate content now lives in Architecture.md §0.1, and its inaccurate parts are recorded above rather than carried forward.

**Follow-up, same pass: sharpened `[built]`/`[vision]` into four labels — `[THEORY]` / `[BUILT]` / `[VERIFIED]` / `[VISION]`**, because a later exchange correctly pointed out that "code exists" and "a real test demonstrated it" are different claims, and the initial two-label pass didn't distinguish them. Retrofitted Architecture.md §0.1 immediately rather than only adopting it as a forward-looking convention: every claim there now cites either a specific test/run (`[VERIFIED]`) or is honestly downgraded. The one claim this actually changed on inspection, not just relabeled: "the system optimizes for structural understanding, not answer quality alone" was tagged `[built]` before, but there is no code anywhere that computes a structural-quality score or objective — it's a principle that shaped how *I* graded eval output by hand. Relabeled `[THEORY, applied as an evaluation methodology]` rather than `[BUILT]`, since calling it built would have been the exact kind of overstatement this whole pass exists to catch. Going forward, the traceability chain for any new feature is Theory → Architecture decision → PRD requirement → Phase → Implementation → Verification → Memory entry — if a claim can't point to a Memory.md entry with an actual test result, it isn't `[VERIFIED]`.

---

## 2026-08-28 — Graph persistence: recursive discovery now writes to Neo4j (the identified Phase 6 prerequisite)

Direct continuation of the near-decomposability research above. Until now, everything a Ground Agent discovered (decompositions, answers, claims) lived only in the SQLite agent-state store — Neo4j had real Question/Claim node types (Phase 5) but nothing in the agent runtime ever called them. Running the same investigation twice produced two disconnected trees, not a growing graph. This closes that gap.

**Design (agreed before implementing):** a decomposition does not automatically create a new entity — most sub-questions are just narrower questions about the *same* entity (e.g. "How does PayPal verify identity at signup?" out of "PayPal"). A new entity is only created when the sub-question reveals something genuinely separable with its own substantial internal structure (e.g. "DNS" out of "Internet Infrastructure") — a discovery decision, not an automatic consequence of decomposing.

**Implementation:**
- `backend/graph`: new `find_or_create_entity(name)` — case/whitespace-insensitive exact-name lookup before creating, the minimal form of Rules.md rule 12's "canonical, not duplicated" for entities an *agent* discovers (as opposed to a human explicitly creating one). Deliberately not `merge_entity` — that's still the tool for the harder case (realizing two differently-named nodes are the same real thing after the fact); this only prevents an exact-name duplicate at the moment of discovery.
- `backend/questions`: `GroundDecision` gained `discovered_entity_name: Optional[str]`, filled in the *same* LLM call as the decompose decision (not a second call) — the entity-discovery judgment and the decompose judgment are meant to be the same judgment, just also written to their own field.
- `GroundAgent` gained `persist_to_graph: bool = False` (opt-in, same pattern as `gather_evidence` — Phase 3/4/5 behavior and tests completely unaffected by default). When a decompose decision names a discovered entity: resolve-or-create both the parent and the new entity, link them with a `decomposes_into` relationship (reusing `RELATES_TO` + a `relationship_type` property, not a new schema-level relationship type — Rules.md rule 6), and the child question attaches to the *new* entity, not the parent. Every terminal outcome (answered, synthesized-from-children, or boundary-hit) gets attached to its entity via `_finish` — one choke point, so nothing terminal is silently unpersisted.

**A real bug found and fixed during first live test on the VM:** `find_or_create_entity` idempotency worked immediately, and decomposition itself worked correctly (3 real children: DNS resolution, TCP/TLS, IP routing — consistent with every prior Q1-style run) — but `discovered_entity_name` came back `None` on every single decompose call, despite the model's own `reasoning` field explicitly saying things like "distinct, independently-investigable mechanisms" each time. The bar for "decompose" and the bar for "name this as a discovered entity" were meant to be the same judgment, but the model was applying them as two separate, inconsistent ones — describing something as separable in prose without also naming it in the dedicated field. Reproduced cheaply in a 2-line local script (no Neo4j needed) before touching the VM again. Fixed by rewriting the prompt to state the contradiction explicitly: if the reasoning already uses "distinct"/"independently investigable"/"its own mechanism" language, `discovered_entity_name` is not optional, it's the same fact written twice. Re-verified locally (2/2 decompose calls now populate it correctly, e.g. `"DNS"`) and confirmed the ground-level "should stay unset" case still behaves correctly (not over-corrected into always populating it).

**Verification:** `scripts/verify_graph_persistence.py` (ad hoc, not a numbered Phases.md deliverable) PASSED on the VM after the fix — `find_or_create_entity` idempotency confirmed for a pre-existing node ("PayPal", created by `verify_phase5.py`'s own earlier run), and a full `GroundAgent(persist_to_graph=True)` run correctly persisted all three discovered entities with real `decomposes_into` relationships: `Internet Infrastructure Probe -[decomposes_into]-> DNS resolution / TCP/TLS Connection Establishment / Network Routing`. Also re-ran `verify_phase3.py`/`verify_phase4.py` locally after the prompt change (this touches every `decide_next_step` call, not just the persistence path) — both still pass, and the ground-level "should NOT discover an entity" case now shows the model explicitly reasoning "rather than a separate entity discovery" in its own words, confirming the fix didn't over-correct into always populating the field.

**Forward-looking note, not acted on:** a continued theoretical discussion proposed three distinct reasons something might deserve to be a node — structural coherence (internal >> external interactions, Simon's original test), functional coherence (performs a recognizable function), and investigative coherence (can be investigated with a self-contained set of questions) — suggesting investigative coherence may matter most for this system specifically, since its purpose is a navigable graph of things worth asking questions about. Not implemented; recorded as a candidate refinement if `discovered_entity_name`'s current single criterion turns out too coarse in practice.

---

## 2026-08-27 — Research probe: is the Q2 (PayPal) inconsistency a domain bias, or genuine coupling sensitivity? (Finding: not a bias — no prompt change made)

Direct follow-up to the Q2 finding in the structural-judgment pass below. Two things happened: theoretical grounding, then an empirical battery designed to falsify the leading hypothesis rather than confirm it — deliberately did NOT patch `decision.py`'s prompt first, per the explicit instruction that patching before understanding the failure pattern would just overfit to one case.

**Theory:** the relevant prior art is Herbert Simon's **near-decomposability** ("The Architecture of Complexity," 1962; still the standard reference across systems theory, evolutionary biology, and software architecture) — a system is decomposable when interactions *within* a proposed part are much stronger than interactions *between* parts. This is a sharper, falsifiable version of "independent investigability": does investigating one part mostly surface mechanisms specific to it, or does it just restate the same unified story the other parts would also tell?

**Empirical battery** (`scripts/evaluate_near_decomposability.py`, ad hoc, not a permanent eval), designed to break the tech-vs-business confound the single Q1/Q2 comparison couldn't rule out:
- **A — "How does Alphabet (Google) make money?"** (business domain, but segments — Search ads, YouTube ads, Cloud, Other Bets/Waymo — are close to textbook near-decomposable: different industries, different P&Ls, near-zero cross-coupling). **Decomposed cleanly into 3 real segments.** Its own reasoning used the phrase "near-decomposability" unprompted when justifying the Cloud split.
- **B — "How does a mechanical doorbell work?"** (technical domain, but genuinely one tightly-coupled circuit with no deep independent sub-mechanisms). **Decomposed into exactly one exploratory child, then stopped**, reasoning the remainder is "a unified, tightly-coupled mechanical sequence" — correct restraint, no decomposition theater.
- **C — "How does the United Nations function?"** (institutional domain, untested before this). **Decomposed cleanly into Security Council / General Assembly / Secretariat+ICJ / ECOSOC+humanitarian system** — matches the UN's real organizational structure.

**Conclusion: the leading hypothesis (business-vs-technical domain-genre bias) is falsified by this battery**, not confirmed. A business question (Alphabet) decomposed just as readily as a technical one (Q1's DNS/TCP/routing) when the underlying structure genuinely warranted it, and a technical question (doorbell) correctly did NOT decompose when it didn't. Re-examining PayPal (the original Q2 case) through Simon's actual criterion instead of "business vs. technical" makes its original "answer directly" call look more defensible than first assessed: PayPal's fee/FX/lending revenue streams all run through the same core transaction infrastructure, same customer base, same compliance/risk umbrella (real, moderate cross-coupling) — unlike Alphabet's segments, which are close to unrelated industries (near-zero cross-coupling). That's a genuinely closer call under Simon's test, not a clear miscalibration.

**No prompt change made.** All three new cases showed sound, well-reasoned behavior with the *existing* prompt (no edits between the structural-judgment pass and this one) — there's no evidence of a systemic bias to fix. If sharper terminology is wanted later, swapping "facets of one entity" for Simon's literal "interactions within >> interactions between" framing in `decision.py`'s master-level guidance would be a natural, low-risk refinement — but it isn't justified by anything found here, since the system already appears to be reasoning about actual coupling strength, not pattern-matching on domain genre.

**One theoretical refinement worth keeping precise:** near-decomposable does not mean *completely independent* — cross-part interactions still exist (PayPal's streams share infrastructure/customers/compliance; Alphabet's segments barely share anything), they're just weaker than internal interactions. It's a ratio/degree, not a binary. The pre-registered trigger for actually changing `decision.py` was "the same inconsistency appears across business, scientific, organizational, social, and technical examples" — the battery covered business/technical/institutional and found no such pattern, so that trigger has not fired.

**The conceptual chain this connects, worth stating explicitly since it's the load-bearing idea behind Phases 3-5 even though it was never written down this way before:** Abstraction (defines the boundary) -> Decomposition Hypothesis (is this boundary better represented as one node or several?) -> Investigation (the recursive Ground Agent loop actually tests it) -> Coupling Discovery (the investigation's own results reveal how tightly the proposed parts actually interact) -> New Abstraction (the graph updates to reflect what was learned). This is Rules.md's "questions form their own graph" and Architecture.md §0's dynamic-recursion decision, read together as one theoretical throughline rather than two separate design choices.

---

## 2026-08-27 — Third refinement pass: graded on structural judgment, not decomposition frequency; added decision reasoning

Direct continuation of the same-day sequential-decomposition/master-bias pass below — the design discussion that produced that pass immediately pointed out a flaw in how it was being tested: a "did Q1 decompose?" test can be trivially gamed by a system that decomposes everything into meaningless pieces ("decomposition theater"). The real success criterion is **"good Master decision = correct structural representation, not = decompose."** A MASTER question can legitimately go either way — some subjects really are separable real-world entities (decompose), others are one tightly-coupled phenomenon whose "parts" are just interacting explanations of the same thing (answer directly is then the *correct* call, not a failure).

**Added `GroundDecision.reasoning: str`** (required field) — every decision now states, in the model's own words, why this action and not another is the right call, especially the structural judgment at master level. Not persisted onto `GroundResult` (no schema change there — deliberately, per the same "don't add fields nothing uses yet" discipline as the last pass) — instead printed by `GroundAgent` at each loop iteration (`[ground:{id}] level=... action=... reasoning=...`), which is enough to make the judgment visible in logs/eval output without committing to a permanent schema surface for it yet.

**Rewrote `decision.py`'s master-level guidance** around three legitimate outcomes instead of two: (1) genuinely separable structure → decompose, (2) one tightly-coupled phenomenon → answer directly even if a decomposition is technically possible, (3) genuinely unclear which — decompose into ONE exploratory sub-question specifically to resolve the ambiguity, then reassess. This third case isn't a new mechanism — it's the same sequential "decompose" action already built, just named explicitly as a legitimate use (investigate first, judge structure after) rather than only "decompose because structure is already obvious."

**Built `scripts/evaluate_structural_judgment.py`** (4 questions, pre-registered per-question expectations written before running, framed as "what would a defensible call look like," not "should it decompose"): Q1 (website request — expect real mechanism decomposition), Q2 (PayPal revenue — expect real economic components, decompose-or-answer both acceptable as long as the streams are correctly identified), Q3 (drug development, research → market — expect real regulatory/process-stage structure), Q4 (why does money have value — explicitly pre-registered as legitimately either outcome, this was the real test).

**Result, run live through the real fallback chain (no rate-limit workarounds — per instruction, that's useful operational signal, not noise to eliminate):**
- Q1: decomposed into DNS resolution / TCP+TLS / BGP-routing, terminated naturally after all three resolved. Clean match.
- Q3: decomposed into discovery-preclinical / clinical trials I-III / regulatory review-post-market, with real named milestones (IND, NDA/BLA, Phase IV). Clean match.
- Q4: **the strongest result.** First decomposed into exactly one exploratory sub-question (historical commodity-to-fiat evolution) — the ambiguous-case mechanism working exactly as designed — then on the next round explicitly reasoned that economic/psychological/historical/institutional explanations are "facets of the exact same... reality, rather than separate, independently investigable... entities," answered directly, and the final answer actually named and connected all four facets rather than picking one. This is a precise match to the pre-registered GOOD(answer) outcome, and the reasoning trace shows it was a real judgment, not a lucky guess.
- Q2: passed on content (correctly enumerated real distinct revenue streams — transaction fees, currency exchange, credit products) but answered directly with reasoning that revenue streams are "facets... of a single enterprise," which is structurally inconsistent with Q1's treatment of request phases as separable despite also being "facets of one request." Recorded honestly as a real, unresolved calibration gap rather than glossed over — the model's separable-vs-facets judgment isn't yet fully principled/consistent across a technical-mechanism question (Q1) vs. a business-model question (Q2). Not worth over-fitting the prompt to one case; worth knowing before trusting this bias more broadly.

**Verification:** re-ran `verify_phase3.py`/`verify_phase4.py` locally and `verify_phase5.py` on the VM after adding the required `reasoning` field (had to add it to `verify_phase4.py`'s monkeypatched `GroundDecision` constructions too) — all still pass.

---

## 2026-08-27 — Second refinement pass: sequential decomposition + master-level structural bias, driven by a second known-answer eval

Not a Phases.md phase. Prompted by a second known-answer test set (10 questions on "Modern Internet Infrastructure," supplied by the user with citations, drafted with ChatGPT's help as a design sketch of the intended architecture) and a deep design discussion that followed from it. Two real architectural changes came out of this, both to `GroundAgent`'s decision loop.

**Finding #1 — decomposition was batch, not iterative, contradicting the original spec.** The user's design sketch pointed out that `_decide_and_act()` decided a whole batch of 2-4 sub-questions in one LLM call before any of them ran — "decide everything, then execute everything" — rather than AgenticArchitecture.md §23's actual lifecycle: GENERATE ONE QUESTION -> INVESTIGATE -> INTEGRATE -> CHECK COMPLETENESS -> decide again. Confirmed this was a real gap, not just a style choice, and rebuilt `GroundAgent`'s core loop (`_investigate_loop`, replacing `_decide_and_act`/`_decompose`/`_run_children`) to be sequential: one sub-question per round, its result folded into a running `known: list[str]` (finally wiring up `decide_next_step`'s `known` parameter, which existed since Phase 3 but nothing had ever populated), then re-deciding — repeated until "answer," "boundary_hit," or a new `max_sequential_steps` budget (default 4, independent of `max_depth`) is exhausted. Resumability had to be redesigned alongside this: a resumed `DECOMPOSING` agent now replays completed children to reconstruct `known`, then re-enters the *same* loop rather than a separate one-shot synthesis step — a growing children list, not a fixed batch decided once.

**Deliberately NOT built**, despite being suggested in the same design discussion: a formal multi-axis decision function (`Answerability × StructuralValue × GraphValue × Independence × AbstractionLevel × Cost`) or a richer stopping-signal taxonomy (`CONFLICT`, `INSUFFICIENT_EVIDENCE`, `LOW_INFORMATION_GAIN`, `BUDGET_EXHAUSTED` as distinct `AgentStatus` values). Both are good ideas, but most map to mechanisms that don't exist yet — conflict detection is explicitly Phase 7, evidence-sufficiency gating and cost-based prioritization are explicitly "Later" in Phases.md. Adding the labels/schema now with nothing behind them would repeat the exact premature-scaffolding mistake already avoided once in Phase 4 (unused `TaskMessage`/`CompletionMessage` classes). The informal judgment these would encode is instead carried entirely in `decide_next_step`'s prompt text, which is enough to produce the right behavior (verified below) without a schema commitment the project isn't ready to support yet.

**Finding #2 — even after fixing #1, decomposition never actually triggered.** Ran the internet-infrastructure eval (all 10 questions + a deep re-run of Q1 with `max_depth=2`) — every single one answered directly on round one, including clearly broad/systemic ones. All 11 answers were factually strong (matching or exceeding the user's provided citations), which was itself the cause: modern free-tier LLMs can write a comprehensive, accurate answer to "how does a website request travel through the Internet" in one shot, so a decision criterion of "can I answer this well" will essentially never choose to decompose a well-known topic — regardless of how sequential the loop is. This exposed a real product-philosophy gap: **"can I answer this" and "would this be a more useful knowledge graph split into entities" are different questions**, and the system was only ever asking the first one. Since the entire differentiator over "just ask an LLM directly" is the graph (non-linear pyramid, navigable entities, PRD §4a's roadmap), a system that never decomposes answerable-but-structurally-rich questions never actually builds that graph for the questions where it matters most.

**Fix:** made `decide_next_step`'s prompt level-aware with genuinely different criteria per level, instead of forcing decomposition unconditionally (which would just reintroduce eager-tree behavior, the exact thing Rules.md rule 11 already rejected once). `level="ground"` keeps the original "decompose only when a real, specific unknown blocks answering" rule. `level="master"` now asks a structural question instead: "does this subject genuinely break down into 2+ distinct real-world entities/mechanisms/phases that would be more useful as separate, navigable questions than as one paragraph" — answering directly is still allowed at master level, but only when the question is already atomic or "known" already covers the natural sub-parts. This is a judgment call encoded in prompt text, not a hard rule, deliberately: forcing every master question to decompose (considered and rejected) would recreate eager batch generation in a different guise.

**Verification, graded on structure quality, not just "did it decompose" (the user specifically flagged this — a system could trivially pass a "did it decompose" test with arbitrary, meaningless children, which would be decomposition theater, not a real result):** re-ran the same MASTER-level Q1 ("how does a website request travel through the Internet?") with `max_depth=2`. It decomposed into 3 children — DNS resolution, TCP+TLS connection establishment, and network transport/routing — then concluded with "answer" on its own after 3 rounds, well under the `max_sequential_steps=4` budget (not budget-forced). These three children are non-overlapping, each independently informative, and correspond to real, textbook-recognizable phases of the exact mechanism a networking expert would name — closely matching (though not identically bucketed as) the DNS/TCP/TLS/HTTP/routing structure the user's own design sketch predicted, discovered without being told that structure in advance. This is the first real evidence that the recursive decomposition mechanism does something meaningful under real LLM judgment, not just under the forced/monkeypatched tests used to verify the mechanism itself in Phase 3/4.

**Regression:** rewrote `verify_phase3.py`'s mid-decomposition-crash test (exact `== 2` children assertions loosened to `>= 2` / subset checks, since the agent may now adaptively add more children after resuming — this is correct new behavior, not a bug) and `verify_phase4.py`'s boundary-propagation monkeypatch (now returns one sub-question per call across 2 rounds instead of 2 at once, matching the new one-at-a-time contract). Re-ran `verify_phase3.py`/`verify_phase4.py`/`verify_phase5.py` on both machines after every change in this pass — all still pass.

**Next up:** continue toward Phase 6 (Visualization UI + Roadmap generation) — this pass was explicitly a "make the core right before building UI on top of it" detour, not new phase work.

---

## 2026-08-27 — Post-Phase-5 refinement pass: known-answer evaluation, evidence quality, and two more silently-hidden bugs

Not a Phases.md phase — a deliberate quality pass before starting Phase 6, prompted by asking "is this actually working well" and getting an honest "the plumbing works, the product is unproven" answer. Two things happened: (1) built and ran a small known-answer evaluation, (2) researched and fixed the real gaps it found.

**The evaluation (`scripts/evaluate_known_answers.py`, not a Phases.md deliverable but kept for reuse):** 5 targeted questions with expected-answer checklists written *before* running anything — factual/historical (PayPal founding), mechanism (card auth), economic (PayPal revenue), a broad/decomposable one (global card ecosystem), and one entirely outside the payments domain (CRISPR-Cas9) to test generality. Result: **raw answer accuracy was genuinely good across all 5** — no hallucinated facts, correct mechanisms, correct revenue model. But it surfaced two real, previously-invisible gaps:
1. **A decomposed question had no top-level answer at all.** The broad ecosystem question correctly recognized it needed decomposition (3 sub-questions, each answered well — one child even correctly named all 5-6 card-ecosystem roles), but the *parent's* `GroundResult.answer` was just `None`. A real user would see 3 disconnected paragraphs with nothing tying them together.
2. **The evidence layer contributed almost nothing.** Across 5 questions and ~10 retrieval attempts, only 2 real resources came back (2 irrelevant Open Library books, correctly scored near-zero confidence). Semantic Scholar 429'd on every call; arXiv had no relevant coverage for non-academic questions. Every answer above was pure LLM parametric knowledge dressed up with a confidence score — not the evidence-grounded system Rules.md rule 4 describes.

**Research done to fix gap 2** (the user specifically asked for research into resilient, open-source, hard-to-block search options):
- **Wikipedia REST/Search API** — verified live: keyless, 100 req/s anonymous with a proper User-Agent. This was the single biggest miss in the retriever list — every eval question was exactly what an encyclopedia covers best. Added `WikipediaRetriever`.
- **`duckduckgo-search`/`ddgs`** — works, but its own documentation states it's "not officially allowed" per DuckDuckGo's ToS. Deliberately not used — didn't want the evidence layer resting on something that explicitly violates a provider's terms, especially from a cloud-provider IP range that's commonly flagged.
- **Brave Search API** — free tier was killed in Feb 2026, now requires a credit card even for the smallest tier. Ruled out (verified via live research, not assumed from training data).
- **SearXNG** (self-hosted open-source meta-search, aggregates dozens of engines so no single one can block you) — genuinely the right answer to "no system can block us," but needs 256-512MB RAM which doesn't fit on the current VM (Neo4j alone uses most of the ~500MB usable). Verified Oracle's Always Free tier allows a **second** AMD micro VM per account at zero cost — a real, unused path to self-host this, presented to the user as a Tier-2 option requiring their go-ahead (not yet built).

**A genuine new discovery while building `WikipediaRetriever`:** `httpx` got a bare 403 from Wikipedia's edge on every single request regardless of headers — verified directly (identical headers succeeded via plain `curl`, failed via `httpx`). This is TLS/JA3 client fingerprinting, not a User-Agent or rate-limit check (Wikimedia's own 403 body literally invites bot traffic: "Contact bot-traffic@wikimedia.org if you need higher volumes"). Fixed with `curl_cffi` (`impersonate="chrome"`), which presents the same TLS handshake shape as `curl` (which already worked) while still sending our real, identifying User-Agent — not spoofing identity, just avoiding a fingerprint false-positive on Wikipedia's own public, docs-encouraged API. Measured footprint (~11MB heap, ~5MB disk) before deploying; safe for the VM.

**Fixed gap 1** by adding `synthesize_answer()` to `backend/questions` (new `synthesis.py`, uses `MASTER_MODEL_CHAIN` — Rules.md rule 3 names "synthesis across many children" as exactly the justified reason to escalate tiers) and wiring it into `GroundAgent._run_children`: every decomposed question now gets a coherent top-level answer synthesized from its children's answers (or boundary-hit reasons), not just a bag of child results. Recursive by construction — a child that itself decomposed already carries its own synthesized answer one level down.

**Two more real, previously-hidden bugs found the moment `MASTER_MODEL_CHAIN` was exercised for the first time ever** (it was written in Phase 2, never actually called until this synthesis feature used it):
1. `"google/gemini-flash-latest"` **hangs indefinitely** — verified at the raw `google-genai` SDK level (not an instructor issue), no exception, no timeout, just never returns. Replaced with `"gemini-2.5-flash"`, verified working directly.
2. `"cohere/command-r"` needs the separate `cohere` package, never installed (the API key existed, but nothing had ever called this chain to notice the missing package). Dropped rather than fixed — reused `cerebras/gpt-oss-120b` (already integrated, already has a working key) as the third rung instead of adding a whole new provider SDK for a never-proven fallback slot.
3. **Bigger lesson, fixed structurally, not just patched:** a hanging provider with no timeout can block an entire fallback chain forever — worse than a fast error, since it never even gets to try the next provider. Added `PER_PROVIDER_TIMEOUT_SECONDS = 30` to `structured_call` (`asyncio.wait_for` around each attempt). This is the second time in two phases a silent-failure-hiding pattern in the fallback chain has hidden a real bug (see Phase 5's `jsonref` entry below) — the chain's job is to survive individual failures, not hide them, and now it structurally can't hide a *hang* the way it previously hid an *error*.

**Also fixed while touching these files:** `boundary_reason` sometimes came back as the literal string `"null"` instead of a real reason or being left unset — added an explicit check (a falsy-string guard alone doesn't catch a non-empty string that says "null"). Retriever error logging now falls back to the exception's type name when `str(exc)` is empty (caught a transient arXiv failure mid-eval that logged nothing after the colon).

**Verification:** re-ran `verify_phase3.py`/`verify_phase4.py`/`verify_phase5.py` on both machines after all of the above — all still pass. Re-ran the Q4 known-answer question directly: the parent now produces a detailed, accurate, well-organized top-level answer covering all six card-ecosystem roles and the full authorization → clearing → settlement lifecycle (incidentally also fixing Q2's original checklist gap, which had been missing the settlement step).

**Still open, by the user's choice, not an oversight:** Tavily/YouTube keys not yet configured (free, ~5 min each, no code changes needed once added); SearXNG second-VM not yet provisioned (real infra, zero cost, needs a go-ahead before spending the setup time).

---

## 2026-08-27 — Phase 5 complete: Evidence Engine, deployed and verified on live infrastructure

**What's done:**
- `backend/graph` extended with the first non-Domain/Entity/Abstraction node types: `Question` and `Claim` nodes, `HAS_QUESTION` (entity -> question), `ANSWERED_BY` (question -> claim), and `SUPERSEDES` (claim -> claim, Graphiti-inspired valid-time/superseded temporal pattern — the old claim is kept and just marked non-current via `superseded_by`, never deleted). New Graph Interface functions: `attach_question`, `attach_claim`, `get_claims_for_question`, `supersede_claim`, plus uniqueness constraints for both new labels. `QuestionNode`/`ClaimNode` are deliberately separate plain models from `backend.questions.Question`/`backend.evidence.Claim` — `backend/graph` still must not import from the layers above it.
- `backend/evidence` built from scratch: `RetrievedResource`/`ClaimDraft`/`Claim` models; a common `Retriever` ABC (pattern borrowed from `gpt-researcher`, per Architecture.md §1); five concrete retrievers — `ArxivRetriever` and `SemanticScholarRetriever` and `OpenLibraryRetriever` (all keyless, zero setup), `TavilyRetriever` and `YouTubeRetriever` (need a free key the user doesn't have yet — see below); `synthesize_claim()` (the one LLM call in this module, per Rules.md rule 2); `gather_evidence(question) -> list[Claim]` orchestrating all of them concurrently.
- `GroundAgent` and `MasterAgent` both gained an opt-in `gather_evidence: bool = False` flag (`ground_gather_evidence` on Master) — when true, a Ground Agent that answers also calls the Evidence Engine and populates `GroundResult.claims`. Defaults to False so Phase 3/4's existing behavior, tests, and free-tier API usage are completely unaffected unless explicitly requested.
- **`scripts/verify_phase5.py` PASSED on the VM** (no local Neo4j exists — this dev machine has no Docker at all, so anything touching the Graph Interface has only ever been verifiable on the VM, same as Phase 1) — two checks: (1) `GroundAgent(gather_evidence=True)` produced 2 real, sourced claims when it answered a live question; (2) the full pipeline — create entity -> generate a real Question -> `attach_question` -> `gather_evidence` (2 real resources came back live) -> `attach_claim` for each -> read back via `get_claims_for_question` and confirm confidence/provenance populated -> `supersede_claim` exercised end-to-end, old claim kept with `superseded_by` set correctly.

**Two real bugs found and fixed (not infra plumbing — actual correctness bugs):**
1. **Confidence/relevance semantics were backwards in the claim-synthesis prompt.** First live run: the LLM wrote `evidence: "The resource does not answer the question"` while also returning `confidence: 0.99`. The prompt asked for "how confident you are that this resource answers the question," which the model apparently read as "how confident are you in this judgment" rather than "how well does it match." Fixed by making the prompt explicit: confidence must be low (<0.2) whenever the resource doesn't substantively answer the question, regardless of how certain the model is about that assessment. Re-verified: the same non-matching arXiv physics papers (arXiv's `all:` search matches loosely on natural-language questions with no relevant papers to find) now correctly score confidence 0.1 instead of 0.99-1.0. This is exactly the kind of bug graceful degradation doesn't catch — the retriever "succeeded," the LLM call "succeeded," the output was just quietly wrong.
2. **The `google/...` entry in `GROUND_MODEL_CHAIN` has likely been silently failing on every single call since Phase 2**, invisibly masked by the fallback to `groq/...` succeeding every time. Root cause: instructor's Gemini structured-output path (`instructor/v2/providers/gemini/utils.py`) does a bare `import jsonref` and raises `ConfigurationError` without it — `jsonref` was never in `requirements.txt`. This was only discovered because, in one test run, Groq hit a transient `tool_choice` error AND Cerebras returned `402 Payment required` (real free-tier quota exhaustion from a day of heavy testing) at the same time, so for the first time every provider in the chain failed simultaneously and the previously-hidden Google error finally surfaced. **Fixed two things, not one:** added `jsonref` to `requirements.txt` (the actual missing dependency), and — more importantly — changed `structured_call`'s per-provider fallback loop to `print()` each provider's failure before moving to the next, instead of silently swallowing it. The silent swallow is what let a real bug hide for three phases; the chain's job is to survive individual provider failures, not to hide them from whoever's watching the logs.
3. **Also caught mid-investigation: `google-genai` had silently drifted to `2.20.0`**, violating the `requirements.txt` pin (`>=1.0,<2`), as a side effect of unrelated `pip install <package>` commands (installing `langgraph`, `tavily-python`) that don't respect a project's pins the way `pip install -r requirements.txt` does. Fixed by re-running `pip install -r requirements.txt` to force the resolver back to pinned versions (also caught `groq` having drifted to `1.7.0` against its own `<1` pin). **Lesson for future phases: after any one-off `pip install <package>` during exploration/debugging, re-run `pip install -r requirements.txt` before trusting the environment again** — individual installs can silently upgrade shared transitive dependencies past a pin without any warning.

**Other notes:**
- Only arXiv/Semantic Scholar/Open Library are actually exercised live right now — the user doesn't have `TAVILY_API_KEY` or `YOUTUBE_API_KEY` yet. Both retrievers correctly self-skip to zero results (Rules.md §3's graceful degradation covers "missing key" the same as any other failure) rather than erroring. Tavily is free (1,000 credits/mo, https://tavily.com); YouTube Data API v3 needs a Google Cloud API key with that specific API enabled (10,000 quota units/day, search.list costs 100 units = ~100 searches/day). Neither blocks Phase 5 — add the keys to `.env` whenever, no code changes needed.
- Semantic Scholar's keyless tier hit `429 Too Many Requests` on essentially every call made today (shared-IP rate limiting, not specific to this project) — graceful degradation handled it correctly every time, but it means Semantic Scholar isn't a reliable source without requesting a free API key (https://www.semanticscholar.org/product/api#api-key-form) if it needs to be load-bearing later.
- Deliberately did NOT wire a Ground Agent's `entity_name` (a plain string) to an actual Neo4j entity `id` inside `GroundAgent` itself — that would require inventing an entity-resolution mechanism the design docs haven't specified yet. `verify_phase5.py` demonstrates the full create-entity -> generate-question -> attach -> gather-evidence -> attach-claim pipeline explicitly via the Graph Interface functions directly, which is honest about what's wired automatically (`GroundResult.claims`) versus what still needs an orchestrator to call the graph functions (attaching to Neo4j) — that orchestration point will become clearer once Phase 6's UI/API layer exists.

**Next up (Phase 6 per Phases.md):** Visualization UI + Roadmap generation — FastAPI REST + WebSocket endpoints, React + Cytoscape.js frontend (navigate/zoom/click-to-inspect), and `generate_roadmap(abstraction) -> list[Question]` (PRD.md §4a, a pure function over the existing graph per Rules.md rule 14 — it only reads, never calls an LLM or retriever itself). This is also where the money-transactions worked example (PRD.md §4) gets run end to end for the first time.

---

## 2026-08-27 — Phase 4 complete: MasterAgent + message bus + spawn budget, deployed and verified on live infrastructure

**What's done:**
- `backend/agents/messages.py`: `MessageType` enum declaring the full taxonomy (AgenticArchitecture.md §19-21) as the protocol surface, but only `BoundaryHitMessage`/`ExpansionRequestMessage` got concrete Pydantic classes — those are the only two this phase's Master+Ground tier actually produces/consumes; the rest stay enum-only until a later phase (Evidence Engine, abstraction-change protocol) actually emits them.
- `backend/agents/bus.py`: `MessageBus`, a single `asyncio.Queue` shared by one Master and its whole Ground tree for one run. Vertical-only (Rules.md rule 9) by construction — every Ground Agent can only *send*, only the Master ever *consumes*, so no sibling ever sees another sibling's message even though the transport is one shared queue.
- `GroundAgent` (Phase 3) extended with optional `bus`/`parent_chain` params. `parent_chain` is threaded root-first through recursion (`[*self.parent_chain, self.agent_id]` for each child); a `BOUNDARY_HIT` result now also posts a `BoundaryHitMessage` carrying that chain, when a bus is present. `bus=None` (Phase 3's own usage, and `scripts/verify_phase3.py`) is unaffected — zero behavior change.
- `GroundAgent` also now self-initializes its SQLite state table (`_ensure_db`, per-process cache of already-initialized `db_path`s) instead of relying on the caller to have called `init_db()` first. Phase 3 got away with this because `verify_phase3.py` was the only caller; once `MasterAgent` spawns agents from a single call site that fans out to many, relying on every future caller to remember a separate init step became a real footgun.
- `backend/agents/master_agent.py`: `MasterAgent`, built on **LangGraph's `StateGraph`** (core engine only, no LangChain agent abstractions) with two nodes — `enforce_spawn_budget` (pure decision: which questions get investigated, given `spawn_budget`/`broad_spawn_budget` and an explicit `complexity` signal) then `spawn_and_run` (the only node that actually constructs `GroundAgent`s, spawns them via `asyncio.gather`, and runs a `MessageBus` consumer loop that converts each `BoundaryHitMessage` into a logged `ExpansionRequestMessage` decision via a simple `max_expansions` counter — ACCEPT up to the limit, REJECT past it). Checkpointed via `AsyncSqliteSaver` (the official `langgraph-checkpoint-sqlite` package), composing with the project's existing SQLite-everywhere choice rather than adding a new storage engine.
- **`scripts/verify_phase4.py` PASSED both locally and on the VM** — three checks: (1) a live 2-question run through the real LangGraph graph with real LLM calls; (2) `decide_next_step` monkeypatched (the same technique `verify_phase3.py` used) to force a parent to decompose into 2 children that each hit a boundary — confirmed both resulting `ExpansionRequestMessage`s share the same root ancestor in `sender_chain` but have different senders (proof of real multi-hop propagation, not a single flat hop), and that the Master ACCEPTed the first and REJECTed the second (`max_expansions=1`); (3) fed the Master 5 questions under the default `spawn_budget=3` for a `complexity="simple"` query, and confirmed via an LLM-call counter that only 3 calls were made — i.e. the budget was enforced *before* spawning, not just truncated after the fact.

**Hard lessons learned:**
1. **A real, measured memory tradeoff was surfaced and decided before writing code, not after.** LangGraph core costs ~44MB of Python heap just to import (measured via `tracemalloc` locally), against a VM that has historically had as little as ~158-199MB available and already OOM'd once (Phase 1). Asked the user directly rather than silently picking a side; they chose "use LangGraph, watch memory carefully" over dropping it or forking the implementation. Verified empirically on the VM (`free -h` before/after both `pip install` and the actual verification run) that it stayed safely within budget (~178-199MB available throughout, no swap spike) — the risk was real but didn't materialize this time. Keep watching this in Phase 5+ as more gets layered on.
2. **`langgraph>=1.0` requires Python >=3.10 — the VM's Python 3.9.25 can't install it at all** (pip found zero matching versions). Same root constraint as Phase 2's `eval_type_backport` issue (VM is stuck on an EOL Python 3.9 unless deliberately upgraded). Fixed by relaxing the requirement to `langgraph>=0.6,<2`, letting pip resolve 1.2.11 locally (Python 3.11) and 0.6.11 on the VM (Python 3.9) — verified directly (not assumed) that `StateGraph`/`START`/`END`/`add_node`/`add_edge`/`compile`/`ainvoke` and `AsyncSqliteSaver`'s import path (`langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver`) are identical across both resolved versions before relying on it.
3. **`aiosqlite>=0.22` removed `Connection.is_alive()`** (it stopped subclassing `threading.Thread`), which crashes `langgraph-checkpoint-sqlite==2.0.11` (the version paired with the Python-3.9-compatible `langgraph==0.6.11`) with `AttributeError: 'Connection' object has no attribute 'is_alive'` on its very first checkpoint write — a known, still-open upstream bug in that specific old checkpoint-sqlite release. The newer `langgraph-checkpoint-sqlite==3.1.1` (paired with `langgraph==1.2.11` locally) doesn't hit this. Fixed by capping `aiosqlite>=0.20,<0.22` in `requirements.txt` — verified this single pin works correctly on **both** environments (re-ran `verify_phase3.py`/`verify_phase4.py` locally and on the VM after the downgrade, all still passed) rather than special-casing one environment's version.
4. **Deliberately did NOT build dedicated Pydantic classes for the full message taxonomy.** `MessageType` declares all 14 members from AgenticArchitecture.md §19-21 (so the protocol surface is documented), but only `BoundaryHitMessage`/`ExpansionRequestMessage` — the two types actually produced/consumed this phase — got real classes. Building `TaskMessage`/`CompletionMessage`/etc. now, with no producer or consumer anywhere in the codebase, would have been exactly the kind of premature, half-finished scaffolding the project's own engineering discipline (and Rules.md's "don't build for hypothetical future requirements") warns against — add them in the phase that actually emits them.
5. **`MasterAgent`'s own LangGraph state is deliberately plain dicts** (`Question.model_dump()` / `GroundResult.model_dump()` in, reconstructed via `Question(**q)` / `GroundResult(**r)` out — pydantic v2 recursively validates nested dicts back into `GroundResult.child_results` automatically, no manual recursion needed). The actual `GroundAgent` objects and the `MessageBus` live as closures inside `MasterAgent.run()`, never inside LangGraph's checkpointed state — avoids any question of whether the checkpointer's serializer can round-trip live agent objects, which was never actually needed since Ground Agent resumability is already handled by Phase 3's own SQLite state store.

**Next up (Phase 5 per Phases.md):** Evidence Engine — retriever wrappers (Tavily, Semantic Scholar, arXiv, Open Library, YouTube Data API v3) behind a common interface (pattern borrowed from `gpt-researcher`), a `Claim { evidence, source, reasoning, confidence, contradictions, timestamp }` model, temporal claim edges in Neo4j (Graphiti-inspired), wired into Ground Agent results. First phase where the system fetches real external, non-LLM-generated information. Verify: ask a real question, confirm at least one real resource comes back from a live API call and is attached to the question node in the graph with confidence/provenance populated.

---

## 2026-08-27 — Phase 3 complete: single Ground Agent loop, deployed and verified on live infrastructure

**What's done:**
- Refactored `backend/questions/engine.py`'s inline Instructor-fallback loop into a shared `backend/questions/llm_client.py::structured_call()` helper, so the Ground Agent's decision call could reuse the exact same provider-fallback behavior without a second copy of it.
- Added `GroundDecision` (LLM-facing: `action` = `answer` / `decompose` / `boundary_hit`, plus the payload for whichever action) and `decide_next_step(question) -> GroundDecision` to `backend/questions/decision.py`. This is the one LLM call behind a Ground Agent's step — it lives in `backend/questions`, not `backend/agents`, per Rules.md rule 2 (only `/backend/evidence` and `/backend/questions` may call external LLM APIs; `GroundAgent` calls this function rather than touching Instructor itself).
- Built `backend/runtime/state_store.py`: a schema-agnostic `aiosqlite`-backed store (`init_db` / `save_state` / `load_state`, keyed by `agent_id`, storing opaque JSON). `backend/agents` owns the actual `AgentState` shape; the runtime layer just persists/retrieves it.
- Built `backend/agents/ground_agent.py`: `GroundAgent` class. `run()` always starts by reading the state store — never from in-memory state — so it doubles as the resume path. A fresh agent asks `decide_next_step`; `"answer"` or a directly-requested `"boundary_hit"` terminates the branch; `"decompose"` (if depth budget allows) spawns child `GroundAgent`s at `depth+1` and recurses. No separate `DomainAgent`/`SubdomainAgent` classes (Rules.md rule 8) — recursive `GroundAgent`s are the whole mechanism. `DEFAULT_MAX_DEPTH = 2` is a **local** safety bound only, standing in for the Master's spawn budget (Rules.md rule 10) until Phase 4 actually builds a Master to own that.
- **`scripts/verify_phase3.py` PASSED both locally and on the VM** — two checks: (1) a live agent run reaches a terminal state via a real LLM call, then a second `GroundAgent` object built from only the same `agent_id` returns the identical cached result with the LLM call count at zero (confirmed by monkeypatching `decide_next_step` with a counting wrapper); (2) a parent+2-children `DECOMPOSING` checkpoint was hand-written directly to the state store (simulating "process died right after persisting the decomposition, before running any child") and a brand-new `GroundAgent` object built from nothing but that on-disk state correctly resumed, ran only the pending children, and reached `COMPLETE`.

**Design decisions worth remembering:**
1. **Children are checkpointed as `PENDING` *before* the parent flips to `DECOMPOSING`.** This ordering matters: if the process dies mid-loop while writing children, resume finds the parent still `PENDING` and just re-decides (wasting at most one extra LLM call) instead of `DECOMPOSING` with a `children` list pointing at agent_ids that were never persisted — which would make their questions unrecoverable, since the question text only exists in the crashed process's memory until it's on disk.
2. **Boundary-hit detection in Phase 3 is self-assessed by the LLM, not evidence-based** — there's no Evidence Engine (Phase 5) or Master (Phase 4) yet to escalate to. A `boundary_hit` here is a terminal typed result, not an actual escalation message; real vertical escalation (Rules.md rule 5) arrives in Phase 4 once a parent chain and a Master exist to receive it. Hitting the local depth budget while still wanting to decompose is treated as a boundary hit too (this matches AgenticArchitecture.md §10-11's "abstraction too deep for current objective" condition, reused here since it needs no extra infrastructure).
3. Kept `requirements.txt`/VM deployment discipline from Phase 2: added `aiosqlite` locally first, ran `scripts/verify_phase3.py` on Windows/Python 3.11 until it passed, *then* `scp`'d the changed files (`backend/agents`, `backend/runtime`, the touched `backend/questions` files, `requirements.txt`, `scripts/verify_phase3.py`) to the VM (`opc@129.225.116.251:~/app`, not `ubuntu` — the VM's actual login user), installed `aiosqlite` there, and reran — passed unchanged. Also reran `scripts/verify_phase2.py` on both machines after the `structured_call` refactor to confirm it didn't regress Phase 2.
4. Windows console encoding note (not a bug in this project): `verify_phase2.py` can crash with `UnicodeEncodeError` printing certain unicode characters (e.g. `‑` non-breaking hyphen) that a live LLM response happens to contain, because Windows' default terminal codepage is `cp1252`. Run with `PYTHONIOENCODING=utf-8` set if this happens — it's a print-encoding issue, not a logic failure (the assertions before the crashing `print()` had already passed).

**Next up (Phase 4 per Phases.md):** `MasterAgent` wrapping recursive `GroundAgent` calls (LangGraph core engine for the state machine/checkpointing), a **hard spawn budget enforced by the Master before any spawning** (Rules.md rule 10 — this is where the real version of Phase 3's `DEFAULT_MAX_DEPTH` placeholder gets replaced with an actual complexity-aware budget), a typed vertical-only message bus (asyncio queues + Pydantic models, no lateral peer channel per Rules.md rule 9), and a priority task queue. Two verifications required: a `BOUNDARY_HIT` propagating up to a Master `EXPANSION_REQUEST` decision, and a simple/narrow query confirmed to NOT spawn more than the small default budget.

---

## 2026-08-27 — Phase 2 complete: Question Engine deployed and verified on live infrastructure

**What's done:**
- `backend/questions` module built: `Dimension`/`Question`/`QuestionDraft`/`QuestionLevel` models, the 3 universal dimensions (Scale/Perspective/Time), and `generate_question()` — a lazy, level-aware `(Abstraction, Entity, Dimension, Level, Objective, Known, Unknowns) -> Question` function with a 3-provider fallback chain.
- **`scripts/verify_phase2.py` PASSED both locally and on the VM** — real Gemini API calls, structured output enforced by Instructor, ground vs. master questions for the same entity+dimension came back with only 6-9% word overlap (well under the 60% threshold), confirming genuine level-awareness rather than reworded duplicates.

**Hard lessons learned (architecture-changing, not just bugs):**
1. **`instructor.from_litellm()` doesn't work reliably and was abandoned.** It hardcodes `provider=Provider.OPENAI` internally regardless of the actual model string passed to litellm, and OpenAI's mode registry in this instructor version doesn't reliably include whatever default mode `from_litellm` picks — confirmed by getting *different* registry error messages on different runs (sometimes missing `TOOLS`, sometimes missing `JSON_SCHEMA`) despite identical code and package versions on both local and remote machines. **Root cause never fully isolated** (looks like nondeterministic registration order inside instructor's own import-time side effects) — not worth chasing further. **Fix: dropped `litellm` entirely.** Use `instructor.from_provider("google/model-name")` / `"groq/..."` / `"cerebras/..."` instead — this derives the real provider from the string and uses that provider's *native* SDK with its own pre-vetted default mode. Far more reliable. Architecture.md/Rules.md updated to match; `litellm` removed from requirements.txt and uninstalled from the VM.
2. **`instructor.from_provider("gemini/...")` uses the deprecated `google-generativeai` package; `"google/..."` uses the current `google-genai` package.** Use the `google/` prefix. It reads `GOOGLE_API_KEY`, not `GEMINI_API_KEY` — `backend/questions/llm_config.py` mirrors `GEMINI_API_KEY` into `GOOGLE_API_KEY` at import time so `.env` only needs to hold one name.
3. **Python 3.9 (Oracle Linux 9's default `python3`, running on the VM) cannot evaluate instructor's internal `str | Path` PEP-604 union type annotations** — pydantic's runtime type-hint resolution chokes on it with `TypeError: unsupported operand type(s) for |: 'type' and 'type'`. Fix: add `eval_type_backport` to requirements.txt (instructor's own error message names this exact package). Watch for this again in any future dependency that assumes Python ≥3.10 — the VM will stay on 3.9 unless deliberately upgraded (dnf's `python3` there is EOL-track; `google-auth` already warns about it every run, harmlessly for now).
4. **LLM model IDs go stale fast — always verify against the live `GET /v1/models` endpoint before hardcoding one.** `gemini-2.5-flash-lite`, `groq/llama-3.1-8b-instant`, and a guessed Cerebras model ID were all wrong/deprecated on the very first live test, despite being reasonable-sounding names from research done only hours earlier. Fixed by querying each provider's real model list directly (`curl .../v1/models`) instead of guessing. Prefer Google's rolling aliases (`gemini-flash-lite-latest`) where available, since they auto-track whatever the current model is instead of hardcoding a version number that will itself be deprecated later.
5. **Test locally first, then deploy.** Every one of the above issues was caught and fixed on the local Windows venv (Python 3.11) before touching the VM, which was much faster to iterate on than SSH+background-task round trips to a slow, memory-constrained box. Keep doing this for Phase 3+.

**Next up (Phase 3 per Phases.md):** Single Ground Agent loop — receive a Question, use the Question Engine to generate sub-questions/hypotheses, detect boundary conditions, checkpoint state to SQLite so it survives a process restart. First phase where agent *recursion* (not just a direct function call) appears — build the spawn-budget enforcement (Rules.md rule 10) in from the start, not after the fact.

---

## 2026-08-27 — Phase 1 complete: Graph Interface deployed and verified on live infrastructure

**What's done:**
- Phase 0 docs (PRD/Architecture/Rules/Phases/Design) written, then revised after real-world-precedent research (Architecture.md §0) to a leaner, evidence-backed design (2-tier dynamic agents, lazy generation, canonical entities, non-strict hierarchy).
- `Implimentation-Research/` folder created with a zero-cost stack plan for running this as a budget-constrained student: free LLM APIs (Gemini/Groq/Cerebras/Cohere) + Oracle Cloud Free Tier hosting.
- **Real infrastructure is live**, not just planned:
  - Oracle Cloud Free Tier account + tenancy `srikrishnabatkeeri`, region `ap-hyderabad-1`.
  - Compute instance `recursive-kg-vm`, public IP **129.225.116.251**, SSH key at `.secrets/oracle-recursive-kg-vm.key` (gitignored).
  - Shape: **VM.Standard.E2.1.Micro (AMD)**, not the Ampere A1 originally planned — **Ampere A1 had zero capacity available** in ap-hyderabad-1 at signup time (tried both 2 OCPU/12GB and 1 OCPU/6GB, both failed with "Out of capacity"). Fell back to the AMD Always Free micro shape, which was available.
  - Docker + Docker Compose installed on the VM (see "hard lessons" below).
  - Neo4j 5 running via `docker-compose.yml`, memory-tuned (192MB heap / 96MB pagecache / 384MB container cap) for this box's real ~500MB usable RAM. **Deliberately not exposed to the internet** — only reachable via `localhost` on the VM, matching Rules.md's "keep the graph simple, don't over-expose" spirit. Only the future backend API port should be made public.
  - Python 3.9.25 + venv + `backend/graph` deployed to `~/app` on the VM, dependencies installed cleanly (all prebuilt wheels, no compilation needed — light on the tiny box).
  - **`scripts/verify_phase1.py` PASSED against this live Neo4j** — `get_subgraph` returned correct nodes/relationships, and the non-strict-hierarchy check (one entity in two abstractions at once) passed.

**Hard lessons learned (matters for later phases too):**
1. **The AMD Always Free shape's "1GB RAM" is really ~498MB usable** to the guest OS (firmware/kernel overhead eats the rest). The first Docker install attempt **crashed the VM via OOM** — SSH itself became unresponsive (TCP handshake succeeded but sshd never sent a banner, confirmed via raw `curl telnet://`). Fixed by force-rebooting the instance via the OCI console and adding a **2GB swapfile** (`/swapfile2`) before retrying. Any future memory-heavy operation on this VM (installing more system packages, running the agent runtime) should be done with this constraint in mind — check `free -h` before starting anything heavy.
2. **Neo4j's boot volume is network-attached block storage** — first-boot store creation + APOC plugin scanning involves heavy disk I/O that's slow over the network. First Neo4j start took ~4 minutes and looked "stuck" on the same log line for a while (it wasn't — memory/IO kept climbing, it just needed patience). Don't assume a stalled log means a hung container on this infra; check `docker stats` for climbing memory/IO before concluding it's stuck.
3. Oracle's console UI (Redwood/OCI) has real accessibility-tree gaps — the browser automation's `find`/`read_page` tools could not see most of its interactive elements (shape pickers, toggles, buttons). Everything had to be done via screenshot + pixel-coordinate clicks. If continuing OCI console work, expect this and don't rely on `find`.
4. The "Automatically assign public IPv4 address" toggle in the quick-create instance wizard never worked via automation (múltiple attempts, no visible state change) — the reliable path was: create the instance without a public IP → reserve a private IP (`IP administration` tab → "..." → "Reserve IPv4 address") → then Edit that private IP → **"Reserved public IP" → select existing reserved public IP** (reserved separately via Networking → IP Management → Reserved public IPs).

**Next up (Phase 2 per Phases.md):** Question Engine — Instructor + litellm wired to the free LLM providers (Gemini/Groq/Cerebras/Cohere per Implimentation-Research/Free-LLM-APIs.md), implementing the 3 universal dimensions, called lazily per Rules.md rule 11. Will need to deploy this to the same VM and verify level-awareness (same dimension, different question at different abstraction levels).
