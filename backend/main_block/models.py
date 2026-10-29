"""The Main Block contract: the only shapes that cross the door between the
main block (Discovery.AI reasoning + Dewey research) and its clients (the chat
model, the Tuni'n portal). docs/research/Reasoning-Research-Orchestration.md;
option B agreed 2026-10-28.

Every answer that leaves the door states whether it is grounded, which sources
back it, what the audit could not trace, and what the evidence did not cover.
A client never has to guess whether text is researched or remembered.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    """Was running when the process stopped. Starting the same request again
    creates a fresh attempt; nothing is silently resumed half-way."""


class ResearchJobRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    question: Optional[str] = Field(default=None, max_length=1000)
    """Defaults to a definition / mechanism / operations question about `topic`."""
    objective: Optional[str] = Field(default=None, max_length=1000)
    """Why the learner wants this (shapes the question, never the evidence)."""
    learner_level: Optional[str] = Field(default=None, max_length=50)
    scope_hint: Optional[str] = Field(default=None, max_length=200)
    """Disambiguates names that collide across domains ("Transmission")."""

    @field_validator("topic", "question", "objective", "learner_level", "scope_hint", mode="before")
    @classmethod
    def _collapse_whitespace(cls, value):
        # "  binary SEARCH tree " built the default question "...tree , how" and so
        # a different fingerprint -> a duplicate job (caught by verify_mainblock #1).
        return " ".join(value.split()) if isinstance(value, str) else value

    def effective_question(self) -> str:
        if self.question:
            return self.question
        return f"What is {self.topic}, how does it work, and what are its main parts and how do they relate?"

    def fingerprint(self) -> str:
        """Same request -> same job (idempotency). Case/whitespace-insensitive."""
        parts = [self.topic, self.effective_question(), self.objective or "", self.learner_level or "", self.scope_hint or ""]
        normalized = "\x1f".join(" ".join(p.lower().split()) for p in parts)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


class Citation(BaseModel):
    claim_id: str
    evidence: str
    source_title: str
    source_url: str
    source_type: str
    content_kind: Optional[str] = None
    retrieved_at: Optional[str] = None
    confidence: float


class GroundedAnswer(BaseModel):
    question: str
    answer: Optional[str]
    """None when nothing could be grounded and no draft is shown (`ask`)."""
    grounded: bool
    support_ratio: Optional[float] = None
    """Share of atomic statements the audit traced to the evidence; None = not audited."""
    citations: list[Citation] = Field(default_factory=list)
    unsupported_statements: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    note: Optional[str] = None


class JobEvent(BaseModel):
    at: str = Field(default_factory=utcnow)
    stage: str
    message: str


class ResearchResult(BaseModel):
    answer: GroundedAnswer
    findings: list[GroundedAnswer] = Field(default_factory=list)
    """One per sub-investigation, in the order they ran."""
    research_response: Optional[dict[str, Any]] = None
    """The stable Discovery.AI `ResearchResponse` (entities, relationships,
    claims, coverage...) when the topic has a persisted decomposition."""
    limitations: list[str] = Field(default_factory=list)


class ResearchJob(BaseModel):
    job_id: str
    owner_id: str
    fingerprint: str
    request: ResearchJobRequest
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    events: list[JobEvent] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    result: Optional[ResearchResult] = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    topic: Optional[str] = Field(default=None, max_length=200)
    """The entity the question is about; included in evidence searches."""


class AskResult(BaseModel):
    answer: GroundedAnswer
    evidence_source: str
    """Dewey's batch source: archive / research / known_gap / unavailable."""
