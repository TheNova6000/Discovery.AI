"""Roadmap Generator (Phase 6, PRD.md §4a).

Sequences an already-investigated abstraction's graph into an ordered, readable
(Question -> Resource -> summary) path -- distinct from free Navigate/Zoom
exploration. Only reads via `backend.graph` (Rules.md rule 14: never calls an
LLM or retriever itself). The Curriculum Compiler (Architecture.md §6.3, Phase
9) extends this exact pattern for the Learning Portal extension -- don't build
that ahead of this module actually working end-to-end (Rules.md, Phases.md).
"""

from .generator import generate_roadmap
from .models import Roadmap, RoadmapStep
from .ordering import order_roadmap_steps

__all__ = [
    "generate_roadmap",
    "order_roadmap_steps",
    "Roadmap",
    "RoadmapStep",
]
