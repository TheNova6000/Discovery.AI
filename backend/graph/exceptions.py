class GraphInterfaceError(Exception):
    """Raised by the Graph Interface layer for any Neo4j-related failure.

    Per docs/Rules.md rule 1, this module is the only place allowed to talk to Neo4j
    directly, and raw driver exceptions must not leak past this boundary.
    """
