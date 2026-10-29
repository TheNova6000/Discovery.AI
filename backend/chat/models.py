"""Chat-model state. A session is the conversation with one learner about one
course: their messages, the course-design brief being built, and the main-block
research job it started."""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.main_block.interface import utcnow
from backend.tunin.models import CourseDesignBrief

Phase = Literal["discovery", "confirming", "researching", "ready"]
"""discovery: gathering the brief (and answering the learner's questions);
confirming: brief complete, waiting for the learner's go-ahead to research;
researching: a main-block research job is running;
ready: research finished -- findings shown, course building comes next."""


class ChatMessage(BaseModel):
    role: Literal["learner", "tunin"]
    text: str
    at: str = Field(default_factory=utcnow)
    kind: Literal["discovery", "answer", "status", "summary", "info"] = "discovery"
    grounded: Optional[bool] = None
    """Set on answers that came from the main block: True only when backed by sources."""


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"cs_{uuid.uuid4().hex[:16]}")
    owner_id: str
    phase: Phase = "discovery"
    brief: CourseDesignBrief = Field(default_factory=CourseDesignBrief)
    messages: list[ChatMessage] = Field(default_factory=list)
    research_job_id: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class ChatReply(BaseModel):
    session: ChatSession
    reply: ChatMessage
