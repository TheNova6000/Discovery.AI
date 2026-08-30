"""Direct Neo4j inspection of what §0.28's extraction-prompt fix actually
persisted during the live payment-lifecycle re-run, bypassing the in-memory
session mirror (which never got refreshed because the overall request errored
out at the synthesize_answer step after every LLM provider was exhausted --
Neo4j writes from ground_agent.py's create_relationship calls happen
independently and earlier, so they persisted regardless).
"""
import asyncio
import sys

sys.path.insert(0, ".")

from backend.graph.driver import close_driver, get_driver


async def main():
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (a)-[r:RELATES_TO]->(b)
            WHERE toLower(a.name) CONTAINS 'capture'
               OR toLower(a.name) CONTAINS 'clearing'
               OR toLower(a.name) CONTAINS 'settlement'
               OR toLower(a.name) CONTAINS 'authorization'
               OR toLower(a.name) CONTAINS 'risk'
               OR toLower(b.name) CONTAINS 'capture'
               OR toLower(b.name) CONTAINS 'clearing'
               OR toLower(b.name) CONTAINS 'settlement'
               OR toLower(b.name) CONTAINS 'authorization'
               OR toLower(b.name) CONTAINS 'risk'
            RETURN a.name AS source, r.relationship_type AS rel, b.name AS target
            ORDER BY source
            """
        )
        rows = await result.data()
        for row in rows:
            print(f"{row['source']!r} -[{row['rel']}]-> {row['target']!r}")
        print(f"\nTotal matching edges: {len(rows)}")
    await close_driver()


if __name__ == "__main__":
    asyncio.run(main())
