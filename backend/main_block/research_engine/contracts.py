"""The contract between Discovery.AI (reasoning) and Dewey (research)
(docs/research/Reasoning-Research-Orchestration.md §3).

Discovery.AI says what it needs to know as an `InformationNeed`; Dewey
answers with an `EvidenceBatch`: passages with provenance plus one
`ProviderReport` per source it consulted, so "nothing exists" can always be
told apart from "we couldn't search".
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .archive import PassageHit

NeedKind = Literal[
    "general",
    "definition",
    "explanation",
    "example",
    "history",
    "comparison",
    "implementation",
    "evidence",
    "prerequisite",
    "misconception",
]

# "general" = not typed yet: routed to every provider. Discovery.AI sends this
# until it classifies its needs (Reasoning-Research-Orchestration.md §4 router).

ProviderStatus = Literal["ok", "no_results", "skipped_no_key", "timed_out", "failed"]

BatchSource = Literal["archive", "research", "known_gap", "unavailable"]
"""Where the passages came from:
- archive: the Archive already covered the need, no provider was called;
- research: providers were called and what they returned was ingested first;
- known_gap: researched recently with nothing useful found, so it isn't
  searched again until the ledger's retry time;
- unavailable: every routed provider failed or was skipped, so nothing could
  be searched (not the same as "nothing exists")."""


class InformationNeed(BaseModel):
    text: str = Field(min_length=1)
    need_kind: NeedKind = "explanation"
    entity_id: Optional[str] = None
    """Graph entity this need is about. Ingested passages are tagged with it,
    but archive lookups stay global: a passage about the topic is useful
    whichever investigation first fetched it."""
    max_passages: int = 6
    min_passages: int = 2
    """Archive hits needed (each covering at least half the need's content
    terms) to count as covered without researching."""


class ProviderReport(BaseModel):
    provider: str
    status: ProviderStatus
    results: int = 0
    detail: Optional[str] = None


class EvidenceBatch(BaseModel):
    need: InformationNeed
    passages: list[PassageHit]
    source: BatchSource
    reports: list[ProviderReport] = Field(default_factory=list)
    passages_ingested: int = 0
