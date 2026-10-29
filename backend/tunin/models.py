"""Tuni'n domain models.

Tuni'n is a client of Discovery.AI, not a second research engine.  These models
describe the *learner-facing* side of the system: the discovery brief, the
approved curriculum, generated modules, assessment evidence, and adaptation
decisions.  Research evidence is represented as `SourceReference` pointers to
real retrieved resources; nothing here fabricates a claim.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class CourseState(str, Enum):
    DISCOVERY = "DISCOVERY"
    BRIEF_READY = "BRIEF_READY"
    RESEARCH_PLANNING = "RESEARCH_PLANNING"
    RESEARCH_RUNNING = "RESEARCH_RUNNING"
    RESEARCH_REVIEW = "RESEARCH_REVIEW"
    CURRICULUM_DRAFT = "CURRICULUM_DRAFT"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    GENERATING_MODULES = "GENERATING_MODULES"
    READY_TO_LEARN = "READY_TO_LEARN"
    MODULE_IN_PROGRESS = "MODULE_IN_PROGRESS"
    ASSESSMENT_PENDING = "ASSESSMENT_PENDING"
    FEEDBACK_PENDING = "FEEDBACK_PENDING"
    ADAPTATION_PENDING = "ADAPTATION_PENDING"
    BUFFER_READY = "BUFFER_READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


class ModuleStatus(str, Enum):
    PLANNED = "planned"
    GENERATED = "generated"
    PUBLISHED = "published"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ResearchMode(str, Enum):
    DISCOVERY_AI = "discovery_ai"
    DIRECT_RETRIEVAL = "direct_retrieval"
    OFFLINE = "offline"


class ResearchJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ExerciseKind(str, Enum):
    MCQ = "mcq"
    SHORT_ANSWER = "short_answer"
    FEYNMAN = "feynman"
    NUMERIC = "numeric"
    CODE = "code"
    PROJECT = "project"


class GradingOutcome(str, Enum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    NEEDS_REVIEW = "needs_review"
    UNSUPPORTED = "unsupported"


class AdaptationAction(str, Enum):
    ADVANCE = "ADVANCE"
    PRACTICE = "PRACTICE"
    REMEDIATE = "REMEDIATE"
    REVISIT_PREREQUISITE = "REVISIT_PREREQUISITE"
    EXTEND = "EXTEND"
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    RESEARCH_GAP = "RESEARCH_GAP"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class SyllabusTopic(BaseModel):
    id: str = Field(default_factory=lambda: new_id("topic"))
    title: str
    description: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    mandatory: bool = True
    estimated_hours: float = 2.0
    source: Literal["learner", "inferred", "research"] = "learner"
    confidence: float = 0.8

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("syllabus topic title must not be blank")
        return value


class ProjectPreferences(BaseModel):
    wants_mini_projects: bool = True
    wants_capstone: bool = True
    capstone_idea: str = ""
    project_style: list[str] = Field(default_factory=list)  # implementation / research / theory
    available_hardware: list[str] = Field(default_factory=list)
    budget: str = ""
    deliverable_expectations: str = ""


class CourseDesignBrief(BaseModel):
    """The validated output of discovery.  Every field is editable, and every
    assumption is explicit rather than silently baked into a prompt."""

    topic: str = ""
    goal: str = ""
    motivation: str = ""
    depth: Literal["introductory", "practical", "advanced", "research"] = "practical"
    prior_knowledge: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    syllabus_topics: list[SyllabusTopic] = Field(default_factory=list)
    mandatory_topics: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    weekly_hours: Optional[float] = None
    target_weeks: Optional[int] = None
    module_length_hours: Optional[float] = None
    projects: ProjectPreferences = Field(default_factory=ProjectPreferences)
    learning_preferences: list[str] = Field(default_factory=list)
    assessment_preferences: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    approved_facts: list[str] = Field(default_factory=list)
    asked: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utcnow)

    def missing_required(self) -> list[str]:
        """Fields that materially block a useful proposal.  This is deliberately
        short: the point of discovery is a usable brief, not a filled-in form."""
        missing: list[str] = []
        if not self.topic.strip():
            missing.append("topic")
        if not self.goal.strip():
            missing.append("goal")
        if len(self.syllabus_topics) < 2:
            missing.append("syllabus")
        if self.weekly_hours is None:
            missing.append("weekly_hours")
        return missing

    @property
    def ready(self) -> bool:
        return not self.missing_required()

    def merge_topics(self, topics: list[SyllabusTopic]) -> None:
        existing = {t.title.strip().lower() for t in self.syllabus_topics}
        for topic in topics:
            if topic.title.strip().lower() not in existing:
                self.syllabus_topics.append(topic)
                existing.add(topic.title.strip().lower())
        self.updated_at = utcnow()


class DiscoveryMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    course_id: str
    role: Literal["assistant", "user", "system"]
    content: str
    created_at: str = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)


class DiscoveryReply(BaseModel):
    message: DiscoveryMessage
    brief: CourseDesignBrief
    done: bool
    next_question: str = ""
    missing: list[str] = Field(default_factory=list)
    llm_used: bool = False


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


class SourceReference(BaseModel):
    id: str = Field(default_factory=lambda: new_id("src"))
    title: str
    url: str
    snippet: str = ""
    source_type: str = "web"
    source_role: Optional[str] = None
    provider: str = ""
    retrieved_at: str = Field(default_factory=utcnow)
    relevance: float = 0.0


class TopicResearch(BaseModel):
    topic_id: str
    topic_title: str
    sources: list[SourceReference] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial", "empty", "error"] = "empty"
    notes: list[str] = Field(default_factory=list)


class ResearchBundle(BaseModel):
    mode: ResearchMode = ResearchMode.OFFLINE
    status: Literal["complete", "partial", "failed"] = "failed"
    topics: list[TopicResearch] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    discovery_ai_abstract_id: Optional[str] = None
    discovery_ai_available: bool = False
    llm_used: bool = False
    started_at: str = Field(default_factory=utcnow)
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def sources_for(self, topic_id: str) -> list[SourceReference]:
        for topic in self.topics:
            if topic.topic_id == topic_id:
                return topic.sources
        return []


class ResearchJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    course_id: str
    status: ResearchJobStatus = ResearchJobStatus.QUEUED
    stage: str = "queued"
    progress: float = 0.0
    message: str = ""
    result: Optional[ResearchBundle] = None
    error: Optional[str] = None
    attempts: int = 0
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Curriculum
# ---------------------------------------------------------------------------


class Lesson(BaseModel):
    id: str
    title: str
    objectives: list[str] = Field(default_factory=list)
    content_md: str
    worked_example_md: str = ""
    teach_back_prompt: str = ""
    source_ids: list[str] = Field(default_factory=list)
    estimated_minutes: int = 25


class ExerciseOption(BaseModel):
    id: str
    text: str


class Exercise(BaseModel):
    id: str
    kind: ExerciseKind
    prompt: str
    concepts: list[str] = Field(default_factory=list)
    options: list[ExerciseOption] = Field(default_factory=list)
    answer_key: Optional[str] = None
    rubric: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    max_score: float = 1.0
    estimated_minutes: int = 10
    manual_only: bool = False

    @model_validator(mode="after")
    def _mcq_has_options(self) -> "Exercise":
        if self.kind == ExerciseKind.MCQ:
            if len(self.options) < 2:
                raise ValueError("an MCQ needs at least two options")
            if not self.answer_key:
                raise ValueError("an MCQ needs a deterministic answer_key")
            valid_ids = {o.id for o in self.options}
            if self.answer_key not in valid_ids:
                raise ValueError("MCQ answer_key must reference one of its option ids")
        return self


class MiniProject(BaseModel):
    title: str
    brief: str
    skills: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list)
    extension_tasks: list[str] = Field(default_factory=list)
    contributes_to_capstone: str = ""


class CapstonePlan(BaseModel):
    title: str
    problem: str
    milestones: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list)
    testing_strategy: list[str] = Field(default_factory=list)
    final_demonstration: str = ""


class ModulePlan(BaseModel):
    id: str
    course_id: str
    proposal_id: str
    sequence: int
    title: str
    purpose: str
    objectives: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    estimated_hours: float = 3.0
    teaching_strategies: list[str] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)
    exercises: list[Exercise] = Field(default_factory=list)
    mini_project: Optional[MiniProject] = None
    assessment_strategy: str = ""
    completion_criteria: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_topic_id: Optional[str] = None
    status: ModuleStatus = ModuleStatus.PLANNED
    version: int = 1
    is_remedial: bool = False
    remediation_for: list[str] = Field(default_factory=list)
    adaptation_note: str = ""
    artifact_dir: str = ""
    published_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _has_teachable_content(self) -> "ModulePlan":
        if not self.objectives:
            raise ValueError("module must declare at least one objective")
        if not self.lessons:
            raise ValueError("module must have at least one lesson")
        if not self.exercises:
            raise ValueError("module must have at least one exercise")
        return self


class SyllabusMapping(BaseModel):
    topic_id: str
    topic_title: str
    coverage: Literal["covered", "partial", "missing"] = "covered"
    module_ids: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    notes: str = ""


class CourseProposal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prop"))
    course_id: str
    version: int = 1
    title: str
    description: str
    audience: str = ""
    objectives: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    estimated_effort_hours: float = 0.0
    completion_plan: str = ""
    syllabus_mapping: list[SyllabusMapping] = Field(default_factory=list)
    modules: list[ModulePlan] = Field(default_factory=list)
    mini_projects: list[MiniProject] = Field(default_factory=list)
    capstone: Optional[CapstonePlan] = None
    capstone_opted_out: bool = False
    learning_methods: list[str] = Field(default_factory=list)
    assessment_strategy: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    research_mode: ResearchMode = ResearchMode.OFFLINE
    sources: list[SourceReference] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.AWAITING_APPROVAL
    created_at: str = Field(default_factory=utcnow)
    approved_at: Optional[str] = None
    supersedes: Optional[int] = None

    @model_validator(mode="after")
    def _approval_has_timestamp(self) -> "CourseProposal":
        if self.status == ProposalStatus.APPROVED and not self.approved_at:
            raise ValueError("approved proposal must record approved_at")
        return self

    def validate_plan(self) -> list[str]:
        """Return validation errors; empty means the plan is publishable."""
        errors: list[str] = []
        if not self.title.strip():
            errors.append("course title is empty")
        if len(self.modules) < 2:
            errors.append("at least two modules are required for the two-module buffer")
        if not self.objectives:
            errors.append("course objectives are empty")
        if not self.capstone and not self.capstone_opted_out:
            errors.append("capstone project is missing")
        for mapping in self.syllabus_mapping:
            if mapping.coverage == "missing":
                errors.append(f"mandatory syllabus topic {mapping.topic_title!r} is not covered")
            if mapping.coverage == "covered" and not mapping.module_ids:
                errors.append(f"syllabus topic {mapping.topic_title!r} is marked covered but maps to no module")
            for module_id in mapping.module_ids:
                if not any(m.id == module_id for m in self.modules):
                    errors.append(
                        f"syllabus topic {mapping.topic_title!r} references unknown module {module_id!r}"
                    )
        for module in self.modules:
            if not module.lessons:
                errors.append(f"module {module.title!r} has no lessons")
            if not module.exercises:
                errors.append(f"module {module.title!r} has no exercises")
            if not module.evidence_refs and self.research_mode == ResearchMode.DISCOVERY_AI:
                errors.append(f"module {module.title!r} has no evidence references")
        return errors


# ---------------------------------------------------------------------------
# Assessment, feedback, learner model
# ---------------------------------------------------------------------------


class GradingResult(BaseModel):
    outcome: GradingOutcome
    score: float = 0.0
    feedback: str = ""
    missing_concepts: list[str] = Field(default_factory=list)
    grader: Literal["deterministic", "heuristic", "llm", "none"] = "deterministic"
    answer_key: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class Attempt(BaseModel):
    id: str = Field(default_factory=lambda: new_id("att"))
    course_id: str
    module_id: str
    exercise_id: str
    learner_id: str
    answer: Any
    confidence: Optional[float] = None
    result: GradingResult
    created_at: str = Field(default_factory=utcnow)


class ModuleFeedback(BaseModel):
    course_id: str
    module_id: str
    learner_id: str
    difficulty: int = Field(ge=1, le=5, default=3)
    clarity: int = Field(ge=1, le=5, default=3)
    pace: int = Field(ge=1, le=5, default=3)
    exercise_quality: int = Field(ge=1, le=5, default=3)
    goal_connection: int = Field(ge=1, le=5, default=3)
    missing_explanations: str = ""
    useful_examples: str = ""
    next_interests: str = ""
    free_text: str = ""
    id: str = Field(default_factory=lambda: new_id("fb"))
    created_at: str = Field(default_factory=utcnow)


class FeedbackClassification(BaseModel):
    categories: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "low"
    requires_approval: bool = False
    summary: str = ""


class MasteryRecord(BaseModel):
    learner_id: str
    course_id: str
    concept_id: str
    concept_name: str
    estimate: float = 0.0
    evidence_count: int = 0
    attempt_count: int = 0
    correct_count: int = 0
    repeated_errors: int = 0
    overconfidence_count: int = 0
    last_success_at: Optional[str] = None
    last_review_at: Optional[str] = None
    recommended_action: str = ""
    updated_at: str = Field(default_factory=utcnow)


class AdaptationDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dec"))
    course_id: str
    module_id: str
    action: AdaptationAction
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    target_concepts: list[str] = Field(default_factory=list)
    generated_module_id: Optional[str] = None
    applied: bool = False
    created_at: str = Field(default_factory=utcnow)


class CourseEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    course_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow)


class ArtifactRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    course_id: str
    module_id: str
    kind: str
    path: str
    version: int = 1
    content_hash: str = ""
    created_at: str = Field(default_factory=utcnow)


class Course(BaseModel):
    id: str = Field(default_factory=lambda: new_id("course"))
    learner_id: str
    title: str = "New Tuni'n course"
    state: CourseState = CourseState.DISCOVERY
    version: int = 1
    brief: CourseDesignBrief = Field(default_factory=CourseDesignBrief)
    research: Optional[ResearchBundle] = None
    proposal: Optional[CourseProposal] = None
    active_module_ids: list[str] = Field(default_factory=list)
    completed_module_ids: list[str] = Field(default_factory=list)
    approved_proposal_version: Optional[int] = None
    error: Optional[str] = None
    last_decision: Optional[AdaptationDecision] = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class CourseSnapshot(BaseModel):
    course: Course
    messages: list[DiscoveryMessage] = Field(default_factory=list)
    research_job: Optional[ResearchJob] = None
    proposal: Optional[CourseProposal] = None
    modules: list[ModulePlan] = Field(default_factory=list)
    mastery: list[MasteryRecord] = Field(default_factory=list)
    decisions: list[AdaptationDecision] = Field(default_factory=list)
    feedback: list[ModuleFeedback] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    active_module_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request/response shapes
# ---------------------------------------------------------------------------


class CreateCourseRequest(BaseModel):
    title: str = ""
    learner_name: str = ""


class DiscoveryMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class ProposalEditRequest(BaseModel):
    version: int
    title: Optional[str] = None
    description: Optional[str] = None
    learning_methods: Optional[list[str]] = None
    module_edits: dict[str, dict[str, Any]] = Field(default_factory=dict)
    remove_optional_project: Optional[str] = None


class ApproveRequest(BaseModel):
    version: int


class AttemptRequest(BaseModel):
    exercise_id: str
    answer: Any
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class FeedbackRequest(BaseModel):
    difficulty: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    pace: int = Field(ge=1, le=5)
    exercise_quality: int = Field(ge=1, le=5)
    goal_connection: int = Field(ge=1, le=5)
    missing_explanations: str = ""
    useful_examples: str = ""
    next_interests: str = ""
    free_text: str = ""
