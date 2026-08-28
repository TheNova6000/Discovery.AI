class EvidenceRetrievalError(Exception):
    """Raised only by the Evidence Engine's own orchestration/synthesis boundary
    (e.g. every LLM provider failed while synthesizing a claim) — never raised by
    an individual retriever for an ordinary API failure.

    Per docs/Rules.md §3, a retriever that fails (missing key, timeout, rate limit,
    malformed response) degrades gracefully to zero results for that source; it
    does not raise upward and does not sink the whole `gather_evidence` call.
    """
