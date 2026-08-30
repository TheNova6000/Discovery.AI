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
from .relation_extraction import (
    CandidateRelation,
    CanonicalRelation,
    RelationExtraction,
    canonicalize_relation,
    extract_relations,
    is_relation_worthy,
    normalize_relationship_type,
)
from .relation_types import PROJECTION_FAMILIES, RelationFamily, get_family, get_relation_info, is_compositional
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
    "extract_relations",
    "is_relation_worthy",
    "canonicalize_relation",
    "normalize_relationship_type",
    "CandidateRelation",
    "CanonicalRelation",
    "RelationExtraction",
    "RelationFamily",
    "PROJECTION_FAMILIES",
    "get_family",
    "get_relation_info",
    "is_compositional",
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
