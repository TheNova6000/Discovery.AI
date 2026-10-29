class QuestionEngineError(Exception):
    """Raised by the Question Engine for any LLM-call or validation failure.

    Per docs/Rules.md rule 1, raw driver/HTTP/LLM-SDK exceptions must not leak past
    this layer's boundary.
    """
