from __future__ import annotations

from .models import Dimension

SCALE = Dimension(
    id="scale",
    name="Scale",
    description="At what level are we observing the system? (physical/individual/interpersonal/"
    "group/organization/institution/society/global — the meaningful scale depends on the abstraction.)",
)

PERSPECTIVE = Dimension(
    id="perspective",
    name="Perspective",
    description="From what viewpoint are we examining the system? (physical/biological/psychological/"
    "social/economic/computational/systemic/legal/political/historical/philosophical.)",
)

TIME = Dimension(
    id="time",
    name="Time",
    description="When are we examining the system, and how does it change? (origin/development/"
    "evolution/current state/future/transformation/failure/adaptation.)",
)

UNIVERSAL_DIMENSIONS: list[Dimension] = [SCALE, PERSPECTIVE, TIME]
"""The 3 dimensions useful across nearly any abstraction. See docs/PRD.md §3 and
System Design spec §9. Domain-specific dimensions (e.g. for payment systems or
organizations) are added later, per spec §11 — not implemented in Phase 2.
"""
