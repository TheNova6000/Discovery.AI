"""Question Engine (Phase 2): (Abstraction, Network, Entity, Dimension, Level, Objective,
Known, Unknowns) -> Question(s). Lazy — see docs/Rules.md rule 11.
"""

from .audit import AtomicClaim, SynthesisAudit, audit_synthesis
from .decision import decide_next_step
from .dimensions import PERSPECTIVE, SCALE, TIME, UNIVERSAL_DIMENSIONS
from .engine import generate_question
from .exceptions import QuestionEngineError
from .intent import Intent, SessionContext, parse_intent
from .models import Dimension, GroundDecision, Question, QuestionDraft, QuestionLevel, SynthesisDraft
from .relationships import ClaimPairRelationship, RelationshipAnalysis, analyze_claim_relationships
from .synthesis import synthesize_answer

__all__ = [
    "generate_question",
    "decide_next_step",
    "synthesize_answer",
    "audit_synthesis",
    "AtomicClaim",
    "SynthesisAudit",
    "analyze_claim_relationships",
    "ClaimPairRelationship",
    "RelationshipAnalysis",
    "parse_intent",
    "Intent",
    "SessionContext",
    "QuestionEngineError",
    "Dimension",
    "GroundDecision",
    "SynthesisDraft",
    "Question",
    "QuestionDraft",
    "QuestionLevel",
    "SCALE",
    "PERSPECTIVE",
    "TIME",
    "UNIVERSAL_DIMENSIONS",
]
