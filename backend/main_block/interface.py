"""Public interface of the MAIN BLOCK (reasoning engine + research engine +
the door that connects them). Everything outside `backend/main_block/` --
the chat model, the Tuni'n portal -- imports from HERE only;
`scripts/verify_mainblock_boundary.py` enforces it.

Operations: start a research job, read its status/result, ask one grounded
question. Every answer is a `GroundedAnswer` that says whether it is backed by
sources, which ones, what couldn't be traced, and what wasn't covered.

Contract types for the course side (owner to specify that part) are exported
too, so the portal never reaches into the engines: `ResearchResponse`,
`Relationship`, `DomainClaim`, and the lesson-authoring calls.
"""

from __future__ import annotations

from .models import (
    AskRequest,
    AskResult,
    Citation,
    GroundedAnswer,
    JobEvent,
    JobStatus,
    ResearchJob,
    ResearchJobRequest,
    ResearchResult,
    utcnow,
)
from .reasoning_engine.interface import (
    DomainClaim,
    Relationship,
    ResearchResponse,
    audit_synthesis,
    compose_lesson_explanation,
)
from .service import JobNotFound, ask, get_job, recover_interrupted, start_research

__all__ = [
    "AskRequest",
    "AskResult",
    "Citation",
    "DomainClaim",
    "GroundedAnswer",
    "JobEvent",
    "JobNotFound",
    "JobStatus",
    "Relationship",
    "ResearchJob",
    "ResearchJobRequest",
    "ResearchResponse",
    "ResearchResult",
    "ask",
    "audit_synthesis",
    "compose_lesson_explanation",
    "get_job",
    "recover_interrupted",
    "start_research",
    "utcnow",
]
