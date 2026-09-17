"""Phase 9.1 -- the Curriculum Compiler (docs/Phases.md, docs/Architecture.md
§0.76, docs/Rules.md rule 16).

`compile_course` is a pure projection over an already-compiled
`ResearchResponse` (R5) into a `Course` of `Module`s -- one per real,
already-complete concept, in real prerequisite order when real
`relationship_type=="requires"` edges exist, in honest discovery order
otherwise. A concept whose `ConceptCompleteness.is_complete` is False is
never compiled into a module; it is surfaced in `Course.incomplete_concepts`
instead (rule 16: "a concept missing a lesson or exercise is a gap it
surfaces, not one it fills inline"). Per rule 16, this package never calls
an LLM, a retriever, or Neo4j directly -- it only reads the Graph
Interface's own already-fetched output (via `ResearchResponse`).
"""

from .compiler import CourseCompilationError, compile_course
from .models import Course, IncompleteConcept, Module

__all__ = [
    "Course",
    "CourseCompilationError",
    "IncompleteConcept",
    "Module",
    "compile_course",
]
