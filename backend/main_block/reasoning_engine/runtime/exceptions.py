class StateStoreError(Exception):
    """Raised by the SQLite state store for any persistence failure.

    Per docs/Rules.md rule 1's convention, raw sqlite3/aiosqlite exceptions must not
    leak past this layer's boundary.
    """
