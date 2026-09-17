"""Phase 10 -- Lesson Authoring (docs/Phases.md, docs/PRD.md §9.6.3,
docs/Rules.md rules 16/19).

`compile_lesson` turns a real, already-compiled `curriculum.Module` (Phase
9.1) into a `Lesson`: an explanation composed only from the module's real
claims, then independently audited (via the existing, unchanged
`audit_synthesis`, Post-Phase-5 epistemic layer) for whether every sentence
actually traces back to those claims. A module with zero claims is never
padded with a fabricated lesson -- `status="insufficient_claims"` surfaces
that honestly instead. Per Rules.md rule 2, the one LLM call this package
needs lives in `backend.questions.lesson_authoring`, not here -- this
package itself calls no LLM/retriever/Neo4j directly.
"""

from .compiler import compile_lesson
from .models import Lesson, LessonSentence

__all__ = ["Lesson", "LessonSentence", "compile_lesson"]
