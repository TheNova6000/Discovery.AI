"""The shape every research-engine source returns: one real retrieved
resource with its provenance. Owned by the research engine; the reasoning
engine receives it through `research_engine.interface`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RetrievedResource(BaseModel):
    """One real result from a retriever (docs/Phases.md Phase 5) — a paper, book,
    web page, or video that might answer a Question. Whatever the source's own API
    returns is normalized into this shape; nothing here is LLM-generated.
    """

    title: str
    url: str
    snippet: str = ""
    source_type: str  # "web" | "paper" | "book" | "video" | "code"
    published: Optional[str] = None
    retrieved_at: str = Field(default_factory=_now)
    source_role: Optional[str] = None
    """Dewey Source Pack research (docs/Memory.md, 2026-09-17): what KIND of
    evidence this retriever structurally produces -- "entity_discovery" /
    "explanation" / "technical_reference" / "implementation" / "evidence" /
    "reference". A fixed, honest property of the retriever itself (e.g. GitHub
    results are always "implementation"), never an LLM guess per result. `None`
    for any retriever that hasn't been classified yet -- an old value reading
    back as `None`, not a fabricated default, per this project's own established
    "empty must be distinguishable from unknown" discipline."""
    acquisition_mode: Optional[str] = None
    content_kind: Optional[str] = None
    """What the text in `snippet` actually is: "full_text" / "excerpt" /
    "summary" / "abstract" / "metadata". Metadata (a repo description, a book
    record, a video description) describes a resource rather than the topic, so
    a claim built on it is capped below "supported" (iteration 01, E1: a GitHub
    README blurb rated 0.70 as evidence about BSTs; reliability-prior reranking,
    arXiv 2607.22584). `None` = not classified, never assumed to be content."""
    """How this resource was actually obtained: "api" (a real, documented,
    officially-sanctioned API call) / "controlled_document" (a small, curated,
    individually-verified set of known pages, not free-text search over an
    entire site) / "archive" (a downloaded, officially-distributed bulk archive,
    no live request per lookup). Recorded so a caller can tell a live API result
    apart from a fetch against a small, hand-verified page list -- these are not
    the same kind of evidence, even when they end up in the same list."""
