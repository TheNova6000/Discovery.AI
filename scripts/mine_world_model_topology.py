"""§0.33 Pass A: mine the REAL, already-accumulated Neo4j World Model for
topology that was never deliberately designed -- zero LLM calls, pure graph
analysis over everything every investigation this project has ever run wrote
to the same database. Answers: does non-tree structure already exist in the
wild, and if so, where did it actually come from (which relationship_types,
which investigations, which layer of the pipeline)?

Uses the project's own single source of truth for relation family
(backend.questions.relation_types.get_family) rather than re-deriving family
classification here -- consistent with every prior pass's discipline of never
maintaining a second copy of that table.
"""
import asyncio
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from backend.graph.driver import close_driver, get_driver
from backend.questions.relation_types import get_family


async def fetch_graph():
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (a)-[r:RELATES_TO]->(b) RETURN a.name AS source, r.relationship_type AS rel, b.name AS target"
        )
        edges = [dict(r) async for r in result]
        node_result = await session.run(
            "MATCH (n) WHERE n.name IS NOT NULL RETURN DISTINCT n.name AS name, n.boundary_kind AS boundary_kind"
        )
        nodes = {r["name"]: r["boundary_kind"] async for r in node_result}
    return nodes, edges


def weakly_connected_components(nodes, edges):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in edges:
        if e["source"] in parent and e["target"] in parent:
            union(e["source"], e["target"])

    components = defaultdict(set)
    for n in nodes:
        components[find(n)].add(n)
    return list(components.values())


def find_directed_cycle(adj, component):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in component}
    path_stack = []

    def dfs(u):
        color[u] = GRAY
        path_stack.append(u)
        for v, rel in adj.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                cycle_start = path_stack.index(v)
                return path_stack[cycle_start:] + [v]
            if color[v] == WHITE:
                found = dfs(v)
                if found:
                    return found
        path_stack.pop()
        color[u] = BLACK
        return None

    for n in component:
        if color[n] == WHITE:
            found = dfs(n)
            if found:
                return found
    return None


async def main():
    nodes, edges = await fetch_graph()
    print(f"World Model: {len(nodes)} nodes, {len(edges)} edges (across every investigation ever run)\n")

    by_family = defaultdict(list)
    for e in edges:
        fam = get_family(e["rel"]) or "unmapped"
        e["family"] = fam
        by_family[fam].append(e)
    print("Edges by relation family:")
    for fam, es in sorted(by_family.items(), key=lambda x: -len(x[1])):
        print(f"  {fam:14s} {len(es):4d}  (e.g. {es[0]['rel']!r})")
    print()

    adj = defaultdict(list)
    in_degree = defaultdict(int)
    for e in edges:
        adj[e["source"]].append((e["target"], e["rel"]))
        in_degree[e["target"]] += 1

    components = weakly_connected_components(nodes, edges)
    real_components = [c for c in components if len(c) > 1]
    print(f"Weakly-connected components with >1 node: {len(real_components)}\n")

    print("=" * 70)
    print("CYCLES (a directed path returning to an ancestor)")
    print("=" * 70)
    found_any_cycle = False
    for comp in real_components:
        cycle = find_directed_cycle(adj, comp)
        if cycle:
            found_any_cycle = True
            print("  CYCLE FOUND:", " -> ".join(cycle))
    if not found_any_cycle:
        print("  none found in the current stored graph")
    print()

    print("=" * 70)
    print("CONVERGENCE (a node with >=2 distinct incoming edges -- DAG candidate)")
    print("=" * 70)
    convergent = {n: d for n, d in in_degree.items() if d >= 2}
    if convergent:
        for n, d in sorted(convergent.items(), key=lambda x: -x[1]):
            incoming = [e for e in edges if e["target"] == n]
            print(f"  {n!r} <- {d} incoming:")
            for e in incoming:
                print(f"      {e['source']!r} -[{e['rel']}/{e['family']}]-> {n!r}")
    else:
        print("  none found")
    print()

    print("=" * 70)
    print("NESTED SPACES (a boundary_kind node whose composition children")
    print("themselves have composition children -- depth >= 2)")
    print("=" * 70)
    comp_children = defaultdict(list)
    for e in edges:
        if e["family"] == "composition":
            comp_children[e["source"]].append(e["target"])
    nested_found = False
    for parent_name, bk in nodes.items():
        if not bk:
            continue
        for child in comp_children.get(parent_name, []):
            if comp_children.get(child):
                nested_found = True
                print(f"  {parent_name!r} -> {child!r} -> {comp_children[child]}")
    if not nested_found:
        print("  none found")
    print()

    print("=" * 70)
    print("CROSS-SPACE EDGES (non-composition edge whose two endpoints have")
    print("DIFFERENT immediate composition parents)")
    print("=" * 70)
    parent_of = {}
    for e in edges:
        if e["family"] == "composition" and e["target"] not in parent_of:
            parent_of[e["target"]] = e["source"]
    cross_found = False
    for e in edges:
        if e["family"] == "composition":
            continue
        ps, pt = parent_of.get(e["source"]), parent_of.get(e["target"])
        if ps and pt and ps != pt:
            cross_found = True
            print(f"  {e['source']!r} (in {ps!r}) -[{e['rel']}/{e['family']}]-> {e['target']!r} (in {pt!r})")
    if not cross_found:
        print("  none found (no non-composition edge currently spans two distinct parents)")
    print()

    print("=" * 70)
    print("TEMPORAL CHAINS (>=2 chained precedes/follows edges)")
    print("=" * 70)
    temporal_edges = [e for e in edges if e["family"] == "temporal"]
    temp_adj = defaultdict(list)
    for e in temporal_edges:
        temp_adj[e["source"]].append(e["target"])
    chain_found = False
    for start in temp_adj:
        if start not in {e["target"] for e in temporal_edges}:  # a chain root
            chain = [start]
            cur = start
            while temp_adj.get(cur):
                cur = temp_adj[cur][0]
                if cur in chain:
                    break
                chain.append(cur)
            if len(chain) >= 3:
                chain_found = True
                print("  " + " -> ".join(chain))
    if not chain_found:
        print("  no chain of length >= 3 found")
    print()

    print("=" * 70)
    print("MIXED NODES (a single node touching >=2 distinct relation families)")
    print("=" * 70)
    families_touching = defaultdict(set)
    for e in edges:
        families_touching[e["source"]].add(e["family"])
        families_touching[e["target"]].add(e["family"])
    mixed = {n: fams for n, fams in families_touching.items() if len(fams) >= 2}
    for n, fams in sorted(mixed.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"  {n!r}: {sorted(fams)}")
    if not mixed:
        print("  none found")

    await close_driver()


if __name__ == "__main__":
    asyncio.run(main())
