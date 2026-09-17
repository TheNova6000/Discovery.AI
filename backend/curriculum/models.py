from __future__ import annotations

from pydantic import BaseModel, Field

from backend.reasoning import Claim

# Phase 9 (docs/Phases.md, docs/Rules.md rule 16): the Curriculum Compiler's
# own types. A Module/Course is a PROJECTION over an already-compiled
# ResearchResponse (R5) -- it reuses the real reasoning.domain.Claim
# objects a module's claims already are, never a new claim/evidence shape.


class IncompleteConcept(BaseModel):
    """A real concept `assess_target_completeness` (Phase 8.3, via R5's
    `ResearchResponse.coverage`) found NOT complete -- surfaced honestly,
    never silently compiled into a thin module (Rules.md rule 16: "a
    concept missing a lesson or exercise is a gap it surfaces, not one it
    fills inline")."""

    entity_id: str
    entity_name: str
    missing_fields: frozenset[str] = Field(default_factory=frozenset)


class Module(BaseModel):
    """One teachable unit -- one real, already-complete concept and its
    real claims (the exact `reasoning.domain.Claim` objects from
    `ResearchResponse.claims`, filtered by `entity_id` -- never
    re-synthesized or copied into a new shape)."""

    entity_id: str
    entity_name: str
    claims: list[Claim] = Field(default_factory=list)


class Course(BaseModel):
    """`compile_course`'s (compiler.py) real output -- modules in real
    dependency order when real `"requires"` edges exist to order them by,
    honestly un-ordered (discovery order, never a fabricated sequence)
    otherwise. `ordered_by_prerequisites` states which case actually
    happened for this specific compilation, so a caller never has to guess
    whether the order carries real meaning."""

    investigation_id: str
    modules: list[Module] = Field(default_factory=list)
    incomplete_concepts: list[IncompleteConcept] = Field(default_factory=list)
    ordered_by_prerequisites: bool
    """True iff at least one real `relationship_type == "requires"` edge
    was found among the complete concepts and used to order `modules`.
    False means `modules` is in the SAME order `ResearchResponse.coverage`
    already listed them in -- not fabricated, not random, but also not a
    real taught-before/after judgment. Confirmed by direct inspection
    (Architecture.md §0.76): no producer in this codebase creates
    `"requires"`-typed relationships today, so this is `False` for every
    real investigation as of this slice -- a real, honestly-stated
    limitation, not a bug."""
