class AgentError(Exception):
    """Raised by the agent runtime for internal invariant violations (e.g. a child
    agent_id referenced by a DECOMPOSING parent has no persisted state).

    Not used for LLM-call failures — those already surface as a typed
    `QuestionEngineError` from `backend.questions` (docs/Rules.md rule 2) and are
    left to propagate rather than being wrapped a second time.
    """
